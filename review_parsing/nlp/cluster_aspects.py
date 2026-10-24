#!/usr/bin/env python3
"""Cluster aspect embedding shards with UMAP and scikit-learn HDBSCAN.

The output retains every aspect's review, sampling, category, and polarity
metadata. Noise aspects are preserved separately for later inspection.
"""

import argparse
import csv
import json
import os
import shutil
import sys
from collections import Counter
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
from sklearn.cluster import HDBSCAN


SUMMARY_COLUMNS = [
    'aspect_cluster_id', 'aspect_observations', 'unique_reviews',
    'mean_similarity_to_centroid', 'mean_membership_strength',
    'top_category', 'top_polarity', 'example_description',
]
OUTPUT_FILES = [
    'aspect_clusters.parquet', 'cluster_summary.csv', 'representative_aspects.csv',
    'representative_aspects.parquet', 'noise_aspects.parquet', 'run_config.json',
]


def load_shards(source):
    manifest_path = source / 'manifest.json'
    if not manifest_path.is_file():
        raise ValueError(f'Missing embedding manifest: {manifest_path}')
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    if manifest.get('status') != 'complete':
        raise ValueError(f'Aspect embeddings are not complete: {source}')
    count = manifest.get('aspect_count')
    shards = manifest.get('completed_shards')
    dimension = manifest.get('embedding_dimension')
    if not all(isinstance(value, int) and value > 0 for value in (count, shards, dimension)):
        raise ValueError('Invalid embedding manifest counts or dimension')
    arrays, tables = [], []
    for number in range(shards):
        stem = f'part-{number:06d}'
        array_path = source / (stem + '.npy')
        meta_path = source / (stem + '.parquet')
        if not array_path.is_file() or not meta_path.is_file():
            raise ValueError(f'Missing aspect embedding shard: {stem}')
        vectors = np.load(array_path, mmap_mode='r', allow_pickle=False)
        metadata = pq.read_table(meta_path)
        if (vectors.ndim != 2 or vectors.shape[1] != dimension or
                vectors.shape[0] != metadata.num_rows):
            raise ValueError(f'Embedding and metadata shape mismatch: {stem}')
        arrays.append(np.asarray(vectors, dtype=np.float32))
        tables.append(metadata)
    if len(list(source.glob('part-*.npy'))) != shards or len(list(source.glob('part-*.parquet'))) != shards:
        raise ValueError('Unexpected extra aspect embedding shards')
    meta = pa.concat_tables(tables)
    if sum(len(part) for part in arrays) != count or meta.num_rows != count:
        raise ValueError('Manifest aspect count differs from shard rows')
    required = {'aspect_id', 'review_key', 'description'}
    if not required <= set(meta.column_names):
        raise ValueError(f'Missing aspect metadata columns: {sorted(required - set(meta.column_names))}')
    ids = meta.column('aspect_id').to_pylist()
    if len(set(ids)) != count or any(not isinstance(item, str) or not item for item in ids):
        raise ValueError('Aspect IDs are missing or duplicated')
    X = np.concatenate(arrays)
    if not np.isfinite(X).all():
        raise ValueError('Non-finite embeddings')
    norms = np.linalg.norm(X, axis=1, keepdims=True)
    if (norms == 0).any():
        raise ValueError('Zero length embedding')
    return X / norms, meta, manifest


def most_common(values):
    counts = Counter(str(value) if value is not None else 'unknown' for value in values)
    return min(counts, key=lambda value: (-counts[value], value)) if counts else 'unknown'


def write_csv(path, rows, columns):
    with path.open('w', newline='', encoding='utf-8') as fp:
        writer = csv.DictWriter(fp, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def summarize(X, result, labels, strength, representatives, seed):
    records = result.to_pylist()
    rng = np.random.default_rng(seed)
    summaries = []
    chosen_indices, chosen_roles, chosen_similarities = [], [], []
    for cluster_id in sorted(set(labels) - {-1}):
        indices = np.flatnonzero(labels == cluster_id)
        original = X[indices]
        centroid = original.mean(axis=0)
        norm = np.linalg.norm(centroid)
        if norm == 0 or not np.isfinite(norm):
            raise ValueError(f'Invalid centroid for cluster {cluster_id}')
        centroid /= norm
        similarities = original @ centroid
        order = np.argsort(-similarities, kind='stable')[:representatives]
        random_positions = rng.choice(len(indices), size=min(representatives, len(indices)), replace=False)
        cluster_rows = [records[i] for i in indices]
        summaries.append({
            'aspect_cluster_id': int(cluster_id),
            'aspect_observations': len(indices),
            'unique_reviews': len({row['review_key'] for row in cluster_rows}),
            'mean_similarity_to_centroid': float(similarities.mean()),
            'mean_membership_strength': float(strength[indices].mean()),
            'top_category': most_common(row.get('category') for row in cluster_rows),
            'top_polarity': most_common(row.get('polarity') for row in cluster_rows),
            'example_description': cluster_rows[int(order[0])]['description'],
        })
        for role, positions in (('centroid', order), ('random', random_positions)):
            for position in positions:
                chosen_indices.append(int(indices[position]))
                chosen_roles.append(role)
                chosen_similarities.append(float(similarities[position]))
    summaries.sort(key=lambda row: (-row['aspect_observations'], row['aspect_cluster_id']))
    selected = result.take(pa.array(chosen_indices, type=pa.int64()))
    selected = selected.append_column('sample_role', pa.array(chosen_roles, type=pa.string()))
    selected = selected.append_column('cosine_similarity_to_centroid',
                                      pa.array(chosen_similarities, type=pa.float32()))
    return summaries, selected


def run(args):
    source = args.input.expanduser().resolve()
    target = args.output.expanduser().resolve()
    if source == target or source in target.parents or target in source.parents:
        raise ValueError('Input and output directories must be separate')
    if not source.is_dir():
        raise ValueError(f'Input folder not found: {source}')
    if args.representatives < 1 or args.neighbors < 2 or args.umap_dims < 2:
        raise ValueError('--representatives must be positive; --neighbors and --umap-dims must be >= 2')
    if target.exists() and any(target.iterdir()) and not args.allow_existing:
        raise FileExistsError(f'Output folder is not empty: {target}. Use a new --output or --allow-existing.')
    if target.exists() and args.allow_existing:
        unexpected = {path.name for path in target.iterdir()} - set(OUTPUT_FILES)
        if unexpected:
            raise ValueError(f'Refusing to replace output with unrelated files: {sorted(unexpected)}')

    X, meta, source_manifest = load_shards(source)
    n = len(X)
    if n < 4:
        raise ValueError('Need at least four aspects')
    if not 2 <= args.min_cluster_size <= n:
        raise ValueError('--min-cluster-size must be between 2 and number of aspects')
    if not 1 <= args.min_samples <= n:
        raise ValueError('--min-samples must be between 1 and number of aspects')

    if args.no_umap:
        Z = X
        neighbors = dims = None
    else:
        try:
            import umap
        except ImportError as exc:
            raise RuntimeError('UMAP is missing. Install umap-learn or run with --no-umap.') from exc
        neighbors = min(args.neighbors, n - 1)
        dims = min(args.umap_dims, n - 2, X.shape[1])
        print(f'UMAP: {n:,} aspects, {X.shape[1]} -> {dims} dimensions, '
              f'{neighbors} neighbors', flush=True)
        Z = umap.UMAP(n_components=dims, n_neighbors=neighbors, min_dist=0.0,
                      metric='cosine', random_state=args.random_state, n_jobs=1).fit_transform(X)
    if not np.isfinite(Z).all():
        raise ValueError('Dimensionality reduction produced non-finite vectors')
    clusterer = HDBSCAN(min_cluster_size=args.min_cluster_size,
                        min_samples=args.min_samples, metric='euclidean',
                        cluster_selection_method='eom', copy=False)
    labels = clusterer.fit_predict(Z).astype(np.int32)
    strength = np.asarray(clusterer.probabilities_, dtype=np.float32)
    if strength.shape != (n,) or not np.isfinite(strength).all():
        raise ValueError('HDBSCAN returned invalid membership strengths')
    result = meta.append_column('aspect_cluster_id', pa.array(labels))
    result = result.append_column('cluster_membership_strength', pa.array(strength))
    result = result.append_column('is_noise', pa.array(labels == -1))
    summaries, selected = summarize(X, result, labels, strength,
                                    args.representatives, args.random_state)
    noise = result.filter(pa.array(labels == -1))
    config = {
        'input': str(source), 'input_source_sha256': source_manifest.get('config', {}).get('source_sha256'),
        'aspects': n, 'clustered_aspects': int((labels != -1).sum()),
        'noise_aspects': int((labels == -1).sum()), 'clusters': len(summaries),
        'min_cluster_size': args.min_cluster_size, 'min_samples': args.min_samples,
        'umap_dims': dims, 'neighbors': neighbors, 'random_state': args.random_state,
        'representatives': args.representatives, 'method': 'sklearn.HDBSCAN',
    }

    target.parent.mkdir(parents=True, exist_ok=True)
    work = target.parent / (target.name + '.incomplete')
    if work.exists():
        raise FileExistsError(f'Previous incomplete output exists: {work}. Remove it before retrying.')
    work.mkdir()
    try:
        pq.write_table(result, work / 'aspect_clusters.parquet')
        write_csv(work / 'cluster_summary.csv', summaries, SUMMARY_COLUMNS)
        pq.write_table(selected, work / 'representative_aspects.parquet')
        write_csv(work / 'representative_aspects.csv', selected.to_pylist(), selected.column_names)
        pq.write_table(noise, work / 'noise_aspects.parquet')
        (work / 'run_config.json').write_text(json.dumps(config, indent=2), encoding='utf-8')
        if target.exists():
            target.rmdir() if not any(target.iterdir()) else shutil.rmtree(target)
        os.replace(work, target)
    except Exception:
        shutil.rmtree(work, ignore_errors=True)
        raise
    print(f'Found {len(summaries)} clusters; {len(noise):,}/{n:,} aspects are noise '
          f'({len(noise) / n:.1%}).', flush=True)
    print(f'Assignments: {target / "aspect_clusters.parquet"}', flush=True)
    print(f'Step 8 input: {target / "representative_aspects.parquet"}', flush=True)
    if n < 200:
        print('Small dataset: cluster quality may be unstable.', flush=True)
    return config


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--min-cluster-size', type=int, default=5)
    parser.add_argument('--min-samples', type=int, default=3)
    parser.add_argument('--umap-dims', type=int, default=10)
    parser.add_argument('--neighbors', type=int, default=15)
    parser.add_argument('--no-umap', action='store_true')
    parser.add_argument('--representatives', type=int, default=5)
    parser.add_argument('--random-state', type=int, default=42)
    parser.add_argument('--allow-existing', action='store_true')
    run(parser.parse_args())


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, RuntimeError) as exc:
        print(f'Error: {exc}', file=sys.stderr)
        sys.exit(1)
