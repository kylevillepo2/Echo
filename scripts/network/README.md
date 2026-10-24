# Switch-report network

From the frontend repo, regenerate in this order:

```sh
python3 pipeline/switching/fix_switching.py apply
python3 pipeline/switching/fix_switching.py stats
python3 scripts/network/export_network.py
python3 -m unittest discover -s scripts/network -p 'test_*.py'
npm run check
npm run dev -- --host 127.0.0.1
```

`apply` rebuilds the corrected CSVs from the preserved `*_v1.csv` inputs and
existing role labels. It makes no model calls. `stats` scans raw reviews for
ratings and review counts, and writes `out/all/app_stats.json` and `.csv`.
The exporter reads those files and atomically replaces
`src/lib/data/network.json`. Paths resolve relative to the scripts; exporter
`--input` and `--output` can override defaults.

## Balance has one source of truth

Only `fix_switching.py stats` calculates scores and buckets. It writes `health`
for all time and `health_by_period` for 2024 and 2025. The exporter copies both
objects exactly; the frontend reads them without recalculating. Missing stats
are an error, with no fallback. Tests compare every exported value against the
stats artifact and deliberately corrupt each supporting field to prove the
comparison rejects disagreement.

Balance includes only actual switch/return reports where **both apps are in our
dataset**, customers only where occupational roles apply, and no forced moves.
`n/a` means occupational role labeling does not apply. Duplicate
review/pair/month/kind rows count once. A return counts in its reported direction
for both incoming and outgoing counts.

The score is `(reports_in - reports_out) / (reports_in + reports_out)`. No eligible
reports produces a null score. Every balance object contains score, bucket,
`reports_in`, `reports_out`, total, and this exact definition:

> Balance of switches reported in reviews, between apps both in our dataset. Not a measure of user growth.

Buckets: Positive switching balance above +0.2; Mixed from -0.2 through +0.2;
Negative switching balance from -0.5 to below -0.2; Strongly negative below -0.5;
Too few reports below 20 total eligible switch reports. Bucketing uses the
unrounded score. Outside apps have no eligible reports and a null score.

Skype's outgoing reports are flagged as forced moves only from **2025-02**
onward; the rule overrides the old blanket flag on earlier reports. Other
configured shutdown exclusions remain in effect.

## Uber markets and review counts

Ambiguous `Uber` endpoints become `Uber (Rides)` for ride counterparts (Lyft,
Bolt, DiDi, inDrive, Waymo, Careem, etc.) and `Uber Eats` for delivery counterparts
(DoorDash, Grubhub, Instacart, Spark Driver, etc.). Uber's own reviews follow the
competitor in that pair. Normalization is shared by corrections, stats, and
export; unknown switch-report counterparts fail explicitly rather than guessing.
Both markets inherit dataset membership from the pooled Uber corpus.

For review totals/ratings, a pooled Uber review is assigned only when its
extracted competitor mentions identify one market. Reviews identifying both
markets, or neither, are left unassigned and counted in stats metadata. The two
market nodes never duplicate the pooled review total. In `edges_monthly.csv`,
review-volume normalization still uses the original pooled corpus; the new
`reviewed_app_volume_app` field identifies that denominator.

## Compact network data

- `nodes`: stable IDs, category, observed membership, review count and monthly
  counts, review-count definition, and copied all-time/yearly balance objects.
- `edges`: source/target IDs, month, review category, kind, switch-report count,
  summed weight, and reason counts. Rebuilt from eligible rows in `edges.csv`.
- `pairs`: up to three real excerpts per directed pair, stored once with review
  ID, original category, reviewed market/app, store, and month. Year/category
  filters never display an excerpt from another period/category. Review text
  remains a source quotation, not generated product wording.

Outside-app switch reports remain visible context and appear in the directional
lists, but are excluded from balance. The UI shows the eligible in/out count and
definition next to each balance badge, and uses “switch reports” throughout.

Output must be below 2,000,000 bytes. If needed, long quote excerpts are shortened
with an ellipsis; counts and reasons are never dropped. An oversized export
preserves the previous file.

The overview shows flows with 25+ switch reports; a category shows flows with 3+.
Search reveals smaller matching flows, and app panels include every connection.
Scroll/pinch to zoom, drag the background to pan, double-click to reset. Focus
the canvas and use `+`, `-`, and `0` for keyboard zoom/reset. Category filters use
the original review category. The original page is preserved at `/classic`.

See [change_report.md](change_report.md) for the bucket changes and new top flows
from this update.
