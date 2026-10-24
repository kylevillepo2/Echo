#!/usr/bin/env python3
"""Step 2 of the Unwrapathon NLP pipeline: sentence embeddings for app reviews.

Two modes:

  Test run (default): embed a random subset (50k rows, fixed seed) and print a report
  with throughput, an estimate for the full dataset, short-review examples and a
  nearest-neighbor sanity check.

      python scripts/embed_reviews.py --input data/reviews-clean.csv

  Full run: embed every row in shards of ~200k. Resumable: rerun the same command
  after a crash and finished shards are skipped.

      python scripts/embed_reviews.py --input data/reviews-clean.csv --full

Output (in --out, default "embeddings/"):
  embeddings_XXXX.npy      float16 vectors, shape (rows, 384), unit-normalized
  ids_XXXX.parquet         one row per vector, same order: review_id, word_count,
                           is_short, plus app/date/stars/version/source/language/text
  manifest.json            model, dims, row counts, short-review share, shard list
The test run writes the same files to <out>/test/ instead.
"""
import argparse
import json
import os
import random
import time
from pathlib import Path

import numpy as np
import pandas as pd

# Columns in the preprocessed CSV (reviews-clean.csv).
ID_COL, TITLE_COL, BODY_COL = "feedback_id", "title", "full_text"
META_COLS = ["app_names", "feedback_date", "stars", "app_versions", "data_source", "language_status"]


def pick_device(requested):
    if requested != "auto":
        return requested
    import torch
    if torch.backends.mps.is_available():
        return "mps"
    if torch.cuda.is_available():
        return "cuda"
    return "cpu"


def build_frame(chunk, short_cutoff):
    """Combine title + body, drop empty text, add word_count / is_short."""
    body = chunk[BODY_COL].fillna("").astype(str).str.strip()
    if TITLE_COL in chunk:
        title = chunk[TITLE_COL].fillna("").astype(str).str.strip()
    else:
        title = pd.Series("", index=chunk.index)
    # "title. body" when both exist; otherwise whichever one is non-empty.
    text = np.where((title != "") & (body != ""), title + ". " + body,
                    np.where(body != "", body, title))
    out = pd.DataFrame({"review_id": chunk[ID_COL].astype(str).to_numpy(), "text": text})
    for col in META_COLS:
        if col in chunk:
            out[col] = chunk[col].to_numpy()  # positional, so chunk row numbers don't matter
    keep = out["text"] != ""
    out = out[keep].reset_index(drop=True)
    out["word_count"] = out["text"].str.split().str.len().astype("int32")
    out["is_short"] = out["word_count"] < short_cutoff
    return out, int((~keep).sum())


def encode(model, texts, batch_size):
    """Encode sorted by length for speed, return vectors in the original order."""
    order = np.argsort([len(t) for t in texts], kind="stable")
    vecs = model.encode([texts[i] for i in order], batch_size=batch_size,
                        normalize_embeddings=True, convert_to_numpy=True, show_progress_bar=False)
    out = np.empty_like(vecs)
    out[order] = vecs
    return out.astype(np.float16)


def save_shard(outdir, idx, vecs, frame):
    emb_path = outdir / f"embeddings_{idx:04d}.npy"
    ids_path = outdir / f"ids_{idx:04d}.parquet"
    tmp_emb = emb_path.with_suffix(".npy.tmp")
    tmp_ids = ids_path.with_suffix(".parquet.tmp")
    with open(tmp_emb, "wb") as fp:
        np.save(fp, vecs)
    frame.to_parquet(tmp_ids, index=False)
    # Write ids first, embeddings last: an embeddings file only exists once both are complete.
    os.replace(tmp_ids, ids_path)
    os.replace(tmp_emb, emb_path)


def write_manifest(outdir, args, dim, shards, rows, skipped, short):
    manifest = {
        "model": args.model, "dimensions": dim, "dtype": "float16", "normalized": True,
        "text": "title. body (body only when title is empty)",
        "input": str(Path(args.input).resolve()), "app_filter": args.app,
        "short_cutoff_words": args.short_cutoff,
        "rows_embedded": rows, "rows_skipped_empty": skipped,
        "short_reviews": short, "short_share": round(short / rows, 4) if rows else 0,
        "shards": shards,
    }
    (outdir / "manifest.json").write_text(json.dumps(manifest, indent=2))
    return manifest


def load_model(args):
    from sentence_transformers import SentenceTransformer
    device = pick_device(args.device)
    model = SentenceTransformer(args.model, device=device)
    print(f"Model {args.model} on {device} ({model.get_sentence_embedding_dimension()} dims)", flush=True)
    return model


def read_chunks(path, size, app=None):
    """Yield CSV chunks; with app set, keep only reviews tagged with that app (exact name)."""
    for chunk in pd.read_csv(path, dtype=str, keep_default_na=False, na_values=[""], chunksize=size):
        if app:
            names = chunk["app_names"].fillna("").str.lower()
            chunk = chunk[names.str.contains(f'"{app.lower()}"', regex=False)]
        yield chunk


# ---------------------------------------------------------------- full run
def run_full(args):
    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)
    model = None
    dim = None
    shards, rows, skipped, short = [], 0, 0, 0
    t0 = time.time()
    for idx, chunk in enumerate(read_chunks(args.input, args.shard_size, args.app)):
        if args.app and chunk.empty:
            continue
        frame, n_skip = build_frame(chunk, args.short_cutoff)
        emb_path = outdir / f"embeddings_{idx:04d}.npy"
        ids_path = outdir / f"ids_{idx:04d}.parquet"
        if emb_path.exists() and ids_path.exists():
            print(f"shard {idx:04d}: exists, skipping", flush=True)
            dim = dim or int(np.load(emb_path, mmap_mode="r").shape[1])
        else:
            if model is None:
                model = load_model(args)
                dim = model.get_sentence_embedding_dimension()
            ts = time.time()
            vecs = encode(model, frame["text"].tolist(), args.batch_size)
            save_shard(outdir, idx, vecs, frame)
            print(f"shard {idx:04d}: {len(frame):,} rows in {time.time() - ts:.0f}s "
                  f"({len(frame) / (time.time() - ts):.0f}/s)", flush=True)
        shards.append({"embeddings": emb_path.name, "ids": ids_path.name, "rows": len(frame)})
        rows += len(frame)
        skipped += n_skip
        short += int(frame["is_short"].sum())
    m = write_manifest(outdir, args, dim, shards, rows, skipped, short)
    print(f"\nDone: {rows:,} embedded, {skipped:,} skipped, {m['short_share']:.1%} short, "
          f"{len(shards)} shards, {(time.time() - t0) / 60:.1f} min total.")


# ---------------------------------------------------------------- test run
def sample_subset(path, n, seed, app=None):
    """Random n rows without loading the whole file: count rows, then sample per chunk."""
    if app:  # one app fits in memory: load its rows, then sample
        rows = pd.concat(read_chunks(path, 500_000, app), ignore_index=True)
        return rows.sample(min(n, len(rows)), random_state=seed).reset_index(drop=True), len(rows)
    total = sum(len(c) for c in pd.read_csv(path, usecols=[ID_COL], dtype=str, chunksize=500_000))
    rng = np.random.default_rng(seed)
    keep = np.sort(rng.choice(total, size=min(n, total), replace=False))
    parts, start = [], 0
    for chunk in read_chunks(path, 500_000):
        end = start + len(chunk)
        sel = keep[(keep >= start) & (keep < end)] - start
        if len(sel):
            parts.append(chunk.iloc[sel])
        start = end
    return pd.concat(parts, ignore_index=True), total


def run_test(args):
    outdir = Path(args.out) / "test"
    outdir.mkdir(parents=True, exist_ok=True)
    print(f"Sampling {args.subset:,} rows (seed {args.seed})...", flush=True)
    sub, total = sample_subset(args.input, args.subset, args.seed, args.app)
    frame, n_skip = build_frame(sub, args.short_cutoff)
    model = load_model(args)
    model.encode(["warm up"] * 8)  # first call includes one-off setup cost
    t0 = time.time()
    vecs = encode(model, frame["text"].tolist(), args.batch_size)
    secs = time.time() - t0
    save_shard(outdir, 0, vecs, frame)
    m = write_manifest(outdir, args, vecs.shape[1],
                       [{"embeddings": "embeddings_0000.npy", "ids": "ids_0000.parquet", "rows": len(frame)}],
                       len(frame), n_skip, int(frame["is_short"].sum()))

    rate = len(frame) / secs
    print("\n=== THROUGHPUT ===")
    print(f"{len(frame):,} reviews in {secs:.0f}s = {rate:,.0f} reviews/sec")
    print(f"Full dataset: {total:,} rows -> about {total / rate / 60:.0f} min of encoding "
          f"(plus a few minutes of CSV reading)")

    print("\n=== SHORT REVIEWS (under %d words) ===" % args.short_cutoff)
    print(f"{m['short_reviews']:,} of {len(frame):,} ({m['short_share']:.1%})")
    shorts = frame[frame["is_short"]]
    for t in shorts.sample(min(10, len(shorts)), random_state=args.seed)["text"]:
        print("  -", t)

    print("\n=== NEAREST NEIGHBORS (5 random non-short reviews) ===")
    v = vecs.astype(np.float32)
    long_idx = np.flatnonzero(~frame["is_short"].to_numpy())
    rnd = random.Random(args.seed)
    for q in rnd.sample(list(long_idx), min(5, len(long_idx))):
        sims = v @ v[q]
        sims[q] = -1
        top = np.argsort(-sims)[:5]
        print(f"\nQUERY [{frame.at[q, 'app_names']} | {frame.at[q, 'stars']}*] {frame.at[q, 'text'][:200]}")
        for j in top:
            print(f"   {sims[j]:.2f} [{frame.at[j, 'app_names']} | {frame.at[j, 'stars']}*] {frame.at[j, 'text'][:160]}")
    print(f"\nTest files written to {outdir}/. Check the neighbors above: are they about the same "
          f"topic, or only the same mood/star rating? Then run again with --full.")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--input", required=True, help="Path to reviews-clean.csv")
    p.add_argument("--out", default="embeddings", help="Output folder (default: embeddings)")
    p.add_argument("--model", default="sentence-transformers/all-MiniLM-L6-v2")
    p.add_argument("--batch-size", type=int, default=256)
    p.add_argument("--subset", type=int, default=50_000, help="Rows for the test run")
    p.add_argument("--short-cutoff", type=int, default=8, help="Reviews under this many words are flagged is_short")
    p.add_argument("--shard-size", type=int, default=200_000)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--device", default="auto", help="auto, mps, cuda or cpu")
    p.add_argument("--full", action="store_true", help="Embed the full dataset (after checking the test run)")
    p.add_argument("--app", default=None, help='Only embed reviews for this app, e.g. --app Spotify')
    args = p.parse_args()
    run_full(args) if args.full else run_test(args)


if __name__ == "__main__":
    main()
