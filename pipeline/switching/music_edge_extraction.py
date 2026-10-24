"""Music-cluster edge extraction for the app-switching graph.

Pipeline:
  1. find_candidates(): keep reviews of a music app that mention another music app
  2. build_messages():  prompt + one review -> LLM call with EDGE_SCHEMA as structured output
  3. validate():        reject hallucinated evidence / unknown apps
  4. to_edges():        convert labeled mentions into directed, weighted graph edges

Directions are always expressed RELATIVE TO THE REVIEWED APP (the app the review
was posted on). That makes the labeling task easier for the LLM and lets us
build edges deterministically in code instead of trusting the model to get
source/target right.
"""
import json
import re

# ---------------------------------------------------------------------------
# Apps
# ---------------------------------------------------------------------------
# Apps whose reviews are in the dataset (we can measure flow both ways).
REVIEWED_MUSIC_APPS = ["Spotify", "Audiomack", "SoundCloud"]

# Canonical name -> regex aliases. Order matters: "YouTube Music" must be
# checked before plain "YouTube".
MUSIC_APPS = {
    "Spotify":        [r"spotify"],
    "Audiomack":      [r"audio\s?mack"],
    "SoundCloud":     [r"sound\s?cloud"],
    "Apple Music":    [r"apple\s?music", r"itunes"],
    "YouTube Music":  [r"youtube\s?music", r"yt\s?music", r"you\s?tube\s?music"],
    "YouTube":        [r"youtube", r"\byt\b"],          # plain YouTube used as a music source
    "Amazon Music":   [r"amazon\s?music", r"amazon\s?prime\s?music"],
    "Pandora":        [r"pandora"],
    "Tidal":          [r"\btidal\b"],
    "Deezer":         [r"deezer"],
    "Boomplay":       [r"boom\s?play"],
    "Anghami":        [r"anghami"],
    "JioSaavn":       [r"jio\s?saavn", r"\bsaavn\b"],
    "Musi":           [r"\bmusi\b"],
    "iHeartRadio":    [r"iheart"],
    "Bandcamp":       [r"bandcamp"],
    "Qobuz":          [r"qobuz"],
}
CANONICAL_APPS = list(MUSIC_APPS) + ["Other"]

_ALIAS_RE = {app: re.compile("|".join(p), re.I) for app, p in MUSIC_APPS.items()}

# ---------------------------------------------------------------------------
# Labels
# ---------------------------------------------------------------------------
RELATIONS = {
    "left_for":              "User has stopped/cancelled/uninstalled the reviewed app and moved to the mentioned app.",
    "leaving_for":           "User says they WILL switch / are about to switch to the mentioned app (intent, not done).",
    "came_from":             "User previously used the mentioned app and moved to the reviewed app.",
    "returned_from":         "User had left the reviewed app for the mentioned app and has now come back.",
    "prefers_mentioned":     "Comparison where the mentioned app is better, with no stated move.",
    "prefers_reviewed":      "Comparison where the reviewed app is better, with no stated move (includes 'better than X').",
    "uses_both":             "User uses both apps side by side.",
    "neutral_comparison":    "Comparison with no clear preference.",
    "not_a_switch_reference": "Mention unrelated to choosing between apps (integration, sharing, import, 'like Spotify Wrapped', name in a playlist, etc.).",
}

REASONS = {
    "price":              "subscription cost, price increase, family/student plan cost",
    "free_tier_limits":   "shuffle-only, skip limits, can't pick songs on free tier",
    "ads":                "too many ads, ad frequency or length",
    "catalog":            "songs/artists missing, removed, greyed out, regional catalog",
    "offline_downloads":  "downloads disappearing, offline limits, download quality",
    "audio_quality":      "bitrate, lossless, hi-res, sound quality",
    "recommendations":    "algorithm, discovery, repetitive suggestions, AI DJ",
    "ui_change":          "redesign, navigation, layout, feature removed from UI",
    "bugs_performance":   "crashes, playback stops, lag, battery, login loops",
    "account_billing":    "charged wrongly, can't cancel, account lost/banned",
    "podcasts_audiobooks": "podcast/audiobook push or features",
    "artist_or_ethics":   "artist payouts, company policy, CEO, values",
    "independent_artists": "uploading, indie/underground/local music, DJ mixes, remixes",
    "social_integration": "friends, sharing, device/car/watch/smart-speaker support",
    "lyrics":             "lyrics availability or paywalling",
    "other":              "anything else; describe in reason_detail",
}

# ---------------------------------------------------------------------------
# JSON schema (strict-mode compatible: every property required, no extras)
# ---------------------------------------------------------------------------
EDGE_SCHEMA = {
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
                    "mentioned_app":     {"type": "string", "enum": CANONICAL_APPS},
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
# Prompt
# ---------------------------------------------------------------------------
def _bullets(d):
    return "\n".join(f"- {k}: {v}" for k, v in d.items())

SYSTEM_PROMPT = f"""You label app store reviews of music streaming apps to measure how users move between apps.

You get: the REVIEWED APP (the app the review was posted on), the star rating, and the review text.
For every OTHER music app mentioned, decide the relationship between the user and the two apps,
always described from the point of view of the REVIEWED APP.

Relations:
{_bullets(RELATIONS)}

Reasons (multi-select, only what the user actually states):
{_bullets(REASONS)}

Rules:
1. Direction is the whole point. Read carefully:
   - "better than X" / "X could never" / "way better than X" in a review of the reviewed app = prefers_reviewed.
   - "X is better" / "X does this for free" = prefers_mentioned.
   - "switching to X", "cancelled and got X", "moving to X" = left_for if done, leaving_for if future/threat.
   - "came from X", "after years on X", "finally ditched X for this" = came_from.
   - "went back to X and came back", "tried X, returning" = returned_from.
2. Star rating is context, not evidence. A 1-star review can still prefer the reviewed app.
3. Only label apps that are actually named. Do not infer a destination ("I'm deleting this") if no app is named; return no mention for that.
4. Plain "YouTube" counts as a music source only when used for listening to music; otherwise not_a_switch_reference.
5. The reviewed app itself is never a mention. Non-music apps (Instagram, TikTok, Waze) are not_a_switch_reference with mentioned_app "Other" — skip them unless they are used as the music source.
6. evidence must be copied exactly from the review text (a contiguous substring), short as possible.
7. confidence: high = explicit statement; medium = strongly implied; low = ambiguous, sarcastic, or garbled.
8. Reviews may be in slang, misspelled, or partly non-English. Do your best; lower the confidence rather than guessing.
"""

FEW_SHOT = [
    {
        "app": "Spotify", "stars": 1,
        "text": "Raised the price AGAIN. Cancelled premium today and switched to YouTube Music since I already pay for YouTube premium.",
        "out": {"mentions": [{
            "mentioned_app": "YouTube Music", "mentioned_app_raw": "YouTube Music",
            "relation": "left_for", "reasons": ["price"],
            "reason_detail": "Spotify price increase; already pays for YouTube Premium",
            "evidence": "Cancelled premium today and switched to YouTube Music",
            "confidence": "high"}]},
    },
    {
        "app": "Audiomack", "stars": 5,
        "text": "way better than spotify, free and i can actually pick my songs. underground artists are all here",
        "out": {"mentions": [{
            "mentioned_app": "Spotify", "mentioned_app_raw": "spotify",
            "relation": "prefers_reviewed", "reasons": ["free_tier_limits", "independent_artists"],
            "reason_detail": "free song choice and underground artists",
            "evidence": "way better than spotify",
            "confidence": "high"}]},
    },
    {
        "app": "SoundCloud", "stars": 2,
        "text": "Ads every 2 songs now. If this keeps up im going to Audiomack. Still the only place for DJ mixes tho",
        "out": {"mentions": [{
            "mentioned_app": "Audiomack", "mentioned_app_raw": "Audiomack",
            "relation": "leaving_for", "reasons": ["ads"],
            "reason_detail": "ads every two songs",
            "evidence": "If this keeps up im going to Audiomack",
            "confidence": "high"}]},
    },
    {
        "app": "Spotify", "stars": 4,
        "text": "Tried Apple Music for 3 months, came back. The recommendations here are just better. Wish I could share stories to Instagram easier.",
        "out": {"mentions": [{
            "mentioned_app": "Apple Music", "mentioned_app_raw": "Apple Music",
            "relation": "returned_from", "reasons": ["recommendations"],
            "reason_detail": "better recommendations on Spotify",
            "evidence": "Tried Apple Music for 3 months, came back",
            "confidence": "high"}]},
    },
]


def _user_block(app, stars, text):
    return f"REVIEWED APP: {app}\nSTARS: {stars}\nREVIEW:\n{text}"


def build_messages(app, stars, text):
    """Chat messages for one review. Pass EDGE_SCHEMA as the structured-output schema."""
    msgs = [{"role": "system", "content": SYSTEM_PROMPT}]
    for ex in FEW_SHOT:
        msgs.append({"role": "user", "content": _user_block(ex["app"], ex["stars"], ex["text"])})
        msgs.append({"role": "assistant", "content": json.dumps(ex["out"])})
    msgs.append({"role": "user", "content": _user_block(app, stars, text)})
    return msgs

# ---------------------------------------------------------------------------
# Candidate filter
# ---------------------------------------------------------------------------
def mentioned_apps(text, reviewed_app):
    """Canonical music apps named in text, excluding the reviewed app."""
    found = set()
    for app, rx in _ALIAS_RE.items():
        if rx.search(text):
            found.add(app)
    if "YouTube Music" in found:
        found.discard("YouTube")  # 'YouTube Music' also matches plain 'youtube'
    found.discard(reviewed_app)
    return sorted(found)


def find_candidates(rows):
    """rows: iterable of dicts with app_name, text. Yields rows that mention another music app."""
    for r in rows:
        if r["app_name"] not in REVIEWED_MUSIC_APPS:
            continue
        hits = mentioned_apps(r["text"] or "", r["app_name"])
        if hits:
            yield {**r, "keyword_hits": hits}

# ---------------------------------------------------------------------------
# Validation + edges
# ---------------------------------------------------------------------------
_norm = lambda s: re.sub(r"\s+", " ", s).strip().casefold()


def validate(result, reviewed_app, text):
    """Drop mentions whose evidence isn't in the review or that name the reviewed app."""
    kept, rejected = [], []
    for m in result.get("mentions", []):
        problem = None
        if m["mentioned_app"] == reviewed_app:
            problem = "self_mention"
        elif m["evidence"] and _norm(m["evidence"]) not in _norm(text):
            problem = "evidence_not_in_text"
        (rejected if problem else kept).append({**m, "_problem": problem} if problem else m)
    return kept, rejected


# relation -> (direction, kind, weight). direction "out" = reviewed -> mentioned.
EDGE_RULES = {
    "left_for":          ("out", "switch",     1.0),
    "leaving_for":       ("out", "intent",     0.5),
    "came_from":         ("in",  "switch",     1.0),
    "returned_from":     ("in",  "return",     1.0),
    "prefers_mentioned": ("out", "preference", 0.25),
    "prefers_reviewed":  ("in",  "preference", 0.25),
}
CONF_WEIGHT = {"high": 1.0, "medium": 0.7, "low": 0.0}  # drop low by default


def to_edges(review, mentions):
    """review: dict with feedback_id, app_name, feedback_date, stars, data_source."""
    edges = []
    for m in mentions:
        rule = EDGE_RULES.get(m["relation"])
        if not rule or m["mentioned_app"] == "Other":
            continue
        direction, kind, w = rule
        w *= CONF_WEIGHT[m["confidence"]]
        if w == 0:
            continue
        src, dst = ((review["app_name"], m["mentioned_app"]) if direction == "out"
                    else (m["mentioned_app"], review["app_name"]))
        edges.append({
            "feedback_id": review["feedback_id"],
            "source": src, "target": dst,
            "kind": kind, "weight": w,
            "reasons": m["reasons"], "reason_detail": m["reason_detail"],
            "month": str(review.get("feedback_date", ""))[:7],
            "stars": review.get("stars"), "data_source": review.get("data_source"),
            "evidence": m["evidence"],
        })
    return edges


if __name__ == "__main__":
    # Self-check: few-shot outputs validate and produce sensible edges.
    for i, ex in enumerate(FEW_SHOT):
        kept, rej = validate(ex["out"], ex["app"], ex["text"])
        assert not rej, rej
        review = {"feedback_id": f"ex{i}", "app_name": ex["app"], "feedback_date": "2025-06-01", "stars": ex["stars"]}
        for e in to_edges(review, kept):
            print(f'{e["source"]:>12} -> {e["target"]:<14} {e["kind"]:<10} w={e["weight"]}  {e["reasons"]}')
    print(mentioned_apps("switched from yt music and itunes, spotify is fine", "Spotify"))
    print(json.dumps(EDGE_SCHEMA)[:80] + "...")
