#!/usr/bin/env python3
"""Stream existing review embeddings into resumable multilabel topic assignments."""
import argparse
import os
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from similarity_common import (VERSION, atomic_json, atomic_parquet, choose, compatible,
                               digest, fingerprint, identity, load_topics, read_json,
                               review_inputs, score, threshold_values)

TOPICS_TYPE = pa.list_(pa.struct([('topic_id', pa.string()), ('similarity', pa.float32()),
                                ('sentiment', pa.string()), ('sentiment_source', pa.string())]))


def known_labels(root):
    reviews, polarities = {}, defaultdict(set)
    for path in (root / 'aspects').glob('*/review_extractions.parquet'):
        for row in pq.read_table(path).to_pylist():
            key = identity(row)
            if key in reviews: raise ValueError('Duplicate sampled review identity')
            reviews[key] = row
    for row in pq.read_table(root / 'refined-topics/refined_aspects.parquet').to_pylist():
        if row.get('topic_id') and row.get('relevance_status') == 'keep':
            polarities[(identity(row), row['topic_id'])].add(row['polarity'])
    return reviews, polarities


def run(args):
    started = time.monotonic()
    if args.batch_size < 1: raise ValueError('batch-size must be positive')
    root = args.run_root.resolve()
    topics, topic_rows, tc = load_topics(args.topic_embeddings)
    ids = [r['topic_id'] for r in topic_rows]
    app, manifest, dim, files = review_inputs(root / 'review-embeddings', args.app)
    compatible(manifest['model'], dim, tc['model'], tc['dimension'])
    if tc['app'] != app or tc['taxonomy_version'] != digest(root / 'refined-topics/canonical_topics.json'):
        raise ValueError('Topic app/taxonomy differs from source')
    if tc['refined_sha256'] != digest(root / 'refined-topics/refined_aspects.parquet'):
        raise ValueError('Refinement changed since topic embedding construction')
    thresholds = read_json(args.threshold_config) if args.threshold_config else {
        'strategy': 'global', 'global_threshold': args.threshold, 'per_topic': {}, 'max_tags': args.max_tags,
        'topic_embedding_identity': tc['identity'], 'calibration_source': 'user_supplied_unvalidated'}
    if thresholds.get('topic_embedding_identity') != tc['identity']:
        raise ValueError('Thresholds belong to different topic embeddings')
    values = threshold_values(thresholds, ids)
    sampled, polarities = known_labels(root)
    extraction_hashes = [digest(p) for p in sorted((root / 'aspects').glob('*/review_extractions.parquet'))]
    config = {'version': VERSION, 'app': app, 'model': tc['model'], 'dimension': dim,
              'taxonomy_version': tc['taxonomy_version'], 'topic_embedding_identity': tc['identity'],
              'representation': tc['method'], 'thresholds': thresholds, 'batch_size': args.batch_size,
              'input_shards': files, 'extraction_hashes': extraction_hashes,
              'implementation_sha256': fingerprint([digest(Path(__file__)), digest(Path(__file__).with_name('similarity_common.py'))])}
    config['identity'] = fingerprint(config)
    out = args.output.resolve()
    if (out / 'config.json').exists():
        if read_json(out / 'config.json') != config:
            raise ValueError('Resume input/settings changed; use a new output folder')
    elif out.exists() and any(out.iterdir()):
        raise ValueError('Existing output has no matching config; use a new folder')
    else:
        out.mkdir(parents=True, exist_ok=True)
        atomic_json(out / 'config.json', config)
    total = 0
    seen = set()
    counts, topics_count = Counter(), Counter()
    hist = np.zeros(40, dtype=np.int64)
    sim_sum, sim_n = 0., 0
    sim_min, sim_max = None, None
    resumed = 0
    full_tmp = out / 'tagged_reviews.parquet.tmp'
    writer = None
    try:
        for file in files:
            source = pq.read_table(file['metadata'])
            metadata = source.to_pylist()
            source_ids = [identity(r) for r in metadata]
            if len(set(source_ids)) != len(source_ids) or seen.intersection(source_ids):
                raise ValueError('Duplicate source review identity; cannot guarantee one output per review')
            seen.update(source_ids)
            part = out / (file['stem'] + '.parquet')
            marker = out / (file['stem'] + '.done.json')
            if marker.exists():
                done = read_json(marker)
                if done['config_identity'] != config['identity'] or digest(part) != done['sha256']:
                    raise ValueError('Completed output shard failed hash validation')
                table = pq.read_table(part)
                if [identity(r) for r in table.to_pylist()] != source_ids:
                    raise ValueError('Completed output does not align with input metadata')
                resumed += 1
            else:
                x = np.load(file['vectors'], mmap_mode='r', allow_pickle=False)
                tags, keys = [], []
                for start in range(0, len(metadata), args.batch_size):
                    sims = score(x[start:start + args.batch_size], topics)
                    matches = choose(sims, values, thresholds['max_tags'])
                    for offset, indices in enumerate(matches):
                        row = metadata[start + offset]
                        key = identity(row)
                        old = sampled.get(key)
                        if old and row['full_text'] != old['text']:
                            raise ValueError('Sampled review text differs from embedded source')
                        keys.append(old['review_key'] if old else f"{manifest['slug']}:{key}")
                        assigned = []
                        for j in indices:
                            ps = polarities.get((key, ids[j]), set())
                            sentiment = next(iter(ps)) if len(ps) == 1 else 'mixed' if ps else 'unknown'
                            assigned.append({'topic_id': ids[j], 'similarity': float(sims[offset, j]),
                                             'sentiment': sentiment,
                                             'sentiment_source': 'existing_aspect_polarity' if ps else 'unknown'})
                        tags.append(assigned)
                table = source.append_column('review_key', pa.array(keys, type=pa.string()))
                table = table.append_column('app_id', pa.array([manifest['slug']] * len(table)))
                table = table.append_column('topics', pa.array(tags, type=TOPICS_TYPE))
                table = table.append_column('method', pa.array(['semantic_similarity'] * len(table)))
                table = table.append_column('taxonomy_version', pa.array([tc['taxonomy_version']] * len(table)))
                table = table.append_column('topic_representation', pa.array([tc['method']] * len(table)))
                atomic_parquet(part, table)
                atomic_json(marker, {'config_identity': config['identity'], 'rows': len(table), 'sha256': digest(part)})
            if len(table) != file['rows']: raise ValueError('Output row count mismatch')
            if writer is None: writer = pq.ParquetWriter(full_tmp, table.schema)
            writer.write_table(table)
            for taglist in table.column('topics').to_pylist():
                if len({t['topic_id'] for t in taglist}) != len(taglist):
                    raise ValueError('Duplicate review/topic assignment')
                counts[len(taglist)] += 1
                for tag in taglist:
                    topics_count[tag['topic_id']] += 1
                    s = tag['similarity']; sim_sum += s; sim_n += 1
                    sim_min = s if sim_min is None else min(s, sim_min)
                    sim_max = s if sim_max is None else max(s, sim_max)
                    hist[min(39, max(0, int((s + 1) * 20)))] += 1
            total += len(table)
            print(f'{file["stem"]}: {total:,}/{manifest["row_count"]:,}', flush=True)
        if total != manifest['row_count'] or len(seen) != total:
            raise ValueError('Input/output population does not reconcile')
        writer.close(); writer = None
        os.replace(full_tmp, out / 'tagged_reviews.parquet')
    finally:
        if writer: writer.close()
    labels = {r['topic_id']: r['canonical_name'] for r in topic_rows}
    report = {'version': VERSION, 'app': app, 'total_reviews_processed': total,
              'reviews_with_topics': total - counts[0], 'reviews_without_topics': counts[0],
              'average_topics_per_review': sim_n / total,
              'topic_count_distribution': dict(sorted(counts.items())),
              'top_20_topics': [{'topic_id': tid, 'name': labels[tid], 'assigned_reviews': n}
                                for tid, n in topics_count.most_common(20)],
              'accepted_similarity_distribution': {'count': sim_n, 'min': sim_min, 'max': sim_max,
                  'mean': sim_sum / sim_n if sim_n else None,
                  'histogram_edges': np.linspace(-1, 1, 41).tolist(), 'histogram_counts': hist.tolist()},
              'embedding_model': tc['model'], 'taxonomy_version': tc['taxonomy_version'],
              'representation': tc['method'], 'threshold_configuration': thresholds,
              'runtime_seconds_this_invocation': time.monotonic() - started, 'resumed_shards': resumed,
              'output_sha256': digest(out / 'tagged_reviews.parquet'),
              'interpretation': 'Semantic topic matches, not calibrated probabilities or verified complaints. New sentiment remains unknown.'}
    atomic_json(out / 'tagging_report.json', report)
    print(f'Done: {total:,} reviews; {total-counts[0]:,} with topics; {resumed} resumed shards')
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run-root', type=Path, required=True)
    p.add_argument('--app', required=True)
    p.add_argument('--topic-embeddings', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    t = p.add_mutually_exclusive_group(required=True)
    t.add_argument('--threshold-config', type=Path)
    t.add_argument('--threshold', type=float, help='Explicit baseline; evaluate before interpreting')
    p.add_argument('--max-tags', type=int, default=5, help='Used only with --threshold')
    p.add_argument('--batch-size', type=int, default=1024)
    run(p.parse_args())


if __name__ == '__main__':
    main()
