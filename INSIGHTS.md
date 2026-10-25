# Topic insight exports

The app reads `static/data/insights/aggregation_validation_report.json` as its catalog, then fetches each listed app JSON **on demand**. The multi-megabyte exports are not imported into the main JavaScript bundle. App responses are cached for the session, with loading, error and retry states.

To add coverage, publish the new `topic-insights-v1` app file and update the aggregation report. The app must already exist in the graph; topic files do not define graph categories or relationships. The report's `output` field is used only for its validated JSON basename, never as a machine-local path or arbitrary URL. Most apps match by ID or normalized name. Legacy map IDs (`bofa`, `capital-one`, `credit-karma`) resolve to their canonical export IDs in `src/lib/data/insights.ts`.

## Current integration

- All supplied finance apps use exported review totals, star distributions, topic counts/shares, monthly coverage and representative snippets.
- Their Overview and Reviews panels do not substitute demo themes, synthetic reviews, rating trends or install correlations for missing export fields.
- App-specific topic IDs are namespaced by app. Topics are not merged into a shared sentiment taxonomy.
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
