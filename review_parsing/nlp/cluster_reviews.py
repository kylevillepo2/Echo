#!/usr/bin/env python3
"""Cluster step-2 app embeddings and retain review-level metadata.

For each app, writes:
  <output>/apps/<slug>/assignments/part-000000.parquet
  <output>/apps/<slug>/centroids.npy
  <output>/apps/<slug>/clusters.parquet
  <output>/apps/<slug>/manifest.json

Assignment rows preserve the order of the corresponding embedding shard.
Cluster IDs are app-local. Similarity is cosine similarity to the center used
for final assignment; centroids.npy contains unit-normalized mean embeddings
of the assigned reviews.
"""

import argparse
import json
import os
import shutil
import sys
from pathlib import Path


def atomic_json(path, obj):
    temp = path.with_name(path.name + '.tmp')
    with temp.open('w', encoding='utf-8') as fp:
        json.dump(obj, fp, indent=2, ensure_ascii=False)
    os.replace(temp, path)


def discover_apps(input_dir, app_filter):
    index_path = input_dir / 'app_index.json'
    if not index_path.is_file():
        raise ValueError(f'Missing embedding index: {index_path}')
    index = json.loads(index_path.read_text(encoding='utf-8'))
    selected = {name: info for name, info in index.items()
                if not app_filter or name.casefold() == app_filter.casefold()}
    if not selected:
        raise ValueError(f'App {app_filter!r} was not found in {index_path}')
    return selected


def validate_shards(app_dir, info):
    import numpy as np
    import pyarrow.parquet as pq

    manifest_path = app_dir / 'manifest.json'
    if not manifest_path.is_file():
        raise ValueError(f'Missing embedding manifest: {manifest_path}')
    source = json.loads(manifest_path.read_text(encoding='utf-8'))
    if source.get('completed_rows') != info['row_count'] or source.get('slug') != info['slug']:
        raise ValueError(f'Embedding output is incomplete or mismatched: {app_dir}')
    expected_shards = source.get('shard_count')
    if not isinstance(expected_shards, int) or expected_shards < 1:
        raise ValueError(f'Invalid embedding shard count: {app_dir}')
    shards = []
    total = 0
    dimension = None
    for number in range(expected_shards):
        stem = f'part-{number:06d}'
        npy = app_dir / (stem + '.npy')
        parquet = app_dir / (stem + '.parquet')
        done = app_dir / (stem + '.done')
        if not (npy.is_file() and parquet.is_file() and done.is_file()):
            raise ValueError(f'Missing completed embedding shard: {app_dir / stem}')
        marker = json.loads(done.read_text(encoding='utf-8'))
        vectors = np.load(npy, mmap_mode='r', allow_pickle=False)
        metadata = pq.ParquetFile(parquet).metadata
        if vectors.ndim != 2 or vectors.shape[0] != metadata.num_rows or vectors.shape[0] != marker.get('row_count'):
            raise ValueError(f'Embedding/metadata row mismatch: {stem}')
        if dimension is None:
            dimension = vectors.shape[1]
        if vectors.shape[1] != dimension or vectors.shape[1] != marker.get('dimensions'):
            raise ValueError(f'Embedding dimension mismatch: {stem}')
        total += vectors.shape[0]
        shards.append((stem, npy, parquet))
    if total != info['row_count']:
        raise ValueError(f'Expected {info["row_count"]} rows, found {total}: {app_dir}')
    return source, shards, dimension


def normalized(vectors):
    import numpy as np

    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    if not np.all(np.isfinite(norms)) or np.any(norms == 0):
        raise ValueError('Embedding shards contain invalid or zero vectors')
    return vectors / norms


def vector_batches(shards, batch_size):
    import numpy as np

    for _, npy, _ in shards:
        shard = np.load(npy, mmap_mode='r', allow_pickle=False)
        for start in range(0, len(shard), batch_size):
            yield normalized(np.asarray(shard[start:start + batch_size], dtype=np.float32))


def train_centers(shards, k, passes, batch_size, seed):
    import numpy as np
    from sklearn.cluster import MiniBatchKMeans

    model = MiniBatchKMeans(n_clusters=k, batch_size=batch_size, random_state=seed,
                            n_init=1, reassignment_ratio=0)
    for epoch in range(passes):
        pending = []
        pending_rows = 0
        for batch in vector_batches(shards, batch_size):
            if not hasattr(model, 'cluster_centers_') and pending_rows + len(batch) < k:
                pending.append(batch)
                pending_rows += len(batch)
                continue
            if pending:
                pending.append(batch)
                batch = np.concatenate(pending)
                pending.clear()
                pending_rows = 0
            model.partial_fit(batch)
        print(f'  training pass {epoch + 1}/{passes} complete', flush=True)
    return normalized(model.cluster_centers_.astype(np.float32))


def assign(vectors, centers):
    import numpy as np

    similarities = vectors @ centers.T
    ids = similarities.argmax(axis=1).astype(np.int32)
    scores = similarities[np.arange(len(ids)), ids]
    return ids, scores


def exact_centers(shards, centers, dimension, batch_size):
    import numpy as np

    sums = np.zeros((len(centers), dimension), dtype=np.float64)
    counts = np.zeros(len(centers), dtype=np.int64)
    for vectors in vector_batches(shards, batch_size):
        ids, _ = assign(vectors, centers)
        np.add.at(sums, ids, vectors)
        counts += np.bincount(ids, minlength=len(centers))
    result = centers.copy()
    nonempty = counts > 0
    result[nonempty] = normalized(sums[nonempty].astype(np.float32))
    return result


def write_assignments(shards, centers, dimension, batch_size, workdir):
    import numpy as np
    import pyarrow as pa
    import pyarrow.parquet as pq

    assignment_dir = workdir / 'assignments'
    assignment_dir.mkdir()
    sums = np.zeros((len(centers), dimension), dtype=np.float64)
    counts = np.zeros(len(centers), dtype=np.int64)
    similarity_sums = np.zeros(len(centers), dtype=np.float64)
    for stem, npy, parquet in shards:
        vectors = np.load(npy, mmap_mode='r', allow_pickle=False)
        source = pq.read_table(parquet)
        labels = np.empty(len(vectors), dtype=np.int32)
        scores = np.empty(len(vectors), dtype=np.float32)
        for start in range(0, len(vectors), batch_size):
            stop = min(start + batch_size, len(vectors))
            batch = normalized(np.asarray(vectors[start:stop], dtype=np.float32))
            ids, similarity = assign(batch, centers)
            labels[start:stop] = ids
            scores[start:stop] = similarity
            np.add.at(sums, ids, batch)
            counts += np.bincount(ids, minlength=len(centers))
            similarity_sums += np.bincount(ids, weights=similarity, minlength=len(centers))
        result = source.append_column('cluster_id', pa.array(labels))
        result = result.append_column('centroid_similarity', pa.array(scores))
        pq.write_table(result, assignment_dir / (stem + '.parquet'), compression='zstd')
        print(f'  assigned {stem}: {len(vectors):,} reviews', flush=True)

    exact = centers.copy()
    nonempty = counts > 0
    exact[nonempty] = normalized(sums[nonempty].astype(np.float32))
    with (workdir / 'centroids.npy').open('wb') as fp:
        np.save(fp, exact)
    summary = pa.table({
        'cluster_id': pa.array(np.arange(len(centers), dtype=np.int32)),
        'size': pa.array(counts),
        'mean_assignment_similarity': pa.array(
            np.divide(similarity_sums, counts, out=np.zeros(len(centers)), where=nonempty).astype(np.float32)),
    })
    pq.write_table(summary, workdir / 'clusters.parquet', compression='zstd')
    return counts


def cluster_app(app, info, input_dir, output_dir, k_requested, passes, batch_size, seed):
    import numpy as np

    source_dir = input_dir / 'apps' / info['slug']
    source, shards, dimension = validate_shards(source_dir, info)
    k = min(k_requested, info['row_count'])
    target = output_dir / 'apps' / info['slug']
    expected = {'app': app, 'slug': info['slug'], 'row_count': info['row_count'],
                'embedding_model': source['model'], 'embedding_dimension': dimension,
                'clusters_requested': k_requested, 'clusters': k,
                'passes': passes, 'batch_size': batch_size, 'seed': seed,
                'method': 'MiniBatchKMeans with cosine assignment'}
    if target.exists():
        manifest_path = target / 'manifest.json'
        if manifest_path.is_file():
            old = json.loads(manifest_path.read_text(encoding='utf-8'))
            if all(old.get(key) == value for key, value in expected.items()) and old.get('completed_rows') == info['row_count']:
                print(f'{app}: already clustered; reusing {target}', flush=True)
                return
        raise ValueError(f'Output already exists with different or incomplete settings: {target}')

    target.parent.mkdir(parents=True, exist_ok=True)
    workdir = target.with_name(target.name + '.incomplete')
    if workdir.exists():
        shutil.rmtree(workdir)
    workdir.mkdir()
    try:
        print(f'{app}: training {k} clusters from {info["row_count"]:,} reviews', flush=True)
        centers = train_centers(shards, k, passes, batch_size, seed)
        centers = exact_centers(shards, centers, dimension, batch_size)
        counts = write_assignments(shards, centers, dimension, batch_size, workdir)
        if int(counts.sum()) != info['row_count']:
            raise RuntimeError(f'Assignment count mismatch for {app}')
        atomic_json(workdir / 'manifest.json', {
            **expected, 'completed_rows': int(counts.sum()),
            'nonempty_clusters': int(np.count_nonzero(counts)),
            'empty_clusters': int(np.count_nonzero(counts == 0)),
            'source_manifest': str((source_dir / 'manifest.json').resolve()),
        })
        os.replace(workdir, target)
        print(f'{app}: complete, {np.count_nonzero(counts)} nonempty clusters -> {target}', flush=True)
    except Exception:
        shutil.rmtree(workdir, ignore_errors=True)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--input', type=Path, required=True, help='Step-2 embeddings directory')
    parser.add_argument('--output', type=Path, required=True, help='Clustering output directory')
    parser.add_argument('--app', help='Cluster only this app (case insensitive exact match)')
    parser.add_argument('--clusters', type=int, default=200, help='Clusters per app (default: 200)')
    parser.add_argument('--passes', type=int, default=3, help='Training passes over shards (default: 3)')
    parser.add_argument('--batch-size', type=int, default=2048, help='Streaming batch size (default: 2048)')
    parser.add_argument('--seed', type=int, default=42)
    args = parser.parse_args()
    if args.clusters < 1 or args.passes < 1 or args.batch_size < 1:
        parser.error('--clusters, --passes, and --batch-size must be positive')
    if args.input.resolve() == args.output.resolve():
        parser.error('--input and --output must differ')
    apps = discover_apps(args.input, args.app)
    for app, info in apps.items():
        cluster_app(app, info, args.input, args.output, args.clusters,
                    args.passes, args.batch_size, args.seed)


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, RuntimeError) as exc:
        print(f'Error: {exc}', file=sys.stderr)
        sys.exit(1)
