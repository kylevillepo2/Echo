#!/usr/bin/env python3
"""Compare two embedding runs for the same app: embed_reviews.py vs. Derek's script.

    python scripts/compare_embeddings.py --mine embeddings/spotify --derek derek_embeddings --app Spotify

Reports:
  1. Coverage: rows in each run, overlap, and which reviews only one run kept (with examples)
  2. Text: how often the two runs built different text for the same review
  3. Vectors: cosine similarity between the two runs' vectors for the same review
  4. Neighbors: the same 5 query reviews, with nearest neighbors from each run side by side
"""
import argparse
import glob
import hashlib
import re

import numpy as np
import pandas as pd


def load_mine(folder):
    ids = sorted(glob.glob(f"{folder}/ids_*.parquet"))
    if not ids:
        raise SystemExit(f"No ids_*.parquet in {folder}. Did you run embed_reviews.py with --full?")
    meta = pd.concat([pd.read_parquet(p) for p in ids], ignore_index=True)
    vecs = np.concatenate([np.load(p.replace("ids_", "embeddings_").replace(".parquet", ".npy")) for p in ids])
    meta = meta.rename(columns={"review_id": "id"})
    return meta, vecs.astype(np.float32)


def load_derek(folder, app):
    # Derek's script stores each app under apps/<slug>/, slug = name + sha1 prefix.
    base = re.sub(r"[^a-z0-9]+", "-", app.casefold()).strip("-")[:55] or "app"
    slug = f'{base}-{hashlib.sha1(app.encode("utf-8")).hexdigest()[:8]}'
    parts = sorted(glob.glob(f"{folder}/apps/{slug}/part-*.parquet"))
    if not parts:
        raise SystemExit(f"No shards in {folder}/apps/{slug}/. Check --derek and --app (exact app name).")
    meta = pd.concat([pd.read_parquet(p) for p in parts], ignore_index=True)
    vecs = np.concatenate([np.load(p.replace(".parquet", ".npy")) for p in parts])
    meta = meta.rename(columns={"feedback_id": "id"})
    meta["id"] = meta["id"].astype(str)
    return meta, vecs.astype(np.float32)


def neighbors(vecs, meta, q, k=5):
    sims = vecs @ vecs[q]
    sims[q] = -1
    top = np.argsort(-sims)[:k]
    return [(float(sims[j]), meta.at[j, "stars"], meta.at[j, "text"]) for j in top]


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--mine", required=True, help="Output folder of embed_reviews.py --full --app ...")
    p.add_argument("--derek", required=True, help="--output folder of Derek's script")
    p.add_argument("--app", required=True)
    p.add_argument("--seed", type=int, default=7)
    a = p.parse_args()

    mine, mv = load_mine(a.mine)
    derek, dv = load_derek(a.derek, a.app)
    mine["id"] = mine["id"].astype(str)
    print(f"=== 1. COVERAGE ({a.app}) ===")
    print(f"mine:  {len(mine):,} rows")
    print(f"derek: {len(derek):,} rows")
    m_ids, d_ids = set(mine["id"]), set(derek["id"])
    both = m_ids & d_ids
    print(f"in both: {len(both):,}   only mine: {len(m_ids - d_ids):,}   only derek: {len(d_ids - m_ids):,}")
    only_m = mine[~mine["id"].isin(d_ids)]
    if len(only_m):
        if "language_status" in only_m:
            print("only-mine rows by language_status:", only_m["language_status"].value_counts().to_dict())
        print("examples of reviews only in mine:")
        for t in only_m.sample(min(8, len(only_m)), random_state=a.seed)["text"]:
            print("   -", t[:150])
    only_d = derek[~derek["id"].isin(m_ids)]
    if len(only_d):
        print("examples of reviews only in derek's:")
        for t in only_d.sample(min(5, len(only_d)), random_state=a.seed)["text"]:
            print("   -", t[:150])
    if "is_short" in mine:
        print(f"short reviews in mine: {mine['is_short'].mean():.1%}")

    # Align the overlapping rows.
    mi = pd.Series(np.arange(len(mine)), index=mine["id"]).loc[sorted(both)].to_numpy()
    di = pd.Series(np.arange(len(derek)), index=derek["id"])
    di = di[~di.index.duplicated()].loc[sorted(both)].to_numpy()

    print("\n=== 2. TEXT DIFFERENCES (same review) ===")
    diff = mine["text"].to_numpy()[mi] != derek["text"].to_numpy()[di]
    print(f"{diff.sum():,} of {len(both):,} overlapping reviews have different text ({diff.mean():.1%})")
    for k in np.flatnonzero(diff)[:3]:
        print(f"   mine:  {mine['text'].iat[mi[k]][:120]}")
        print(f"   derek: {derek['text'].iat[di[k]][:120]}\n")

    print("=== 3. VECTOR AGREEMENT (same review) ===")
    cos = np.sum(mv[mi] * dv[di], axis=1)
    print(f"cosine similarity  mean {cos.mean():.4f}   min {cos.min():.4f}   "
          f"share > 0.999: {(cos > 0.999).mean():.1%}")
    if (~diff).any():
        print(f"  same-text reviews only: mean {cos[~diff].mean():.4f} (should be ~1.0)")

    print("\n=== 4. NEAREST NEIGHBORS, side by side ===")
    rng = np.random.default_rng(a.seed)
    long_rows = [k for k in range(len(mi)) if len(mine["text"].iat[mi[k]].split()) >= 8]
    for k in rng.choice(long_rows, size=min(5, len(long_rows)), replace=False):
        print(f"\nQUERY [{mine['stars'].iat[mi[k]]}*] {mine['text'].iat[mi[k]][:180]}")
        for name, vecs, meta, idx in (("mine ", mv, mine, mi[k]), ("derek", dv, derek, di[k])):
            for s, st, t in neighbors(vecs, meta, idx):
                print(f"   {name} {s:.2f} [{st}*] {t[:130]}")


if __name__ == "__main__":
    main()
