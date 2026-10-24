# Agent handoff: Unwrapathon NLP pipeline

## Objective and scope

Build a sampling-aware pipeline that turns app reviews into specific product topics with review-level provenance. Spotify is the pilot. Run commands from `review_parsing/`. The source data is `app-store-reviews.csv`, outside this repository; generated data and API checkpoints are local artifacts and are ignored by Git. The snapshot below describes artifacts on the original developer's machine; these files are not included in this branch.

The intended downstream use is a topic taxonomy for review classification, app comparison, and time trends. Weighted prevalence and the application backend are **not implemented**. Do not infer population prevalence from extracted-aspect or topic-cluster counts.

## Current Spotify snapshot (2026-10-24)

| Artifact | Path | Status |
| --- | --- | --- |
| Review embeddings | `embeddings/spotify-all/` | 101,123 Spotify reviews, 21 shards |
| Review clusters and samples | `clusters/spotify-sampled-50/spotify-2a0cb6b4/` | 50 clusters; 1,987 unique sampled reviews |
| Aspect extraction | `aspects/spotify-test-50/spotify-2a0cb6b4/` | 1,894 of 1,987 sampled reviews processed; 1,575 aspects; 93 reviews still pending |
| Aspect embeddings | `aspect-embeddings/spotify/` | 1,575 normalized 384-dimensional vectors |
| Aspect clusters | `aspect-clusters/spotify/` | 109 non-noise clusters; 192 noise aspects |
| Pairwise refinement | `refined-topics/spotify/` | 91 topics; 18 merged clusters; 37 noise aspects mapped; baseline for comparison |
| Global refinement v1 | `refined-topics/spotify-global/` | Completed but poor: 94 clusters marked `needs_split`; do not use as the main taxonomy |
| Global refinement v3 | `refined-topics/spotify-global-v3/` | Completed: 80 topics, 9 split clusters, 2 review clusters; 1,265 of 1,575 aspects have a topic ID |

The extraction folder name `spotify-test-50` is historical: the run was extended to 1,894 reviews. Its existing aspect embeddings and later stages reflect the current 1,575-aspect snapshot. Finishing the remaining 93 extractions changes the Parquet source hash, so create new aspect-embedding and downstream output folders rather than resuming those old shards against changed input.

The global v3 result needs **manual semantic review** before being treated as a stable classification taxonomy. In particular, inspect Advertising, Pricing, Playback, Shuffle, Queue, and any `needs_split`/`needs_review` clusters. The original pairwise output remains available for side-by-side comparison. The global v3 report records 32 API calls and approximately $0.27 in estimated token cost; the estimate may exclude failed, uncheckpointed responses.

## Code map

- `nlp/run_app_pipeline.py`: Single-app entry point for Steps 2–7. It chains the five existing stage CLIs, checks output compatibility, and resumes completed work. It does not run topic refinement.
- `nlp/generate_app_embeddings.py`: Filters and partitions input CSV by app, encodes full review text, writes aligned vector/metadata shards with completion markers.
- `nlp/cluster_app_reviews.py`: Fits 50 review clusters on a uniform training sample, assigns all reviews, and selects representative, random, and boundary reviews. `clusters/spotify-sampled-50/.../run_config.json` records counts and parameters.
- `nlp/extract_review_aspects.py`: Async Responses API extraction with strict schema, behavioral signals, exact evidence checks, rate limiting, and JSONL checkpointing. Default model is `gpt-4o-mini`. Version/config checks protect resume.
- `nlp/embed_aspects.py`: Encodes only aspect descriptions, retaining all source aspect/review metadata in aligned Parquet shards. Input file hash protects resume.
- `nlp/cluster_aspects.py`: UMAP to 10 dimensions, then scikit-learn HDBSCAN; writes one assignment per aspect plus representatives and noise.
- `nlp/refine_aspect_clusters.py`: CLI and preserved pairwise strategy (`--strategy pairwise`). Global is the default. Shared Pydantic schemas, checkpoint runner, and output helpers live here.
- `nlp/global_aspect_refinement.py`: One global structured LLM proposal over all compact cluster profiles when feasible; deterministic coverage checks and targeted repair/verification; noise assignment; final row-level export.
- `nlp/evaluate_aspect_extraction.py`: Manual QA worksheet generator for extraction outputs.
- `tests/`: Offline unit and mocked-API regression tests. They make no paid calls.

## Stable output and data invariants

1. A `.npy` shard row aligns with the same row in its matching `.parquet` shard.
2. `aspect_id` is `review_key:aspect_index`. `review_key` and original review `cluster_id` connect topics back to sampled reviews.
3. `aspect_clusters.parquet` is authoritative for original Step 7 aspects. `refined_aspects.parquet` must retain exactly one row for every source aspect. Clusters needing split or review and noise aspects stay in that file with an explicit status.
4. Keep product category, polarity, and behavioral intent separate. A shared feature word does not make two failure modes equivalent. Positive and negative experiences remain distinguishable in row-level metadata.
5. Preserve `sample_roles` and `random_inclusion_probability`. For prevalence, use probability-sampled reviews only and deduplicate by `(review_key, topic_id)` before weighting. Do not treat cluster sizes as estimated users.
6. Checkpoint files are version and source aware. Use `--resume` only with identical settings and input. Use a fresh output directory after code/prompt/source changes.

## Current Step 8 strategy and review points

Global v3 uses `gpt-6.1-sol` by default. The 109 compact Spotify profiles fit in one request (dry-run input estimate around 19,000 tokens). A valid global response must account for every non-noise cluster exactly once. The v3 validator rejects proposals that mark more than 20% of clusters for splitting or map fewer than 75% of non-noise aspects to topics; it asks the model for a targeted correction before failing. It does not force a bad result into the final files.

`refined-topics/spotify-global-v3/topic_catalog.md` is the readable final topic list, grouped by parent category; `topic_catalog.csv` is the spreadsheet-ready version. The per-topic review counts are for sampled reviews only. `dry_run_review.md` lists local similarity suggestions. These are **not approved merges**: for example, queue playback and queue removal can have similar embeddings while remaining distinct issues. `validation_report.json` records global verification and near-duplicate checks. `global_refinement_response.json` preserves the model's original proposal. `refinement_report.json` gives the final counts.

## Useful commands

```bash
# Current global result summary
cat refined-topics/spotify-global-v3/refinement_report.json

# Inspect current taxonomy
.venv/bin/python - <<'PY'
import json
from pathlib import Path
data = json.loads(Path('refined-topics/spotify-global-v3/canonical_topics.json').read_text())
for topic in data['topics']:
    print(topic['topic_id'], topic['canonical_name'], topic['relevance_status'])
PY

# Run all offline tests
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest discover -s tests -q
```

To finish extraction, rerun `nlp/extract_review_aspects.py` with the existing `--output aspects/spotify-test-50`; it resumes completed review keys. Then regenerate Step 6 onward into **new** output folders. Do not start paid extraction or refinement without a user request. Never read or commit the real `.env` key.

## Next work

1. Manually compare global v3 and pairwise topics on sampled descriptions; correct any merged topics that mix distinct failures, and inspect the nine split clusters.
2. Decide whether to finish the 93 pending sampled-review extractions and rebuild downstream artifacts from the larger aspect set.
3. Implement review-level topic classification and weighted aggregation with uncertainty estimates. Monthly trends require careful handling of the review sample design and dates.
4. Expand beyond Spotify only after the pilot's extraction and taxonomy quality are validated.
