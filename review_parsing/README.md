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

## Step 9A: offline semantic similarity tagging

### One command for the complete similarity workflow

If an app has completed topic refinement but has no similarity predictions yet:

```bash
cd "/Users/test/Documents/ChatGPT/Unwrapathon/review_parsing"
.venv/bin/python nlp/run_similarity_workflow.py "Venmo"
```

This builds local description-based topic embeddings, calibrates the threshold
on validation reviews, evaluates held-out test reviews, tags every original review
using its saved embedding, and exports a readable CSV with names, definitions,
scores, earlier LLM labels, and editable verdict/notes columns. It needs no API
key and makes no paid calls. The sentence-transformer must already be cached.

The default output folder is `<app-run>/similarity-workflow-v1/`. Open:

`description/evaluation/global_inspection_readable.csv`

The full corpus assignments are in:

`description/tagging-global/tagged_reviews.parquet`

Replace `"Venmo"` with `"Cash App"` or another app with a completed refinement run.
The workflow prints every output path. Rerun the same command to reuse verified
completed stages and resume incomplete tagging shards. Manual notes in the readable
CSV are preserved. Changed settings, source data, or implementation require a fresh
`--output` folder. An interrupted topic build/evaluation that leaves partial files
may also require a fresh output folder; original embeddings and extractions remain.

```bash
# Show the intended run without writing or loading the encoder.
.venv/bin/python nlp/run_similarity_workflow.py "Venmo" --dry-run

# Compare description and prototype methods in a separate output folder.
.venv/bin/python nlp/run_similarity_workflow.py "Venmo" --method both \
  --output pipeline-runs/venmo-english-full-20261024/similarity-comparison-v1

# Select a particular completed source run if discovery is ambiguous.
.venv/bin/python nlp/run_similarity_workflow.py "Cash App" \
  --run-root pipeline-runs/cash-app-english-full-20261024
```

Other options are `--strategy global|per_topic`, `--seed`, `--max-tags`,
`--min-support`, `--threshold-grid`, `--inspection-count`, `--batch-size`, and
`--device`. Global thresholds are calibrated separately for each app; Cash App's
0.45 threshold is not automatically reused for Venmo. Results are a provisional
semantic-similarity baseline, not human-verified complaint statistics.

### One command to combine reviews and readable tags

After similarity evaluation exists for an app, run:

```bash
cd "/Users/test/Documents/ChatGPT/Unwrapathon/review_parsing"
.venv/bin/python nlp/run_similarity_inspection.py "Cash App"
```

Replace `"Cash App"` with the exact app name, such as `"Venmo"`. The workflow
finds the app's completed run, joins `global_inspection.csv` to that same run's
`topic_catalog.csv`, and writes `global_inspection_readable.csv` beside the
inspection input. It prints the full path. Columns include review text, readable
assigned tags, assigned scores and definitions, earlier LLM labels and definitions,
extra/missed tags, and editable human verdict/notes. Raw IDs and exact scores remain.
Repeated runs retain verdicts and notes entered in the readable output.

To choose a specific run or include both representations/threshold strategies:

```bash
.venv/bin/python nlp/run_similarity_inspection.py "Cash App" \
  --run-root pipeline-runs/cash-app-english-full-20261024 \
  --method all --strategy all

# Show intended operations without writing.
.venv/bin/python nlp/run_similarity_inspection.py "Cash App" --dry-run
```

`--run-root` resolves ambiguity if several runs exist for one app. `--runs-root`
changes the directory searched for app runs; `--evaluation-dir` selects a different
evaluation folder; `--output-dir` selects a different parent for readable files.
The workflow performs only the CSV merge. It does not generate predictions,
rerun the NLP pipeline, or make API calls. If an app has no similarity evaluation
yet, run `nlp/run_similarity_workflow.py "App Name"` instead.

### Build and evaluate the tagging baseline

This independent baseline assigns zero or more approved canonical topics to every
embedded review. It trains no classifier, makes no OpenAI calls, and preserves
the existing extraction/refinement outputs. Description vectors are encoded
locally using the review model (which must already be cached). Prototype vectors
reuse compatible aspect embeddings. Frontend integration and monthly aggregation
are outside this stage.

Run from `review_parsing/`. Cash App is the first completed app:

```bash
RUN=pipeline-runs/cash-app-english-full-20261024

# Build description representations; local_files_only=True prevents downloads.
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 .venv/bin/python nlp/build_topic_embeddings.py \
  --run-root "$RUN" --app "Cash App" --method description \
  --output "$RUN/topic-embeddings/description-v1"

# Build prototypes from only the training text groups.
.venv/bin/python nlp/build_topic_embeddings.py \
  --run-root "$RUN" --app "Cash App" --method prototype \
  --output "$RUN/topic-embeddings/prototype-v1"

# Tune on validation only, then score test. Repeat for prototype-v1.
.venv/bin/python nlp/evaluate_similarity_tagging.py \
  --run-root "$RUN" --app "Cash App" \
  --topic-embeddings "$RUN/topic-embeddings/description-v1" \
  --output "$RUN/similarity-evaluation/description-v1"

# Apply the evaluated global threshold to every original review.
.venv/bin/python nlp/tag_reviews_similarity.py \
  --run-root "$RUN" --app "Cash App" \
  --topic-embeddings "$RUN/topic-embeddings/description-v1" \
  --threshold-config "$RUN/similarity-evaluation/description-v1/global_thresholds.json" \
  --output "$RUN/similarity-tagging/description-global-v1" --batch-size 1024
```

The prototype evaluation uses the same command with `prototype-v1` paths. Both
evaluations write `per_topic_thresholds.json`; supply that file to the tagger to
try calibrated per-topic thresholds. Only topics with at least five positive AND
five negative validation reviews get an individual threshold; all others fall
back to the global threshold. `--min-support` changes that requirement.
Per-topic calibration is sparse and experimental for this Cash App sample.

`--threshold-grid` accepts comma-separated candidate cosine thresholds (default
0.20 through 0.80, in steps of 0.05). The global choice maximizes validation
micro-F1, with higher thresholds breaking ties. Per-topic choices maximize
validation topic F1 before the tag cap. This may not maximize capped joint F1;
the separately reported validation/test results include the cap. `--max-tags`
defaults to five. The tagger also accepts an explicit `--threshold` instead of a
configuration file, with `--max-tags` setting its cap; such thresholds are marked
unvalidated. When a configuration is supplied, its saved cap takes precedence.
There is no automatic top-topic fallback.

Topic outputs contain `topic_vectors.npy`, row-aligned `topic_metadata.parquet`,
and `config.json`. Only `keep` topics are used; topics overlapping split/review
clusters are blocked. Topic IDs are scoped to the app's taxonomy, not a shared
finance taxonomy. Never merge matching numeric topic IDs across apps.
Taxonomy version is the SHA-256 of `canonical_topics.json`. Model identifiers,
dimensions, source hashes, topic ordering, and vector validity are checked.
The historical embedding manifests do not record a model revision, so identical
model IDs/dimensions are the strongest compatibility evidence currently available;
they cannot prove that different historical model revisions were identical.

The evaluation joins the actual schema by `(data_source, feedback_id)` and
checks text equality. The sampled extractor's `review_key` contains a review
cluster ID, which does not exist in full-review embedding metadata. The tagger
preserves sampled keys and uses `<app-slug>:<source>:<feedback-id>` for other
reviews. Original metadata columns, IDs, ratings, timestamps, and full text remain
unchanged. Sentiment is retained only for matching existing aspect/topic labels;
otherwise it is `unknown`. Multiple existing polarities become `mixed`.

Evaluation splits normalized identical text together using a seeded SHA-256
60/20/20 partition: training constructs prototypes; validation tunes thresholds;
test is evaluated after calibration. Different source IDs with identical text
cannot straddle partitions. No validation/test aspect contributes to a prototype.
Prototype metadata records its exact training review keys and distinct-review
support. Topics with no training examples are omitted from prototypes and reported;
evaluation still counts their approved-topic reference labels as missed.

Reference labels remain provisional: extraction and taxonomy are machine outputs,
and the original taxonomy/clustering already saw the full sample. No independent
human labels were available for this run. Reviews with unresolved aspect labels
are excluded from metric scoring; zero-aspect reviews are included as provisional
negatives. Reported precision/recall therefore describe this restricted reference,
not unbiased accuracy on all reviews. Similarity cannot establish negation,
resolution, or a negative complaint. Do not compute complaint percentages from it.

Evaluation outputs include micro/macro precision, recall and F1, per-topic support,
zero-tag rate, average tags, threshold sweeps, exact partitions, and 120 test-review
inspection rows per strategy when available (`--inspection-count` changes this).
Inspection balances multi-topic, low-similarity, near-tie, negation-candidate,
high-star, rare-topic, and zero-prediction examples. These are heuristic inspection
groups, not automatically validated semantics. Inspect
`global_inspection.csv` and `per_topic_inspection.csv` for false positives and misses.

Tagging outputs contain one `tagged_reviews.parquet` record per input review,
including empty topic lists, plus a `tagging_report.json` with assignment counts,
top topics, cosine distribution, thresholds, source/model/taxonomy information and
runtime. Each tag stores raw cosine similarity and sentiment provenance. Cosine
similarity is not a probability. Intermediate `part-*.parquet` shards have atomic
completion records with hashes. Repeating an identical tagging command validates
and reuses completed shards, then streams the combined Parquet again. Interrupted
unmarked shards are rebuilt. Changed inputs, code, or configuration require a new
output folder. Build/evaluation commands also require fresh output folders.

To extend to another finance app, repeat these three CLIs against that app's own
completed run and exact app name (for example `Venmo`). Build and calibrate its
separate taxonomy; do not reuse Cash App thresholds or prototypes. Generated files
remain under ignored `pipeline-runs/`; only implementation and tests belong in Git.

Cash App v1 processed all 62,785 reviews using 38 approved topics. Validation chose
global thresholds 0.45 (description) and 0.55 (prototype). On 280 evaluable test
reviews, provisional micro-F1 was 0.1714 and 0.1611 respectively. Only one topic
met per-topic calibration support requirements. This is a working baseline for
comparison with a supervised approach, not a validated classifier for prevalence.
