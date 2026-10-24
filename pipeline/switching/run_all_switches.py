#!/usr/bin/env python3
"""Switching graph for all apps: same approach as run_music_edges.py, every category.

Steps (outputs go to <workspace>/out/all/):
  candidates  reviews naming a competitor in the same category -> candidates.jsonl, app_month_counts.csv
  pilot       label a sample spread across categories and report quality
  full        label every candidate (resumable, budget guard)
  edges       mentions.csv, edges.csv, edges_monthly.csv (music labels reused from out/results/)

Examples (from the workspace folder):
  python3 unwrapathon/pipeline/switching/run_all_switches.py candidates
  python3 unwrapathon/pipeline/switching/run_all_switches.py pilot --n 300
  python3 unwrapathon/pipeline/switching/run_all_switches.py full --max-cost 40
  python3 unwrapathon/pipeline/switching/run_all_switches.py edges

Music is not relabeled: its labels come from run_music_edges.py's full run, with
music reasons mapped onto the shared reason list. Standard library only.
"""
import argparse
import csv
import json
import math
import os
import random
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
import run_music_edges as rme  # noqa: E402  (LLM client, resumable labeling, quote-fixed validation, cost)
import switch_extraction as sx  # noqa: E402

ROOT = rme.ROOT
DATA_CSV = ROOT / "data" / "reviews-clean.csv"
OUT = ROOT / "out" / "all"
CAND = OUT / "candidates.jsonl"
RESULTS = OUT / "results"
MODEL = "gpt-6-luna"
MAX_WORKERS = 128  # the API key is shared with another pipeline; drop --workers on rate-limit errors

MUSIC_CAND = rme.CAND
MUSIC_RESULTS = rme.results_path("full", MODEL)


# ---------------------------------------------------------------------------
# Step 1: candidates (+ review volume for every app)
# ---------------------------------------------------------------------------
def build_candidates(csv_path):
    OUT.mkdir(parents=True, exist_ok=True)
    month_counts = Counter()
    n_rows = n_cand = 0
    unknown = Counter()
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
            for raw_name in names:
                app = sx.canonical_app(raw_name)
                cid = sx.APP_CATEGORY.get(app)
                if not cid:
                    unknown[raw_name] += 1
                    continue
                month_counts[(app, month)] += 1
                if sx.CATEGORIES[cid].get("reuse"):
                    continue  # music: labels reused from the music pipeline
                hits = sx.mentioned_apps(text, app, cid)
                if not hits:
                    continue
                n_cand += 1
                out.write(json.dumps({
                    "feedback_id": r["feedback_id"], "app_name": app, "category": cid, "text": text,
                    "feedback_date": r.get("feedback_date", ""), "stars": r.get("stars", ""),
                    "data_source": r.get("data_source", ""), "language_status": r.get("language_status", ""),
                    "keyword_hits": hits,
                }, ensure_ascii=False) + "\n")
            if n_rows % 1_000_000 == 0:
                print(f"  scanned {n_rows:,} rows, {n_cand:,} candidates", flush=True)
    os.replace(tmp, CAND)
    with (OUT / "app_month_counts.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["app_name", "category", "month", "reviews"])
        for (app, month), c in sorted(month_counts.items()):
            w.writerow([app, sx.APP_CATEGORY[app], month, c])
    print(f"Scanned {n_rows:,} rows -> {n_cand:,} candidates in {CAND}")
    if unknown:
        print("Apps not in categories.json (skipped):", dict(unknown))
    report_candidates()


def load_candidates():
    if not CAND.exists():
        sys.exit("No candidates yet. Run: run_all_switches.py candidates")
    with CAND.open() as f:
        return [json.loads(l) for l in f]


def load_music_candidates():
    with MUSIC_CAND.open() as f:
        return [{**json.loads(l), "category": "music"} for l in f]


def report_candidates():
    cands = load_candidates() + load_music_candidates()
    vol = Counter()
    with (OUT / "app_month_counts.csv").open() as f:
        for r in csv.DictReader(f):
            vol[r["category"]] += int(r["reviews"])
    by_cat = Counter(c["category"] for c in cands)
    print(f"\n{'category':<18} {'candidates':>10} {'reviews':>10} {'rate':>6}   top pairs (reviewed app -> named app)")
    for cid, n in by_cat.most_common():
        pairs = Counter((c["app_name"], h) for c in cands if c["category"] == cid for h in c["keyword_hits"])
        top = ", ".join(f"{a}->{b} {k:,}" for (a, b), k in pairs.most_common(4))
        note = " (reused)" if sx.CATEGORIES[cid].get("reuse") else ""
        print(f"{cid:<18} {n:>10,} {vol[cid]:>10,} {n / max(vol[cid], 1):>6.1%}   {top}{note}")
    for cid in sx.CATEGORIES:
        if cid not in by_cat:
            print(f"{cid:<18} {0:>10} {vol[cid]:>10,}")
    print(f"{'TOTAL':<18} {len(cands):>10,}  (to label: {sum(n for c, n in by_cat.items() if c != 'music'):,})")
    pairs = Counter((c["app_name"], h) for c in cands for h in c["keyword_hits"])
    print("\nTop 25 pairs overall:")
    for (a, b), k in pairs.most_common(25):
        print(f"  {a:>24} -> {b:<22} {k:,}")


# ---------------------------------------------------------------------------
# LLM call with the per-category prompt and schema
# ---------------------------------------------------------------------------
class CategoryLLM(rme.LLM):
    rate_limited = 0  # 429 responses seen (each one is retried)
    _lock = threading.Lock()

    def _post(self, body, tries=6):
        """Same retry policy as rme.LLM._post, but every 429 is logged, so throttling is visible early."""
        payload = json.dumps(body).encode()
        for attempt in range(tries):
            req = urllib.request.Request(self.url, data=payload, headers={
                "Authorization": f"Bearer {self.key}", "Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=120) as resp:
                    return json.loads(resp.read())
            except urllib.error.HTTPError as e:
                detail = e.read().decode(errors="replace")[:500]
                if e.code == 429:
                    with CategoryLLM._lock:
                        CategoryLLM.rate_limited += 1
                        n = CategoryLLM.rate_limited
                    if n <= 5 or n % 50 == 0:
                        print(f"  RATE LIMIT 429 #{n} (retrying): {detail[:160]}", flush=True)
                if e.code in (429, 500, 502, 503, 504, 520) and attempt < tries - 1:
                    time.sleep(min(60, 2 ** attempt + random.random()))
                    continue
                raise RuntimeError(f"HTTP {e.code}: {detail}") from None
            except (urllib.error.URLError, TimeoutError) as e:
                if attempt < tries - 1:
                    time.sleep(min(60, 2 ** attempt + random.random()))
                    continue
                raise RuntimeError(f"network: {e}") from None

    def label(self, c):
        if self.mock:
            return ({"mentions": [{"mentioned_app": a, "mentioned_app_raw": a, "relation": "prefers_mentioned",
                                   "reasons": ["other"], "reason_detail": "mock", "evidence": "", "confidence": "high"}
                                  for a in c["keyword_hits"]]},
                    {"prompt_tokens": 0, "completion_tokens": 0, "cached_tokens": 0})
        body = {
            "model": self.model,
            "messages": sx.build_messages(c["category"], c["app_name"], c["stars"], c["text"]),
            "response_format": {"type": "json_schema",
                                "json_schema": {"name": "switch_edges", "strict": True,
                                                "schema": sx.edge_schema(c["category"])}},
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

    def label_batch(self, cid, cands):
        """Label several same-category reviews in one request. Returns ({id: mentions}, usage)."""
        items = [(rme.key(c), c["app_name"], c["stars"], c["text"]) for c in cands]
        if self.mock:  # drops the last review on purpose, to exercise the missing-id path
            zero = {"prompt_tokens": 0, "completion_tokens": 0, "cached_tokens": 0}
            return {rme.key(c): self.label(c)[0] for c in cands[:-1]}, zero
        body = {
            "model": self.model,
            "messages": sx.build_batch_messages(cid, items),
            "response_format": {"type": "json_schema",
                                "json_schema": {"name": "switch_edges_batch", "strict": True,
                                                "schema": sx.batch_schema(cid)}},
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
        out = {}
        for entry in json.loads(msg["content"]).get("reviews", []):
            rid = str(entry.get("id", "")).strip()
            if rid and rid not in out:
                out[rid] = {"mentions": entry.get("mentions", [])}
        return out, usage


def run_batches(cands, llm, path, workers, batch_size):
    """Batched, resumable labeling. Validation is per review, exactly as in single mode.
    Reviews missing from a batch's output are relabeled one at a time."""
    RESULTS.mkdir(parents=True, exist_ok=True)
    done = rme.done_keys(path)
    todo = [c for c in cands if rme.key(c) not in done]
    by_cat = defaultdict(list)
    for c in todo:
        by_cat[c["category"]].append(c)
    batches = [(cid, v[i:i + batch_size]) for cid, v in by_cat.items() for i in range(0, len(v), batch_size)]
    print(f"{llm.model} batch={batch_size}: {len(done):,} already done, {len(todo):,} to go "
          f"in {len(batches):,} requests -> {path.name}", flush=True)
    if not batches:
        return
    lock = threading.Lock()
    stats = Counter()
    missing = []
    t0 = time.time()

    def work(cid, batch):
        try:
            labels, usage = llm.label_batch(cid, batch)
        except Exception as e:  # whole request failed: mark each review failed; rerun retries them
            return [{"key": rme.key(c), "ok": False, "model": llm.model, "error": str(e)[:500]} for c in batch], []
        got = [c for c in batch if rme.key(c) in labels]
        share = {k: v / max(len(got), 1) for k, v in usage.items()}
        recs = []
        for c in got:
            kept, rejected = rme.validate(labels[rme.key(c)], c["app_name"], c["text"])
            recs.append({"key": rme.key(c), "ok": True, "model": llm.model, "batch": len(batch),
                         "mentions": kept, "rejected": rejected, "usage": share})
        return recs, [c for c in batch if rme.key(c) not in labels]

    with path.open("a") as out, ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(work, cid, b) for cid, b in batches]
        for i, fut in enumerate(as_completed(futures), 1):
            recs, miss = fut.result()
            with lock:
                for rec in recs:
                    out.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    stats["ok" if rec["ok"] else "error"] += 1
                    if rec["ok"]:
                        for k, v in rec["usage"].items():
                            stats[k] += v
                    elif stats["error"] <= 3:
                        print(f"  error: {rec['error']}", flush=True)
                    if not rec["ok"] and "HTTP 429" in rec.get("error", ""):
                        stats["rate_limited"] += 1
                out.flush()
                missing += miss
            if i % 25 == 0 or i == len(batches):
                rate = (stats["ok"] + stats["error"]) / max(time.time() - t0, 1e-9)
                print(f"  {i:,}/{len(batches):,} requests  ok={stats['ok']:,} err={stats['error']:,} "
                      f"missing={len(missing):,}  {rate:.1f} reviews/s  ~${rme.cost(llm.model, stats):.2f} so far",
                      flush=True)
    if stats["rate_limited"]:
        print(f"  {stats['rate_limited']} reviews failed on rate limits: rerun with --workers 12.")
    if missing:
        print(f"  {len(missing)} reviews missing from batch output: relabeling them one at a time.")
        rme.run_labels(missing, llm, path, min(workers, 8))
    if stats["error"]:
        print(f"  {stats['error']} failed; rerun the same command to retry them.")


def results_path(tag):
    return RESULTS / f"{tag}_{MODEL}.jsonl"


def make_llm(args):
    return CategoryLLM(MODEL, args.base_url, args.reasoning_effort, args.mock)


def usage_stats(records):
    s = Counter()
    for r in records:
        for k, v in r["usage"].items():
            s[k] += v
        s["mentions"] += len(r["mentions"])
        s["rejected"] += len(r["rejected"])
    return s


# ---------------------------------------------------------------------------
# Pilot
# ---------------------------------------------------------------------------
def pilot_sample(cands, n, seed):
    """Spread n reviews across categories: sqrt-proportional, at least 6 each (when available)."""
    by_cat = defaultdict(list)
    for c in cands:
        by_cat[c["category"]].append(c)
    weights = {cid: math.sqrt(len(v)) for cid, v in by_cat.items()}
    total_w = sum(weights.values())
    alloc = {cid: min(len(by_cat[cid]), max(6, round(n * w / total_w))) for cid, w in weights.items()}
    while sum(alloc.values()) > n:  # trim the largest allocations
        big = max(alloc, key=lambda k: alloc[k])
        alloc[big] -= 1
    rng = random.Random(seed)
    sample = []
    for cid in sorted(by_cat):
        sample += rng.sample(by_cat[cid], alloc[cid])
    return sample


def pilot_tag(batch):
    return f"pilot_b{batch}" if batch else "pilot"


def label(cands, args, path):
    workers = min(args.workers, MAX_WORKERS)
    if args.batch:
        run_batches(cands, make_llm(args), path, workers, args.batch)
    else:
        rme.run_labels(cands, make_llm(args), path, workers)


def pilot(args):
    cands = load_candidates()
    sample = pilot_sample(cands, args.n, args.seed)
    path = results_path(pilot_tag(args.batch))
    label(sample, args, path)
    res = rme.load_results(path)
    by_key = {rme.key(c): c for c in sample}
    recs = [res[k] for k in by_key if k in res]
    s = usage_stats(recs)
    per_review = rme.cost(MODEL, s) / max(len(recs), 1)
    print(f"\n=== Pilot: {len(recs)}/{len(sample)} reviews labeled ===")
    print(f"mentions kept {s['mentions']}, rejected {s['rejected']} "
          f"({s['rejected'] / max(s['mentions'] + s['rejected'], 1):.1%}); cost ${rme.cost(MODEL, s):.3f}; "
          f"cached {s['cached_tokens'] / max(s['prompt_tokens'], 1):.0%} of prompt tokens")
    print(f"projected full run: {len(cands):,} reviews x ${per_review:.5f} = ${per_review * len(cands):.2f}")

    print(f"\n{'category':<18} {'n':>4} {'kept':>5} {'rej%':>5}  relation mix")
    for cid in sorted({c['category'] for c in sample}):
        rs = [res[k] for k, c in by_key.items() if c["category"] == cid and k in res]
        cs = usage_stats(rs)
        rel = Counter(m["relation"] for r in rs for m in r["mentions"])
        rej = cs["rejected"] / max(cs["mentions"] + cs["rejected"], 1)
        mix = ", ".join(f"{k} {v}" for k, v in rel.most_common())
        print(f"{cid:<18} {len(rs):>4} {cs['mentions']:>5} {rej:>5.1%}  {mix}")
    rej_all = [(by_key[r["key"]], x) for r in recs for x in r["rejected"]]
    if rej_all:
        print("\nRejected evidence:")
        for c, x in rej_all:
            print(f"  [{c['app_name']}] {x['mentioned_app']} {x['relation']} {x['_problem']}: \"{x['evidence'][:90]}\"")


def compare(args):
    """Relation agreement between two pilot runs on the same sample (per review x named app)."""
    sample = pilot_sample(load_candidates(), args.n, args.seed)
    by_key = {rme.key(c): c for c in sample}
    a_tag, b_tag = pilot_tag(args.a), pilot_tag(args.b)
    ra, rb = rme.load_results(results_path(a_tag)), rme.load_results(results_path(b_tag))
    keys = [k for k in by_key if k in ra and k in rb]
    agree = total = 0
    per_cat = defaultdict(lambda: [0, 0])
    direction = {"left_for": "out", "leaving_for": "out", "prefers_mentioned": "out",
                 "came_from": "in", "returned_from": "in", "prefers_reviewed": "in"}
    dir_agree = dir_total = 0
    rows = []
    for k in keys:
        la = {m["mentioned_app"]: m["relation"] for m in ra[k]["mentions"]}
        lb = {m["mentioned_app"]: m["relation"] for m in rb[k]["mentions"]}
        for app in sorted(set(la) | set(lb)):
            x, y = la.get(app, "(none)"), lb.get(app, "(none)")
            total += 1
            per_cat[by_key[k]["category"]][1] += 1
            if x == y:
                agree += 1
                per_cat[by_key[k]["category"]][0] += 1
            else:
                rows.append([by_key[k]["category"], by_key[k]["app_name"], app, x, y, by_key[k]["text"][:400]])
            if x in direction or y in direction:
                dir_total += 1
                dir_agree += direction.get(x) == direction.get(y)

    def rej(res):
        s = usage_stats(res[k] for k in keys)
        return s["rejected"] / max(s["mentions"] + s["rejected"], 1), s

    rej_a, sa = rej(ra)
    rej_b, sb = rej(rb)
    print(f"{len(keys)} reviews labeled by both ({a_tag} vs {b_tag})")
    print(f"relation agreement: {agree}/{total} = {agree / max(total, 1):.1%}")
    print(f"edge-direction agreement (where either has a directional relation): "
          f"{dir_agree}/{dir_total} = {dir_agree / max(dir_total, 1):.1%}")
    print(f"rejected evidence: {a_tag} {rej_a:.1%} ({sa['rejected']}) vs {b_tag} {rej_b:.1%} ({sb['rejected']})")
    print(f"cost per review: {a_tag} ${rme.cost(MODEL, sa) / len(keys):.5f} vs {b_tag} ${rme.cost(MODEL, sb) / len(keys):.5f}")
    print("per category agreement:", ", ".join(f"{c} {a}/{t}" for c, (a, t) in sorted(per_cat.items())))
    out = OUT / f"compare_{a_tag}_vs_{b_tag}.csv"
    with out.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["category", "reviewed_app", "mentioned_app", a_tag, b_tag, "text"])
        w.writerows(rows)
    print(f"{len(rows)} disagreements in {out}")


# ---------------------------------------------------------------------------
# Full run with a budget guard
# ---------------------------------------------------------------------------
def spent(path):
    return rme.cost(MODEL, usage_stats(rme.load_results(path).values()))


def full(args):
    path = results_path("full")
    done = rme.done_keys(path)
    cands = [c for c in load_candidates() if rme.key(c) not in done]
    if args.priority:  # unfinished reviews of these categories first, in this order; the rest keep file order
        order = {cid: i for i, cid in enumerate(args.priority.split(","))}
        cands.sort(key=lambda c: order.get(c["category"], len(order)))
        print("remaining by category:", dict(Counter(c["category"] for c in cands)), flush=True)
    chunk = args.chunk
    for i in range(0, len(cands), chunk):
        so_far = spent(path)
        if so_far >= args.max_cost:
            print(f"Stopping: spend ${so_far:.2f} reached the ${args.max_cost:.2f} limit. Rerun with a higher --max-cost to continue.")
            return
        print(f"[chunk {i // chunk + 1}/{math.ceil(len(cands) / chunk)}] spend so far ${so_far:.2f}", flush=True)
        label(cands[i:i + chunk], args, path)
    res = rme.load_results(path)
    print(f"Done: {len(res):,}/{len(load_candidates()):,} labeled, total ${spent(path):.2f}")


# ---------------------------------------------------------------------------
# Edges (music reused + all other categories)
# ---------------------------------------------------------------------------
def labeled_reviews():
    """Yield (candidate, mentions) for music (reasons mapped) and every other category."""
    music_res = rme.load_results(MUSIC_RESULTS)
    for c in load_music_candidates():
        r = music_res.get(rme.key(c))
        if r:
            yield c, [{**m, "reasons": sx.map_music_reasons(m["reasons"])} for m in r["mentions"]]
    res = rme.load_results(results_path("full"))
    for c in load_candidates():
        r = res.get(rme.key(c))
        if r:
            yield c, r["mentions"]


def edges(args):
    n_all = len(load_candidates())
    n_done = len(rme.load_results(results_path("full")))
    if n_done < n_all:
        print(f"Warning: {n_all - n_done:,} of {n_all:,} candidates not labeled yet; building edges from the rest.")

    mention_rows, edge_rows = [], []
    for c, mentions in labeled_reviews():
        for m in mentions:
            mention_rows.append({
                "feedback_id": c["feedback_id"], "category": c["category"], "reviewed_app": c["app_name"],
                "mentioned_app": m["mentioned_app"], "mentioned_app_raw": m.get("mentioned_app_raw", ""),
                "relation": m["relation"], "confidence": m["confidence"], "reasons": ";".join(m["reasons"]),
                "reason_detail": m["reason_detail"], "evidence": m["evidence"], "month": c["feedback_date"][:7],
                "stars": c["stars"], "data_source": c["data_source"],
            })
        for e in mx.to_edges(c, mentions):
            e["reasons"] = ";".join(e["reasons"])
            e["category"] = c["category"]
            e["reviewed_app"] = c["app_name"]
            edge_rows.append(e)

    rme.write_csv(OUT / "mentions.csv", mention_rows)
    rme.write_csv(OUT / "edges.csv", edge_rows)

    volume = {}
    with (OUT / "app_month_counts.csv").open() as f:
        for row in csv.DictReader(f):
            volume[(row["app_name"], row["month"])] = int(row["reviews"])
    agg = defaultdict(lambda: [0, 0.0])
    for e in edge_rows:
        a = agg[(e["category"], e["month"], e["source"], e["target"], e["kind"], e["reviewed_app"])]
        a[0] += 1
        a[1] += e["weight"]
    monthly = []
    for (cid, month, src, dst, kind, reviewed), (n, w) in sorted(agg.items()):
        vol = volume.get((reviewed, month), 0)
        monthly.append({"category": cid, "month": month, "source": src, "target": dst, "kind": kind,
                        "observed_in_reviews_of": reviewed, "count": n, "weight": round(w, 3),
                        "reviewed_app_volume": vol,
                        "weight_per_10k_reviews": round(w / vol * 1e4, 3) if vol else ""})
    rme.write_csv(OUT / "edges_monthly.csv", monthly)

    print(f"{len(mention_rows):,} mentions, {len(edge_rows):,} edges")
    print("relations:", ", ".join(f"{k} {v}" for k, v in Counter(r["relation"] for r in mention_rows).most_common()))
    print("\nedges per category (all kinds / switch+return):")
    kinds = Counter(e["category"] for e in edge_rows)
    sw = [e for e in edge_rows if e["kind"] in ("switch", "return")]
    swc = Counter(e["category"] for e in sw)
    for cid, n in kinds.most_common():
        print(f"  {cid:<18} {n:>6,} / {swc[cid]:>5,}")

    def reasons_of(rows):
        rc = Counter(x for e in rows for x in e["reasons"].split(";") if x)
        return ", ".join(f"{k} {v}" for k, v in rc.most_common(3))

    top = Counter((e["category"], e["source"], e["target"]) for e in sw)
    print("\nTop 20 switch flows (switch + return):")
    for (cid, s, t), n in top.most_common(20):
        rows = [e for e in sw if (e["category"], e["source"], e["target"]) == (cid, s, t)]
        print(f"  {s:>24} -> {t:<22} {n:>5,}  [{cid}]  {reasons_of(rows)}")
    print("\nTop 3 per category:")
    for cid in sx.CATEGORIES:
        rows = [(k, n) for k, n in top.most_common() if k[0] == cid][:3]
        flows = "; ".join(f"{s} -> {t} {n}" for (_, s, t), n in rows) or "(none)"
        print(f"  {cid:<18} {flows}")
    print(f"\nWrote mentions.csv, edges.csv, edges_monthly.csv to {OUT}")


# ---------------------------------------------------------------------------
def main():
    rme.load_env()
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    def llm_args(sp):
        sp.add_argument("--base-url", default=os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"))
        sp.add_argument("--reasoning-effort", default=None)
        sp.add_argument("--workers", type=int, default=24, help=f"concurrent requests (capped at {MAX_WORKERS})")
        sp.add_argument("--batch", type=int, default=20, help="reviews per request; 0 = one review per request")
        sp.add_argument("--mock", action="store_true", help="fake labels, no API calls")

    sc = sub.add_parser("candidates")
    sc.add_argument("--csv", default=str(DATA_CSV))
    sub.add_parser("report")

    sp = sub.add_parser("pilot")
    sp.add_argument("--n", type=int, default=300)
    sp.add_argument("--seed", type=int, default=11)
    llm_args(sp)

    sf = sub.add_parser("full")
    sf.add_argument("--max-cost", type=float, default=40.0, help="stop before starting a chunk once spend reaches this")
    sf.add_argument("--chunk", type=int, default=4000)
    sf.add_argument("--priority", default="", help="comma-separated categories to label first, e.g. payments_banking,dating")
    llm_args(sf)

    sx_ = sub.add_parser("compare", help="agreement between two pilot runs, e.g. --a 0 --b 20")
    sx_.add_argument("--a", type=int, default=0, help="batch size of run A (0 = single)")
    sx_.add_argument("--b", type=int, default=20)
    sx_.add_argument("--n", type=int, default=300)
    sx_.add_argument("--seed", type=int, default=11)

    sub.add_parser("edges")

    args = p.parse_args()
    if args.cmd == "candidates":
        build_candidates(args.csv)
    elif args.cmd == "report":
        report_candidates()
    elif args.cmd == "pilot":
        pilot(args)
    elif args.cmd == "full":
        full(args)
    elif args.cmd == "compare":
        compare(args)
    elif args.cmd == "edges":
        edges(args)


if __name__ == "__main__":
    main()
