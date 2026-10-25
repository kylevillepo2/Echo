# Topic insight exports

Vite discovers every `topic-insights-v1` app JSON in `static/data/insights/` and generates a lightweight, ignored `catalog.json` before dev/build. The browser fetches each app JSON **on demand**. The multi-megabyte exports are not imported into the main JavaScript bundle. App responses are cached for the session, with loading, error and retry states.

To add coverage, drop a new app file in that directory. Vite watches additions, removals and changes during development and regenerates the catalog. The app must already exist in the graph; topic files do not define graph categories or relationships. Most apps match by ID or normalized name. Legacy map IDs (`bofa`, `capital-one`, `credit-karma`) resolve to their canonical export IDs in `src/lib/data/insights.ts`.

The aggregation report may cover only the latest pipeline run. It supplies optional validation status, not the discovery list. Report results are used only when the app identity, export timestamp and counts match; other files have an unknown report status, not a failed or verified status. All app files are independently schema/count-checked. The report and input app files are never rewritten by the catalog generator.

## Current integration

- All supplied apps use exported review totals, star distributions, topic counts/shares, monthly coverage and representative snippets.
- Their Overview and Reviews panels do not substitute demo themes, synthetic reviews, rating trends or install correlations for missing export fields.
- App-specific topic IDs are namespaced by app. In Overview, positive topics have an average rating of at least 4★, negative topics below 3★, and mixed topics 3–under 4★. Topics without rated reviews are separate. This is an explicit rating-based grouping, not sentiment inferred from topic names or cosine similarity. Topic identities remain app-scoped.
- Representative reviews are deduplicated by `review_key`, retaining all topic tags. Individual dates, star ratings, full review text and sentiment are not invented.
- Topic share denominators include untagged reviews. Topics can overlap, so topic counts/shares must not be summed as distinct app reviews.
- Partial and insufficient-volume months are marked. Trend labels come from the export's complete-month comparison, not the last partial month.
- Cosine similarity is not displayed as sentiment, confidence or a probability. Aggregation validation is not human verification of topic assignments.
- App nodes use catalog review totals. Demo reception rings/scores are suppressed for exported apps because this schema does not supply a reception score. Other map topology and uncovered app analytics retain their existing demo/API behavior.
- Switching flows are separate data; topic insight files do not create flow arrows. Downloads and install-impact analytics are omitted from exported app overviews until supplied by a compatible analytics source.

The parser checks app identity, schema version, numeric values, unique app-scoped topic IDs, and reconciliation of review, rating and monthly totals. A broken covered export shows an explicit error and retry action instead of reverting to demo analytics.

Run the adapter checks with:

```sh
node --test scripts/insights.test.mjs
```
