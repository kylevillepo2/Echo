#!/usr/bin/env python3
"""Score your hand labels (label_me.csv) against the model's labels (model_labels.csv).
Usage: python3 score_validation.py
"""
import csv, math
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).parent
# Each relation -> (does it create an edge?, direction relative to reviewed app, kind)
REL = {
    "left_for": ("out", "switch"), "leaving_for": ("out", "intent"),
    "came_from": ("in", "switch"), "returned_from": ("in", "switch"),
    "prefers_mentioned": ("out", "preference"), "prefers_reviewed": ("in", "preference"),
    "uses_both": ("none", "none"), "neutral_comparison": ("none", "none"),
    "not_a_switch_reference": ("none", "none"),
}
SHORT = {"lf": "left_for", "lv": "leaving_for", "cf": "came_from", "rf": "returned_from",
         "pm": "prefers_mentioned", "pr": "prefers_reviewed", "ub": "uses_both",
         "nc": "neutral_comparison", "ns": "not_a_switch_reference"}

def wilson(k, n, z=1.96):
    if n == 0: return (0, 0)
    p = k / n; d = 1 + z*z/n
    c = (p + z*z/(2*n)) / d; h = z*math.sqrt(p*(1-p)/n + z*z/(4*n*n)) / d
    return (max(0, c-h), min(1, c+h))

def pct(k, n):
    lo, hi = wilson(k, n)
    return f"{k}/{n} = {k/n:.0%} (95% range {lo:.0%}-{hi:.0%})" if n else "n/a"

model = {r["row"]: r for r in csv.DictReader(open(HERE / "model_labels.csv"))}
mine = {}
for r in csv.DictReader(open(HERE / "label_me.csv")):
    v = (r["your_relation"] or "").strip().lower()
    v = SHORT.get(v, v)
    if v:
        if v not in REL:
            raise SystemExit(f"Row {r['row']}: unknown relation '{r['your_relation']}'. Use: {', '.join(REL)} or {', '.join(SHORT)}")
        mine[r["row"]] = v
if not mine:
    raise SystemExit("No labels yet: fill the your_relation column in label_me.csv")

stats = defaultdict(Counter); wrong = []
for row, you in mine.items():
    m = model[row]; mr = m["model_relation"]
    for key in ("all", f"story:{m['story']}", f"model group:{m['group']}"):
        s = stats[key]; s["n"] += 1
        s["exact"] += mr == you
        s["direction"] += REL[mr][0] == REL[you][0]
        s["edge"] += (REL[mr][0] != "none") == (REL[you][0] != "none")
        s["kind"] += REL[mr] == REL[you]
    if mr != you: wrong.append((row, m["reviewed_app"], m["mentioned_app"], mr, you))

print(f"Labeled {len(mine)} of {len(model)} rows\n")
for key in ["all"] + sorted(k for k in stats if k != "all"):
    s = stats[key]; n = s["n"]
    print(f"[{key}]")
    print(f"  exact relation      {pct(s['exact'], n)}")
    print(f"  direction correct   {pct(s['direction'], n)}   (out / in / no edge)")
    print(f"  edge vs no-edge     {pct(s['edge'], n)}")
    print(f"  direction + kind    {pct(s['kind'], n)}   (what the graph shows)")
print("\nDisagreements (row, reviewed -> mentioned, model, you):")
for w in wrong: print("  ", *w)
