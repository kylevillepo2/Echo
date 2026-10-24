#!/usr/bin/env python3
"""Export customer switch reports into a compact, standalone network dataset.

Run from any directory: python3 unwrapathon/scripts/network/export_network.py
Health is copied exclusively from app_stats.json; missing stats fail explicitly.
Inputs are read only. Monthly aggregates are rebuilt from edges.csv so role and
forced-move filtering also works with older, unfiltered edges_monthly.csv files.
Quotes are stored once per directed pair (at most three); monthly edges refer to
their pair by source/target. Quotes retain their own month for time filtering.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
from copy import deepcopy
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "pipeline/switching"))
import report_rules as reports  # noqa: E402


def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as handle:
        yield from csv.DictReader(handle)


def app_id(name):
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "app"
    return slug + "-" + hashlib.sha1(name.encode()).hexdigest()[:6]


def assert_health_matches_stats(data, stats):
    """Fail on any copied all-time/yearly health disagreement, including counts."""
    records = {record["app"]: record for record in stats["apps"] + stats.get("outside_apps", [])}
    for node in data["nodes"]:
        record = records[node["name"]]
        if node["health"] != record["health"] or node["healthByPeriod"] != record["health_by_period"]:
            raise ValueError(f"Health disagrees with app_stats.json for {node['name']}")


def export(input_dir):
    categories = defaultdict(Counter)
    reviews = defaultdict(Counter)
    observed = set()
    for row in read_csv(input_dir / "app_month_counts.csv"):
        name = row["app_name"].strip()
        observed.add(name)
        categories[name][row.get("category") or "other"] += 1
        reviews[name][row["month"]] += int(row["reviews"])

    stats_path = input_dir / "app_stats.json"
    if not stats_path.exists():
        raise ValueError("app_stats.json is required. Run pipeline/switching/fix_switching.py stats first.")
    raw_stats = json.loads(stats_path.read_text())
    stats = {record["app"]: record for record in raw_stats["apps"] + raw_stats.get("outside_apps", [])}
    for name, record in stats.items():
        if "health" not in record or "health_by_period" not in record:
            raise ValueError(f"Missing authoritative balance for {name}; rerun fix_switching.py stats.")
        categories[name][record.get("category") or "other"] += 1
    observed = {name for name, record in stats.items() if record["in_dataset"]}
    for name, record in stats.items():
        if record["in_dataset"]:
            reviews[name] = Counter(record["reviews_per_month"])

    groups = {}
    candidates = defaultdict(dict)
    names = set(stats)
    excluded = Counter()
    raw_edges = list(read_csv(input_dir / "edges.csv"))
    for row in raw_edges:
        if row["kind"] not in {"switch", "return"}:
            excluded["not_actual_switch_report"] += 1
        elif not reports.is_customer(row):
            excluded["non_customer"] += 1
        elif reports.is_forced(row):
            excluded["forced_move"] += 1
    for row in reports.switch_reports(raw_edges):
        source, target = row["source"], row["target"]
        month, kind = row.get("month", ""), row["kind"]
        names.update((source, target))
        for name in (source, target):
            categories[name][row.get("category") or "other"] += 1
        key = (source, target, month, kind, row.get("category") or "other")
        group = groups.setdefault(key, {"count": 0, "weight": 0, "reasons": Counter()})
        group["count"] += 1
        group["weight"] += float(row.get("weight") or 1)
        group["reasons"].update(set(filter(None, (r.strip() for r in row.get("reasons", "").split(";")))))
        quote = row.get("evidence", "").strip()
        if quote:
            candidates[(source, target)].setdefault(quote, {
                "text": quote, "month": month, "reviewedApp": row.get("reviewed_app", ""),
                "reviewId": row.get("feedback_id", ""), "store": row.get("data_source", ""),
                "category": row.get("category") or "other"
            })

    nodes = []
    for name in sorted(names):
        if name not in stats:
            raise ValueError(f"No app_stats.json record for {name}; rerun fix_switching.py stats.")
        record = stats[name]
        nodes.append({"id": app_id(name), "name": name,
                      "category": record.get("category") or categories[name].most_common(1)[0][0],
                      "observed": name in observed,
                      "reviewCount": int(record.get("total_reviews", sum(reviews[name].values()))),
                      "reviewsByMonth": dict(sorted(reviews[name].items())),
                      "reviewCountDefinition": record.get("review_count_definition", "Reviews in our dataset."),
                      "health": deepcopy(record["health"]), "healthByPeriod": deepcopy(record["health_by_period"])})

    edges = [{"source": app_id(source), "target": app_id(target), "month": month, "kind": kind, "category": category,
              "count": values["count"], "weight": round(values["weight"], 4),
              "reasons": [{"reason": reason, "count": count}
                          for reason, count in values["reasons"].most_common()]}
             for (source, target, month, kind, category), values in sorted(groups.items())]
    pairs = []
    for (source, target), quotes in sorted(candidates.items()):
        # Prioritize readable excerpts, with one from each available year first.
        ordered = sorted(quotes.values(), key=lambda q: (not 70 <= len(q["text"]) <= 600, len(q["text"]), q["text"]))
        selected, years = [], set()
        for quote in ordered:
            year = quote["month"][:4]
            if year not in years:
                selected.append(quote)
                years.add(year)
            if len(selected) == 3:
                break
        for quote in ordered:
            if len(selected) == 3:
                break
            if quote not in selected:
                selected.append(quote)
        pairs.append({"source": app_id(source), "target": app_id(target), "quotes": selected})
    data = {"meta": {"definition": raw_stats["meta"]["switch_definition"],
                     "healthDefinition": raw_stats["meta"]["definition"],
                     "healthSource": "app_stats.json", "excluded": dict(excluded)},
            "nodes": nodes, "edges": edges, "pairs": pairs}
    assert_health_matches_stats(data, raw_stats)
    return data



def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=REPO.parent / "out/all")
    parser.add_argument("--output", type=Path, default=REPO / "src/lib/data/network.json")
    args = parser.parse_args()
    data = export(args.input)
    # Keep all counts/reasons; shorten quote excerpts only if needed for budget.
    for limit in (1000, 600, 350, 200):
        for pair in data["pairs"]:
            for quote in pair["quotes"]:
                if len(quote["text"]) > limit:
                    quote["text"] = quote["text"][:limit].rstrip() + "…"
        payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n"
        if len(payload.encode()) < 2_000_000:
            break
    else:
        raise SystemExit("Export exceeds 2 MB; previous network.json was preserved.")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temp = args.output.with_suffix(".tmp")
    temp.write_text(payload, encoding="utf-8")
    temp.replace(args.output)
    print(f"Wrote {args.output}: {len(data['nodes'])} apps, {len(data['edges'])} monthly edges, {len(payload.encode()):,} bytes")


if __name__ == "__main__":
    main()
