"""Cross-category edge extraction for the app-switching graph.

Same approach as music_edge_extraction.py (which stays unchanged and is reused for
music), generalized to every category in categories.json:

  1. mentioned_apps(): which apps in the reviewed app's category a review names
  2. build_messages(): shared prompt + one review -> LLM call with a per-category schema
  3. validation:      music_edge_extraction.validate (evidence must be in the review)
  4. edges:           music_edge_extraction.to_edges (same relations, weights, confidence)

Relations and edge rules are identical to music. Reasons use a shared list that
works across categories; MUSIC_REASON_MAP folds the music reasons into it.
"""
import json
import re
from functools import lru_cache
from pathlib import Path

import music_edge_extraction as mx

CONFIG_PATH = Path(__file__).resolve().parent / "categories.json"

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
CONFIG = json.loads(CONFIG_PATH.read_text())
CATEGORIES = CONFIG["categories"]
APP_MERGES = CONFIG.get("app_merges", {})

APP_CATEGORY = {app: cid for cid, c in CATEGORIES.items() for app in c["apps"]}


def canonical_app(name):
    name = (name or "").strip()  # the data has 'Capital One Mobile ' with a trailing space
    return APP_MERGES.get(name, name)


def category_apps(cid):
    """Every node a review in this category can name: reviewed apps + outside competitors."""
    c = CATEGORIES[cid]
    return list(dict.fromkeys(c["apps"] + c["competitors"]))


@lru_cache(maxsize=None)
def _compiled(cid):
    """Aliases must sit on word boundaries, so 'her app' can't match inside 'other apps'."""
    c = CATEGORIES[cid]
    return [(app, re.compile(rf"(?<![^\W_])(?:{p})(?![^\W_])", re.I))
            for app, pats in c["aliases"].items() if not app.startswith("_") for p in pats]


def mentioned_apps(text, reviewed_app, cid=None):
    """Apps in the reviewed app's category named in text, excluding the app itself.

    Overlapping matches resolve to the longest one, so 'Uber Eats' never also
    counts as 'Uber', and 'YouTube TV' never as 'YouTube'.
    """
    cid = cid or APP_CATEGORY.get(reviewed_app)
    if not cid or not text:
        return []
    spans = []
    for app, rx in _compiled(cid):
        for m in rx.finditer(text):
            if m.end() > m.start():
                spans.append((m.start(), m.end(), app))
    spans.sort(key=lambda s: (-(s[1] - s[0]), s[0]))
    taken, found = [], set()
    for start, end, app in spans:
        if any(start < e and s < end for s, e in taken):
            continue
        taken.append((start, end))
        found.add(app)
    self_names = {reviewed_app, *CATEGORIES[cid].get("self_aliases", {}).get(reviewed_app, [])}
    return sorted(found - self_names)


# ---------------------------------------------------------------------------
# Labels
# ---------------------------------------------------------------------------
RELATIONS = mx.RELATIONS  # identical relations: edges are built with mx.to_edges

REASONS = {
    "price_fees":              "subscription or product price, price increases, fees (transfer, instant, delivery, service), payouts/pay rates",
    "ads":                     "too many ads, ad frequency or length, sponsored content",
    "missing_features_limits": "a feature is missing, removed or paywalled; free-tier limits, swipe/skip/usage caps",
    "content_selection":       "catalog, selection, matches/people available, inventory, content quality or relevance, recommendations",
    "bugs_performance":        "crashes, glitches, slow app, battery drain, login loops, things not loading",
    "design_changes":          "redesign, new layout, navigation changes, UI clutter",
    "customer_support":        "support quality, can't reach a human, disputes and refunds handled badly",
    "account_security_trust":  "account locked/banned/hacked, fraud, scams, fake profiles, money held, wrong charges",
    "policy_privacy":          "company policy, data/privacy, censorship/moderation, ethics, terms changes",
    "speed_availability":      "service speed or availability: wait times, delivery or transfer speed, drivers/riders available, regions supported",
    "other":                   "anything else; describe in reason_detail",
}

# Music reasons -> shared reasons (for the combined output; music labels are reused, not redone).
MUSIC_REASON_MAP = {
    "price":               "price_fees",
    "free_tier_limits":    "missing_features_limits",
    "ads":                 "ads",
    "catalog":             "content_selection",
    "offline_downloads":   "missing_features_limits",
    "audio_quality":       "content_selection",
    "recommendations":     "content_selection",
    "ui_change":           "design_changes",
    "bugs_performance":    "bugs_performance",
    "account_billing":     "account_security_trust",
    "podcasts_audiobooks": "content_selection",
    "artist_or_ethics":    "policy_privacy",
    "independent_artists": "content_selection",
    "social_integration":  "missing_features_limits",
    "lyrics":              "missing_features_limits",
    "other":               "other",
}
assert set(MUSIC_REASON_MAP) == set(mx.REASONS) and set(MUSIC_REASON_MAP.values()) <= set(REASONS)


def map_music_reasons(reasons):
    return list(dict.fromkeys(MUSIC_REASON_MAP.get(r, "other") for r in reasons))


@lru_cache(maxsize=None)
def edge_schema(cid):
    """Strict structured-output schema; mentioned_app is limited to this category's apps."""
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["mentions"],
        "properties": {
            "mentions": {
                "type": "array",
                "description": "One entry per distinct OTHER app mentioned. Empty if none.",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["mentioned_app", "mentioned_app_raw", "relation",
                                 "reasons", "reason_detail", "evidence", "confidence"],
                    "properties": {
                        "mentioned_app":     {"type": "string", "enum": category_apps(cid) + ["Other"]},
                        "mentioned_app_raw": {"type": "string", "description": "App name exactly as written in the review."},
                        "relation":          {"type": "string", "enum": list(RELATIONS)},
                        "reasons": {
                            "type": "array",
                            "items": {"type": "string", "enum": list(REASONS)},
                            "description": "Why the user moved/prefers. Empty if no reason is stated. Never guess.",
                        },
                        "reason_detail": {"type": "string", "description": "<=15 words, plain summary of the stated reason. Empty string if none."},
                        "evidence":      {"type": "string", "description": "Exact contiguous substring of the review supporting the relation."},
                        "confidence":    {"type": "string", "enum": ["high", "medium", "low"]},
                    },
                },
            }
        },
    }


# ---------------------------------------------------------------------------
# Prompt (shared across categories so the prefix is cached; the category goes in the user turn)
# ---------------------------------------------------------------------------
def _bullets(d):
    return "\n".join(f"- {k}: {v}" for k, v in d.items())


SYSTEM_PROMPT = f"""You label app store reviews to measure how users move between competing apps.

You get: the CATEGORY, the REVIEWED APP (the app the review was posted on), the apps that count as
competitors in this category, the star rating, and the review text. For every OTHER competing app
mentioned, decide the relationship between the user and the two apps, always described from the
point of view of the REVIEWED APP.

Relations:
{_bullets(RELATIONS)}

Reasons (multi-select, only what the user actually states):
{_bullets(REASONS)}

Rules:
1. Direction is the whole point. Read carefully:
   - "better than X" / "X could never" / "way better than X" in a review of the reviewed app = prefers_reviewed.
   - "X is better" / "X does this for free" / "X pays more" = prefers_mentioned.
   - "switching to X", "cancelled and got X", "moving to X", "deleting this, back to X" = left_for if done, leaving_for if future/threat.
   - "came from X", "after years on X", "finally ditched X for this" = came_from.
   - "went back to X and came back", "tried X, returning" = returned_from.
2. Star rating is context, not evidence. A 1-star review can still prefer the reviewed app.
3. Only label apps that are actually named. Do not infer a destination ("I'm deleting this") if no app is named.
4. A named app must be an alternative for the same job. Otherwise it is not_a_switch_reference:
   sending money between apps or linking accounts (paying someone's Venmo from Cash App), integrations and
   logins ("sign in with Google"), where content is shared or posted, channels on a device (Netflix on a Roku),
   a package from Amazon carried by UPS, a person's name that matches an app.
5. The reviewer may be a customer, a driver/courier, a seller/merchant or a creator. Label from their point of view
   but still relative to the REVIEWED APP: an Uber driver saying "DoorDash pays more" = prefers_mentioned.
6. Use the most specific app name from the list. If a review says plain "Uber" while talking about food delivery,
   use "Uber Eats" if it is in the list. Use "Other" for apps not in the list (they are dropped later).
7. The reviewed app itself is never a mention.
8. evidence must be copied exactly from the review text (a contiguous substring), short as possible.
9. confidence: high = explicit statement; medium = strongly implied; low = ambiguous, sarcastic, or garbled.
10. Reviews may be in slang, misspelled, or partly non-English. Do your best; lower the confidence rather than guessing.
"""

FEW_SHOT = [
    {
        "category": "payments_banking", "app": "Cash App", "stars": 1,
        "text": "They charge a fee for everything now. Closed my account and moved my direct deposit to Chime. I still use it to pay my roommate on Venmo lol",
        "out": {"mentions": [
            {"mentioned_app": "Chime", "mentioned_app_raw": "Chime", "relation": "left_for", "reasons": ["price_fees"],
             "reason_detail": "fees on everything", "evidence": "Closed my account and moved my direct deposit to Chime",
             "confidence": "high"},
            {"mentioned_app": "Venmo", "mentioned_app_raw": "Venmo", "relation": "uses_both", "reasons": [],
             "reason_detail": "", "evidence": "I still use it to pay my roommate on Venmo", "confidence": "medium"}]},
    },
    {
        "category": "dating", "app": "Hinge", "stars": 5,
        "text": "so much better than tinder, actual conversations instead of hookups. met my bf here after 2 years of bumble",
        "out": {"mentions": [
            {"mentioned_app": "Tinder", "mentioned_app_raw": "tinder", "relation": "prefers_reviewed", "reasons": ["content_selection"],
             "reason_detail": "real conversations instead of hookups", "evidence": "so much better than tinder", "confidence": "high"},
            {"mentioned_app": "Bumble", "mentioned_app_raw": "bumble", "relation": "came_from", "reasons": [],
             "reason_detail": "", "evidence": "after 2 years of bumble", "confidence": "high"}]},
    },
    {
        "category": "rides_delivery", "app": "DoorDash", "stars": 2,
        "text": "Order was 50 min late and support just gave me a $5 credit. Going back to Uber, their eats is faster where I live.",
        "out": {"mentions": [
            {"mentioned_app": "Uber Eats", "mentioned_app_raw": "Uber", "relation": "leaving_for",
             "reasons": ["speed_availability", "customer_support"], "reason_detail": "late order, weak support response",
             "evidence": "Going back to Uber, their eats is faster where I live", "confidence": "high"}]},
    },
    {
        "category": "video_streaming", "app": "Roku", "stars": 4,
        "text": "Netflix and Hulu run great on it. Tried a Fire Stick for a month, came back, the Roku remote is just simpler.",
        "out": {"mentions": [
            {"mentioned_app": "Netflix", "mentioned_app_raw": "Netflix", "relation": "not_a_switch_reference", "reasons": [],
             "reason_detail": "", "evidence": "Netflix and Hulu run great on it", "confidence": "high"},
            {"mentioned_app": "Hulu", "mentioned_app_raw": "Hulu", "relation": "not_a_switch_reference", "reasons": [],
             "reason_detail": "", "evidence": "Netflix and Hulu run great on it", "confidence": "high"},
            {"mentioned_app": "Fire TV", "mentioned_app_raw": "Fire Stick", "relation": "returned_from", "reasons": ["design_changes"],
             "reason_detail": "Roku remote is simpler", "evidence": "Tried a Fire Stick for a month, came back", "confidence": "high"}]},
    },
]


def _user_block(cid, app, stars, text):
    c = CATEGORIES[cid]
    others = [a for a in category_apps(cid) if a != app]
    return (f"CATEGORY: {c['label']}\nREVIEWED APP: {app}\n"
            f"COMPETING APPS: {', '.join(others)}\nSTARS: {stars}\nREVIEW:\n{text}")


def build_messages(cid, app, stars, text):
    msgs = [{"role": "system", "content": SYSTEM_PROMPT}]
    for ex in FEW_SHOT:
        msgs.append({"role": "user", "content": _user_block(ex["category"], ex["app"], ex["stars"], ex["text"])})
        msgs.append({"role": "assistant", "content": json.dumps(ex["out"])})
    msgs.append({"role": "user", "content": _user_block(cid, app, stars, text)})
    return msgs


# ---------------------------------------------------------------------------
# Batch mode: one request labels many reviews of the same category
# ---------------------------------------------------------------------------
def _example_block():
    parts = []
    for ex in FEW_SHOT:
        parts.append(f"{_user_block(ex['category'], ex['app'], ex['stars'], ex['text'])}\nOUTPUT mentions: "
                     f"{json.dumps(ex['out']['mentions'], ensure_ascii=False)}")
    return "\n\n".join(parts)


BATCH_SYSTEM_PROMPT = SYSTEM_PROMPT + f"""
Batch format:
You get several reviews in one message, each starting with "=== REVIEW id=<id> ===". Label each review
independently, using only that review's own text: evidence must be copied from that same review.
Return exactly one entry per review id, in the same order, with "mentions" as defined above
(an empty list when no competing app is meaningfully mentioned).

Worked examples (one review each, shown with the mentions you would return for it):

{_example_block()}
"""


@lru_cache(maxsize=None)
def batch_schema(cid):
    item = edge_schema(cid)["properties"]["mentions"]
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["reviews"],
        "properties": {
            "reviews": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["id", "mentions"],
                    "properties": {"id": {"type": "string"}, "mentions": item},
                },
            }
        },
    }


def build_batch_messages(cid, items):
    """items: list of (id, reviewed_app, stars, text), all in category cid."""
    c = CATEGORIES[cid]
    head = (f"CATEGORY: {c['label']}\nAPPS IN THIS CATEGORY (reviewed apps and competitors): "
            f"{', '.join(category_apps(cid))}\n\n{len(items)} reviews follow.")
    blocks = [head]
    for rid, app, stars, text in items:
        blocks.append(f"=== REVIEW id={rid} ===\nREVIEWED APP: {app}\nSTARS: {stars}\nREVIEW:\n{text}")
    return [{"role": "system", "content": BATCH_SYSTEM_PROMPT},
            {"role": "user", "content": "\n\n".join(blocks)}]


if __name__ == "__main__":
    for ex in FEW_SHOT:
        kept, rej = mx.validate(ex["out"], ex["app"], ex["text"])
        assert not rej, rej
        assert all(m["mentioned_app"] in category_apps(ex["category"]) for m in kept)
    tests = [
        ("DoorDash", "uber eats is cheaper than this, and Uber rides too"),
        ("Uber", "I order on Uber Eats all the time but Lyft is cheaper"),
        ("Reddit", "threads won't load. Moving to Lemmy and the Threads app"),
        ("Cash App", "Dave from support was useless, switched to Chime. Apple is great. Apple Pay works"),
        ("Hinge", "got a match today. Match.com is worse"),
        ("Roku", "YouTube TV and youtube both work, max app too, Max is great"),
    ]
    for app, text in tests:
        print(f"{app:10} | {mentioned_apps(text, app)} | {text}")
