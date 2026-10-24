#!/usr/bin/env python3
"""Assign embedding shards to the nearest cluster centroid (cosine similarity).

Uses centroids.npy from cluster_reviews.py. Works on any folder written by
embed_reviews.py (embeddings_XXXX.npy + ids_XXXX.parquet), e.g. another app later.
Short reviews (is_short = True) get cluster_id -1 and no similarity, the same as in
review_clusters.parquet.

    python scripts/assign_clusters.py --centroids clusters/spotify/centroids.npy \
        --input embeddings/spotify --shard 0018 --out reassigned_0018.parquet
"""
import argparse
import glob
from pathlib import Path

import numpy as np
import pandas as pd

ID_COLS = ["review_id", "cluster_id", "sim_to_centroid"]


def assign(vecs, centroids, batch=50_000):
    """Nearest centroid by cosine. vecs and centroids are unit-normalized."""
    labels = np.empty(len(vecs), dtype=np.int32)
    sims = np.empty(len(vecs), dtype=np.float32)
    for s in range(0, len(vecs), batch):
        block = vecs[s:s + batch].astype(np.float32) @ centroids.T
        labels[s:s + batch] = block.argmax(axis=1)
        sims[s:s + batch] = block[np.arange(len(block)), labels[s:s + batch]]
    return labels, sims


def assign_frame(meta, vecs, centroids):
    """Return meta with cluster_id and sim_to_centroid; short reviews get -1 / NaN."""
    if len(meta) != len(vecs):
        raise SystemExit(f"Row count mismatch: {len(meta)} metadata rows vs {len(vecs)} vectors")
    short = meta["is_short"].to_numpy(bool)
    cluster = np.full(len(meta), -1, dtype=np.int32)
    sim = np.full(len(meta), np.nan, dtype=np.float32)
    cluster[~short], sim[~short] = assign(vecs[~short], centroids)
    out = meta.copy()
    out["cluster_id"], out["sim_to_centroid"] = cluster, sim
    return out[ID_COLS + [c for c in meta.columns if c not in ID_COLS]]


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--centroids", required=True)
    p.add_argument("--input", required=True, help="Folder with embeddings_XXXX.npy + ids_XXXX.parquet")
    p.add_argument("--shard", action="append", help="Only these shard numbers (e.g. 0018); repeatable")
    p.add_argument("--out", required=True, help="Output .parquet")
    a = p.parse_args()

    centroids = np.load(a.centroids).astype(np.float32)
    ids = sorted(glob.glob(f"{a.input}/ids_*.parquet"))
    if a.shard:
        ids = [f for f in ids if Path(f).stem.split("_")[1] in a.shard]
    if not ids:
        raise SystemExit(f"No matching ids_*.parquet in {a.input}")
    parts = []
    for f in ids:
        vecs = np.load(f.replace("ids_", "embeddings_").replace(".parquet", ".npy"), mmap_mode="r")
        parts.append(assign_frame(pd.read_parquet(f), vecs, centroids))
        print(f"{Path(f).name}: {len(parts[-1]):,} rows assigned")
    out = pd.concat(parts, ignore_index=True)
    out.to_parquet(a.out, index=False)
    print(f"Wrote {len(out):,} rows to {a.out}")


if __name__ == "__main__":
    main()
