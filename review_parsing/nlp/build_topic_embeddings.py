#!/usr/bin/env python3
"""Build approved-topic description vectors or training-only aspect prototypes."""
import argparse
from collections import Counter
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from similarity_common import (VERSION, atomic_json, atomic_parquet, compatible, digest,
                               fingerprint, normalize, read_json, review_inputs, split_for)


def run(args, encoder=None):
    run_root = args.run_root.resolve()
    taxonomy_path = run_root / 'refined-topics/canonical_topics.json'
    refined_path = run_root / 'refined-topics/refined_aspects.parquet'
    taxonomy = read_json(taxonomy_path)
    name, review_manifest, dim, _ = review_inputs(run_root / 'review-embeddings', args.app)
    refined = pq.read_table(refined_path).to_pylist()
    if any(r['app_name'] != name for r in refined):
        raise ValueError('Refined aspect app differs from requested app')
    blocked = {r['cluster_id'] for r in taxonomy.get('clusters_needing_split', []) + taxonomy.get('clusters_needing_review', [])}
    topics = sorted((t for t in taxonomy['topics'] if t['relevance_status'] == 'keep'
                     and not blocked.intersection(t['original_cluster_ids'])), key=lambda t: t['topic_id'])
    if not topics or len({t['topic_id'] for t in topics}) != len(topics):
        raise ValueError('No approved topics or duplicate topic IDs')
    config = {'version': VERSION, 'app': name, 'method': args.method, 'seed': args.seed,
              'taxonomy_version': digest(taxonomy_path), 'model': review_manifest['model'],
              'dimension': dim, 'refined_sha256': digest(refined_path),
              'split_policy': 'normalized-text-sha256-60/20/20',
              'prototype_partition': 'train', 'excluded_topic_count': len(taxonomy['topics']) - len(topics)}
    rows, vectors, missing = [], [], []
    train_by_topic = {t['topic_id']: [] for t in topics}
    if args.method == 'prototype':
        manifest = read_json(run_root / 'aspect-embeddings/manifest.json')
        compatible(config['model'], dim, manifest['config']['model'], manifest['embedding_dimension'])
        if manifest.get('status') != 'complete':
            raise ValueError('Aspect embeddings incomplete')
        by_id = {r['aspect_id']: r for r in refined}
        if len(by_id) != len(refined):
            raise ValueError('Duplicate refined aspect IDs')
        seen, hashes = set(), []
        for i in range(manifest['completed_shards']):
            path = run_root / 'aspect-embeddings' / f'part-{i:06d}.npy'
            meta = pq.read_table(path.with_suffix('.parquet')).to_pylist()
            x = normalize(np.load(path, allow_pickle=False))
            compatible(config['model'], dim, manifest['config']['model'], x.shape[1])
            if len(x) != len(meta):
                raise ValueError('Aspect embedding alignment failed')
            hashes.append([digest(path), digest(path.with_suffix('.parquet'))])
            for row, vector in zip(meta, x):
                aid = row['aspect_id']
                if aid in seen or aid not in by_id:
                    raise ValueError('Aspect ID duplicate or absent from refinement')
                seen.add(aid)
                ref = by_id[aid]
                if row['review_key'] != ref['review_key'] or row['description'] != ref['description']:
                    raise ValueError('Aspect metadata does not match refinement')
                if ref['topic_id'] in train_by_topic and ref['relevance_status'] == 'keep' and split_for(ref, args.seed) == 'train':
                    train_by_topic[ref['topic_id']].append((ref, vector))
        if len(seen) != len(refined) or len(seen) != manifest['aspect_count']:
            raise ValueError('Aspect coverage mismatch')
        config['aspect_shard_hashes'] = hashes
    else:
        if encoder is None:
            from sentence_transformers import SentenceTransformer
            encoder = SentenceTransformer(config['model'], device=args.device, local_files_only=True)
        texts = [f"Topic: {t['canonical_name']}\nDescription: {t['definition']}" for t in topics]
        vectors = list(normalize(encoder.encode(texts, batch_size=64, convert_to_numpy=True,
                                                normalize_embeddings=True, show_progress_bar=False)))
    for topic in topics:
        members = train_by_topic[topic['topic_id']]
        if args.method == 'prototype':
            if not members:
                missing.append(topic['topic_id'])
                continue
            vectors.append(normalize(np.mean([x for _, x in members], axis=0, keepdims=True))[0])
        # Polarity is descriptive training metadata, never inferred for new reviews.
        polarities = Counter(r['polarity'] for r in refined if r['topic_id'] == topic['topic_id']
                             and split_for(r, args.seed) == 'train')
        rows.append({**topic, 'embedding_row': len(rows),
                     'training_aspect_count': len(members),
                     'distinct_training_reviews': len({r['review_key'] for r, _ in members}),
                     'training_review_keys': sorted({r['review_key'] for r, _ in members}),
                     'training_polarity_counts': __import__('json').dumps(dict(polarities), sort_keys=True)})
    if not vectors:
        raise ValueError('No training prototypes available')
    x = normalize(np.stack(vectors))
    compatible(config['model'], dim, config['model'], x.shape[1])
    config['topics_without_training_prototypes'] = missing
    config['topic_ids'] = [r['topic_id'] for r in rows]
    out = args.output.resolve()
    if out.exists() and any(out.iterdir()):
        raise ValueError('Use a new empty topic output folder')
    out.mkdir(parents=True, exist_ok=True)
    with (out / 'topic_vectors.npy.tmp').open('wb') as f:
        np.save(f, x)
    (out / 'topic_vectors.npy.tmp').replace(out / 'topic_vectors.npy')
    atomic_parquet(out / 'topic_metadata.parquet', pa.Table.from_pylist(rows))
    config['vectors_sha256'] = digest(out / 'topic_vectors.npy')
    config['metadata_sha256'] = digest(out / 'topic_metadata.parquet')
    config['identity'] = fingerprint(config)
    atomic_json(out / 'config.json', config)
    print(f"Built {len(rows)} {args.method} topics; omitted {len(missing)} without training examples")
    return config


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run-root', type=Path, required=True)
    p.add_argument('--app', required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--method', choices=['description', 'prototype'], required=True)
    p.add_argument('--seed', type=int, default=42)
    p.add_argument('--device', default='cpu')
    run(p.parse_args())


if __name__ == '__main__':
    main()
