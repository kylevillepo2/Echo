#!/usr/bin/env python3
"""Step 3 of the Unwrapathon NLP pipeline: cluster review embeddings into sampling groups.

    python scripts/cluster_reviews.py --input embeddings/spotify --out clusters/spotify --k 200

- Short reviews (is_short) become cluster -1 and are left out of K-means.
- MiniBatchKMeans on the rest; centroids are re-normalized, and each review is assigned
  to its most cosine-similar centroid (the same rule assign_clusters.py uses).
- Every k in --try-k is scored first (silhouette, largest share, tiny clusters, median
  size); the table goes into manifest.json. --try-k "" skips this.

Outputs in --out: review_clusters.parquet, centroids.npy, cluster_summary.csv,
kmeans_model.joblib, manifest.json.
"""
import argparse
import json
import time
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from scipy import sparse
from sklearn.cluster import MiniBatchKMeans
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics import silhouette_score

from assign_clusters import assign, assign_frame


def load_embeddings(folder):
    """Read manifest + shards; stop if any row counts disagree."""
    folder = Path(folder)
    manifest = json.loads((folder / "manifest.json").read_text())
    metas, vecs = [], []
    for s in manifest["shards"]:
        meta = pd.read_parquet(folder / s["ids"])
        v = np.load(folder / s["embeddings"], mmap_mode="r")
        if not (len(meta) == v.shape[0] == s["rows"]):
            raise SystemExit(f"Row count mismatch in {s['ids']}: parquet {len(meta)}, "
                             f"npy {v.shape[0]}, manifest {s['rows']}")
        metas.append(meta)
        vecs.append(np.asarray(v))
    meta = pd.concat(metas, ignore_index=True)
    vecs = np.concatenate(vecs)
    if len(meta) != manifest["rows_embedded"]:
        raise SystemExit(f"Total rows {len(meta)} != manifest rows_embedded {manifest['rows_embedded']}")
    return manifest, meta, vecs


def fit(X, k, seed):
    km = MiniBatchKMeans(n_clusters=k, random_state=seed, n_init=3, batch_size=4096)
    km.fit(X)
    c = km.cluster_centers_.astype(np.float32)
    c /= np.linalg.norm(c, axis=1, keepdims=True)
    labels, sims = assign(X, c)
    return km, c, labels, sims


def score(X, k, labels, sample_idx, seed):
    sizes = np.bincount(labels, minlength=k)
    return {
        "k": k,
        "silhouette_cosine": round(float(silhouette_score(X[sample_idx], labels[sample_idx],
                                                          metric="cosine", random_state=seed)), 4),
        "largest_share": round(float(sizes.max() / len(labels)), 4),
        "clusters_under_100": int((sizes < 100).sum()),
        "empty_clusters": int((sizes == 0).sum()),
        "median_size": int(np.median(sizes)),
        "smallest_size": int(sizes.min()),
        "largest_size": int(sizes.max()),
    }


def keywords(texts, cluster_ids, clusters, n=8):
    """Top n terms by (cluster mean TF-IDF - mean TF-IDF over all text)."""
    vec = TfidfVectorizer(stop_words="english", min_df=5, max_df=0.5, sublinear_tf=True,
                          max_features=50_000, token_pattern=r"(?u)\b[^\W\d_][^\W\d_]+\b")
    T = vec.fit_transform(texts)
    terms = np.array(vec.get_feature_names_out())
    overall = np.asarray(T.mean(axis=0)).ravel()
    row_of = {c: i for i, c in enumerate(clusters)}
    ind = sparse.csr_matrix((np.ones(len(cluster_ids)), ([row_of[c] for c in cluster_ids],
                                                         np.arange(len(cluster_ids)))),
                            shape=(len(clusters), len(cluster_ids)))
    sizes = np.asarray(ind.sum(axis=1)).ravel()
    means = np.asarray((ind @ T).todense()) / np.maximum(sizes, 1)[:, None]
    lift = means - overall
    return {c: ", ".join(terms[np.argsort(-lift[i])[:n]]) for i, c in enumerate(clusters)}


def summarize(df, n_total):
    df = df.assign(stars_num=pd.to_numeric(df["stars"], errors="coerce"),
                   date=pd.to_datetime(df["feedback_date"], errors="coerce"),
                   norm_text=df["text"].str.lower().str.strip())
    rows = []
    for cid, g in df.groupby("cluster_id", sort=True):
        top3 = g.nlargest(3, "sim_to_centroid")["text"] if cid >= 0 else g["text"].head(0)
        rows.append({
            "cluster_id": cid, "size": len(g), "share_of_all": round(len(g) / n_total, 4),
            "mean_stars": round(g["stars_num"].mean(), 2),
            "pct_1_star": round((g["stars_num"] == 1).mean() * 100, 1),
            "pct_5_star": round((g["stars_num"] == 5).mean() * 100, 1),
            "pct_unknown_language": round((g["language_status"] == "unknown").mean() * 100, 1),
            "pct_duplicate_text": round(g["norm_text"].duplicated().mean() * 100, 1),
            "earliest_date": g["date"].min().date() if g["date"].notna().any() else None,
            "latest_date": g["date"].max().date() if g["date"].notna().any() else None,
            "mean_sim_to_centroid": round(float(g["sim_to_centroid"].mean()), 4) if cid >= 0 else None,
            "top3_reviews": " || ".join(t.replace("\n", " ")[:300] for t in top3),
        })
    return pd.DataFrame(rows)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--input", required=True, help="Folder written by embed_reviews.py --full")
    p.add_argument("--out", required=True, help="Output folder")
    p.add_argument("--k", type=int, required=True, help="Number of clusters for the outputs")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--try-k", default="50,100,200,400", help='k values to score first ("" to skip)')
    p.add_argument("--silhouette-sample", type=int, default=20_000)
    a = p.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    manifest_in, meta, vecs = load_embeddings(a.input)
    short = meta["is_short"].to_numpy(bool)
    X = vecs[~short].astype(np.float32)
    print(f"{len(meta):,} reviews: {short.sum():,} short (cluster -1), {len(X):,} to cluster", flush=True)

    rng = np.random.default_rng(a.seed)
    sample_idx = rng.choice(len(X), size=min(a.silhouette_sample, len(X)), replace=False)
    table, fitted = [], {}
    for k in [int(x) for x in a.try_k.split(",") if x.strip()]:
        ts = time.time()
        km, c, labels, sims = fit(X, k, a.seed)
        table.append(score(X, k, labels, sample_idx, a.seed))
        print(f"k={k}: {table[-1]}  ({time.time() - ts:.0f}s)", flush=True)
        if k == a.k:
            fitted[k] = (km, c, labels, sims)
    if table:
        print("\n" + pd.DataFrame(table).to_string(index=False) + "\n")
    km, c, labels, _ = fitted.get(a.k) or fit(X, a.k, a.seed)
    agree = float((labels == km.labels_).mean())
    print(f"k={a.k}: cosine assignment matches K-means' own labels for {agree:.2%} of reviews")

    # 1. review_clusters.parquet (via the same code path as assign_clusters.py)
    df = assign_frame(meta, vecs, c)
    df.to_parquet(out / "review_clusters.parquet", index=False)
    # 2. centroids, model
    np.save(out / "centroids.npy", c)
    joblib.dump(km, out / "kmeans_model.joblib")
    # 3. summary
    summary = summarize(df, len(df))
    kw = keywords(df["text"].tolist(), df["cluster_id"].to_numpy(), summary["cluster_id"].tolist())
    summary.insert(summary.columns.get_loc("top3_reviews"), "keywords", summary["cluster_id"].map(kw))
    summary.to_csv(out / "cluster_summary.csv", index=False)
    # 5. manifest
    sizes = np.bincount(df.loc[~short, "cluster_id"], minlength=a.k)
    m = {
        "input": str(Path(a.input).resolve()), "embedding_model": manifest_in["model"],
        "k": a.k, "seed": a.seed,
        "kmeans": {"algorithm": "MiniBatchKMeans", "n_init": 3, "batch_size": 4096},
        "assignment": "argmax cosine to re-normalized centroids (centroids.npy); "
                      "kmeans_model.joblib .predict() uses raw centroids and can differ slightly",
        "assignment_matches_kmeans_labels": round(agree, 4),
        "rows_total": int(len(df)), "rows_clustered": int(len(X)), "short_reviews": int(short.sum()),
        "short_cutoff_words": manifest_in.get("short_cutoff_words"),
        "chosen_k_stats": {"largest_share_of_clustered": round(float(sizes.max() / len(X)), 4),
                           "clusters_under_100": int((sizes < 100).sum()),
                           "median_size": int(np.median(sizes))},
        "k_selection": table,
    }
    (out / "manifest.json").write_text(json.dumps(m, indent=2))
    print(f"Wrote outputs to {out}/ in {(time.time() - t0) / 60:.1f} min")


if __name__ == "__main__":
    main()
