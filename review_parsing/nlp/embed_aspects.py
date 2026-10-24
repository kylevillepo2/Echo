#!/usr/bin/env python3
"""Embed extracted aspect descriptions into aligned, resumable shards.

Each part-NNNNNN.npy row matches the same row in part-NNNNNN.parquet.
The Parquet file retains every source column and adds aspect_id, formed from
review_key and aspect_index. Only description is passed to the encoder.
"""

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq


def atomic_json(path, value):
    temporary = path.with_name(path.name + '.tmp')
    try:
        with temporary.open('w', encoding='utf-8') as fp:
            json.dump(value, fp, indent=2, ensure_ascii=False)
            fp.flush()
            os.fsync(fp.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def load_aspects(path, max_aspects=None):
    # Read one snapshot: the extractor may atomically replace this Parquet file
    # while a longer run is still exporting results.
    contents = path.read_bytes()
    fingerprint = hashlib.sha256(contents).hexdigest()
    table = pq.read_table(pa.BufferReader(contents))
    required = {'review_key', 'aspect_index', 'description'}
    missing = required - set(table.column_names)
    if missing:
        raise ValueError(f'Missing aspect columns: {", ".join(sorted(missing))}')
    if max_aspects is not None:
        table = table.slice(0, max_aspects)
    if table.num_rows == 0:
        raise ValueError('No aspects available to embed')

    keys = table.column('review_key').to_pylist()
    indexes = table.column('aspect_index').to_pylist()
    descriptions = table.column('description').to_pylist()
    ids = []
    for row_number, (key, index, description) in enumerate(zip(keys, indexes, descriptions)):
        if not isinstance(key, str) or not key or not isinstance(index, int) or index < 0:
            raise ValueError(f'Invalid review_key or aspect_index at row {row_number}')
        if not isinstance(description, str) or not description.strip():
            raise ValueError(f'Empty aspect description at row {row_number}')
        ids.append(f'{key}:{index}')
    if len(set(ids)) != len(ids):
        raise ValueError('Duplicate aspect_id values in input')
    if 'aspect_id' in table.column_names:
        raise ValueError('Input already has an aspect_id column')
    return table.append_column('aspect_id', pa.array(ids)), descriptions, fingerprint


def config_for(args, source, fingerprint, row_count):
    return {
        'source': str(source),
        'source_sha256': fingerprint,
        'aspect_count': row_count,
        'model': args.model,
        'dtype': args.dtype,
        'shard_size': args.shard_size,
        'max_aspects': args.max_aspects,
        'normalized': True,
        'encoded_column': 'description',
    }


def shard_paths(output, number):
    stem = f'part-{number:06d}'
    return output / (stem + '.npy'), output / (stem + '.parquet')


def verify_shard(array_path, meta_path, expected_ids, dtype, dimension):
    vectors = np.load(array_path, mmap_mode='r', allow_pickle=False)
    ids = pq.read_table(meta_path, columns=['aspect_id']).column('aspect_id').to_pylist()
    if vectors.ndim != 2 or vectors.shape[0] != len(expected_ids):
        raise RuntimeError(f'Embedding row count or shape mismatch: {array_path}')
    if vectors.dtype != np.dtype(dtype) or ids != expected_ids:
        raise RuntimeError(f'Embedding dtype or aspect IDs mismatch: {array_path}')
    if dimension is not None and vectors.shape[1] != dimension:
        raise RuntimeError(f'Embedding dimension mismatch: {array_path}')
    if not np.isfinite(vectors).all():
        raise RuntimeError(f'Nonfinite embeddings: {array_path}')
    norms = np.linalg.norm(np.asarray(vectors, dtype=np.float32), axis=1)
    tolerance = 0.01 if dtype == 'float16' else 0.001
    if not np.allclose(norms, 1.0, atol=tolerance):
        raise RuntimeError(f'Embeddings are not unit normalized: {array_path}')
    return vectors.shape[1]


def write_shard(output, number, vectors, metadata):
    array_path, meta_path = shard_paths(output, number)
    array_temp = output / f'part-{number:06d}.tmp.npy'
    meta_temp = output / f'part-{number:06d}.tmp.parquet'
    try:
        with array_temp.open('wb') as fp:
            np.save(fp, vectors)
        pq.write_table(metadata, meta_temp)
        os.replace(array_temp, array_path)
        os.replace(meta_temp, meta_path)
    finally:
        array_temp.unlink(missing_ok=True)
        meta_temp.unlink(missing_ok=True)


def run(args, encoder_factory=None):
    if args.batch_size < 1 or args.shard_size < 1:
        raise ValueError('--batch-size and --shard-size must be positive')
    if args.max_aspects is not None and args.max_aspects < 1:
        raise ValueError('--max-aspects must be positive')
    source = args.input.expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f'Input not found: {source}')
    table, descriptions, fingerprint = load_aspects(source, args.max_aspects)
    output = args.output.expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    config = config_for(args, source, fingerprint, table.num_rows)
    manifest_path = output / 'manifest.json'
    if args.force:
        for pattern in ('part-*.npy', 'part-*.parquet', 'part-*.tmp.npy', 'part-*.tmp.parquet'):
            for path in output.glob(pattern):
                path.unlink()
        manifest_path.unlink(missing_ok=True)
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        if manifest.get('config') != config:
            raise RuntimeError('Input or settings changed. Use a new --output folder or --force.')
    else:
        if any(output.glob('part-*')):
            raise RuntimeError('Existing shards have no manifest. Use a new --output folder or --force.')
        manifest = {'config': config, 'status': 'in_progress', 'completed_shards': 0}
        atomic_json(manifest_path, manifest)

    total = table.num_rows
    total_shards = (total + args.shard_size - 1) // args.shard_size
    for pattern in ('part-*.tmp.npy', 'part-*.tmp.parquet'):
        for path in output.glob(pattern):
            path.unlink()
    expected_stems = {f'part-{number:06d}' for number in range(total_shards)}
    for path in output.glob('part-*'):
        if path.suffix in {'.npy', '.parquet'} and path.stem not in expected_stems:
            raise RuntimeError(f'Unexpected shard in output: {path}')

    remaining = []
    dimension = manifest.get('embedding_dimension')
    if dimension is not None and (not isinstance(dimension, int) or dimension < 1):
        raise RuntimeError('Invalid embedding dimension in manifest')
    for number in range(total_shards):
        start = number * args.shard_size
        end = min(start + args.shard_size, total)
        array_path, meta_path = shard_paths(output, number)
        if array_path.exists() and meta_path.exists():
            try:
                found = verify_shard(array_path, meta_path,
                                     table.column('aspect_id').slice(start, end - start).to_pylist(),
                                     args.dtype, dimension)
            except Exception as exc:
                raise RuntimeError(f'Existing shard {number} failed verification: {exc}. '
                                   'Use --force or a new output folder.') from exc
            dimension = found
            print(f'Skipping complete shard {number + 1}/{total_shards}', flush=True)
        else:
            # An interrupted paired write may leave one file. Rebuild the pair.
            array_path.unlink(missing_ok=True)
            meta_path.unlink(missing_ok=True)
            remaining.append(number)

    if remaining:
        if encoder_factory is None:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as exc:
                raise RuntimeError('Install sentence-transformers to embed aspects') from exc
            encoder_factory = SentenceTransformer
        print(f'Loading {args.model}...', flush=True)
        model = encoder_factory(args.model, device=args.device)
        for number in remaining:
            start = number * args.shard_size
            end = min(start + args.shard_size, total)
            vectors = model.encode(descriptions[start:end], batch_size=args.batch_size,
                                   convert_to_numpy=True, normalize_embeddings=True,
                                   show_progress_bar=False)
            vectors = np.asarray(vectors, dtype=np.float32)
            if (vectors.ndim != 2 or vectors.shape[0] != end - start or
                    vectors.shape[1] < 1 or not np.isfinite(vectors).all()):
                raise RuntimeError(f'Invalid embeddings for shard {number}')
            norms = np.linalg.norm(vectors, axis=1, keepdims=True)
            if not np.isfinite(norms).all() or np.any(norms == 0):
                raise RuntimeError(f'Zero or invalid embeddings for shard {number}')
            vectors = (vectors / norms).astype(args.dtype)
            if dimension is not None and vectors.shape[1] != dimension:
                raise RuntimeError(f'Embedding dimension changed in shard {number}')
            dimension = vectors.shape[1]
            verify_norms = np.linalg.norm(vectors.astype(np.float32), axis=1)
            if not np.allclose(verify_norms, 1.0, atol=0.01 if args.dtype == 'float16' else 0.001):
                raise RuntimeError(f'Embeddings lost normalization in shard {number}')
            write_shard(output, number, vectors, table.slice(start, end - start))
            manifest = {'config': config, 'status': 'in_progress',
                        'completed_shards': number + 1, 'embedding_dimension': dimension}
            atomic_json(manifest_path, manifest)
            print(f'Embedded {end:,}/{total:,} aspects (shard {number + 1}/{total_shards})', flush=True)

    atomic_json(manifest_path, {'config': config, 'status': 'complete',
                                'completed_shards': total_shards,
                                'embedding_dimension': dimension, 'aspect_count': total})
    print(f'Done. Saved {total:,} aspect embeddings to {output}', flush=True)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True, help='Extractor review_aspects.parquet')
    parser.add_argument('--output', type=Path, required=True, help='Output shard folder')
    parser.add_argument('--model', default='sentence-transformers/all-MiniLM-L6-v2')
    parser.add_argument('--device', default=None, help='Sentence Transformers device, such as cpu or mps')
    parser.add_argument('--batch-size', type=int, default=64)
    parser.add_argument('--shard-size', type=int, default=5000)
    parser.add_argument('--dtype', choices=['float32', 'float16'], default='float32')
    parser.add_argument('--max-aspects', type=int, default=None)
    parser.add_argument('--force', action='store_true', help='Replace this output folder’s embedding shards')
    args = parser.parse_args()
    run(args)


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, RuntimeError) as exc:
        print(f'Error: {exc}', file=sys.stderr)
        sys.exit(1)
