#!/usr/bin/env python3
"""Tune on validation reviews, then report provisional held-out test metrics."""
import argparse
import csv
import json
import re
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from enrich_similarity_inspection import enrich_rows

from similarity_common import (VERSION, atomic_json, atomic_parquet, choose, compatible, digest, identity,
                               load_topics, provisional_labels, read_json, review_inputs,
                               score, split_for)


def metrics(truth, prediction, ids):
    tp = (truth & prediction).sum(axis=0)
    fp = (~truth & prediction).sum(axis=0)
    fn = (truth & ~prediction).sum(axis=0)
    def ratio(a, b):
        return np.divide(a, b, out=np.zeros_like(np.asarray(a), dtype=float), where=np.asarray(b) != 0)
    precision, recall = ratio(tp, tp + fp), ratio(tp, tp + fn)
    f1 = ratio(2 * tp, 2 * tp + fp + fn)
    per_topic = [{'topic_id': tid, 'precision': float(precision[i]), 'recall': float(recall[i]),
                  'f1': float(f1[i]), 'support': int(truth[:, i].sum()),
                  'predicted': int(prediction[:, i].sum())} for i, tid in enumerate(ids)]
    return {'reviews': len(truth), 'micro_precision': float(ratio(tp.sum(), (tp + fp).sum())),
            'micro_recall': float(ratio(tp.sum(), (tp + fn).sum())),
            'micro_f1': float(ratio(2 * tp.sum(), (2 * tp + fp + fn).sum())),
            'macro_precision': float(precision.mean()), 'macro_recall': float(recall.mean()),
            'macro_f1': float(f1.mean()), 'macro_basis': 'all approved topics; zero division = 0',
            'average_topics_per_review': float(prediction.sum(axis=1).mean()),
            'zero_topics_percent': float(100 * (~prediction.any(axis=1)).mean()),
            'per_topic': per_topic}


def predictions(scores, thresholds, cap):
    result = np.zeros(scores.shape, dtype=bool)
    for i, indices in enumerate(choose(scores, thresholds, cap)):
        result[i, indices] = True
    return result


def tune(scores, truth, ids, grid, cap, min_support):
    sweep = []
    for threshold in grid:
        m = metrics(truth, predictions(scores, threshold, cap), ids)
        sweep.append({'threshold': threshold, 'micro_f1': m['micro_f1'],
                      'precision': m['micro_precision'], 'recall': m['micro_recall']})
    # Deterministic tie break: prefer the higher threshold.
    best = max(sweep, key=lambda x: (x['micro_f1'], x['threshold']))['threshold']
    per_topic = {}
    for j, tid in enumerate(ids):
        positives = int(truth[:, j].sum())
        if min(positives, len(truth) - positives) < min_support:
            continue
        candidates = []
        for threshold in grid:
            p = scores[:, j] >= threshold
            tp = int((p & truth[:, j]).sum())
            denom = int(p.sum() + positives)
            candidates.append((2 * tp / denom if denom else 0, threshold))
        per_topic[tid] = max(candidates)[1]
    return best, per_topic, sweep


def inspect_rows(rows, truth, scores, predicted, ids, seed, count):
    # Labels indicate inspection reasons, not automatic truth about negation.
    buckets = {'multi_topic': [], 'low_similarity': [], 'similar_topics': [],
               'negation_candidate': [], 'positive_feature': [], 'rare_topic': [], 'zero_prediction': []}
    supports = truth.sum(axis=0)
    for i, row in enumerate(rows):
        text = row.get('text') or ''
        ordered = np.sort(scores[i])
        if truth[i].sum() > 1 or predicted[i].sum() > 1: buckets['multi_topic'].append(i)
        if scores[i].max() < 0.4: buckets['low_similarity'].append(i)
        if len(ordered) > 1 and ordered[-1] - ordered[-2] < 0.04: buckets['similar_topics'].append(i)
        if re.search(r"\b(never|not|no|hasn't|haven't|don't|didn't)\b", text, re.I): buckets['negation_candidate'].append(i)
        if int(row.get('stars') or 0) >= 4: buckets['positive_feature'].append(i)
        if np.any(truth[i] & (supports <= 5)): buckets['rare_topic'].append(i)
        if not predicted[i].any(): buckets['zero_prediction'].append(i)
    rng = np.random.default_rng(seed)
    selected = []
    for bucket in buckets.values():
        for i in rng.permutation(bucket)[:max(1, count // len(buckets))]:
            if int(i) not in selected: selected.append(int(i))
    for i in rng.permutation(len(rows)):
        if len(selected) >= min(count, len(rows)): break
        if int(i) not in selected: selected.append(int(i))
    result = []
    for i in selected[:count]:
        labels = [ids[j] for j in np.flatnonzero(truth[i])]
        pred = [ids[j] for j in np.flatnonzero(predicted[i])]
        # Topic-specific thresholds can accept a topic outside the raw top five.
        # Keep every assigned score as well as the leading unassigned candidates.
        top = list(np.argsort(-scores[i], kind='stable')[:5])
        top += [j for j in np.flatnonzero(predicted[i]) if j not in top]
        result.append({'review_key': rows[i]['review_key'], 'review_text': rows[i]['text'],
                       'true_topic_ids': json.dumps(labels), 'predicted_topic_ids': json.dumps(pred),
                       'similarity_scores': json.dumps({ids[j]: float(scores[i, j]) for j in top}),
                       'false_positive_topics': json.dumps(sorted(set(pred) - set(labels))),
                       'false_negative_topics': json.dumps(sorted(set(labels) - set(pred))),
                       'inspection_reasons': ','.join(k for k, b in buckets.items() if i in b),
                       'label_source': 'provisional_machine_reference'})
    return result, {k: len(v) for k, v in buckets.items()}


def run(args):
    out = args.output.resolve()
    if out.exists() and any(out.iterdir()):
        raise ValueError('Use a new empty evaluation output folder')
    root = args.run_root.resolve()
    x_topics, topic_rows, config = load_topics(args.topic_embeddings)
    app, manifest, dim, files = review_inputs(root / 'review-embeddings', args.app)
    compatible(manifest['model'], dim, config['model'], config['dimension'])
    if app != config['app'] or digest(root / 'refined-topics/canonical_topics.json') != config['taxonomy_version']:
        raise ValueError('App or taxonomy changed')
    refined = root / 'refined-topics/refined_aspects.parquet'
    if digest(refined) != config['refined_sha256']:
        raise ValueError('Refined labels changed since topic construction')
    extraction_files = list((root / 'aspects').glob('*/review_extractions.parquet'))
    if len(extraction_files) != 1:
        raise ValueError('Expected exactly one app extraction table')
    taxonomy = read_json(root / 'refined-topics/canonical_topics.json')
    blocked = {r['cluster_id'] for r in taxonomy.get('clusters_needing_split', []) + taxonomy.get('clusters_needing_review', [])}
    ids = sorted(t['topic_id'] for t in taxonomy['topics'] if t['relevance_status'] == 'keep'
                 and not blocked.intersection(t['original_cluster_ids']))
    labels = provisional_labels(refined, extraction_files[0], ids)
    wanted = {k: v for k, v in labels.items() if not v['unresolved'] and split_for(v['review'], config['seed']) != 'train'}
    rows, vectors, found = [], [], set()
    for shard in files:
        x = np.load(shard['vectors'], mmap_mode='r', allow_pickle=False)
        for i, row in enumerate(pq.read_table(shard['metadata']).to_pylist()):
            key = identity(row)
            if key in wanted:
                if key in found: raise ValueError('Duplicate evaluation identity in full corpus')
                found.add(key)
                source = wanted[key]['review']
                if row['full_text'] != source['text']:
                    raise ValueError('Evaluation text differs from embedded review')
                if split_for(row, config['seed']) != split_for(source, config['seed']):
                    raise ValueError('Evaluation split mismatch')
                rows.append(source)
                vectors.append(x[i].astype(np.float32))
    if found != set(wanted):
        raise ValueError('Some labeled reviews are absent from review embeddings')
    scores = np.full((len(rows), len(ids)), -2.0, dtype=np.float32)
    topic_index = {tid: j for j, tid in enumerate(ids)}
    actual_scores = score(np.stack(vectors), x_topics)
    for j, topic in enumerate(topic_rows): scores[:, topic_index[topic['topic_id']]] = actual_scores[:, j]
    truth = np.array([[tid in labels[identity(row)]['topics'] for tid in ids] for row in rows], dtype=bool)
    val = np.array([split_for(row, config['seed']) == 'validation' for row in rows])
    if min(val.sum(), (~val).sum()) < 20:
        raise ValueError('Insufficient held-out reviews: need >=20 validation and test reviews')
    grid = sorted(set(float(v) for v in args.threshold_grid.split(',')))
    if not grid or any(not np.isfinite(v) or not -1 <= v <= 1 for v in grid):
        raise ValueError('Threshold grid must contain finite cosine values in [-1,1]')
    best, per_topic, sweep = tune(scores[val], truth[val], ids, grid, args.max_tags, args.min_support)
    actual_ids = {r['topic_id'] for r in topic_rows}
    per_topic = {k: v for k, v in per_topic.items() if k in actual_ids}
    output = {'version': VERSION, 'method': config['method'], 'taxonomy_version': config['taxonomy_version'],
              'topic_embedding_identity': config['identity'], 'seed': config['seed'],
              'partition_counts': {'train_all_labeled': sum(split_for(v['review'], config['seed']) == 'train' for v in labels.values()),
                                   'validation_evaluable': int(val.sum()), 'test_evaluable': int((~val).sum()),
                                   'excluded_uncertain_label_reviews': sum(v['unresolved'] for v in labels.values())},
              'validation_sweep': sweep, 'results': {},
              'limitations': ['Reference labels are machine-generated, not independent human annotations.',
                             'Taxonomy and aspect clustering were created using the full original sample; topic discovery is not held out.',
                             'Prototypes use train text groups only; validation tunes thresholds; test is untouched by tuning.',
                             'Zero-aspect extractions are provisional negatives, not verified absences.',
                             'Reviews containing unresolved aspects are excluded from scoring; results apply only to the evaluable subset.',
                             'Semantic similarity does not validate negation, complaint polarity, or resolution.',
                             'Macro metrics include zero-support topics with zero-division set to zero.']}
    out.mkdir(parents=True, exist_ok=True)
    atomic_parquet(out / 'evaluation_partitions.parquet', pa.Table.from_pylist([
        {'review_key': v['review']['review_key'], 'identity': key,
         'partition': split_for(v['review'], config['seed']), 'evaluable': not v['unresolved']}
        for key, v in sorted(labels.items())]))
    for strategy in ['global', 'per_topic']:
        threshold_config = {'version': VERSION, 'strategy': strategy, 'global_threshold': best,
                            'per_topic': per_topic if strategy == 'per_topic' else {}, 'max_tags': args.max_tags,
                            'topic_embedding_identity': config['identity'],
                            'calibration_source': 'validation_partition_only', 'minimum_positive_and_negative_support': args.min_support}
        values = [threshold_config['per_topic'].get(t, best) for t in ids]
        prediction = predictions(scores, values, args.max_tags)
        output['results'][strategy] = {'validation': metrics(truth[val], prediction[val], ids),
                                        'test': metrics(truth[~val], prediction[~val], ids),
                                        'thresholds': threshold_config}
        atomic_json(out / f'{strategy}_thresholds.json', threshold_config)
        inspection, coverage = inspect_rows([r for r, isval in zip(rows, val) if not isval],
                                            truth[~val], scores[~val], prediction[~val], ids, config['seed'], args.inspection_count)
        if inspection:
            inspection = enrich_rows(inspection, {t['topic_id']: t for t in taxonomy['topics']})
            with (out / f'{strategy}_inspection.csv').open('w', newline='') as f:
                w = csv.DictWriter(f, fieldnames=list(inspection[0])); w.writeheader(); w.writerows(inspection)
        output['results'][strategy]['inspection_candidate_counts'] = coverage
    output['per_topic_tuned_count'] = len(per_topic)
    atomic_json(out / 'evaluation_report.json', output)
    print(json.dumps({'method': config['method'], 'partitions': output['partition_counts'],
                      'global_threshold': best, 'tuned_topics': len(per_topic),
                      'test_micro_f1': output['results']['global']['test']['micro_f1']}, indent=2))
    return output


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run-root', type=Path, required=True)
    p.add_argument('--app', required=True)
    p.add_argument('--topic-embeddings', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--threshold-grid', default='0.2,0.25,0.3,0.35,0.4,0.45,0.5,0.55,0.6,0.65,0.7,0.75,0.8')
    p.add_argument('--max-tags', type=int, default=5)
    p.add_argument('--min-support', type=int, default=5)
    p.add_argument('--inspection-count', type=int, default=120)
    run(p.parse_args())


if __name__ == '__main__':
    main()
