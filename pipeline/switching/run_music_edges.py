#!/usr/bin/env python3
"""Run music edge extraction end to end. Standard library only (no pip installs).

Steps:
  candidates  reviews-clean.csv -> out/music_candidates.jsonl (+ out/app_month_counts.csv)
  pilot       label a fixed random sample with 1+ models and compare them
  full        label every candidate with one model (resumable)
  edges       turn labels into out/music_mentions.csv, out/music_edges.csv, out/music_edges_monthly.csv

Examples:
  python3 run_music_edges.py candidates
  python3 run_music_edges.py pilot --n 200 --models gpt-6-luna,gpt-5.4-mini
  python3 run_music_edges.py full --model gpt-6-luna
  python3 run_music_edges.py edges --model gpt-6-luna

API key: OPENAI_API_KEY in the environment or in a .env file at the project root.
Optional OPENAI_BASE_URL (or --base-url) if the key is for a proxy / organizer endpoint.
Test the plumbing without spending anything: add --mock.
"""
import argparse
import csv
import json
import os
import random
import re
import sys
import threading
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import music_edge_extraction as mx  # noqa: E402

ROOT = HERE.parents[2]  # workspace root (script lives in unwrapathon/pipeline/switching/)
OUT = ROOT / "out"
CAND = OUT / "music_candidates.jsonl"
RESULTS = OUT / "results"

# Approximate standard-tier prices per 1M tokens (input, cached input, output).
# From a third-party Oct 2026 rate card: confirm on OpenAI's pricing page.
PRICES = {
    "gpt-6-luna":   (0.10, 0.01, 0.50),
    "gpt-5.4-nano": (0.20, 0.02, 1.25),
    "gpt-5.4-mini": (0.75, 0.075, 4.50),
    "gpt-5.4":      (2.50, 0.25, 15.00),
}

csv.field_size_limit(10**9)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
def load_env():
    env_file = ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


# ---------------------------------------------------------------------------
# Step 1: candidates
# ---------------------------------------------------------------------------
def build_candidates(csv_path):
    OUT.mkdir(exist_ok=True)
    month_counts = Counter()
    n_rows = n_cand = 0
    tmp = CAND.with_suffix(".tmp")
    with open(csv_path, encoding="utf-8", errors="replace", newline="") as f, tmp.open("w") as out:
        lines = (l.replace("\x00", "") for l in f)  # file contains stray NUL bytes
        for r in csv.DictReader(lines):
            n_rows += 1
            try:
                names = json.loads(r.get("app_names") or "[]")
            except json.JSONDecodeError:
                names = [r.get("app_names", "")]
            body = (r.get("full_text") or "").strip()
            title = (r.get("title") or "").strip()
            text = f"{title}. {body}" if title and title.casefold() not in body.casefold() else (body or title)
            month = (r.get("feedback_date") or "")[:7]
            for app in set(names) & set(mx.REVIEWED_MUSIC_APPS):
                month_counts[(app, month)] += 1
                hits = mx.mentioned_apps(text, app)
                if not hits:
                    continue
                n_cand += 1
                out.write(json.dumps({
                    "feedback_id": r["feedback_id"], "app_name": app, "text": text,
                    "feedback_date": r.get("feedback_date", ""), "stars": r.get("stars", ""),
                    "data_source": r.get("data_source", ""), "language_status": r.get("language_status", ""),
                    "keyword_hits": hits,
                }, ensure_ascii=False) + "\n")
            if n_rows % 500_000 == 0:
                print(f"  scanned {n_rows:,} rows, {n_cand:,} candidates", flush=True)
    os.replace(tmp, CAND)
    with (OUT / "app_month_counts.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["app_name", "month", "reviews"])
        for (app, month), c in sorted(month_counts.items()):
            w.writerow([app, month, c])
    print(f"Scanned {n_rows:,} rows -> {n_cand:,} candidates in {CAND}")


def load_candidates():
    if not CAND.exists():
        sys.exit("No candidates yet. Run: python3 run_music_edges.py candidates")
    with CAND.open() as f:
        return [json.loads(l) for l in f]


def key(c):
    return f'{c["feedback_id"]}|{c["app_name"]}'


# Curly quotes -> straight. Models often write "I'm" where the review has "I’m"
# (iOS smart punctuation), which made mx.validate reject correct evidence.
_QUOTES = str.maketrans({"‘": "'", "’": "'", "‚": "'", "′": "'",
                         "“": '"', "”": '"', "„": '"', "″": '"'})


def validate(result, app, text):
    """mx.validate with quote-insensitive evidence matching."""
    for m in result.get("mentions", []):
        m["evidence"] = (m.get("evidence") or "").translate(_QUOTES)
    return mx.validate(result, app, text.translate(_QUOTES))


# ---------------------------------------------------------------------------
# LLM call
# ---------------------------------------------------------------------------
class LLM:
    def __init__(self, model, base_url, reasoning_effort, mock=False):
        self.model, self.mock, self.reasoning_effort = model, mock, reasoning_effort
        self.url = base_url.rstrip("/") + "/chat/completions"
        self.key = os.environ.get("OPENAI_API_KEY", "")
        if not mock and not self.key:
            sys.exit("Set OPENAI_API_KEY in the environment or in .env at the project root.")

    def label(self, c):
        if self.mock:
            return _mock_label(c), {"prompt_tokens": 0, "completion_tokens": 0, "cached_tokens": 0}
        body = {
            "model": self.model,
            "messages": mx.build_messages(c["app_name"], c["stars"], c["text"]),
            "response_format": {"type": "json_schema",
                                "json_schema": {"name": "music_edges", "strict": True, "schema": mx.EDGE_SCHEMA}},
        }
        if self.reasoning_effort:
            body["reasoning_effort"] = self.reasoning_effort
        data = self._post(body)
        msg = data["choices"][0]["message"]
        if msg.get("refusal"):
            raise RuntimeError(f"refusal: {msg['refusal'][:200]}")
        u = data.get("usage", {})
        usage = {"prompt_tokens": u.get("prompt_tokens", 0),
                 "completion_tokens": u.get("completion_tokens", 0),
                 "cached_tokens": (u.get("prompt_tokens_details") or {}).get("cached_tokens", 0)}
        return json.loads(msg["content"]), usage

    def _post(self, body, tries=6):
        payload = json.dumps(body).encode()
        for attempt in range(tries):
            req = urllib.request.Request(self.url, data=payload, headers={
                "Authorization": f"Bearer {self.key}", "Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=120) as resp:
                    return json.loads(resp.read())
            except urllib.error.HTTPError as e:
                detail = e.read().decode(errors="replace")[:500]
                if e.code in (429, 500, 502, 503, 504) and attempt < tries - 1:
                    time.sleep(min(60, 2 ** attempt + random.random()))
                    continue
                raise RuntimeError(f"HTTP {e.code}: {detail}") from None
            except (urllib.error.URLError, TimeoutError) as e:
                if attempt < tries - 1:
                    time.sleep(min(60, 2 ** attempt + random.random()))
                    continue
                raise RuntimeError(f"network: {e}") from None


def _mock_label(c):
    """Fake labels for testing the pipeline offline."""
    rels = ["left_for", "came_from", "prefers_reviewed", "not_a_switch_reference"]
    return {"mentions": [{
        "mentioned_app": app, "mentioned_app_raw": app, "relation": rels[hash(c["feedback_id"]) % 4],
        "reasons": ["other"], "reason_detail": "mock", "evidence": "", "confidence": "high"}
        for app in c["keyword_hits"]]}


# ---------------------------------------------------------------------------
# Labeling (resumable)
# ---------------------------------------------------------------------------
def results_path(tag, model):
    return RESULTS / f"{tag}_{re.sub(r'[^A-Za-z0-9._-]+', '_', model)}.jsonl"


def done_keys(path):
    done = set()
    if path.exists():
        with path.open() as f:
            for line in f:
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    continue  # partial last line from a crash
                if r.get("ok"):
                    done.add(r["key"])
    return done


def run_labels(cands, llm, path, workers):
    RESULTS.mkdir(parents=True, exist_ok=True)
    done = done_keys(path)
    todo = [c for c in cands if key(c) not in done]
    print(f"{llm.model}: {len(done):,} already done, {len(todo):,} to go -> {path.name}", flush=True)
    if not todo:
        return
    lock = threading.Lock()
    stats = Counter()
    t0 = time.time()

    def work(c):
        try:
            result, usage = llm.label(c)
            kept, rejected = validate(result, c["app_name"], c["text"])
            return {"key": key(c), "ok": True, "model": llm.model, "mentions": kept,
                    "rejected": rejected, "usage": usage}
        except Exception as e:  # keep going; failures are retried on the next run
            return {"key": key(c), "ok": False, "model": llm.model, "error": str(e)[:500]}

    with path.open("a") as out, ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(work, c) for c in todo]
        for i, fut in enumerate(as_completed(futures), 1):
            rec = fut.result()
            with lock:
                out.write(json.dumps(rec, ensure_ascii=False) + "\n")
                out.flush()
                stats["ok" if rec["ok"] else "error"] += 1
                if rec["ok"]:
                    for k, v in rec["usage"].items():
                        stats[k] += v
                    stats["rejected"] += len(rec["rejected"])
                elif stats["error"] <= 3:
                    print(f"  error: {rec['error']}", flush=True)
            if i % 250 == 0 or i == len(todo):
                rate = i / max(time.time() - t0, 1e-9)
                print(f"  {i:,}/{len(todo):,}  ok={stats['ok']:,} err={stats['error']:,}  "
                      f"{rate:.1f}/s  ~${cost(llm.model, stats):.2f} so far", flush=True)
    if stats["error"]:
        print(f"  {stats['error']} failed; rerun the same command to retry them.")


def cost(model, s):
    p = PRICES.get(model)
    if not p:
        return 0.0
    uncached = s["prompt_tokens"] - s["cached_tokens"]
    return (uncached * p[0] + s["cached_tokens"] * p[1] + s["completion_tokens"] * p[2]) / 1e6


def load_results(path):
    """Latest successful record per key."""
    best = {}
    if path.exists():
        with path.open() as f:
            for line in f:
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if r.get("ok"):
                    best[r["key"]] = r
    return best


# ---------------------------------------------------------------------------
# Pilot comparison
# ---------------------------------------------------------------------------
def pilot(args):
    cands = load_candidates()
    rng = random.Random(args.seed)
    sample = rng.sample(cands, min(args.n, len(cands)))
    models = [m.strip() for m in args.models.split(",") if m.strip()]
    for m in models:
        run_labels(sample, LLM(m, args.base_url, args.reasoning_effort, args.mock),
                   results_path("pilot", m), args.workers)

    by_key = {key(c): c for c in sample}
    res = {m: load_results(results_path("pilot", m)) for m in models}
    print("\n=== Pilot summary ===")
    for m in models:
        rs = [r for k, r in res[m].items() if k in by_key]
        s = Counter()
        rel = Counter()
        for r in rs:
            for k2, v in r["usage"].items():
                s[k2] += v
            s["mentions"] += len(r["mentions"])
            s["rejected"] += len(r["rejected"])
            rel.update(x["relation"] for x in r["mentions"])
        per = cost(m, s) / max(len(rs), 1)
        print(f"\n{m}: {len(rs)} reviews, {s['mentions']} mentions, "
              f"{s['rejected']} rejected ({s['rejected'] / max(s['mentions'] + s['rejected'], 1):.1%})")
        print(f"  cost ~${cost(m, s):.3f}  ->  full run of {len(cands):,} ~ ${per * len(cands):.2f}")
        print("  relations:", ", ".join(f"{k} {v}" for k, v in rel.most_common()))

    if len(models) >= 2:
        a, b = models[0], models[1]
        rows, agree, total = [], 0, 0
        for k, c in by_key.items():
            if k not in res[a] or k not in res[b]:
                continue
            la = {x["mentioned_app"]: x for x in res[a][k]["mentions"]}
            lb = {x["mentioned_app"]: x for x in res[b][k]["mentions"]}
            for app in sorted(set(la) | set(lb)):
                ra = la.get(app, {}).get("relation", "(none)")
                rb = lb.get(app, {}).get("relation", "(none)")
                total += 1
                if ra == rb:
                    agree += 1
                else:
                    rows.append([c["app_name"], app, c["stars"], ra, rb, c["text"]])
        print(f"\nRelation agreement {a} vs {b}: {agree}/{total} = {agree / max(total, 1):.1%}")
        dis = OUT / "pilot_disagreements.csv"
        with dis.open("w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["reviewed_app", "mentioned_app", "stars", a, b, "text"])
            w.writerows(rows)
        print(f"Read the {len(rows)} disagreements in {dis}")


# ---------------------------------------------------------------------------
# Edges
# ---------------------------------------------------------------------------
def edges(args):
    cands = {key(c): c for c in load_candidates()}
    res = load_results(results_path("full", args.model))
    if not res:
        sys.exit(f"No full-run results for {args.model}. Run: python3 run_music_edges.py full --model {args.model}")
    missing = len(cands) - len(set(cands) & set(res))
    if missing:
        print(f"Warning: {missing:,} candidates not labeled yet; building edges from the rest.")

    mention_rows, edge_rows = [], []
    for k, r in res.items():
        c = cands.get(k)
        if not c:
            continue
        for m in r["mentions"]:
            mention_rows.append({
                "feedback_id": c["feedback_id"], "reviewed_app": c["app_name"], "mentioned_app": m["mentioned_app"],
                "relation": m["relation"], "confidence": m["confidence"], "reasons": ";".join(m["reasons"]),
                "reason_detail": m["reason_detail"], "evidence": m["evidence"], "month": c["feedback_date"][:7],
                "stars": c["stars"], "data_source": c["data_source"],
            })
        for e in mx.to_edges(c, r["mentions"]):
            e["reasons"] = ";".join(e["reasons"])
            e["reviewed_app"] = c["app_name"]
            edge_rows.append(e)

    write_csv(OUT / "music_mentions.csv", mention_rows)
    write_csv(OUT / "music_edges.csv", edge_rows)

    # Monthly aggregate, with the source app's review volume for normalization.
    volume = {}
    with (OUT / "app_month_counts.csv").open() as f:
        for row in csv.DictReader(f):
            volume[(row["app_name"], row["month"])] = int(row["reviews"])
    agg = defaultdict(lambda: [0, 0.0])
    for e in edge_rows:
        a = agg[(e["month"], e["source"], e["target"], e["kind"], e["reviewed_app"])]
        a[0] += 1
        a[1] += e["weight"]
    monthly = []
    for (month, src, dst, kind, reviewed), (n, w) in sorted(agg.items()):
        # Normalize by the volume of the app whose reviews produced the edge.
        vol = volume.get((reviewed, month), 0)
        monthly.append({"month": month, "source": src, "target": dst, "kind": kind,
                        "observed_in_reviews_of": reviewed, "count": n,
                        "weight": round(w, 3), "reviewed_app_volume": vol,
                        "weight_per_10k_reviews": round(w / vol * 1e4, 3) if vol else ""})
    write_csv(OUT / "music_edges_monthly.csv", monthly)

    rel = Counter(r["relation"] for r in mention_rows)
    print(f"{len(mention_rows):,} mentions, {len(edge_rows):,} edges")
    print("relations:", ", ".join(f"{k} {v}" for k, v in rel.most_common()))
    top = Counter()
    for e in edge_rows:
        if e["kind"] in ("switch", "return"):
            top[(e["source"], e["target"])] += 1
    print("top actual switches:")
    for (s, t), n in top.most_common(12):
        print(f"  {s:>14} -> {t:<14} {n:,}")
    print(f"Wrote music_mentions.csv, music_edges.csv, music_edges_monthly.csv to {OUT}")


def write_csv(path, rows):
    with path.open("w", newline="") as f:
        if not rows:
            return
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


# ---------------------------------------------------------------------------
def main():
    load_env()
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    def llm_args(sp):
        sp.add_argument("--base-url", default=os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"))
        sp.add_argument("--reasoning-effort", default=None,
                        help="e.g. low/minimal for reasoning models; leave unset for models that reject it")
        sp.add_argument("--workers", type=int, default=16, help="concurrent requests")
        sp.add_argument("--mock", action="store_true", help="fake labels, no API calls")

    sc = sub.add_parser("candidates")
    sc.add_argument("--csv", default=str(ROOT / "data" / "reviews-clean.csv"))

    sp = sub.add_parser("pilot")
    sp.add_argument("--n", type=int, default=200)
    sp.add_argument("--models", default="gpt-6-luna,gpt-5.4-mini")
    sp.add_argument("--seed", type=int, default=7)
    llm_args(sp)

    sf = sub.add_parser("full")
    sf.add_argument("--model", required=True)
    llm_args(sf)

    se = sub.add_parser("edges")
    se.add_argument("--model", required=True)

    args = p.parse_args()
    if args.cmd == "candidates":
        build_candidates(args.csv)
    elif args.cmd == "pilot":
        pilot(args)
    elif args.cmd == "full":
        run_labels(load_candidates(), LLM(args.model, args.base_url, args.reasoning_effort, args.mock),
                   results_path("full", args.model), args.workers)
    elif args.cmd == "edges":
        edges(args)


if __name__ == "__main__":
    main()
