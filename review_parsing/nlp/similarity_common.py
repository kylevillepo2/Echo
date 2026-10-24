"""Shared, offline primitives for Step 9A. No extraction or refinement imports."""
import hashlib
import json
import os
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

VERSION = 'similarity-v1'


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text())


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False))
    os.replace(tmp, path)


def atomic_parquet(path, table):
    tmp = path.with_name(path.name + '.tmp')
    pq.write_table(table, tmp)
    os.replace(tmp, path)


def normalize(vectors):
    x = np.asarray(vectors, dtype=np.float32)
    if x.ndim != 2 or not np.isfinite(x).all():
        raise ValueError('Expected finite 2D embeddings')
    norms = np.linalg.norm(x, axis=1, keepdims=True)
    if np.any(norms <= 0):
        raise ValueError('Zero-length embedding')
    return x / norms


def score(reviews, topics):
    if reviews.shape[1] != topics.shape[1]:
        raise ValueError('Incompatible embedding dimensions')
    return np.clip(normalize(reviews) @ normalize(topics).T, -1, 1)


def compatible(model_a, dim_a, model_b, dim_b):
    if model_a != model_b or dim_a != dim_b:
        raise ValueError(f'Incompatible embedding spaces: {model_a}/{dim_a}, {model_b}/{dim_b}')


def identity(row):
    fid = str(row.get('feedback_id') or '').strip()
    if not fid:
        raise ValueError('Missing feedback_id; cannot safely join review identities')
    return f"{row.get('data_source', '')}:{fid}"


def split_for(row, seed=42):
    # Identical text stays together, even under different source IDs. This also
    # prevents duplicated generic reviews from leaking across evaluation sets.
    text = ' '.join((row.get('full_text') or row.get('text') or '').split()).casefold()
    token = hashlib.sha256(f'{seed}:{text}'.encode()).digest()
    bucket = int.from_bytes(token[:8], 'big') % 100
    return 'train' if bucket < 60 else 'validation' if bucket < 80 else 'test'


def review_inputs(root, app):
    root = Path(root).resolve()
    index = read_json(root / 'app_index.json')
    name = next((n for n in index if n.casefold() == app.casefold()), None)
    if name is None:
        raise ValueError(f'App not found: {app}')
    folder = root / 'apps' / index[name]['slug']
    manifest = read_json(folder / 'manifest.json')
    if manifest.get('completed_rows') != manifest.get('row_count'):
        raise ValueError('Review embeddings are incomplete')
    paths = sorted(folder.glob('part-*.npy'))
    if len(paths) != manifest['shard_count']:
        raise ValueError('Review shard count differs from manifest')
    files = []
    total = 0
    dim = None
    for path in paths:
        meta = path.with_suffix('.parquet')
        marker = path.with_suffix('.done')
        x = np.load(path, mmap_mode='r', allow_pickle=False)
        done = read_json(marker)
        count = pq.ParquetFile(meta).metadata.num_rows
        if x.ndim != 2 or x.shape[0] != count or done['row_count'] != count:
            raise ValueError(f'Review vector/metadata alignment failed: {path}')
        if done['model'] != manifest['model'] or done['dimensions'] != x.shape[1]:
            raise ValueError('Review completion marker has incompatible model/dimension')
        if dim is not None and x.shape[1] != dim:
            raise ValueError('Review shard dimensions differ')
        dim = x.shape[1]
        total += count
        files.append({'stem': path.stem, 'vectors': str(path), 'metadata': str(meta),
                      'vector_sha256': digest(path), 'metadata_sha256': digest(meta), 'rows': count})
    if total != manifest['row_count'] or not dim:
        raise ValueError('Review count differs from manifest')
    return name, manifest, dim, files


def load_topics(root):
    root = Path(root)
    config = read_json(root / 'config.json')
    if config.get('version') != VERSION:
        raise ValueError('Unsupported topic embedding version')
    if digest(root / 'topic_vectors.npy') != config['vectors_sha256'] or digest(root / 'topic_metadata.parquet') != config['metadata_sha256']:
        raise ValueError('Topic outputs changed after construction')
    x = normalize(np.load(root / 'topic_vectors.npy', allow_pickle=False))
    rows = pq.read_table(root / 'topic_metadata.parquet').to_pylist()
    ids = [r['topic_id'] for r in rows]
    if len(rows) != len(x) or len(set(ids)) != len(ids) or not rows:
        raise ValueError('Invalid or duplicate topic ID alignment')
    if any(r['embedding_row'] != i or r['relevance_status'] != 'keep' for i, r in enumerate(rows)):
        raise ValueError('Topic row order or approval status invalid')
    return x, rows, config


def choose(scores, thresholds, max_tags):
    if max_tags < 1:
        raise ValueError('max_tags must be positive')
    thresholds = np.asarray(thresholds)
    if not np.isfinite(thresholds).all() or np.any((thresholds < -1) | (thresholds > 1)):
        raise ValueError('Thresholds must be finite cosine values in [-1, 1]')
    out = []
    for row in scores:
        eligible = np.flatnonzero(row >= thresholds)
        order = eligible[np.argsort(-row[eligible], kind='stable')][:max_tags]
        out.append(order.tolist())
    return out


def threshold_values(config, ids):
    unknown = set(config.get('per_topic', {})) - set(ids)
    if unknown:
        raise ValueError(f'Unknown threshold topic IDs: {sorted(unknown)}')
    values = [config.get('per_topic', {}).get(tid, config['global_threshold']) for tid in ids]
    choose(np.empty((0, len(ids))), values, config['max_tags'])
    return values


def provisional_labels(refined, extractions, topic_ids):
    """Include zero-aspect negatives; exclude uncertain-label reviews entirely."""
    approved = set(topic_ids)
    reviews = pq.read_table(extractions).to_pylist()
    by_identity = {}
    for row in reviews:
        key = identity(row)
        if key in by_identity:
            raise ValueError('Duplicate source review identity in extractions')
        by_identity[key] = {'review': row, 'topics': set(), 'unresolved': False}
    for row in pq.read_table(refined).to_pylist():
        item = by_identity.get(identity(row))
        if item is None:
            raise ValueError('Refined aspect missing from extraction universe')
        if row.get('relevance_status') == 'keep' and row.get('topic_id') in approved:
            item['topics'].add(row['topic_id'])
        elif row.get('relevance_status') != 'exclude':
            item['unresolved'] = True
    return by_identity
