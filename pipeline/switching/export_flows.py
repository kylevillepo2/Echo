#!/usr/bin/env python3
"""Export the music switching graph for the frontend's Flows view.

Reads (from the workspace's out/ folder, produced by run_music_edges.py):
  out/music_edges.csv          one row per labeled edge (with evidence)
  out/music_edges_monthly.csv  monthly aggregate per source/target/kind/observing app
  out/app_month_counts.csv     monthly review volume of each observed app

Writes:
  unwrapathon/src/lib/data/flows.json

Edges stay split by the app whose reviews they were seen in ("o"), because
weight_per_10k is normalized by that app's review volume. The frontend sums
weight and volume per observing app over any period, then adds the rates.

Usage:
  python3 unwrapathon/pipeline/switching/export_flows.py
Standard library only.
"""
import csv
import json
import re
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import music_edge_extraction as mx  # noqa: E402

ROOT = HERE.parents[2]                       # workspace root
OUT = ROOT / "out"
DEST = HERE.parents[1] / "src" / "lib" / "data" / "flows.json"

OBSERVED = list(mx.REVIEWED_MUSIC_APPS)      # apps whose reviews we have
KINDS = ["switch", "return", "intent", "preference"]
EXAMPLES_PER_GROUP = 5
LOW_VOLUME_SHARE = 0.25                      # month < 25% of the app's median = partial
MODEL = "gpt-6-luna"
REASON_LABELS = {
    "price": "Price", "free_tier_limits": "Free-tier limits", "ads": "Ads", "catalog": "Catalog",
    "offline_downloads": "Offline & downloads", "audio_quality": "Audio quality",
    "recommendations": "Recommendations", "ui_change": "UI changes", "bugs_performance": "Bugs & performance",
    "account_billing": "Account & billing", "podcasts_audiobooks": "Podcasts & audiobooks",
    "artist_or_ethics": "Artists & ethics", "independent_artists": "Indie artists",
    "social_integration": "Social & devices", "lyrics": "Lyrics", "other": "Other",
}

csv.field_size_limit(10**9)


def slug(name):
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def split_reasons(s):
    return [r for r in (s or "").split(";") if r]


def month_range(first, last):
    y, m = map(int, first.split("-"))
    out = []
    while f"{y:04d}-{m:02d}" <= last:
        out.append(f"{y:04d}-{m:02d}")
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


def read_csv(name):
    path = OUT / name
    if not path.exists():
        sys.exit(f"Missing {path}. Run run_music_edges.py edges first.")
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def main():
    edge_rows = read_csv("music_edges.csv")
    monthly_rows = read_csv("music_edges_monthly.csv")
    volume_rows = read_csv("app_month_counts.csv")

    # ---- review volume and coverage --------------------------------------
    volume = defaultdict(dict)  # app -> month -> reviews
    for r in volume_rows:
        if r["month"]:
            volume[r["app_name"]][r["month"]] = int(r["reviews"])
    all_months = sorted({m for v in volume.values() for m in v} |
                        {r["month"] for r in monthly_rows if r["month"]})
    months = month_range(all_months[0], all_months[-1])

    medians = {a: statistics.median([v for v in volume[a].values() if v] or [0]) for a in OBSERVED}
    month_info = []
    for m in months:
        missing = [a for a in OBSERVED if not volume[a].get(m)]
        low = [a for a in OBSERVED
               if volume[a].get(m) and volume[a][m] < LOW_VOLUME_SHARE * medians[a]]
        notes = []
        if missing:
            notes.append(f"No {', '.join(missing)} reviews")
        if low:
            notes.append(f"Low {', '.join(low)} volume")
        month_info.append({
            "month": m,
            "full": not missing and not low,
            "missing": [slug(a) for a in missing],
            "low": [slug(a) for a in low],
            "note": "; ".join(notes),
        })
    full = [x["month"] for x in month_info if x["full"]]
    # Longest contiguous run of full-coverage months.
    best, run = [], []
    for x in month_info:
        run = run + [x["month"]] if x["full"] else []
        if len(run) > len(best):
            best = run
    coverage = {
        "start": best[0] if best else None,
        "end": best[-1] if best else None,
        "months": best,
        "note": ("Months where Spotify, Audiomack and SoundCloud all have normal review volume. "
                 "Other months are partial: flows seen in a missing app's reviews are absent."),
    }

    # ---- reasons per monthly group, from the edge rows --------------------
    reason_counts = defaultdict(Counter)  # (month,s,t,k,o) -> Counter
    for e in edge_rows:
        reason_counts[(e["month"], e["source"], e["target"], e["kind"], e["reviewed_app"])].update(
            split_reasons(e["reasons"]))

    edges = []
    for r in monthly_rows:
        k = (r["month"], r["source"], r["target"], r["kind"], r["observed_in_reviews_of"])
        rc = reason_counts.get(k, Counter())
        edges.append({
            "m": r["month"],
            "s": slug(r["source"]), "t": slug(r["target"]),
            "k": r["kind"],
            "o": slug(r["observed_in_reviews_of"]),
            "n": int(r["count"]),
            "w": round(float(r["weight"]), 3),
            "w10k": round(float(r["weight_per_10k_reviews"]), 3) if r["weight_per_10k_reviews"] else 0,
            # All reasons, most common first (the first three are the top 3). Keeping them all
            # makes period breakdowns exact; top-3 alone dropped about a third of mentions.
            "r": [[name, c] for name, c in rc.most_common()],
        })

    # ---- nodes ------------------------------------------------------------
    names = {e["source"] for e in edge_rows} | {e["target"] for e in edge_rows} | set(OBSERVED)
    involvement = Counter()
    for e in edge_rows:
        involvement[e["source"]] += 1
        involvement[e["target"]] += 1
    nodes = []
    for name in sorted(names, key=lambda n: (n not in OBSERVED, -involvement[n], n)):
        node = {"id": slug(name), "name": name, "observed": name in OBSERVED,
                "edgeCount": involvement[name]}
        if name in OBSERVED:
            node["volume"] = {m: volume[name].get(m, 0) for m in months}
            node["totalVolume"] = sum(volume[name].values())
        nodes.append(node)

    # ---- example reviews --------------------------------------------------
    def quality(e):
        ev = e["evidence"].strip()
        length_ok = 25 <= len(ev) <= 220
        return (float(e["weight"]), bool(split_reasons(e["reasons"])), length_ok, len(e["reason_detail"]) > 0)

    groups = defaultdict(list)
    for e in edge_rows:
        if e["evidence"].strip():
            groups[(e["source"], e["target"], e["kind"])].append(e)
    examples = {}
    for (s, t, k), rows in groups.items():
        rows.sort(key=lambda e: (quality(e), e["month"]), reverse=True)
        picked, seen_text, seen_month = [], set(), Counter()
        for e in rows:
            norm = re.sub(r"\W+", " ", e["evidence"].lower()).strip()
            if norm in seen_text or seen_month[e["month"]] >= 2:
                continue  # skip near-duplicates; spread across months
            seen_text.add(norm)
            seen_month[e["month"]] += 1
            picked.append({
                "q": e["evidence"].strip()[:280],
                "stars": int(e["stars"]) if str(e["stars"]).isdigit() else None,
                "m": e["month"],
                "r": split_reasons(e["reasons"]),
                "d": e["reason_detail"].strip(),
                "o": slug(e["reviewed_app"]),
                "src": e["data_source"],
            })
            if len(picked) == EXAMPLES_PER_GROUP:
                break
        examples[f"{slug(s)}|{slug(t)}|{k}"] = picked

    # ---- reasons legend ---------------------------------------------------
    total_reasons = Counter()
    for e in edge_rows:
        total_reasons.update(split_reasons(e["reasons"]))
    reasons = [{"id": rid, "label": REASON_LABELS.get(rid, rid.replace("_", " ")), "description": mx.REASONS.get(rid, ""),
                "count": total_reasons.get(rid, 0)}
               for rid in sorted(mx.REASONS, key=lambda r: -total_reasons.get(r, 0))]

    # ---- timeline annotations, with numbers from the data -----------------
    def out_rows(month, src="Spotify"):
        return [e for e in edge_rows if e["month"] == month and e["source"] == src
                and e["reviewed_app"] == src and e["kind"] in ("switch", "intent")]

    dec = [e for e in out_rows("2024-12") if e["target"] == "Apple Music"]
    nov = [e for e in out_rows("2024-11") if e["target"] == "Apple Music"]
    wrapped = sum("wrapped" in (e["reason_detail"] + " " + e["evidence"]).lower() for e in dec)

    def fa(rows):
        return sum(bool({"free_tier_limits", "ads"} & set(split_reasons(e["reasons"])))
                   for e in rows)

    feb, mar = out_rows("2025-02"), out_rows("2025-03")
    annotations = [
        {"month": "2024-12", "label": "Spotify Wrapped",
         "detail": (f"Spotify → Apple Music switches and intents rose from {len(nov)} to {len(dec)}; "
                    f"{wrapped} of December's mention Wrapped.")},
        {"month": "2025-03", "label": "Free-tier & ads spike",
         "detail": (f"Spotify's outbound switches and intents hit {len(mar)} (from {len(feb)} in Feb); "
                    f"{fa(mar)} cite free-tier limits or ads (Feb: {fa(feb)}).")},
    ]

    payload = {
        "meta": {
            "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "model": MODEL,
            "edgeRows": len(edge_rows),
            "kinds": KINDS,
            "observed": [slug(a) for a in OBSERVED],
            "normalization": ("weight_per_10k = edge weight / reviews of the app the edge was observed in "
                              "x 10,000. Weight: switch/return 1.0, intent 0.5, preference 0.25, "
                              "x 0.7 for medium confidence."),
        },
        "months": month_info,
        "coverage": coverage,
        "reasons": reasons,
        "nodes": nodes,
        "edges": edges,
        "examples": examples,
        "annotations": annotations,
    }
    DEST.parent.mkdir(parents=True, exist_ok=True)
    DEST.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    size = DEST.stat().st_size
    print(f"Wrote {DEST} ({size / 1024:.0f} KB): {len(nodes)} nodes, {len(edges)} monthly edges, "
          f"{sum(len(v) for v in examples.values())} examples, coverage {coverage['start']}..{coverage['end']}")
    partial = [x for x in month_info if not x["full"]]
    print("partial months:", ", ".join(f"{x['month']} ({x['note']})" for x in partial))
    for a in annotations:
        print(f"annotation {a['month']}: {a['detail']}")


if __name__ == "__main__":
    main()
