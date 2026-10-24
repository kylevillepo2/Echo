#!/usr/bin/env python3
"""Step 4 of the Unwrapathon NLP pipeline: pick reviews from each cluster for LLM aspect extraction.

    python scripts/sample_reviews.py --budget 1000 --out samples/spotify_pilot
    python scripts/sample_reviews.py --budget 8000 --out samples/spotify_full

Per cluster label (clusters/spotify/cluster_labels.csv):
  topic        1 centroid + 1 outlier + random reviews. The allocation is split by
               size x spread (spread = 1 - mean sim_to_centroid), with at least
               --min-random random reviews per cluster.
  filler       1 random review
  non_english  nothing (listed in sampling_plan.csv with zeros)

Random rows are a simple random sample of the whole cluster (duplicates kept), so
inclusion_prob = n_random / cluster_size and weight = cluster_size / n_random. Only
random rows carry weights; centroid/outlier rows are for the LLM, not for estimates.
A review can appear both as centroid/outlier and as random (same review_id, different
sample_type).
"""
import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

KEEP_COLS = ["text", "app_names", "feedback_date", "stars", "app_versions"]
OUT_COLS = ["review_id", "cluster_id", "cluster_label", "sample_type", "inclusion_prob",
            "weight", "sim_to_centroid"] + KEEP_COLS


def allocate(weights, total, floor, caps):
    """Integer allocation proportional to weights, each >= floor and <= cap, summing to ~total."""
    floor = np.minimum(floor, caps)
    if total <= floor.sum():
        return floor.astype(int)
    alloc = np.zeros(len(weights))
    fixed = np.zeros(len(weights), bool)
    for _ in range(len(weights)):  # water-filling: pin clusters at their floor/cap, re-split the rest
        free = ~fixed
        share = (total - alloc[fixed].sum()) * weights[free] / weights[free].sum()
        alloc[free] = share
        low, high = free & (alloc < floor), free & (alloc > caps)
        if not (low.any() or high.any()):
            break
        alloc[low], alloc[high] = floor[low], caps[high]
        fixed |= low | high
    out = np.floor(alloc).astype(int)
    rem = int(round(total - out.sum()))
    order = np.argsort(-(alloc - out))  # largest remainders first, within caps
    for i in order:
        if rem <= 0:
            break
        if out[i] < caps[i]:
            out[i] += 1
            rem -= 1
    return out


def pick_extreme(g, closest):
    """Closest (or farthest) review whose text is unique in the cluster; fall back to any."""
    order = g.sort_values("sim_to_centroid", ascending=not closest)
    unique = order[~order["norm_text"].duplicated(keep=False)]
    return (unique if len(unique) else order).iloc[0]


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--clusters", default="clusters/spotify", help="Folder from cluster_reviews.py")
    p.add_argument("--labels", default=None, help="Default: <clusters>/cluster_labels.csv")
    p.add_argument("--out", default="samples/spotify_pilot")
    p.add_argument("--budget", type=int, default=1000, help="Total reviews to sample (about)")
    p.add_argument("--min-random", type=int, default=5, help="Minimum random reviews per topic cluster")
    p.add_argument("--seed", type=int, default=42)
    a = p.parse_args()
    cdir, out = Path(a.clusters), Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(a.seed)

    reviews = pd.read_parquet(cdir / "review_clusters.parquet")
    summary = pd.read_csv(cdir / "cluster_summary.csv")
    labels = pd.read_csv(a.labels or cdir / "cluster_labels.csv")
    missing = set(summary["cluster_id"]) - set(labels["cluster_id"])
    if missing:
        raise SystemExit(f"Clusters without a label: {sorted(missing)}")
    reviews["norm_text"] = reviews["text"].str.lower().str.strip()
    plan = summary[["cluster_id", "size", "mean_sim_to_centroid"]].merge(labels, on="cluster_id")
    plan["spread"] = (1 - plan["mean_sim_to_centroid"]).round(4)

    # Allocation: filler 1 each, topic clusters share the rest.
    plan[["n_centroid", "n_outlier", "n_random"]] = 0
    is_filler, is_topic = plan["label"] == "filler", plan["label"] == "topic"
    plan.loc[is_filler, "n_random"] = 1
    topic = plan[is_topic]
    topic_budget = a.budget - int(is_filler.sum())
    alloc = allocate((topic["size"] * topic["spread"]).to_numpy(float), topic_budget,
                     np.full(len(topic), a.min_random + 2.0), topic["size"].to_numpy(float) + 2)
    plan.loc[is_topic, "n_centroid"] = 1
    plan.loc[is_topic, "n_outlier"] = 1
    plan.loc[is_topic, "n_random"] = alloc - 2
    warnings = []
    minimum = int(is_filler.sum()) + len(topic) * (a.min_random + 2)
    if minimum > a.budget:
        warnings.append(f"Budget {a.budget} is below the minimum {minimum} "
                        f"({len(topic)} topic clusters x {a.min_random + 2} + {int(is_filler.sum())} filler); "
                        f"every topic cluster got only the minimum.")

    # Draw samples.
    rows = []
    groups = dict(tuple(reviews.groupby("cluster_id")))
    for _, c in plan.sort_values("cluster_id").iterrows():
        g, n = groups[c["cluster_id"]], len(groups[c["cluster_id"]])
        picks = []
        if c["n_centroid"]:
            cen = pick_extreme(g, closest=True)
            picks.append((cen, "centroid"))
            rest = g[g["review_id"] != cen["review_id"]]
            picks.append((pick_extreme(rest, closest=False), "outlier"))
        if c["n_random"]:
            idx = rng.choice(n, size=int(c["n_random"]), replace=False)
            picks += [(g.iloc[i], "random") for i in sorted(idx)]
        for r, kind in picks:
            rec = {col: r[col] for col in ["review_id", "cluster_id", "sim_to_centroid"] + KEEP_COLS}
            rec.update(cluster_label=c["label"], sample_type=kind,
                       inclusion_prob=c["n_random"] / n if kind == "random" else np.nan,
                       weight=n / c["n_random"] if kind == "random" else np.nan)
            rows.append(rec)
    samples = pd.DataFrame(rows)[OUT_COLS]
    samples.to_parquet(out / "sampled_reviews.parquet", index=False)

    plan["n_total"] = plan[["n_centroid", "n_random", "n_outlier"]].sum(axis=1)
    plan[["cluster_id", "label", "reason", "size", "spread", "n_centroid", "n_random", "n_outlier",
          "n_total"]].to_csv(out / "sampling_plan.csv", index=False)

    rnd = samples[samples["sample_type"] == "random"]
    overlap = int(samples[samples["sample_type"] != "random"]["review_id"].isin(rnd["review_id"]).sum())
    by_label = plan.groupby("label").agg(clusters=("cluster_id", "size"), reviews=("size", "sum"),
                                         sampled=("n_total", "sum"))
    manifest = {
        "seed": a.seed, "budget": a.budget, "min_random_per_topic_cluster": a.min_random,
        "total_sampled": int(len(samples)),
        "unique_reviews": int(samples["review_id"].nunique()),
        "centroid_or_outlier_also_drawn_as_random": overlap,
        "by_sample_type": samples["sample_type"].value_counts().to_dict(),
        "by_label": {k: {kk: int(vv) for kk, vv in v.items()} for k, v in by_label.to_dict("index").items()},
        "by_label_and_type": {f"{k[0]}/{k[1]}": int(v) for k, v in
                              samples.groupby(["cluster_label", "sample_type"]).size().items()},
        "weighted_population": int(round(rnd["weight"].sum())),
        "non_english_reviews_not_sampled": int(plan.loc[plan["label"] == "non_english", "size"].sum()),
        "inputs": {"clusters": str(cdir), "labels": str(a.labels or cdir / "cluster_labels.csv")},
        "warnings": warnings,
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2))
    for w in warnings:
        print("WARNING:", w)
    print(json.dumps({k: manifest[k] for k in ["total_sampled", "unique_reviews", "by_sample_type",
                                               "by_label", "weighted_population"]}, indent=1))


if __name__ == "__main__":
    main()
