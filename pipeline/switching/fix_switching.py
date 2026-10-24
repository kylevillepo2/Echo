#!/usr/bin/env python3
"""Corrections and per-app stats for the all-apps switching graph (out/all/).

Steps:
  roles  ask gpt-6-luna (batches of 10) whether each rides/delivery review was written by a
         customer, a driver/courier, or is unclear (resumable)
  apply  write corrected mentions.csv, edges.csv, edges_monthly.csv (originals kept as *_v1.csv):
         reviewer_role column, Uber market split (self-edges dropped),
         forced_move flag for apps that shut down (categories.json "shutdowns")
  stats  app_stats.json + app_stats.csv: review stats from the raw data plus switching health

Examples (from the workspace folder):
  python3 unwrapathon/pipeline/switching/fix_switching.py roles --workers 48
  python3 unwrapathon/pipeline/switching/fix_switching.py apply
  python3 unwrapathon/pipeline/switching/fix_switching.py stats
"""
import argparse
import csv
import json
import os
import shutil
import sys
import threading
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import run_all_switches as ras  # noqa: E402
import run_music_edges as rme  # noqa: E402
import switch_extraction as sx  # noqa: E402
import report_rules as reports  # noqa: E402

OUT = ras.OUT
MODEL = ras.MODEL
ROLES = ["customer", "driver/courier", "unclear"]
RIDES_APPS = {"Uber", "Lyft", "DoorDash", "Uber Eats", "Grubhub", "Instacart"}  # plus every rides_delivery review
NODE_MERGES = sx.CONFIG.get("node_merges", {})
SHUTDOWNS = sx.CONFIG.get("shutdowns", {})
ROLES_PATH = ras.RESULTS / f"roles_{MODEL}.jsonl"

csv.field_size_limit(10**9)


def read_csv(path):
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def v1(name):
    """Original file, preserved once as *_v1.csv before the first correction."""
    cur, old = OUT / f"{name}.csv", OUT / f"{name}_v1.csv"
    if not old.exists():
        shutil.copyfile(cur, old)
    return old


# ---------------------------------------------------------------------------
# Step 1: reviewer roles
# ---------------------------------------------------------------------------
ROLE_PROMPT = """You read app store reviews of ride-hailing and delivery apps (Uber, Lyft, DoorDash, Uber Eats,
Grubhub, Instacart, Spark Driver). For each review, decide who wrote it:
- customer: rides as a passenger, or orders food/groceries/packages as a customer.
- driver/courier: works for a platform as a driver, Dasher, courier, or Instacart/Spark shopper. Signs: talks about
  their pay or earnings, offers, acceptance rate, deactivation, ratings from customers, dashing, "as a driver".
- unclear: you can't tell, or the writer is a restaurant/merchant or someone else.
Decide from the review text only. Return exactly one entry per review id, in the same order."""


def role_schema():
    return {"type": "object", "additionalProperties": False, "required": ["reviews"],
            "properties": {"reviews": {"type": "array", "items": {
                "type": "object", "additionalProperties": False, "required": ["id", "role"],
                "properties": {"id": {"type": "string"}, "role": {"type": "string", "enum": ROLES}}}}}}


class RoleLLM(ras.CategoryLLM):
    def roles(self, cands):
        # Short per-batch ids (r1, r2, ...): the model tends to trim "feedback_id|app" keys.
        local = {f"r{i}": rme.key(c) for i, c in enumerate(cands, 1)}
        blocks = [f"{len(cands)} reviews follow."]
        for rid, c in zip(local, cands):
            blocks.append(f"=== REVIEW id={rid} ===\nREVIEWED APP: {c['app_name']}\nSTARS: {c['stars']}\nREVIEW:\n{c['text']}")
        body = {"model": self.model,
                "messages": [{"role": "system", "content": ROLE_PROMPT},
                             {"role": "user", "content": "\n\n".join(blocks)}],
                "response_format": {"type": "json_schema",
                                    "json_schema": {"name": "reviewer_roles", "strict": True, "schema": role_schema()}}}
        data = self._post(body)
        u = data.get("usage", {})
        usage = {"prompt_tokens": u.get("prompt_tokens", 0), "completion_tokens": u.get("completion_tokens", 0),
                 "cached_tokens": (u.get("prompt_tokens_details") or {}).get("cached_tokens", 0)}
        out = {}
        for e in json.loads(data["choices"][0]["message"]["content"]).get("reviews", []):
            key = local.get(str(e.get("id", "")).strip())
            if key and key not in out and e.get("role") in ROLES:
                out[key] = e["role"]
        return out, usage


def rides_review_keys():
    keys = set()
    for e in read_csv(v1("edges")):
        if e["category"] == "rides_delivery" or e["source"] in RIDES_APPS or e["target"] in RIDES_APPS:
            keys.add(f'{e["feedback_id"]}|{e["reviewed_app"]}')
    return keys


def load_roles():
    roles = {}
    if ROLES_PATH.exists():
        for line in ROLES_PATH.open():
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if r.get("ok"):
                roles[r["key"]] = r["role"]
    return roles


def classify_roles(args):
    keys = rides_review_keys()
    cands = [c for c in ras.load_candidates() if rme.key(c) in keys]
    done = load_roles()
    todo = [c for c in cands if rme.key(c) not in done]
    print(f"{len(keys):,} rides reviews behind edges; {len(done):,} done, {len(todo):,} to classify", flush=True)
    llm = RoleLLM(MODEL, args.base_url, None)
    lock = threading.Lock()
    stats = Counter()
    t0 = time.time()

    def work(batch):
        try:
            got, usage = llm.roles(batch)
        except Exception as e:
            return [{"key": rme.key(c), "ok": False, "error": str(e)[:300]} for c in batch], batch
        share = {k: v / max(len(got), 1) for k, v in usage.items()}
        recs = [{"key": rme.key(c), "ok": True, "role": got[rme.key(c)], "usage": share} for c in batch if rme.key(c) in got]
        return recs, [c for c in batch if rme.key(c) not in got]

    for attempt in range(3):  # missing ids are retried in later rounds
        if not todo:
            break
        batches = [todo[i:i + args.batch] for i in range(0, len(todo), args.batch)]
        retry = []
        ROLES_PATH.parent.mkdir(parents=True, exist_ok=True)
        with ROLES_PATH.open("a") as out, ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = [pool.submit(work, b) for b in batches]
            for i, fut in enumerate(as_completed(futures), 1):
                recs, miss = fut.result()
                with lock:
                    for rec in recs:
                        out.write(json.dumps(rec) + "\n")
                        stats["ok"] += 1
                        for k, v in rec["usage"].items():
                            stats[k] += v
                    out.flush()
                    retry += miss
                if i % 100 == 0 or i == len(batches):
                    print(f"  round {attempt + 1}: {i:,}/{len(batches):,} requests, ok={stats['ok']:,}, "
                          f"missing={len(retry):,}, {stats['ok'] / max(time.time() - t0, 1):.0f}/s, "
                          f"~${rme.cost(MODEL, stats):.2f}", flush=True)
        todo = retry
    roles = load_roles()
    print(f"Classified {len(set(roles) & keys):,}/{len(keys):,}; this run ~${rme.cost(MODEL, stats):.2f}")
    print("roles:", dict(Counter(roles[k] for k in keys if k in roles)))


# ---------------------------------------------------------------------------
# Step 2: apply corrections
# ---------------------------------------------------------------------------
def merge_node(name):
    return NODE_MERGES.get(name, name)


def apply(args):
    roles = load_roles()
    edges_old, mentions_old = read_csv(v1("edges")), read_csv(v1("mentions"))
    v1("edges_monthly")

    def role_of(fid, reviewed, apps, category):
        if category != "rides_delivery" and not (set(apps) & RIDES_APPS):
            return "n/a"
        return roles.get(f"{fid}|{reviewed}", "unclassified")

    edges, self_edges = [], Counter()
    for e in edges_old:
        normalized = reports.normalize_edge(e)
        src, dst = normalized["source"], normalized["target"]
        if src == dst:
            self_edges[(e["reviewed_app"], e["source"], e["target"], e["kind"])] += 1
            continue
        edges.append({**normalized,
                      "reviewer_role": role_of(e["feedback_id"], e["reviewed_app"], (e["source"], e["target"]), e["category"]),
                      "forced_move": reports.is_forced(normalized, SHUTDOWNS)})
    mentions, self_mentions = [], 0
    for m in mentions_old:
        normalized = reports.normalize_edge({"source": m["reviewed_app"], "target": m["mentioned_app"], **m}, allow_unassigned=True)
        app, reviewed = normalized["target"], normalized["source"]
        if app == reviewed:
            self_mentions += 1
            continue
        mentions.append({**m, "mentioned_app": app, "reviewed_app": reviewed,
                         "reviewed_app_original": m["reviewed_app"],
                         "reviewer_role": role_of(m["feedback_id"], m["reviewed_app"], (m["reviewed_app"], m["mentioned_app"]), m["category"])})

    rme.write_csv(OUT / "edges.csv", edges)
    rme.write_csv(OUT / "mentions.csv", mentions)

    volume = {(r["app_name"], r["month"]): int(r["reviews"]) for r in read_csv(OUT / "app_month_counts.csv")}
    agg = defaultdict(lambda: [0, 0.0])
    for e in edges:
        agg[(e["category"], e["month"], e["source"], e["target"], e["kind"], e["reviewed_app"],
             e["reviewer_role"], e["forced_move"])][0] += 1
        agg[(e["category"], e["month"], e["source"], e["target"], e["kind"], e["reviewed_app"],
             e["reviewer_role"], e["forced_move"])][1] += float(e["weight"])
    monthly = []
    for (cid, month, s, t, kind, reviewed, role, forced), (n, w) in sorted(agg.items(), key=lambda x: tuple(map(str, x[0]))):
        original_reviewed = "Uber" if reviewed in {reports.UBER_RIDES, reports.UBER_EATS} else reviewed
        vol = volume.get((original_reviewed, month), 0)
        monthly.append({"category": cid, "month": month, "source": s, "target": t, "kind": kind,
                        "observed_in_reviews_of": reviewed, "reviewer_role": role, "forced_move": forced,
                        "count": n, "weight": round(w, 3), "reviewed_app_volume": vol,
                        "reviewed_app_volume_app": original_reviewed,
                        "weight_per_10k_reviews": round(w / vol * 1e4, 3) if vol else ""})
    rme.write_csv(OUT / "edges_monthly.csv", monthly)

    print(f"edges {len(edges_old):,} -> {len(edges):,}; self-edges dropped after market naming: "
          f"{sum(self_edges.values())} {dict(self_edges)}")
    print(f"mentions {len(mentions_old):,} -> {len(mentions):,} ({self_mentions} self-mentions dropped after market naming)")
    rides = [e for e in edges if e["reviewer_role"] != "n/a"]
    print("reviewer_role on rides edges:", dict(Counter(e["reviewer_role"] for e in rides)))
    forced = [e for e in edges if e["forced_move"]]
    print("forced_move edges:", dict(Counter(f'{e["source"]} -> {e["target"]}' for e in forced).most_common(12)),
          f"(total {len(forced)})")

    sw = [e for e in edges if e["kind"] in ("switch", "return")]
    print("\nDriver share of the top rides switch flows (switch + return):")
    top_rides = Counter((e["source"], e["target"]) for e in sw if e["reviewer_role"] != "n/a")
    for (s, t), n in top_rides.most_common(8):
        rc = Counter(e["reviewer_role"] for e in sw if (e["source"], e["target"]) == (s, t))
        print(f"  {s:>10} -> {t:<10} {n:>4}  customer {rc['customer']:>4}  driver {rc['driver/courier']:>4} "
              f"({rc['driver/courier'] / n:.0%})  unclear {rc['unclear'] + rc['unclassified']:>3}")

    clean = [e for e in sw if e["reviewer_role"] in ("customer", "n/a") and not e["forced_move"]]
    top = Counter((e["category"], e["source"], e["target"]) for e in clean)
    print("\nTop 20 switch flows, customers only, no forced moves:")
    for (cid, s, t), n in top.most_common(20):
        rc = Counter(x for e in clean if (e["category"], e["source"], e["target"]) == (cid, s, t)
                     for x in e["reasons"].split(";") if x)
        print(f"  {s:>14} -> {t:<14} {n:>4}  [{cid}]  {', '.join(f'{k} {v}' for k, v in rc.most_common(2))}")


# ---------------------------------------------------------------------------
# Step 3: per-app stats and switching balance (the only health calculation)
# ---------------------------------------------------------------------------
BALANCE_DEFINITION = "Balance of switches reported in reviews, between apps both in our dataset. Not a measure of user growth."
BUCKETS = {
    "Positive switching balance": "> +0.2",
    "Mixed": "-0.2 to +0.2",
    "Negative switching balance": "-0.5 to below -0.2",
    "Strongly negative": "< -0.5",
    "Too few reports": "fewer than 20 switch reports",
}


def health_bucket(score, total):
    if total < 20:
        return "Too few reports"
    if score > .2:
        return "Positive switching balance"
    if score >= -.2:
        return "Mixed"
    if score >= -.5:
        return "Negative switching balance"
    return "Strongly negative"


def balance_record(app, scoped_reports):
    incoming = sum(row["target"] == app for row in scoped_reports)
    outgoing = sum(row["source"] == app for row in scoped_reports)
    total = incoming + outgoing
    score = (incoming - outgoing) / total if total else None
    return {"score": round(score, 6) if score is not None else None,
            "bucket": health_bucket(score or 0, total), "reports_in": incoming,
            "reports_out": outgoing, "total": total, "source": "app_stats",
            "definition": BALANCE_DEFINITION}


def scan_reviews(uber_markets):
    """One pass over raw reviews; pooled Uber reviews need market attribution."""
    stars = defaultdict(lambda: defaultdict(Counter))
    coverage = Counter()
    with open(ras.DATA_CSV, encoding="utf-8", errors="replace", newline="") as f:
        for row in csv.DictReader(line.replace("\x00", "") for line in f):
            try:
                names = json.loads(row.get("app_names") or "[]")
            except json.JSONDecodeError:
                names = [row.get("app_names", "")]
            try:
                star = int(float(row.get("stars") or 0))
            except ValueError:
                star = 0
            month = (row.get("feedback_date") or "")[:7]
            for raw_name in names:
                name = sx.canonical_app(raw_name)
                if name == "Uber":
                    coverage["pooled_uber_reviews"] += 1
                    name = uber_markets.get(row["feedback_id"])
                    if name is None:
                        coverage["unassigned_uber_reviews"] += 1
                        continue
                    coverage[name] += 1
                stars[name][month][star] += 1
    return stars, dict(coverage)


def avg(counter):
    count = sum(v for k, v in counter.items() if 1 <= k <= 5)
    return round(sum(k * v for k, v in counter.items() if 1 <= k <= 5) / count, 3) if count else None


def flow_list(rows, key, k=3):
    groups = defaultdict(list)
    for row in rows:
        groups[row[key]].append(row)
    result = []
    for app, items in sorted(groups.items(), key=lambda item: (-len(item[1]), item[0]))[:k]:
        reasons = Counter(reason for row in items for reason in set(row.get("reasons", "").split(";")) if reason)
        top = reasons.most_common(1)
        result.append({"app": app, "count": len(items), "top_reason": top[0][0] if top else None,
                       "top_reason_count": top[0][1] if top else 0})
    return result


def review_stats(months):
    ms = sorted(month for month in months if month)
    total = Counter()
    for month in ms:
        total.update(months[month])

    def window(selected):
        count = Counter()
        for month in selected:
            count.update(months[month])
        return count

    def trend(first, last):
        a, b = avg(window(first)), avg(window(last))
        return {"first_3_months": first, "first_3_avg": a, "first_3_reviews": sum(window(first).values()),
                "last_3_months": last, "last_3_avg": b, "last_3_reviews": sum(window(last).values()),
                "change": round(b - a, 3) if a is not None and b is not None else None}

    volumes = sorted(sum(months[month].values()) for month in ms)
    median = volumes[len(volumes) // 2] if volumes else 0
    normal = [month for month in ms if sum(months[month].values()) >= .25 * median]
    return {"total_reviews": sum(total.values()), "avg_stars": avg(total),
            "star_distribution": {str(star): total.get(star, 0) for star in range(1, 6)},
            "months_with_data": ms, "first_month": ms[0] if ms else None, "last_month": ms[-1] if ms else None,
            "reviews_per_month": {month: sum(months[month].values()) for month in ms},
            "rating_trend": {**trend(normal[:3], normal[-3:]), "months_used": "normal-volume months only"},
            "rating_trend_raw": trend(ms[:3], ms[-3:])}


def build_stats(edges, star_data, app_categories, shutdowns=None):
    """Build the sole source of all-time and yearly balance values."""
    clean = list(reports.switch_reports(edges, shutdowns))
    dataset = reports.dataset_categories(app_categories)
    # Both endpoints must belong to the observed dataset. Outside-app reports
    # remain available as context in flow lists, but never affect balance.
    scoped = [row for row in clean if row["source"] in dataset and row["target"] in dataset]
    nodes = set(dataset) | {app for row in clean for app in (row["source"], row["target"])}
    years = ["2024", "2025"]  # periods exposed by the network UI
    by_year = {year: [row for row in scoped if row.get("month", "").startswith(year)] for year in years}
    category_of = dict(dataset)
    for row in clean:
        for name in (row["source"], row["target"]):
            category_of.setdefault(name, row.get("category") or "other")
    apps, outside = [], []
    for app in sorted(nodes):
        outgoing = [row for row in clean if row["source"] == app]
        incoming = [row for row in clean if row["target"] == app]
        record = {"app": app, "category": category_of.get(app, "other"), "in_dataset": app in dataset,
                  "reports_out_to": flow_list(outgoing, "target"), "reports_in_from": flow_list(incoming, "source"),
                  "health": balance_record(app, scoped),
                  "health_by_period": {year: balance_record(app, rows) for year, rows in by_year.items()}}
        if app in dataset:
            record.update(review_stats(star_data.get(app, {})))
            if app in {reports.UBER_RIDES, reports.UBER_EATS}:
                record["review_count_definition"] = "Uber reviews assigned by the competitor mentioned; unassigned or mixed-market reviews excluded."
            apps.append(record)
        else:
            record["note"] = "Only seen through other apps' reviews; excluded from switching balance."
            outside.append(record)
    top = Counter((row["source"], row["target"]) for row in clean)
    meta = {"generated_from": "out/all/edges.csv + data/reviews-clean.csv",
            "definition": BALANCE_DEFINITION,
            "switch_definition": "Switch reports include switch and return kinds, customers only where roles apply; forced moves excluded; duplicate review/pair/month/kind rows counted once.",
            "score_definition": "(switch reports in - switch reports out) / (switch reports in + switch reports out); returns count in their reported direction.",
            "scope": "Both apps in the dataset, including the two Uber markets inherited from the pooled Uber corpus.",
            "buckets": BUCKETS, "eligible_switch_reports": len(scoped),
            "context_switch_reports": len(clean), "outside_scope_switch_reports": len(clean) - len(scoped),
            "skype_forced_from": "2025-02",
            "lists": "Top 3 counterpart apps by switch reports; may include outside-app context excluded from balance.",
            "top_flows": [{"source": source, "target": target, "count": count} for (source, target), count in top.most_common(20)],
            "top_uber_flows": [{"source": source, "target": target, "count": count} for (source, target), count in top.most_common()
                               if source in {reports.UBER_RIDES, reports.UBER_EATS} or target in {reports.UBER_RIDES, reports.UBER_EATS}][:12]}
    return {"meta": meta, "apps": apps, "outside_apps": outside}


def stats(args):
    edges = read_csv(OUT / "edges.csv")
    print("Scanning reviews for stats and Uber market attribution...", flush=True)
    star_data, coverage = scan_reviews(reports.uber_review_markets(read_csv(OUT / "mentions.csv")))
    data = build_stats(edges, star_data, sx.APP_CATEGORY, SHUTDOWNS)
    data["meta"]["uber_review_attribution"] = coverage
    path = OUT / "app_stats.json"
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n")
    temporary.replace(path)
    rows = []
    for record in data["apps"] + data["outside_apps"]:
        health = record["health"]
        rows.append({"app": record["app"], "category": record["category"], "in_dataset": record["in_dataset"],
                     "total_reviews": record.get("total_reviews", ""), "avg_stars": record.get("avg_stars", ""),
                     **{f"stars_{star}": record.get("star_distribution", {}).get(star, "") for star in "12345"},
                     "first_month": record.get("first_month", ""), "last_month": record.get("last_month", ""),
                     "months": len(record.get("months_with_data", [])),
                     "first_3_avg": record.get("rating_trend", {}).get("first_3_avg", ""),
                     "last_3_avg": record.get("rating_trend", {}).get("last_3_avg", ""),
                     "rating_change": record.get("rating_trend", {}).get("change", ""),
                     "switch_reports_in": health["reports_in"], "switch_reports_out": health["reports_out"],
                     "total_switch_reports": health["total"], "score": health["score"], "bucket": health["bucket"],
                     "definition": health["definition"],
                     "reports_out_to": json.dumps(record["reports_out_to"], ensure_ascii=False),
                     "reports_in_from": json.dumps(record["reports_in_from"], ensure_ascii=False)})
    rme.write_csv(OUT / "app_stats.csv", rows)
    print(f"Wrote stats for {len(data['apps'])} dataset apps and {len(data['outside_apps'])} outside apps.")
    print(f"Eligible switch reports: {data['meta']['eligible_switch_reports']}; outside scope: {data['meta']['outside_scope_switch_reports']}")
    print("Uber review attribution:", coverage)
    for flow in data["meta"]["top_uber_flows"]:
        print(f"  {flow['source']} -> {flow['target']}: {flow['count']} switch reports")


def main():
    rme.load_env()
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sr = sub.add_parser("roles")
    sr.add_argument("--base-url", default=os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"))
    sr.add_argument("--workers", type=int, default=48)
    sr.add_argument("--batch", type=int, default=10)
    sub.add_parser("apply")
    sub.add_parser("stats")
    args = p.parse_args()
    {"roles": classify_roles, "apply": apply, "stats": stats}[args.cmd](args)


if __name__ == "__main__":
    main()
