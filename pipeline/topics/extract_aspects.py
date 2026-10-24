#!/usr/bin/env python3
"""Step 5 of the Unwrapathon NLP pipeline: LLM aspect extraction for sampled reviews.

    python scripts/extract_aspects.py --limit 50     # stage 1: first 50 reviews
    python scripts/extract_aspects.py                # stage 2: everything else (resumable)
    python scripts/extract_aspects.py --build-only   # rebuild the parquet/manifest, no API calls

The API call (key from .env, base URL, retries, prices) is reused from run_music_edges.py.
Results are appended to raw_results.jsonl. On rerun, reviews already done with the
current prompt version are skipped, so a prompt change re-extracts everything.
Stops submitting new requests once --max-cost (all runs together) is reached.
"""
import argparse
import hashlib
import json
import re
import sys
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[3]  # workspace root (script lives in unwrapathon/pipeline/topics/)
# run_music_edges.py lives in the app repo; import it from there (not copied).
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "switching"))
sys.dont_write_bytecode = True  # don't leave __pycache__ in the app repo
import run_music_edges as rme  # noqa: E402  (load_env, LLM._post, cost, _QUOTES)
sys.dont_write_bytecode = False
MAX_CHARS = 1500

SENTIMENTS = ["negative", "positive", "mixed", "neutral"]
ASPECT_TYPES = ["bug", "performance", "pricing", "ads", "feature_request", "feature_change",
                "content_catalog", "ui_ux", "account_billing", "customer_support",
                "recommendations", "general_praise", "other"]

SYSTEM_PROMPT = """You extract aspects from one app-store review of the Spotify app.

An aspect is one specific thing the reviewer talks about: a problem, something they like, a request, or a change they noticed. Return every distinct aspect in the review and nothing that is not in it.

Fields for each aspect:
- description: a neutral phrase of 3-8 words naming the specific thing. Leave out sentiment and judgment words (terrible, great, good, best, bad, poor, love, hate, annoying, awful, amazing) and the app name. Name both the feature and what about it: "lyrics shown for most songs", not "lyrics feature". Use plain, standard wording so that different reviews about the same thing get the same description. Good: "shuffle repeats the same songs", "ads after every song", "premium required to pick songs", "app crashes on launch", "lyrics missing for songs", "request to bring back car mode", "Create button placed over Library". Bad: "terrible shuffle", "Spotify is amazing", "ads".
- sentiment: the reviewer's attitude toward this aspect: negative, positive, mixed or neutral (neutral for plain requests or observations).
- aspect_type, one of:
  bug: something broken or not working as intended (crashes, playback stops, errors, missing data)
  performance: slow, laggy, battery, storage or data use
  pricing: price, value for money, paywalls, free-tier limits that push toward premium (skip limits, can't choose songs)
  ads: number, length, timing or content of ads
  feature_request: asks for something that does not exist yet
  feature_change: reaction to a recent change, redesign or removal of an existing feature
  content_catalog: availability or variety of songs, artists, podcasts, audiobooks, genres or regional music
  ui_ux: layout, navigation, design, ease of use (not tied to a recent change)
  account_billing: login, account, payments, charges, cancellation, refunds, plans
  customer_support: contact with support or how support handled a problem
  recommendations: suggestions, algorithm, autoplay picks, smart shuffle choices, AI DJ picks
  general_praise: praise with no specific point
  other: anything else, including complaints with no specific point
- feature: the product feature involved, short and lowercase (e.g. shuffle, smart shuffle, playlists, liked songs, queue, lyrics, offline mode, downloads, search, home screen, library, create button, wrapped, ai dj, podcasts, audiobooks, recommendations, login, subscription, family plan, free tier, sound quality, widget, car mode). Use "ads" for any ads aspect, "subscription" for premium price or plans, "free tier" for limits on free users. Use "none" when no specific feature is involved.
- evidence: an exact, contiguous quote from the review that supports the aspect, from a few words up to one sentence. Copy it character for character, including typos and odd spelling. Do not paraphrase, fix, add punctuation, shorten with "...", or join separate parts.

Rules:
- One aspect per distinct issue. "Too many ads and it crashes" gives 2 aspects. Do not split one issue into near-duplicates.
- If the review is only generic praise or a generic complaint with no specific point ("love it", "best app", "worst app ever"), return exactly one aspect: aspect_type general_praise (praise) or other (complaint), feature "none", description "overall satisfaction with app" or "overall dissatisfaction with app".
- If a review has specific points plus overall praise or complaint, list the specific points; add the overall one only if it is a separate statement.
- Reviews not in English: write description in English, copy evidence in the original language.
- If the review has no usable content (gibberish, emoji only, unrelated text), return an empty list.
- Do not invent or infer anything that is not stated in the review."""

SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["aspects"],
    "properties": {"aspects": {"type": "array", "items": {
        "type": "object", "additionalProperties": False,
        "required": ["description", "sentiment", "aspect_type", "feature", "evidence"],
        "properties": {
            "description": {"type": "string"},
            "sentiment": {"type": "string", "enum": SENTIMENTS},
            "aspect_type": {"type": "string", "enum": ASPECT_TYPES},
            "feature": {"type": "string"},
            "evidence": {"type": "string"},
        }}}},
}
PROMPT_VERSION = hashlib.sha1((SYSTEM_PROMPT + json.dumps(SCHEMA, sort_keys=True)).encode()).hexdigest()[:10]


def norm(s):
    return re.sub(r"\s+", " ", (s or "").translate(rme._QUOTES)).strip().casefold()


def evidence_ok(evidence, text):
    """Exact match after normalizing case, whitespace, quotes and punctuation at the ends."""
    e = norm(evidence).strip(" .,!?;:'\"()-…")
    return bool(e) and e in norm(text)


def load_reviews(path):
    """One row per review_id. A review drawn as both random and centroid/outlier keeps
    the random row (and its weight); the other types go in also_sampled_as."""
    s = pd.read_parquet(path)
    s["_rank"] = (s["sample_type"] != "random").astype(int)
    s = s.sort_values(["_rank"], kind="stable")
    also = s.groupby("review_id")["sample_type"].apply(lambda x: ",".join(sorted(set(x.iloc[1:])))).rename("also_sampled_as")
    first = s.drop_duplicates("review_id").drop(columns="_rank").merge(also, on="review_id")
    order = {rid: i for i, rid in enumerate(pd.read_parquet(path, columns=["review_id"])["review_id"].drop_duplicates())}
    first = first.sort_values("review_id", key=lambda c: c.map(order)).reset_index(drop=True)
    first["llm_text"] = first["text"].str.slice(0, MAX_CHARS)
    return first


def read_jsonl(path):
    recs = []
    if path.exists():
        with path.open() as f:
            for line in f:
                try:
                    recs.append(json.loads(line))
                except json.JSONDecodeError:
                    continue  # partial last line after a crash
    return recs


def run_cost(model, recs):
    s = Counter()
    for r in recs:
        for k, v in (r.get("usage") or {}).items():
            s[k] += v
    return rme.cost(model, s), s


class Extractor(rme.LLM):
    def extract(self, text):
        body = {
            "model": self.model,
            "messages": [{"role": "system", "content": SYSTEM_PROMPT},
                         {"role": "user", "content": f"Review:\n{text}"}],
            "response_format": {"type": "json_schema",
                                "json_schema": {"name": "review_aspects", "strict": True, "schema": SCHEMA}},
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
                 "cached_tokens": (u.get("prompt_tokens_details") or {}).get("cached_tokens", 0),
                 "reasoning_tokens": (u.get("completion_tokens_details") or {}).get("reasoning_tokens", 0)}
        return msg["content"], usage


def run(a, reviews, raw_path):
    recs = read_jsonl(raw_path)
    done = {r["review_id"] for r in recs if r.get("ok") and r.get("prompt_version") == PROMPT_VERSION}
    todo = reviews[~reviews["review_id"].isin(done)]
    if a.limit:
        todo = todo[todo.index < a.limit]  # first N reviews of the input (by position)
    spent, _ = run_cost(a.model, recs)
    print(f"prompt {PROMPT_VERSION}: {len(done):,} done, {len(todo):,} to run; ${spent:.3f} spent so far", flush=True)
    if todo.empty:
        return
    if spent >= a.max_cost:
        sys.exit(f"Already spent ${spent:.2f} >= --max-cost ${a.max_cost:.2f}; not starting.")
    llm = Extractor(a.model, a.base_url, a.reasoning_effort)
    lock, stop = threading.Lock(), threading.Event()
    stats = Counter()
    t0 = time.time()

    def work(row):
        if stop.is_set():
            return None
        rec = {"review_id": row.review_id, "model": a.model, "prompt_version": PROMPT_VERSION,
               "reasoning_effort": a.reasoning_effort, "ts": time.strftime("%Y-%m-%dT%H:%M:%S")}
        try:
            raw, usage = llm.extract(row.llm_text)
            rec.update(ok=True, raw=raw, usage=usage, aspects=json.loads(raw)["aspects"])
        except Exception as e:  # recorded; retried on the next run
            rec.update(ok=False, error=str(e)[:500])
        return rec

    with raw_path.open("a") as out, ThreadPoolExecutor(max_workers=a.workers) as pool:
        futures = [pool.submit(work, row) for row in todo.itertuples()]
        for i, fut in enumerate(as_completed(futures), 1):
            rec = fut.result()
            if rec is None:
                continue
            with lock:
                out.write(json.dumps(rec, ensure_ascii=False) + "\n")
                out.flush()
                stats["ok" if rec["ok"] else "error"] += 1
                if rec["ok"]:
                    for k, v in rec["usage"].items():
                        stats[k] += v
                elif stats["error"] <= 3:
                    print(f"  error: {rec['error']}", flush=True)
                total = spent + rme.cost(a.model, stats)
                if total >= a.max_cost and not stop.is_set():
                    stop.set()
                    print(f"  STOP: cost ${total:.2f} reached --max-cost ${a.max_cost:.2f}", flush=True)
            if i % 100 == 0 or i == len(futures):
                print(f"  {i:,}/{len(futures):,} ok={stats['ok']:,} err={stats['error']:,} "
                      f"{i / max(time.time() - t0, 1e-9):.1f}/s ~${spent + rme.cost(a.model, stats):.3f} total",
                      flush=True)
    if stats["error"]:
        print(f"  {stats['error']} failed; rerun the same command to retry them.")


def build(a, reviews, out):
    recs = read_jsonl(out / "raw_results.jsonl")
    latest = {}
    for r in recs:
        if r.get("ok") and r.get("prompt_version") == PROMPT_VERSION:
            latest[r["review_id"]] = r
    meta = reviews.set_index("review_id")
    rows = []
    for rid, r in latest.items():
        m = meta.loc[rid]
        for i, asp in enumerate(r["aspects"]):
            rows.append({
                "review_id": rid, "cluster_id": int(m["cluster_id"]), "cluster_label": m["cluster_label"],
                "sample_type": m["sample_type"], "also_sampled_as": m["also_sampled_as"], "weight": m["weight"],
                "aspect_idx": i, "description": asp["description"], "sentiment": asp["sentiment"],
                "aspect_type": asp["aspect_type"], "feature": asp["feature"].strip().lower() or "none",
                "evidence": asp["evidence"], "evidence_valid": evidence_ok(asp["evidence"], m["text"]),
                "stars": m["stars"], "feedback_date": m["feedback_date"], "app_versions": m["app_versions"],
                "text": m["text"], "text_truncated": len(m["text"]) > MAX_CHARS,
            })
    asp = pd.DataFrame(rows)
    asp.to_parquet(out / "extracted_aspects.parquet", index=False)

    failed_ids = {r["review_id"] for r in recs if not r.get("ok")} - set(latest)
    n_aspects = Counter({rid: len(r["aspects"]) for rid, r in latest.items()})
    generic_types = {"general_praise", "other"}
    no_specific = sum(1 for rid, r in latest.items()
                      if all(x["aspect_type"] in generic_types and x["feature"].strip().lower() == "none"
                             for x in r["aspects"]))
    cost, usage = run_cost(a.model, recs)
    manifest = {
        "model": a.model, "reasoning_effort": a.reasoning_effort, "prompt_version": PROMPT_VERSION,
        "input": str(Path(a.input)), "reviews_in_input": int(len(reviews)),
        "reviews_processed": len(latest), "reviews_failed": len(failed_ids),
        "reviews_with_zero_aspects": sum(1 for v in n_aspects.values() if v == 0),
        "reviews_with_no_specific_aspect": no_specific,
        "aspects_extracted": int(len(asp)),
        "evidence_valid_rate": round(float(asp["evidence_valid"].mean()), 4) if len(asp) else None,
        "evidence_invalid": int((~asp["evidence_valid"]).sum()) if len(asp) else 0,
        "failures": [{"review_id": r["review_id"], "error": r.get("error")} for r in recs
                     if not r.get("ok") and r["review_id"] in failed_ids][:50],
        "total_cost_usd_all_runs": round(cost, 4), "usage_all_runs": dict(usage),
        "price_note": "cost uses run_music_edges.PRICES (approximate rate card, not billed amounts)",
        "max_chars": MAX_CHARS, "system_prompt": SYSTEM_PROMPT, "schema": SCHEMA,
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
    print(json.dumps({k: manifest[k] for k in ["reviews_processed", "reviews_failed", "aspects_extracted",
                                               "reviews_with_zero_aspects", "reviews_with_no_specific_aspect",
                                               "evidence_valid_rate", "total_cost_usd_all_runs"]}, indent=1))


def main():
    rme.load_env()
    import os
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--input", default=str(ROOT / "samples/spotify_pilot/sampled_reviews.parquet"))
    p.add_argument("--out", default=str(ROOT / "extractions/spotify"))
    p.add_argument("--model", default="gpt-6-luna")
    p.add_argument("--reasoning-effort", default="low")
    p.add_argument("--base-url", default=os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"))
    p.add_argument("--workers", type=int, default=6)
    p.add_argument("--limit", type=int, default=None, help="Only the first N reviews (stage 1)")
    p.add_argument("--max-cost", type=float, default=5.0, help="Stop when total cost (all runs) reaches this")
    p.add_argument("--build-only", action="store_true")
    a = p.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    reviews = load_reviews(a.input)
    if not a.build_only:
        run(a, reviews, out / "raw_results.jsonl")
    build(a, reviews, out)


if __name__ == "__main__":
    main()
