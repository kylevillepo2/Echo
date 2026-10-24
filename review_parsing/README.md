# Unwrapathon NLP pipeline

This project turns app-store reviews into specific, review-traceable product topics. It uses local sentence embeddings and clustering to select informative reviews, an LLM to extract aspects from those samples, then aspect clustering and LLM refinement to build a topic taxonomy. Spotify is the current pilot app.

## Quickstart

Run these commands from the `review_parsing/` directory. Python 3.14 and the versions in `requirements.txt` were used for the Spotify pilot.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

Put your OpenAI API key in a local `.env` file:

```text
OPENAI_API_KEY=your-key-here
```

Run the pipeline for one app. The name must match an `app_names` value in the CSV (case insensitive). By default, the script reads `~/Downloads/app-store-reviews.csv`:

```bash
.venv/bin/python nlp/run_app_pipeline.py Spotify
```

If the CSV is elsewhere, supply its path. Quote app names that contain spaces:

```bash
.venv/bin/python nlp/run_app_pipeline.py "Your App Name" --input /path/to/app-store-reviews.csv
```

This command runs review embeddings, review clustering and sampling, aspect extraction, aspect embeddings, and aspect clustering. Aspect extraction makes **paid OpenAI API calls**. Rerun the same command to resume completed work. Results go to `pipeline-runs/<app-slug>/`; inspect `aspect-clusters/cluster_summary.csv` for cluster summaries and `aspect-clusters/aspect_clusters.parquet` for one assignment per aspect. Topic refinement is a separate stage.

## What is implemented

| Stage | Script | Main output |
| --- | --- | --- |
| Review embeddings | `nlp/generate_app_embeddings.py` | Per-app `.npy` vectors and aligned Parquet metadata |
| Review clustering and sampling | `nlp/cluster_app_reviews.py` | Cluster assignments and representative, random, and boundary samples |
| Aspect extraction | `nlp/extract_review_aspects.py` | Review aspects, behavioral signals, validation issues, and a resumable log |
| Aspect embeddings | `nlp/embed_aspects.py` | Normalized description vectors and aligned aspect metadata |
| Aspect clustering | `nlp/cluster_aspects.py` | HDBSCAN assignments, summaries, representatives, and noise aspects |
| Topic refinement | `nlp/refine_aspect_clusters.py` | Canonical topics, cluster mapping, and review-level refined aspects |

The current Step 8 CLI defaults to `--strategy global`: it sends compact profiles of all source aspect clusters in one structured LLM request when they fit, then validates coverage and verifies questionable decisions. The earlier `--strategy pairwise` remains available for comparison. `nlp/global_aspect_refinement.py` implements the global strategy.

The `.env` file and generated review data are ignored by Git. The embedding and clustering stages run locally; aspect extraction and topic refinement make paid OpenAI API calls.

## Individual stage commands

Run these commands from the `review_parsing/` directory. Replace the CSV path with your copy of `app-store-reviews.csv`.

```bash
.venv/bin/python nlp/generate_app_embeddings.py \
  --input /path/to/app-store-reviews.csv \
  --output embeddings/spotify-all --app Spotify

.venv/bin/python nlp/cluster_app_reviews.py \
  --embedding-root embeddings/spotify-all \
  --output clusters/spotify-sampled-50 --app Spotify --clusters 50

.venv/bin/python nlp/extract_review_aspects.py \
  --cluster-root clusters/spotify-sampled-50 \
  --output aspects/spotify-sampled --app Spotify \
  --batch-size 10 --concurrency 5

.venv/bin/python nlp/embed_aspects.py \
  --input aspects/spotify-sampled/spotify-2a0cb6b4/review_aspects.parquet \
  --output aspect-embeddings/spotify

.venv/bin/python nlp/cluster_aspects.py \
  --input aspect-embeddings/spotify --output aspect-clusters/spotify \
  --min-cluster-size 5 --min-samples 3 --umap-dims 10 --neighbors 15
```

Before making paid topic-refinement calls, inspect its local dry run:

```bash
.venv/bin/python nlp/refine_aspect_clusters.py \
  --strategy global --input aspect-clusters/spotify \
  --output refined-topics/spotify-global --dry-run
```

The dry run writes `dry_run_review.md` and `dry_run_report.json` to the output folder. To run the API stage, repeat the command without `--dry-run` and add `--model gpt-6.1-sol`. If interrupted, rerun with `--resume`. Use a **new output folder** after changing source data, model, or prompt version; checkpoint configuration is intentionally strict.

## Inspect results

The completed Spotify run has a readable topic list at `refined-topics/spotify-global-v3/topic_catalog.md` and a spreadsheet-ready `topic_catalog.csv`. Future global runs create both files automatically. Counts in the catalog are distinct sampled reviews, not estimates for all Spotify reviews. Topics marked `needs_review` and source clusters needing a split still require inspection.

`canonical_topics.json` contains the machine-readable names, definitions, parent categories, relevance status, and source aspect-cluster IDs. `cluster_mapping.parquet` maps original aspect clusters to topics. `refined_aspects.parquet` has one row per extracted aspect and retains the original review ID, text, date, app, polarity, sample role, and random inclusion probability. `refinement_report.json` summarizes coverage, split/review flags, API usage, and estimated cost.

## Statistical guardrails

- The extractor processes **sampled reviews**, not every review in the app embedding set.
- Multiple aspects from one review can map to one topic. Downstream review counts must deduplicate by `(review_key, topic_id)`.
- Only random-role samples with known `random_inclusion_probability` support population prevalence estimates. Representative and boundary examples are for discovery and inspection.
- Counts of extracted aspects or sampled reviews are not counts of affected users. Weighted aggregation and trend analysis are future work.
- HDBSCAN noise, excluded topics, and clusters marked for review or splitting remain in the exported row-level data.

## Tests and handoff

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest discover -s tests -q
```

See [CONTEXT.md](CONTEXT.md) for the current Spotify artifact paths, known limitations, and agent handoff notes.
