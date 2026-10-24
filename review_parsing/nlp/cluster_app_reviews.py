#!/usr/bin/env python3
"""Cluster an app's embedding shards and select reviews for aspect extraction.

Training uses a uniform random sample of reviews. Every review is assigned to
its nearest normalized K-means center by cosine similarity. Output for each app:

  <output>/<app_slug>/centroids.npy
  <output>/<app_slug>/cluster_summary.csv
  <output>/<app_slug>/cluster_samples.csv
  <output>/<app_slug>/cluster_samples.parquet
  <output>/<app_slug>/run_config.json
  <output>/<app_slug>/assignments/part-000000.parquet ...

Only sample_type=random has a known inclusion_probability and should be used
for cluster-level prevalence estimates. Representative and boundary reviews
are selected for inspection and qualitative aspect discovery.
"""

import argparse
import csv
import heapq
import json
import os
import shutil
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


def load_app(embedding_root, app):
    import numpy as np
    import pyarrow.parquet as pq

    index_path = embedding_root / 'app_index.json'
    if not index_path.is_file():
        raise ValueError(f'Missing embedding index: {index_path}')
    index = json.loads(index_path.read_text(encoding='utf-8'))
    matches = [(name, value) for name, value in index.items() if name.casefold() == app.casefold()]
    if len(matches) != 1:
        raise ValueError(f'App {app!r} not found uniquely in {index_path}')
    app_name, info = matches[0]
    folder = embedding_root / 'apps' / info['slug']
    manifest_path = folder / 'manifest.json'
    if not manifest_path.is_file():
        raise ValueError(f'Missing completed app manifest: {manifest_path}')
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    total = info['row_count']
    if manifest.get('completed_rows') != total or manifest.get('slug') != info['slug']:
        raise ValueError(f'Embedding app is incomplete or mismatched: {folder}')
    shard_count = manifest.get('shard_count')
    if not isinstance(shard_count, int) or shard_count < 1:
        raise ValueError(f'Invalid shard count in {manifest_path}')
    shards = []
    dimension = None
    observed = 0
    for number in range(shard_count):
        stem = f'part-{number:06d}'
        vector_path = folder / (stem + '.npy')
        meta_path = folder / (stem + '.parquet')
        done_path = folder / (stem + '.done')
        if not all(path.is_file() for path in (vector_path, meta_path, done_path)):
            raise ValueError(f'Missing completed shard: {folder / stem}')
        vectors = np.load(vector_path, mmap_mode='r', allow_pickle=False)
        marker = json.loads(done_path.read_text(encoding='utf-8'))
        rows = pq.ParquetFile(meta_path).metadata.num_rows
        if vectors.ndim != 2 or len(vectors) != rows or rows != marker.get('row_count'):
            raise ValueError(f'Embedding/metadata row mismatch: {stem}')
        if dimension is None:
            dimension = vectors.shape[1]
        if vectors.shape[1] != dimension or dimension != marker.get('dimensions'):
            raise ValueError(f'Embedding dimension mismatch: {stem}')
        shards.append((stem, vector_path, meta_path, rows))
        observed += rows
    if observed != total:
        raise ValueError(f'Expected {total} reviews, found {observed} in {folder}')
    return app_name, info['slug'], manifest, shards, dimension, total


def unit_vectors(vectors):
    import numpy as np

    array = np.asarray(vectors, dtype=np.float32)
    norms = np.linalg.norm(array, axis=1, keepdims=True)
    if not np.all(np.isfinite(norms)) or np.any(norms == 0):
        raise ValueError('Embedding shard contains an invalid or zero vector')
    return array / norms


def uniform_training_sample(shards, total, train_size, rng):
    import numpy as np

    count = min(train_size, total)
    selected = np.sort(rng.choice(total, size=count, replace=False))
    samples = []
    offset = 0
    for _, vector_path, _, rows in shards:
        lo = np.searchsorted(selected, offset, side='left')
        hi = np.searchsorted(selected, offset + rows, side='left')
        if hi > lo:
            vectors = np.load(vector_path, mmap_mode='r', allow_pickle=False)
            samples.append(unit_vectors(vectors[selected[lo:hi] - offset]))
        offset += rows
    result = np.concatenate(samples)
    if len(result) != count:
        raise RuntimeError('Training sample count mismatch')
    return result


def score_batch(vectors, centers):
    import numpy as np

    similarities = vectors @ centers.T
    labels = similarities.argmax(axis=1).astype(np.int32)
    best = similarities[np.arange(len(labels)), labels].astype(np.float32)
    if centers.shape[0] > 1:
        second = np.partition(similarities, -2, axis=1)[:, -2]
        margins = (best - second).astype(np.float32)
    else:
        margins = np.zeros(len(labels), dtype=np.float32)
    return labels, best, margins


def keep_top(heap, amount, priority, sequence, record):
    if amount == 0:
        return
    item = (priority, sequence, record)
    if len(heap) < amount:
        heapq.heappush(heap, item)
    elif priority > heap[0][0]:
        heapq.heapreplace(heap, item)


def write_csv(path, rows, columns):
    with path.open('w', newline='', encoding='utf-8') as fp:
        writer = csv.DictWriter(fp, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def run(args):
    import numpy as np
    import pyarrow as pa
    import pyarrow.parquet as pq
    from sklearn.cluster import MiniBatchKMeans

    embedding_root = Path(args.embedding_root)
    app, slug, source_manifest, shards, dimension, total = load_app(embedding_root, args.app)
    k = min(args.clusters, total)
    output_root = Path(args.output)
    output_root.mkdir(parents=True, exist_ok=True)
    target = output_root / slug
    if target.exists() and not args.overwrite:
        raise ValueError(f'Output already exists: {target}. Use a new --output or --overwrite.')
    workdir = output_root / (slug + '.incomplete')
    if workdir.exists():
        shutil.rmtree(workdir)
    workdir.mkdir()
    try:
        rng = np.random.default_rng(args.seed)
        train = uniform_training_sample(shards, total, args.train_size, rng)
        print(f'{app}: fitting {k} clusters on {len(train):,} of {total:,} reviews', flush=True)
        model = MiniBatchKMeans(n_clusters=k, batch_size=min(args.kmeans_batch_size, len(train)),
                                max_iter=args.max_iter, n_init=3, random_state=args.seed)
        model.fit(train)
        centers = unit_vectors(model.cluster_centers_)
        with (workdir / 'centroids.npy').open('wb') as fp:
            np.save(fp, centers)

        assignment_dir = workdir / 'assignments'
        assignment_dir.mkdir()
        sizes = np.zeros(k, dtype=np.int64)
        rating_sum = np.zeros(k, dtype=np.float64)
        rating_valid = np.zeros(k, dtype=np.int64)
        low_ratings = np.zeros(k, dtype=np.int64)
        similarity_sum = np.zeros(k, dtype=np.float64)
        min_date = [None] * k
        max_date = [None] * k
        source_counts = [Counter() for _ in range(k)]
        representatives = [[] for _ in range(k)]
        random_samples = [[] for _ in range(k)]
        boundaries = [[] for _ in range(k)]
        completed = 0
        sequence = 0
        for shard_number, (stem, vector_path, meta_path, rows) in enumerate(shards, 1):
            vectors = np.load(vector_path, mmap_mode='r', allow_pickle=False)
            metadata = pq.read_table(meta_path)
            records = metadata.to_pylist()
            labels_all = np.empty(rows, dtype=np.int32)
            similarities_all = np.empty(rows, dtype=np.float32)
            margins_all = np.empty(rows, dtype=np.float32)
            for start in range(0, rows, args.assign_batch_size):
                stop = min(start + args.assign_batch_size, rows)
                batch = unit_vectors(vectors[start:stop])
                labels, similarities, margins = score_batch(batch, centers)
                labels_all[start:stop] = labels
                similarities_all[start:stop] = similarities
                margins_all[start:stop] = margins
            for i, source in enumerate(records):
                cid = int(labels_all[i])
                sim = float(similarities_all[i])
                margin = float(margins_all[i])
                sizes[cid] += 1
                similarity_sum[cid] += sim
                try:
                    stars = float(source.get('stars') or '')
                    if not np.isfinite(stars):
                        raise ValueError
                except (TypeError, ValueError):
                    stars = None
                if stars is not None:
                    rating_sum[cid] += stars
                    rating_valid[cid] += 1
                    if stars <= 2:
                        low_ratings[cid] += 1
                date = source.get('feedback_date')
                if date:
                    min_date[cid] = min(min_date[cid], date) if min_date[cid] else date
                    max_date[cid] = max(max_date[cid], date) if max_date[cid] else date
                data_source = source.get('data_source') or ''
                source_counts[cid][data_source] += 1
                record = {
                    'cluster_id': cid,
                    'feedback_id': source.get('feedback_id'),
                    'app_name': app,
                    'text': source.get('full_text'),
                    'title': source.get('title'),
                    'stars': source.get('stars'),
                    'feedback_date': date,
                    'data_source': data_source,
                    'app_versions': source.get('app_versions'),
                    'language_status': source.get('language_status'),
                    'cosine_similarity': sim,
                    'margin_to_second_cluster': margin,
                }
                keep_top(representatives[cid], args.representatives, sim, sequence, record)
                keep_top(boundaries[cid], args.boundary_per_cluster, -margin, sequence, record)
                reservoir = random_samples[cid]
                seen = int(sizes[cid])
                if len(reservoir) < args.random_per_cluster:
                    reservoir.append(record)
                elif args.random_per_cluster:
                    pos = int(rng.integers(0, seen))
                    if pos < args.random_per_cluster:
                        reservoir[pos] = record
                sequence += 1
            assigned = metadata.append_column('cluster_id', pa.array(labels_all))
            assigned = assigned.append_column('cosine_similarity', pa.array(similarities_all))
            assigned = assigned.append_column('margin_to_second_cluster', pa.array(margins_all))
            pq.write_table(assigned, assignment_dir / (stem + '.parquet'), compression='zstd')
            completed += rows
            print(f'  [{shard_number}/{len(shards)}] assigned {completed:,}/{total:,}', flush=True)
        if int(sizes.sum()) != total:
            raise RuntimeError('Assignment total does not match embedding manifest')

        summary_rows = []
        for cid, raw_n in enumerate(sizes):
            n = int(raw_n)
            summary_rows.append({
                'cluster_id': cid,
                'review_count': n,
                'share_of_app_pct': round(100 * n / total, 3),
                'avg_stars': round(float(rating_sum[cid] / rating_valid[cid]), 3) if rating_valid[cid] else None,
                'one_two_star_pct': round(100 * int(low_ratings[cid]) / rating_valid[cid], 2) if rating_valid[cid] else None,
                'avg_cosine_similarity': round(float(similarity_sum[cid] / n), 4) if n else None,
                'min_feedback_date': min_date[cid],
                'max_feedback_date': max_date[cid],
                'source_counts_json': json.dumps(dict(source_counts[cid]), ensure_ascii=False),
            })
        summary_rows.sort(key=lambda row: (-row['review_count'], row['cluster_id']))
        summary_columns = ['cluster_id', 'review_count', 'share_of_app_pct', 'avg_stars',
                           'one_two_star_pct', 'avg_cosine_similarity', 'min_feedback_date',
                           'max_feedback_date', 'source_counts_json']
        write_csv(workdir / 'cluster_summary.csv', summary_rows, summary_columns)

        samples = []
        for cid in range(k):
            n = int(sizes[cid])
            probability = min(args.random_per_cluster, n) / n if n else None
            for _, _, record in sorted(representatives[cid], reverse=True):
                samples.append({**record, 'sample_type': 'representative', 'inclusion_probability': None})
            for record in random_samples[cid]:
                samples.append({**record, 'sample_type': 'random', 'inclusion_probability': probability})
            for _, _, record in sorted(boundaries[cid], reverse=True):
                samples.append({**record, 'sample_type': 'boundary', 'inclusion_probability': None})
        samples.sort(key=lambda row: (row['cluster_id'], row['sample_type'], -row['cosine_similarity']))
        sample_columns = ['sample_type', 'cluster_id', 'feedback_id', 'app_name', 'text', 'title',
                          'stars', 'feedback_date', 'data_source', 'app_versions',
                          'language_status', 'cosine_similarity', 'margin_to_second_cluster',
                          'inclusion_probability']
        write_csv(workdir / 'cluster_samples.csv', samples, sample_columns)
        if samples:
            pq.write_table(pa.Table.from_pylist(samples).select(sample_columns),
                           workdir / 'cluster_samples.parquet', compression='zstd')
        else:
            pq.write_table(pa.table({column: pa.array([], type=pa.string()) for column in sample_columns}),
                           workdir / 'cluster_samples.parquet')

        config = {
            'app': app, 'slug': slug, 'embedding_root': str(embedding_root.resolve()),
            'source_manifest': source_manifest, 'total_reviews': total,
            'embedding_dimension': dimension,
            'method': 'MiniBatchKMeans fit on uniform review sample, cosine assign with normalized centers',
            'clusters': k, 'training_sample_size': len(train),
            'representatives_per_cluster': args.representatives,
            'random_per_cluster': args.random_per_cluster,
            'boundary_per_cluster': args.boundary_per_cluster,
            'seed': args.seed, 'completed_rows': completed,
            'created_at_utc': datetime.now(timezone.utc).isoformat(),
        }
        with (workdir / 'run_config.json').open('w', encoding='utf-8') as fp:
            json.dump(config, fp, indent=2, ensure_ascii=False)
        if target.exists():
            backup = output_root / (slug + '.previous')
            if backup.exists():
                raise ValueError(f'Cannot overwrite while backup exists: {backup}')
            os.replace(target, backup)
            try:
                os.replace(workdir, target)
            except Exception:
                os.replace(backup, target)
                raise
            shutil.rmtree(backup)
        else:
            os.replace(workdir, target)
        print(f'{app}: complete. {len(samples):,} sample rows saved to {target}', flush=True)
    except Exception:
        shutil.rmtree(workdir, ignore_errors=True)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--embedding-root', default='embeddings/spotify-all')
    parser.add_argument('--output', default='clusters/pasted-spotify')
    parser.add_argument('--app', default='Spotify')
    parser.add_argument('--clusters', type=int, default=50)
    parser.add_argument('--train-size', type=int, default=30000)
    parser.add_argument('--kmeans-batch-size', type=int, default=2048)
    parser.add_argument('--assign-batch-size', type=int, default=2048)
    parser.add_argument('--max-iter', type=int, default=100)
    parser.add_argument('--representatives', type=int, default=5)
    parser.add_argument('--random-per-cluster', type=int, default=30)
    parser.add_argument('--boundary-per-cluster', type=int, default=5)
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--overwrite', action='store_true')
    args = parser.parse_args()
    for name in ('clusters', 'train_size', 'kmeans_batch_size', 'assign_batch_size', 'max_iter'):
        if getattr(args, name) < 1:
            parser.error(f'--{name.replace("_", "-")} must be positive')
    for name in ('representatives', 'random_per_cluster', 'boundary_per_cluster'):
        if getattr(args, name) < 0:
            parser.error(f'--{name.replace("_", "-")} cannot be negative')
    run(args)


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, RuntimeError) as exc:
        print(f'Error: {exc}', file=sys.stderr)
        sys.exit(1)
