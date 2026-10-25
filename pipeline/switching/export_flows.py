#!/usr/bin/env python3
"""Export the all-apps switching graph for the frontend's flow overlay.

Reads (from the workspace's out/all/ folder, produced by run_all_switches.py + fix_switching.py):
  out/all/edges.csv            one row per labeled edge, with reviewer_role and forced_move
  out/all/app_month_counts.csv monthly review volume of each reviewed app
  out/all/app_stats.json       per-app health from switching

Writes:
  unwrapathon/src/lib/data/flows.json

Same rules as the health scores: customers only (rides & delivery reviews by drivers/couriers
or of unclear role are left out) and no forced moves (apps that shut down). Months are limited
to WINDOW, where most reviewed apps have data.

Edges stay split by the app whose reviews they were seen in ("o"), because weight per 10k is
normalized by that app's review volume. The frontend sums weight and volume per observing app
over any period, then adds the rates.

App ids match the demo corpus (src/lib/api/mock.ts) by name, so flows line up with map nodes.

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
import switch_extraction as sx  # noqa: E402

ROOT = HERE.parents[2]                       # workspace root
OUT = ROOT / "out" / "all"
REPO = HERE.parents[1]
DEST = REPO / "src" / "lib" / "data" / "flows.json"
MOCK = REPO / "src" / "lib" / "api" / "mock.ts"

WINDOW = ("2024-06", "2026-05")              # months where most reviewed apps have data
KINDS = ["switch", "return", "intent", "preference"]
EXAMPLES_PER_GROUP = 3                       # 2 for preferences
QUOTE_CHARS = 180
LOW_VOLUME_SHARE = 0.25                      # month < 25% of the app's median = partial
MODEL = "gpt-6-luna"
# fix_switching.py splits the pooled Uber corpus into two reviewed markets. Both are normalized by
# pooled Uber volume (as in edges_monthly.csv); Uber (Rides) is the demo map's Uber node.
UBER_MARKETS = {"Uber (Rides)", "Uber Eats"}
DEMO_ALIASES = {"Uber (Rides)": "Uber"}

csv.field_size_limit(10**9)


def slug(name):
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def demo_ids():
    """App name -> id in the demo corpus, so flow nodes and map nodes share ids."""
    text = MOCK.read_text()
    return {name: id_ for id_, name in re.findall(r"id:\s*'([^']+)',\s*\n\s*name:\s*'([^']+)'", text)}


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


def read_csv(path):
    if not path.exists():
        sys.exit(f"Missing {path}. Run run_all_switches.py edges and fix_switching.py apply first.")
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def main():
    months = month_range(*WINDOW)
    in_window = set(months)
    all_edges = read_csv(OUT / "edges.csv")
    if "reviewer_role" not in all_edges[0]:
        sys.exit("edges.csv has no reviewer_role column. Run fix_switching.py apply first.")
    kept, seen = [], set()
    for e in all_edges:
        if e["reviewer_role"] not in ("customer", "n/a") or e["forced_move"] == "True":
            continue
        k = (e["feedback_id"], e["source"], e["target"], e["month"], e["kind"])
        if k in seen:  # duplicate review/pair/month/kind rows count once (as in app_stats)
            continue
        seen.add(k)
        kept.append(e)
    edge_rows = [e for e in kept if e["month"] in in_window]
    stats = json.loads((OUT / "app_stats.json").read_text())

    demo = demo_ids()
    observed_names = sorted(a["app"] for a in stats["apps"])
    missing_demo = [a for a in observed_names if DEMO_ALIASES.get(a, a) not in demo]
    if missing_demo:
        print("Warning: reviewed apps not in the demo corpus (kept with slug ids):", missing_demo)

    def node_id(name):
        return demo.get(DEMO_ALIASES.get(name, name), slug(name))

    def volume_app(name):
        return "Uber" if name in UBER_MARKETS else name

    def category(name):
        return sx.APP_CATEGORY.get(volume_app(name))

    # ---- review volume and per-app partial months ---------------------------------
    volume = defaultdict(dict)
    for r in read_csv(OUT / "app_month_counts.csv"):
        if r["month"] in in_window:
            volume[r["app_name"]][r["month"]] = int(r["reviews"])
    for market in UBER_MARKETS:
        volume[market] = volume["Uber"]
    low_months = {}
    for a in observed_names:
        if a not in volume and a not in UBER_MARKETS:
            print("Warning: no review volume for", a)
        med = statistics.median([v for v in volume[a].values() if v] or [0])
        low_months[a] = [m for m in months if volume[a].get(m, 0) < LOW_VOLUME_SHARE * med]

    month_info = []
    for m in months:
        missing = [a for a in observed_names if not volume[a].get(m)]
        low = [a for a in observed_names if volume[a].get(m) and m in low_months[a]]
        notes = []
        if missing:
            notes.append(f"No reviews for {len(missing)} apps" if len(missing) > 3 else f"No {', '.join(missing)} reviews")
        if low:
            notes.append(f"Low volume for {len(low)} apps" if len(low) > 3 else f"Low {', '.join(low)} volume")
        month_info.append({"month": m, "full": not missing and not low,
                           "missing": [node_id(a) for a in missing], "low": [node_id(a) for a in low],
                           "note": "; ".join(notes)})
    # Global coverage (all reviewed apps normal) is short; the frontend computes it per cluster.
    best, run = [], []
    for x in month_info:
        run = run + [x["month"]] if x["full"] else []
        if len(run) > len(best):
            best = run
    coverage = {"start": best[0] if best else months[0], "end": best[-1] if best else months[-1],
                "months": best or months,
                "note": "Months where every reviewed app has normal volume. The map recomputes this per cluster."}

    # ---- monthly edges, split by observing app ---------------------------------------
    agg = defaultdict(lambda: {"n": 0, "w": 0.0, "r": Counter()})
    for e in edge_rows:
        a = agg[(e["month"], e["source"], e["target"], e["kind"], e["reviewed_app"])]
        a["n"] += 1
        a["w"] += float(e["weight"])
        a["r"].update(split_reasons(e["reasons"]))
    edges = []
    for (m, s, t, k, o), a in sorted(agg.items()):
        vol = volume[o].get(m, 0)
        edges.append({"m": m, "s": node_id(s), "t": node_id(t), "k": k, "o": node_id(o),
                      "n": a["n"], "w": round(a["w"], 3), "w10k": round(a["w"] / vol * 1e4, 3) if vol else 0,
                      "r": [[name, c] for name, c in a["r"].most_common()]})

    # ---- nodes -------------------------------------------------------------------------
    observed = set(observed_names)
    involvement = Counter()
    seen_in = defaultdict(Counter)
    for e in edge_rows:
        involvement[e["source"]] += 1
        involvement[e["target"]] += 1
        for app in (e["source"], e["target"]):
            if app not in observed:
                seen_in[app][e["reviewed_app"]] += 1
    category_of = {}
    for cid, c in sx.CATEGORIES.items():
        for a in c["apps"] + c["competitors"]:
            category_of.setdefault(sx.CONFIG.get("node_merges", {}).get(a, a), cid)
    health = {a["app"]: a for a in stats["apps"]}
    names = set(involvement) | observed
    nodes = []
    for name in sorted(names, key=lambda n: (n not in observed, -involvement[n], n)):
        cid = category(name) or category_of.get(name)
        node = {"id": node_id(name), "name": name, "observed": name in observed,
                "edgeCount": involvement[name], "category": cid,
                "categoryLabel": sx.CATEGORIES.get(cid, {}).get("label", cid)}
        if name in observed:
            node["volume"] = {m: volume[name].get(m, 0) for m in months}
            node["totalVolume"] = sum(node["volume"].values())
            node["lowMonths"] = low_months[name]
            h = health.get(name, {})
            hh, trend = h.get("health", {}), h.get("rating_trend", {})

            def health_of(x):
                return {"score": x.get("score"), "bucket": x.get("bucket"), "reportsIn": x.get("reports_in"),
                        "reportsOut": x.get("reports_out"), "total": x.get("total")}
            node["health"] = health_of(hh)
            node["healthByPeriod"] = {y: health_of(v) for y, v in h.get("health_by_period", {}).items()}
            node["rating"] = {"avg": h.get("avg_stars"), "trend": trend.get("change")}
            if h.get("review_count_definition"):
                node["volumeNote"] = "Pooled Uber reviews (both markets) used for normalization."
        else:
            node["seenIn"] = [node_id(a) for a, _ in seen_in[name].most_common(4)]
        nodes.append(node)

    # ---- example quotes ------------------------------------------------------------------
    def quality(e):
        ev = e["evidence"].strip()
        return (float(e["weight"]), bool(split_reasons(e["reasons"])), 25 <= len(ev) <= QUOTE_CHARS, bool(e["reason_detail"]))

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
                continue
            seen_text.add(norm)
            seen_month[e["month"]] += 1
            picked.append({"q": e["evidence"].strip()[:QUOTE_CHARS],
                           "stars": int(e["stars"]) if str(e["stars"]).isdigit() else None,
                           "m": e["month"], "r": split_reasons(e["reasons"]), "d": e["reason_detail"].strip()[:120],
                           "o": node_id(e["reviewed_app"])})
            if len(picked) == (2 if k == "preference" else EXAMPLES_PER_GROUP):
                break
        examples[f"{node_id(s)}|{node_id(t)}|{k}"] = picked

    # ---- reasons -----------------------------------------------------------------------
    total_reasons = Counter(r for e in edge_rows for r in split_reasons(e["reasons"]))
    labels = {"price_fees": "Price & fees", "ads": "Ads", "missing_features_limits": "Features & limits",
              "content_selection": "Content & selection", "bugs_performance": "Bugs & performance",
              "design_changes": "Design changes", "customer_support": "Customer support",
              "account_security_trust": "Account & trust", "policy_privacy": "Policy & privacy",
              "speed_availability": "Speed & availability", "other": "Other"}
    reasons = [{"id": rid, "label": labels.get(rid, rid), "description": sx.REASONS.get(rid, ""),
                "count": total_reasons.get(rid, 0)}
               for rid in sorted(sx.REASONS, key=lambda r: -total_reasons.get(r, 0))]

    # ---- annotations (shown when the focused cluster contains one of `apps`) ------------
    def out_rows(month, src):
        return [e for e in edge_rows if e["month"] == month and e["source"] == src
                and e["reviewed_app"] == src and e["kind"] in ("switch", "intent")]

    def fa(rows):
        return sum(bool({"missing_features_limits", "ads"} & set(split_reasons(e["reasons"]))) for e in rows)

    dec = [e for e in out_rows("2024-12", "Spotify") if e["target"] == "Apple Music"]
    nov = [e for e in out_rows("2024-11", "Spotify") if e["target"] == "Apple Music"]
    wrapped = sum("wrapped" in (e["reason_detail"] + " " + e["evidence"]).lower() for e in dec)
    feb, mar = out_rows("2025-02", "Spotify"), out_rows("2025-03", "Spotify")
    annotations = [
        {"month": "2024-12", "label": "Spotify Wrapped", "apps": [node_id("Spotify")],
         "detail": (f"Spotify → Apple Music switches and intents rose from {len(nov)} to {len(dec)}; "
                    f"{wrapped} of December's mention Wrapped.")},
        {"month": "2025-03", "label": "Free-tier & ads spike", "apps": [node_id("Spotify")],
         "detail": (f"Spotify's outbound switches and intents hit {len(mar)} (from {len(feb)} in Feb); "
                    f"{fa(mar)} cite feature limits or ads (Feb: {fa(feb)}).")},
    ]

    # ---- compact edge encoding: months, nodes, kinds and reasons by index ----------------
    # Row: [month, source, target, kind, observed_in, count, weight, weight_per_10k, r0, c0, r1, c1, ...]
    node_index = {n["id"]: i for i, n in enumerate(nodes)}
    month_index = {m: i for i, m in enumerate(months)}
    reason_index = {r["id"]: i for i, r in enumerate(reasons)}
    rows = []
    for e in edges:
        row = [month_index[e["m"]], node_index[e["s"]], node_index[e["t"]], KINDS.index(e["k"]), node_index[e["o"]],
               e["n"], round(e["w"], 2), round(e["w10k"], 2)]
        for name, c in e["r"]:
            row += [reason_index[name], c]
        rows.append(row)
    compact_edges = {"format": "[month, source, target, kind, observed_in, count, weight, weight_per_10k, "
                               "reason, count, reason, count, ...] with months/nodes/kinds/reasons as indexes",
                     "rows": rows}

    payload = {
        "meta": {
            "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "model": MODEL,
            "edgeRows": len(edge_rows),
            "kinds": KINDS,
            "observed": [node_id(a) for a in observed_names],
            "window": list(WINDOW),
            "healthDefinition": stats["meta"].get("definition", ""),
            "healthBuckets": stats["meta"].get("buckets", {}),
            "filters": "customers only (rides & delivery drivers/couriers and unclear roles excluded); "
                       "forced moves from shut-down apps excluded",
            "normalization": ("weight_per_10k = edge weight / reviews of the app the edge was observed in "
                              "x 10,000. Weight: switch/return 1.0, intent 0.5, preference 0.25, "
                              "x 0.7 for medium confidence."),
        },
        "months": month_info,
        "coverage": coverage,
        "reasons": reasons,
        "nodes": nodes,
        "edges": compact_edges,
        "examples": examples,
        "annotations": annotations,
    }
    DEST.parent.mkdir(parents=True, exist_ok=True)
    DEST.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    size = DEST.stat().st_size
    dropped = len(kept) - len(edge_rows)
    print(f"Wrote {DEST} ({size / 1024:.0f} KB): {len(nodes)} nodes ({len(observed_names)} reviewed), "
          f"{len(edges):,} monthly edge rows from {len(edge_rows):,} edges, "
          f"{sum(len(v) for v in examples.values()):,} quotes")
    print(f"Filtered out: {len(all_edges) - len(kept):,} driver/unclear/forced edges; "
          f"{dropped:,} edges outside {WINDOW[0]}..{WINDOW[1]}")
    for a in annotations:
        print(f"annotation {a['month']}: {a['detail']}")


if __name__ == "__main__":
    main()
