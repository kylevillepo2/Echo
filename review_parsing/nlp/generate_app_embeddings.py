#!/usr/bin/env python3
"""Generate resumable, per-app sentence embeddings from app-store-reviews.csv.

Output layout:
  <output>/staging/<app_slug>.jsonl          # Review input partitions
  <output>/apps/<app_slug>/part-000000.npy    # Embeddings, shape (N, D), float16
  <output>/apps/<app_slug>/part-000000.parquet # Matching row metadata
  <output>/apps/<app_slug>/part-000000.done   # Completed shard marker
  <output>/apps/<app_slug>/manifest.json      # App-level metadata
  <output>/app_index.json                     # App names, slugs, row counts
  <output>/staging_complete.json              # Stage checkpoint

The nth row in a .npy shard matches the nth row of the same-numbered
.parquet shard. Embeddings are unit-normalized before storage.
"""

import argparse
import ast
import csv
import hashlib
import json
import os
import re
import sys
from collections import Counter, OrderedDict
from pathlib import Path


def parse_apps(value):
    if not value:
        return []
    try:
        decoded = ast.literal_eval(value)
        if isinstance(decoded, list):
            return sorted({str(x).strip() for x in decoded if str(x).strip()})
        if isinstance(decoded, str) and decoded.strip():
            return [decoded.strip()]
    except (ValueError, SyntaxError):
        pass
    return [value.strip()] if value.strip() else []


def slugify(app):
    base = re.sub(r'[^a-z0-9]+', '-', app.casefold()).strip('-')[:55] or 'app'
    return f'{base}-{hashlib.sha1(app.encode("utf-8")).hexdigest()[:8]}'


def atomic_json(path, obj):
    temp = path.with_name(path.name + '.tmp')
    with temp.open('w', encoding='utf-8') as fp:
        json.dump(obj, fp, indent=2, ensure_ascii=False)
    os.replace(temp, path)


class OpenFiles:
    """Bound open staging file descriptors."""

    def __init__(self, max_open=24):
        self.handles = OrderedDict()
        self.max_open = max_open

    def append(self, path, value):
        key = str(path)
        if key in self.handles:
            fp = self.handles.pop(key)
        else:
            if len(self.handles) >= self.max_open:
                _, old = self.handles.popitem(last=False)
                old.close()
            fp = open(path, 'a', encoding='utf-8')
        fp.write(json.dumps(value, ensure_ascii=False) + '\n')
        self.handles[key] = fp

    def close(self):
        for fp in self.handles.values():
            fp.close()
        self.handles.clear()


def partition_csv(input_path, outdir, include_unknown, limit_per_app, app_filter=None):
    stage = outdir / 'staging'
    checkpoint = outdir / 'staging_complete.json'
    index_path = outdir / 'app_index.json'
    source = input_path.stat()
    settings = {
        'input': str(input_path.resolve()),
        'input_size': source.st_size,
        'input_mtime_ns': source.st_mtime_ns,
        'include_unknown': include_unknown,
        'limit_per_app': limit_per_app,
        'app_filter': app_filter.casefold() if app_filter else None,
    }
    if checkpoint.exists() and index_path.exists():
        existing = json.loads(checkpoint.read_text(encoding='utf-8'))
        if all(existing.get(key) == value for key, value in settings.items()):
            index = json.loads(index_path.read_text(encoding='utf-8'))
            if all((stage / (entry['slug'] + '.jsonl')).exists() for entry in index.values()):
                print('Reusing completed app partitions.', flush=True)
                return index
        raise RuntimeError('Existing staging belongs to different input/settings or is incomplete. Use another --output folder.')
    if checkpoint.exists():
        raise RuntimeError('Incomplete staging checkpoint. Use another --output folder.')
    # The index can exist without a checkpoint if staging was interrupted
    # between the two atomic writes. In that case, rebuild it from the CSV.
    index_path.unlink(missing_ok=True)

    stage.mkdir(parents=True, exist_ok=True)
    # Clean partitions left by an interrupted first pass.
    for path in stage.glob('*.jsonl'):
        path.unlink()
    counts = Counter()
    files = OpenFiles()
    try:
        with input_path.open('r', newline='', encoding='utf-8-sig') as fp:
            reader = csv.DictReader(fp)
            required = {'app_names', 'full_text', 'language_status'}
            missing = required - set(reader.fieldnames or [])
            if missing:
                raise ValueError(f'Missing CSV columns: {", ".join(sorted(missing))}')
            for row in reader:
                text = (row.get('full_text') or '').strip()
                if not text:
                    continue
                language = (row.get('language_status') or '').strip().casefold()
                if language != 'english' and not (include_unknown and language == 'unknown'):
                    continue
                for app in parse_apps(row.get('app_names')):
                    if app_filter and app.casefold() != app_filter.casefold():
                        continue
                    if limit_per_app is not None and counts[app] >= limit_per_app:
                        continue
                    files.append(stage / (slugify(app) + '.jsonl'), row)
                    counts[app] += 1
    finally:
        files.close()

    index = {app: {'slug': slugify(app), 'row_count': count}
             for app, count in sorted(counts.items())}
    atomic_json(index_path, index)
    atomic_json(checkpoint, settings)
    print(f'Partitioned {sum(counts.values()):,} reviews across {len(index)} apps.', flush=True)
    return index


def rows_from_jsonl(path, shard_size):
    with path.open('r', encoding='utf-8') as fp:
        while True:
            rows = []
            for _ in range(shard_size):
                line = fp.readline()
                if not line:
                    break
                rows.append(json.loads(line))
            if not rows:
                return
            yield rows


def embed_app(app, info, outdir, model, model_name, batch_size, shard_size):
    import numpy as np
    import pyarrow as pa
    import pyarrow.parquet as pq

    app_dir = outdir / 'apps' / info['slug']
    app_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = app_dir / 'manifest.json'
    expected = {'app': app, 'slug': info['slug'], 'row_count': info['row_count'],
                'model': model_name, 'shard_size': shard_size,
                'dtype': 'float16', 'normalized': True}
    if manifest_path.exists():
        existing = json.loads(manifest_path.read_text(encoding='utf-8'))
        if any(existing.get(k) != v for k, v in expected.items()):
            raise RuntimeError(f'Existing embeddings for {app} use different settings. Use another --output folder.')

    completed = 0
    for number, rows in enumerate(rows_from_jsonl(outdir / 'staging' / (info['slug'] + '.jsonl'), shard_size)):
        stem = f'part-{number:06d}'
        npy = app_dir / (stem + '.npy')
        parquet = app_dir / (stem + '.parquet')
        done = app_dir / (stem + '.done')
        if done.exists():
            if not npy.exists() or not parquet.exists():
                raise RuntimeError(f'Completed shard is missing data: {done}')
            marker = json.loads(done.read_text(encoding='utf-8'))
            if marker.get('row_count') != len(rows) or marker.get('model') != model_name:
                raise RuntimeError(f'Completed shard has different rows or model: {done}')
            completed += len(rows)
            continue

        texts = [row['full_text'] for row in rows]
        vectors = model.encode(texts, batch_size=batch_size, normalize_embeddings=True,
                               convert_to_numpy=True, show_progress_bar=False)
        vectors = np.asarray(vectors, dtype=np.float32)
        if vectors.ndim != 2 or len(vectors) != len(rows):
            raise RuntimeError(f'Model returned an unexpected shape for {app} {stem}')
        # Normalize again explicitly, then convert to compact storage precision.
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        if np.any(norms == 0):
            raise RuntimeError(f'Model returned a zero vector for {app} {stem}')
        vectors = (vectors / norms).astype(np.float16)

        npy_tmp = app_dir / (stem + '.npy.tmp')
        parquet_tmp = app_dir / (stem + '.parquet.tmp')
        try:
            with npy_tmp.open('wb') as fp:
                np.save(fp, vectors)
            pq.write_table(pa.Table.from_pylist(rows), parquet_tmp)
            os.replace(npy_tmp, npy)
            os.replace(parquet_tmp, parquet)
            atomic_json(done, {'row_count': len(rows), 'dimensions': vectors.shape[1],
                               'model': model_name})
        finally:
            npy_tmp.unlink(missing_ok=True)
            parquet_tmp.unlink(missing_ok=True)
        completed += len(rows)
        print(f'{app}: {completed:,}/{info["row_count"]:,}', flush=True)

    if completed != info['row_count']:
        raise RuntimeError(f'Staging row count changed for {app}: expected {info["row_count"]}, got {completed}')
    atomic_json(manifest_path, {**expected, 'completed_rows': completed,
                                'shard_count': (completed + shard_size - 1) // shard_size})
    print(f'{app}: complete ({completed:,} reviews)', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--input', type=Path, default=Path.home() / 'Downloads' / 'app-store-reviews.csv')
    parser.add_argument('--output', type=Path, default=Path.home() / 'Downloads' / 'app-embeddings')
    parser.add_argument('--app', help='Process only this app (case insensitive exact match)')
    parser.add_argument('--limit-per-app', type=int, help='Keep at most this many eligible reviews per app')
    parser.add_argument('--include-unknown', action='store_true', help='Include reviews with unknown language status')
    parser.add_argument('--model', default='sentence-transformers/all-MiniLM-L6-v2')
    parser.add_argument('--batch-size', type=int, default=64)
    parser.add_argument('--shard-size', type=int, default=5000)
    args = parser.parse_args()
    if args.limit_per_app is not None and args.limit_per_app < 1:
        parser.error('--limit-per-app must be positive')
    if args.batch_size < 1 or args.shard_size < 1:
        parser.error('--batch-size and --shard-size must be positive')
    if not args.input.is_file():
        parser.error(f'Input CSV not found: {args.input}')
    args.output.mkdir(parents=True, exist_ok=True)

    index = partition_csv(args.input, args.output, args.include_unknown,
                          args.limit_per_app, args.app)
    if args.app and not index:
        parser.error(f'No eligible reviews found for app {args.app!r}')
    if not index:
        parser.error('No eligible reviews found')

    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:
        raise SystemExit('Install dependencies: python3 -m pip install sentence-transformers numpy pyarrow') from exc
    model = SentenceTransformer(args.model)
    for app, info in index.items():
        embed_app(app, info, args.output, model, args.model, args.batch_size, args.shard_size)


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, RuntimeError, csv.Error) as exc:
        print(f'Error: {exc}', file=sys.stderr)
        sys.exit(1)
