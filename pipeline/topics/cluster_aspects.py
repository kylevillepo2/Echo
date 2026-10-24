#!/usr/bin/env python3
"""Steps 6-7 of the Unwrapathon NLP pipeline: embed aspect descriptions and group paraphrases.

    python scripts/cluster_aspects.py --model sentence-transformers/all-mpnet-base-v2 --threshold 0.35

- Generic rows (general_praise, or "overall satisfaction/dissatisfaction ..." descriptions)
  get aspect_cluster_id -1 ("general sentiment") and are not embedded.
- Feature names are mapped to a short canonical list (FEATURE_MAP below, saved as feature_map.csv).
- Descriptions are embedded (unit-normalized) and clustered with agglomerative clustering,
  cosine distance, average linkage and a distance threshold. Sentiment is not used.
- Every model in --compare-models x every threshold in --try-thresholds is scored first;
  the table goes into manifest.json. Outputs are written for --model / --threshold.

Outputs in --out: aspect_embeddings.npy, aspect_ids.parquet, aspect_clusters.parquet,
aspect_cluster_summary.csv, feature_map.csv, manifest.json. No API calls.
"""
import argparse
import json
import re
import sys
import time
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.cluster import AgglomerativeClustering

ROOT = Path(__file__).resolve().parents[3]  # workspace root (script lives in unwrapathon/pipeline/topics/)

# Canonical feature for every feature value seen in step 5 (Spotify pilot).
FEATURE_GROUPS = {
    "none": ["none", "other", "app"],
    "ads": ["ads", "banners"],
    "free tier": ["free tier"],
    "subscription": ["subscription", "family plan"],
    "account": ["login", "account", "profiles", "date of birth", "location"],
    "playlists": ["playlists", "blend"],
    "library": ["library", "liked songs", "music library", "local files", "sorting", "pins",
                "recent listening", "albums"],
    "playback": ["playback", "music playback", "background playback", "loop", "loop mode", "playhead",
                 "playback order", "play in order", "playback controls", "next song button", "skip",
                 "autoplay", "sleep timer"],
    "shuffle": ["shuffle", "smart shuffle"],
    "queue": ["queue"],
    "recommendations": ["recommendations", "music discovery", "daylist", "new releases", "radio",
                        "genre selection", "feed"],
    "AI DJ": ["ai dj", "ai"],
    "catalog": ["music", "music catalog", "songs", "song selection", "audio content"],
    "podcasts": ["podcasts", "video", "videos", "channels"],
    "audiobooks": ["audiobooks"],
    "sound quality": ["sound quality", "volume control", "equalizer", "effects", "dolby atmos",
                      "surround sound"],
    "lyrics": ["lyrics", "translations", "guitar chords"],
    "search": ["search"],
    "offline & downloads": ["downloads", "offline mode", "mobile data"],
    "Wrapped": ["wrapped"],
    "Create button": ["create button"],
    "interface": ["interface", "ui", "navigation", "app usability", "home screen", "navigation bar",
                  "app interface", "layout", "widget", "canvas", "customization", "settings",
                  "now playing screen", "screen orientation", "screenshots"],
    "devices & casting": ["casting", "spotify connect", "sync", "device switching", "device connection",
                          "apple watch", "homepod", "google assistant", "alexa devices", "car mode",
                          "android compatibility"],
    "app updates & install": ["app updates", "app update", "app launch", "installation", "clipboard"],
    "social & sharing": ["friends", "jams", "sharing", "links", "social features", "user-uploaded images"],
    "customer support": ["customer support", "customer service", "reporting"],
    "notifications": ["notifications", "new music notifications", "emails", "rating prompt"],
    "content filters": ["explicit content", "explicit music filters"],
    "concerts & merch": ["concerts", "merch"],
    "artist payouts": ["artist payouts"],
}
FEATURE_MAP = {f: canon for canon, fs in FEATURE_GROUPS.items() for f in fs}

GENERIC_DESC = re.compile(r"^overall (?:(?:dis)?satisfaction with (?:the )?(?:app|service|music)|user experience)$",
                          re.I)

# Phrase pairs from the plan: (a, b, should they be in the same cluster?)
EXAMPLE_PAIRS = [
    ("too many ads", "ads after every song", True),
    ("frequent ads", "ads appear too frequently", True),
    ("ads after every song", "ads interrupt podcasts", False),
    ("lyrics missing for songs", "lyrics moved behind premium", False),
    ("high sound quality", "poor sound quality", True),
    ("shuffle repeats the same songs", "shuffle plays songs in the same order", True),
    ("app crashes on launch", "app crashes during playback", True),
    ("premium required to pick songs", "subscription price is expensive", False),
]


def embed(model_name, texts):
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer(model_name, device="cpu")
    return model.encode(texts, batch_size=128, normalize_embeddings=True, convert_to_numpy=True,
                        show_progress_bar=False).astype(np.float32)


def cluster(vecs, threshold):
    ac = AgglomerativeClustering(n_clusters=None, metric="cosine", linkage="average",
                                 distance_threshold=threshold)
    return ac.fit_predict(vecs)


def relabel_by_size(labels):
    """Cluster ids 0..n-1, largest first (ties by first appearance)."""
    counts = Counter(labels)
    order = sorted(counts, key=lambda c: (-counts[c], np.flatnonzero(labels == c)[0]))
    new = {c: i for i, c in enumerate(order)}
    return np.array([new[c] for c in labels])


def score(labels, df):
    sizes = pd.Series(labels).value_counts()
    multi = sizes[sizes >= 2].index
    sub = df.assign(c=labels)
    sub = sub[sub["c"].isin(multi)]

    def purity(col):
        if sub.empty:
            return None
        return round(float(sub.groupby("c")[col].agg(lambda s: s.value_counts().iloc[0]).sum() / len(sub)), 4)
    return {"clusters": int(len(sizes)), "singletons": int((sizes == 1).sum()),
            "largest": int(sizes.max()), "rows_in_multi_clusters": int(len(sub)),
            "aspect_type_purity": purity("aspect_type"), "feature_purity": purity("canonical_feature")}


def summarize(df, vecs, labels):
    rows = []
    for cid in sorted(set(labels)):
        idx = np.flatnonzero(labels == cid)
        g = df.iloc[idx]
        sent = g["sentiment"].value_counts()
        base = {"aspect_cluster_id": int(cid), "size": len(g), "reviews": int(g["review_id"].nunique()),
                **{f"n_{s}": int(sent.get(s, 0)) for s in ["negative", "positive", "neutral", "mixed"]},
                "top_aspect_type": g["aspect_type"].value_counts().index[0],
                "top_canonical_feature": g["canonical_feature"].value_counts().index[0]}
        if cid == -1:
            base.update(name="general sentiment", top5_descriptions=" | ".join(g["description"].value_counts().index[:5]),
                        example_evidence=g["evidence"].iloc[0], cohesion=None)
        else:
            center = vecs[idx].mean(axis=0)
            center /= np.linalg.norm(center)
            sims = vecs[idx] @ center
            order = idx[np.argsort(-sims)]
            top = list(dict.fromkeys(df["description"].iloc[order].str.lower()))[:5]
            base.update(name=top[0], top5_descriptions=" | ".join(top),
                        example_evidence=df["evidence"].iloc[order[0]], cohesion=round(float(sims.mean()), 4))
        rows.append(base)
    return pd.DataFrame(rows)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--input", default=str(ROOT / "extractions/spotify/extracted_aspects.parquet"))
    p.add_argument("--out", default=str(ROOT / "aspects/spotify"))
    p.add_argument("--model", default="sentence-transformers/all-mpnet-base-v2")
    p.add_argument("--threshold", type=float, default=0.35, help="Cosine distance threshold")
    p.add_argument("--compare-models", default="sentence-transformers/all-MiniLM-L6-v2,"
                                               "sentence-transformers/all-mpnet-base-v2",
                   help='Models to score in the comparison table ("" to skip)')
    p.add_argument("--try-thresholds", default="0.25,0.35,0.45")
    a = p.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    df = pd.read_parquet(a.input)
    unknown = sorted(set(df["feature"]) - set(FEATURE_MAP))
    if unknown:
        print(f"WARNING: {len(unknown)} features not in FEATURE_MAP, kept as-is: {unknown}")
    df["canonical_feature"] = df["feature"].map(FEATURE_MAP).fillna(df["feature"])
    fmap = (df.groupby(["feature", "canonical_feature"]).size().rename("count").reset_index()
              .sort_values(["canonical_feature", "count"], ascending=[True, False]))
    fmap.to_csv(out / "feature_map.csv", index=False)

    generic = (df["aspect_type"] == "general_praise") | df["description"].str.strip().str.match(GENERIC_DESC)
    work = df[~generic].reset_index(drop=True)
    texts = work["description"].str.strip().tolist()
    print(f"{len(df):,} aspects: {int(generic.sum()):,} generic (-1), {len(work):,} to cluster; "
          f"{df['feature'].nunique()} features -> {df['canonical_feature'].nunique()} canonical", flush=True)

    thresholds = [float(x) for x in a.try_thresholds.split(",") if x.strip()]
    models = [m.strip() for m in a.compare_models.split(",") if m.strip()]
    if a.model not in models:
        models.append(a.model)
    table, pair_checks, chosen_vecs = [], [], None
    for m in models:
        vecs = embed(m, texts)
        pv = embed(m, [x for pair in EXAMPLE_PAIRS for x in pair[:2]])
        for i, (x, y, same) in enumerate(EXAMPLE_PAIRS):
            pair_checks.append({"model": m, "a": x, "b": y, "should_merge": same,
                                "cosine_distance": round(float(1 - pv[2 * i] @ pv[2 * i + 1]), 3)})
        for t in sorted(set(thresholds + [a.threshold])):
            row = {"model": m, "threshold": t, **score(cluster(vecs, t), work)}
            table.append(row)
            print(row, flush=True)
        if m == a.model:
            chosen_vecs = vecs
    print("\n" + pd.DataFrame(table).to_string(index=False))
    print("\nExample pair distances (merge directly if below the threshold):")
    print(pd.DataFrame(pair_checks).to_string(index=False))

    labels = relabel_by_size(cluster(chosen_vecs, a.threshold))
    work["aspect_cluster_id"] = labels
    np.save(out / "aspect_embeddings.npy", chosen_vecs)
    work[["review_id", "aspect_idx"]].to_parquet(out / "aspect_ids.parquet", index=False)

    gen = df[generic].assign(aspect_cluster_id=-1)
    allrows = pd.concat([work, gen], ignore_index=True).sort_values(["review_id", "aspect_idx"]).reset_index(drop=True)
    summary = pd.concat([summarize(gen.reset_index(drop=True), None, np.full(len(gen), -1)),
                         summarize(work, chosen_vecs, labels)], ignore_index=True)
    names = summary.set_index("aspect_cluster_id")["name"]
    allrows["aspect_cluster_name"] = allrows["aspect_cluster_id"].map(names)
    allrows.to_parquet(out / "aspect_clusters.parquet", index=False)
    summary.to_csv(out / "aspect_cluster_summary.csv", index=False)

    sizes = pd.Series(labels).value_counts()
    manifest = {
        "input": a.input, "model": a.model, "threshold": a.threshold,
        "clustering": "AgglomerativeClustering(metric=cosine, linkage=average, distance_threshold)",
        "embedded_text": "description", "normalized": True,
        "rows_total": int(len(df)), "rows_generic": int(generic.sum()), "rows_clustered": int(len(work)),
        "clusters": int(len(sizes)), "singletons": int((sizes == 1).sum()), "largest_cluster": int(sizes.max()),
        "features": int(df["feature"].nunique()), "canonical_features": int(df["canonical_feature"].nunique()),
        "threshold_comparison": table, "example_pair_distances": pair_checks,
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"\nWrote {out}/ in {time.time() - t0:.0f}s: {len(sizes)} clusters, "
          f"{(sizes == 1).sum()} singletons, {int(generic.sum())} generic rows")


if __name__ == "__main__":
    main()
