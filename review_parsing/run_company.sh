#!/usr/bin/env bash
set -euo pipefail

FIXED_COMMIT="f6d8f0c763c61972dae0171f58b75b21ea804e21"
DEFAULT_INPUT="/Users/test/Downloads/Unwrap/ToUse/app-store-feedback-cleanedup.csv"
EXTERNAL_ENV="/Users/test/Documents/ChatGPT/unwrap hackathon/.env"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="$SCRIPT_DIR/.venv/bin/python"
CURRENT_STAGE="initialization"
MODE=""
APP_REQUESTED=""
INPUT="$DEFAULT_INPUT"
RUN_ROOT=""
DATE_TAG="$(date +%Y%m%d)"
RUN_ROOT_OVERRIDDEN=0

usage() {
  cat <<'EOF'
Usage:
  ./run_company.sh "Exact App Label" --plan [--input PATH] [--run-root PATH] [--date-tag TAG]
  ./run_company.sh "Exact App Label" --paid [--input PATH] [--run-root PATH] [--date-tag TAG]

Modes:
  --plan   Validate and print the complete workflow without starting it or calling an API.
  --paid   Run/resume the complete local and paid workflow.

No work is performed unless exactly one mode is supplied.
EOF
}

print_cmd() {
  printf '  '
  printf '%q ' "$@"
  printf '\n'
}

die() {
  printf 'Error: %s\n' "$*" >&2
  exit 2
}

if [[ $# -eq 0 ]]; then
  usage
  exit 2
fi
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
  usage
  exit 0
fi

APP_REQUESTED="$1"
shift
while [[ $# -gt 0 ]]; do
  case "$1" in
    --plan|--paid)
      [[ -z "$MODE" ]] || die "choose exactly one of --plan or --paid"
      MODE="${1#--}"
      shift
      ;;
    --input)
      [[ $# -ge 2 ]] || die "--input requires a path"
      INPUT="$2"
      shift 2
      ;;
    --run-root)
      [[ $# -ge 2 ]] || die "--run-root requires a path"
      RUN_ROOT="$2"
      RUN_ROOT_OVERRIDDEN=1
      shift 2
      ;;
    --date-tag)
      [[ $# -ge 2 ]] || die "--date-tag requires a value"
      DATE_TAG="$2"
      shift 2
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      die "unknown option: $1"
      ;;
  esac
done
[[ -n "$MODE" ]] || {
  usage
  exit 2
}
[[ -n "$APP_REQUESTED" ]] || die "app label cannot be empty"
[[ "$APP_REQUESTED" != *$'\n'* && "$APP_REQUESTED" != *$'\t'* ]] || die "app label cannot contain tabs or newlines"
[[ "$DATE_TAG" =~ ^[A-Za-z0-9._-]+$ ]] || die "--date-tag may contain only letters, numbers, dot, underscore, or hyphen"
[[ -x "$PY" ]] || die "missing pipeline environment: $PY"
"$PY" - <<'PY'
import importlib.util
import sys
required = ("numpy", "pyarrow", "sklearn", "sentence_transformers", "umap", "openai", "pydantic")
missing = [name for name in required if importlib.util.find_spec(name) is None]
if missing:
    raise SystemExit("pipeline environment is missing: " + ", ".join(missing))
if sys.version_info < (3, 14):
    raise SystemExit(f"pipeline environment must use Python 3.14+, found {sys.version.split()[0]}")
PY

INPUT="$("$PY" - "$INPUT" <<'PY'
from pathlib import Path
import sys
print(Path(sys.argv[1]).expanduser().resolve())
PY
)"
[[ -f "$INPUT" ]] || die "input CSV not found: $INPUT"

CORE_FILES=(
  requirements.txt
  nlp/generate_app_embeddings.py
  nlp/cluster_app_reviews.py
  nlp/extract_review_aspects.py
  nlp/embed_aspects.py
  nlp/cluster_aspects.py
  nlp/refine_aspect_clusters.py
  nlp/global_aspect_refinement.py
)
git -C "$SCRIPT_DIR" cat-file -e "$FIXED_COMMIT^{commit}" 2>/dev/null ||
  die "fixed workflow commit is unavailable: $FIXED_COMMIT"
git -C "$SCRIPT_DIR" diff --quiet "$FIXED_COMMIT" HEAD -- "${CORE_FILES[@]}" ||
  die "authoritative workflow files differ from fixed commit $FIXED_COMMIT"
git -C "$SCRIPT_DIR" diff --quiet -- "${CORE_FILES[@]}" ||
  die "authoritative workflow files have uncommitted changes"
CHECKOUT_SHA="$(git -C "$SCRIPT_DIR" rev-parse HEAD)"

CURRENT_STAGE="CSV app validation"
POPULATION_TSV="$("$PY" - "$INPUT" "$APP_REQUESTED" <<'PY'
import csv
import json
import sys
from collections import Counter
from pathlib import Path

path = Path(sys.argv[1])
wanted = sys.argv[2].casefold()
labels = Counter()
languages = Counter()
eligible_english = 0
dates = []
with path.open("r", encoding="utf-8-sig", newline="") as raw:
    reader = csv.DictReader((line.replace("\x00", "") for line in raw))
    required = {"app_names", "full_text", "language_status", "feedback_date"}
    missing = required - set(reader.fieldnames or [])
    if missing:
        raise SystemExit("missing CSV columns: " + ", ".join(sorted(missing)))
    for row in reader:
        try:
            apps = json.loads(row.get("app_names") or "[]")
        except json.JSONDecodeError as exc:
            raise SystemExit(f"invalid app_names JSON: {exc}")
        matches = [str(app) for app in apps if str(app).casefold() == wanted]
        for label in matches:
            labels[label] += 1
            status = (row.get("language_status") or "").strip().casefold() or "<blank>"
            languages[status] += 1
            if status == "english" and (row.get("full_text") or "").strip():
                eligible_english += 1
            date = (row.get("feedback_date") or "").strip()
            if date:
                dates.append(date)
if len(labels) != 1:
    found = ", ".join(f"{name!r} ({count})" for name, count in sorted(labels.items())) or "none"
    raise SystemExit(f"expected exactly one case-insensitive app label; found {found}")
label, total = next(iter(labels.items()))
if "\t" in label or "\n" in label:
    raise SystemExit("matched app label contains unsupported whitespace")
english = languages.get("english", 0)
unknown = languages.get("unknown", 0)
other = total - english - unknown
if eligible_english < 1:
    raise SystemExit("matched app has no eligible English reviews")
if not dates:
    raise SystemExit("matched app has no feedback dates")
print("\t".join(map(str, (
    label, total, english, unknown, other, eligible_english, min(dates), max(dates)
))))
PY
)"
IFS=$'\t' read -r APP TOTAL_ROWS ENGLISH_ROWS UNKNOWN_ROWS OTHER_ROWS ELIGIBLE_ROWS DATE_MIN DATE_MAX <<< "$POPULATION_TSV"

SAFE_APP="$("$PY" - "$APP" <<'PY'
import re
import sys
safe = re.sub(r"[^a-z0-9]+", "-", sys.argv[1].casefold()).strip("-") or "app"
print(safe)
PY
)"
PLANNED_SLUG="$("$PY" - "$SCRIPT_DIR/nlp" "$APP" <<'PY'
import sys
sys.path.insert(0, sys.argv[1])
from generate_app_embeddings import slugify
print(slugify(sys.argv[2]))
PY
)"
if [[ "$RUN_ROOT_OVERRIDDEN" -eq 0 ]]; then
  RUN_ROOT="$SCRIPT_DIR/pipeline-runs/${SAFE_APP}-english-full-${DATE_TAG}"
fi
RUN_ROOT="$("$PY" - "$RUN_ROOT" <<'PY'
from pathlib import Path
import sys
print(Path(sys.argv[1]).expanduser().resolve())
PY
)"
SOURCE_SHA="$(shasum -a 256 "$INPUT" | awk '{print $1}')"

printf 'App label: %s\n' "$APP"
printf 'Workflow: fixed content %s (checkout %s)\n' "$FIXED_COMMIT" "$CHECKOUT_SHA"
printf 'Population: total=%s english=%s unknown=%s other=%s eligible_english=%s\n' \
  "$TOTAL_ROWS" "$ENGLISH_ROWS" "$UNKNOWN_ROWS" "$OTHER_ROWS" "$ELIGIBLE_ROWS"
printf 'Date range: %s to %s\n' "$DATE_MIN" "$DATE_MAX"
printf 'Input SHA-256: %s\n' "$SOURCE_SHA"
printf 'Run root: %s\n' "$RUN_ROOT"
printf 'Source-generated slug: %s\n' "$PLANNED_SLUG"

EMBED_ROOT="$RUN_ROOT/review-embeddings"
REVIEW_CLUSTER_ROOT="$RUN_ROOT/review-clusters"
ASPECT_ROOT="$RUN_ROOT/aspects"
ASPECT_EMBED_ROOT="$RUN_ROOT/aspect-embeddings"
ASPECT_CLUSTER_ROOT="$RUN_ROOT/aspect-clusters"
REFINE_ROOT="$RUN_ROOT/refined-topics"

EMBED_CMD=(
  "$PY" "$SCRIPT_DIR/nlp/generate_app_embeddings.py"
  --input "$INPUT" --output "$EMBED_ROOT" --app "$APP"
  --model sentence-transformers/all-MiniLM-L6-v2 --batch-size 64 --shard-size 5000
)
REVIEW_CLUSTER_CMD=(
  "$PY" "$SCRIPT_DIR/nlp/cluster_app_reviews.py"
  --embedding-root "$EMBED_ROOT" --output "$REVIEW_CLUSTER_ROOT" --app "$APP"
  --clusters 50 --train-size 30000 --kmeans-batch-size 2048
  --assign-batch-size 2048 --max-iter 100 --representatives 5
  --random-per-cluster 30 --boundary-per-cluster 5 --seed 42
)
EXTRACT_CMD_BASE=(
  "$PY" "$SCRIPT_DIR/nlp/extract_review_aspects.py"
  --cluster-root "$REVIEW_CLUSTER_ROOT" --output "$ASPECT_ROOT" --app "$APP"
  --model gpt-4o-mini --batch-size 8 --concurrency 5
  --max-retry-seconds 120 --max-chars 2500
  --sample-types random,representative,boundary --retries 3
)
ASPECT_EMBED_CMD=(
  "$PY" "$SCRIPT_DIR/nlp/embed_aspects.py"
  --input "$ASPECT_ROOT/$PLANNED_SLUG/review_aspects.parquet" --output "$ASPECT_EMBED_ROOT"
  --model sentence-transformers/all-MiniLM-L6-v2
)
ASPECT_CLUSTER_CMD=(
  "$PY" "$SCRIPT_DIR/nlp/cluster_aspects.py"
  --input "$ASPECT_EMBED_ROOT" --output "$ASPECT_CLUSTER_ROOT"
  --min-cluster-size 5 --min-samples 3 --umap-dims 10 --neighbors 15
  --representatives 5 --random-state 42
)
REFINE_CMD_BASE=(
  "$PY" "$SCRIPT_DIR/nlp/refine_aspect_clusters.py"
  --strategy global --input "$ASPECT_CLUSTER_ROOT" --output "$REFINE_ROOT"
  --model gpt-6.1-sol --concurrency 5
  --similarity-threshold 0.72 --noise-threshold 0.70
  --duplicate-threshold 0.83 --review-threshold 0.86 --neighbors 7
  --max-repair-attempts 2 --max-input-tokens 180000 --max-output-tokens 64000
  --retries 3 --input-cost-per-million 2.0 --output-cost-per-million 10.0
)

if [[ "$MODE" == "plan" ]]; then
  printf '\nPlan only: no output directory was created and no API call was made.\n'
  printf '1. Full English review embeddings:\n'
  print_cmd "${EMBED_CMD[@]}"
  printf '2. Review clustering and sampling:\n'
  print_cmd "${REVIEW_CLUSTER_CMD[@]}"
  printf '3. Resolve the source-generated slug from review-embeddings/app_index.json.\n'
  printf '4. Full resumable aspect extraction (paid, unbounded):\n'
  print_cmd "${EXTRACT_CMD_BASE[@]}"
  printf '5. Local aspect embedding (the paid run re-resolves and verifies this slug from app_index.json):\n'
  print_cmd "${ASPECT_EMBED_CMD[@]}"
  printf '6. Local aspect clustering:\n'
  print_cmd "${ASPECT_CLUSTER_CMD[@]}"
  printf '7. Global refinement dry run, then paid refinement/resume:\n'
  print_cmd "${REFINE_CMD_BASE[@]}" --dry-run
  print_cmd "${REFINE_CMD_BASE[@]}"
  print_cmd "${REFINE_CMD_BASE[@]}" --resume
  printf '8. Structural validation and manual_review_packet.md generation.\n'
  exit 0
fi

valid_key() {
  [[ -n "${OPENAI_API_KEY:-}" &&
     "${OPENAI_API_KEY}" != "your-api-key" &&
     "${OPENAI_API_KEY}" != "sk-proj-your-full-key" &&
     "${OPENAI_API_KEY}" != "your-key-here" ]]
}

load_key() {
  set +x
  if valid_key; then
    return 0
  fi
  local env_file
  for env_file in "$SCRIPT_DIR/.env" "$EXTERNAL_ENV"; do
    if [[ -f "$env_file" ]]; then
      set -a
      # shellcheck disable=SC1090
      source "$env_file"
      set +a
      if valid_key; then
        return 0
      fi
    fi
  done
  return 1
}

CURRENT_STAGE="API key validation"
load_key || die "no valid OPENAI_API_KEY source is available; no work was started"

RESUME_CMD=(
  "$SCRIPT_DIR/run_company.sh" "$APP" --paid
  --input "$INPUT" --run-root "$RUN_ROOT" --date-tag "$DATE_TAG"
)
on_error() {
  local code=$?
  trap - ERR
  printf '\nFAILED stage: %s (exit %s)\n' "$CURRENT_STAGE" "$code" >&2
  printf 'Resume safely with:\n' >&2
  print_cmd "${RESUME_CMD[@]}" >&2
  exit "$code"
}
trap on_error ERR

CURRENT_STAGE="run-root compatibility"
CONFIG_PATH="$RUN_ROOT/company_workflow_config.json"
"$PY" - "$RUN_ROOT" "$CONFIG_PATH" "$APP" "$INPUT" "$SOURCE_SHA" "$ELIGIBLE_ROWS" <<'PY'
import json
import os
import sys
from pathlib import Path

run, config_path = Path(sys.argv[1]), Path(sys.argv[2])
source = Path(sys.argv[4])
expected = {
    "workflow": "derek-review-parsing-full-v1",
    "fixed_commit": "f6d8f0c763c61972dae0171f58b75b21ea804e21",
    "app": sys.argv[3],
    "input": str(source),
    "input_sha256": sys.argv[5],
    "input_size": source.stat().st_size,
    "input_mtime_ns": source.stat().st_mtime_ns,
    "eligible_english_rows": int(sys.argv[6]),
    "review_model": "sentence-transformers/all-MiniLM-L6-v2",
    "review_clusters": 50,
    "extraction_model": "gpt-4o-mini",
    "aspect_model": "sentence-transformers/all-MiniLM-L6-v2",
    "refinement_model": "gpt-6.1-sol",
}
if run.exists():
    if not run.is_dir():
        raise SystemExit(f"run root is not a directory: {run}")
    if config_path.exists():
        found = json.loads(config_path.read_text(encoding="utf-8"))
        if found != expected:
            raise SystemExit(f"existing run configuration mismatch: {config_path}")
    elif any(run.iterdir()):
        raise SystemExit(f"existing nonempty run lacks operator config: {run}")
else:
    run.mkdir(parents=True)
if not config_path.exists():
    temp = config_path.with_suffix(".tmp")
    temp.write_text(json.dumps(expected, indent=2), encoding="utf-8")
    os.replace(temp, config_path)
PY

CURRENT_STAGE="review embeddings"
printf '\n== Review embeddings ==\n'
print_cmd "${EMBED_CMD[@]}"
"${EMBED_CMD[@]}"

CURRENT_STAGE="embedding validation and slug resolution"
SLUG="$("$PY" - "$EMBED_ROOT" "$APP" "$ELIGIBLE_ROWS" <<'PY'
import json
import sys
from pathlib import Path
import numpy as np
import pyarrow.parquet as pq

root, app, expected_rows = Path(sys.argv[1]), sys.argv[2], int(sys.argv[3])
index = json.loads((root / "app_index.json").read_text(encoding="utf-8"))
matches = [(name, info) for name, info in index.items() if name.casefold() == app.casefold()]
if len(matches) != 1:
    raise SystemExit(f"expected one app index match, found {len(matches)}")
name, info = matches[0]
slug = info["slug"]
manifest = json.loads((root / "apps" / slug / "manifest.json").read_text(encoding="utf-8"))
if info["row_count"] != expected_rows or manifest.get("completed_rows") != expected_rows:
    raise SystemExit("embedding row count does not match eligible English population")
rows = 0
dimensions = set()
for number in range(manifest["shard_count"]):
    folder = root / "apps" / slug
    stem = f"part-{number:06d}"
    vectors = np.load(folder / f"{stem}.npy", mmap_mode="r", allow_pickle=False)
    metadata_rows = pq.ParquetFile(folder / f"{stem}.parquet").metadata.num_rows
    done = json.loads((folder / f"{stem}.done").read_text(encoding="utf-8"))
    if vectors.ndim != 2 or len(vectors) != metadata_rows or metadata_rows != done["row_count"]:
        raise SystemExit(f"embedding alignment failure: {stem}")
    if not np.isfinite(vectors).all():
        raise SystemExit(f"non-finite embedding values: {stem}")
    rows += metadata_rows
    dimensions.add(vectors.shape[1])
if rows != expected_rows or dimensions != {384}:
    raise SystemExit(f"unexpected embedding result: rows={rows}, dimensions={dimensions}")
print(slug)
PY
)"
printf 'Resolved source slug: %s\n' "$SLUG"

CURRENT_STAGE="review clustering"
REVIEW_CLUSTER_PATH="$REVIEW_CLUSTER_ROOT/$SLUG"
if [[ -e "$REVIEW_CLUSTER_PATH" ]]; then
  printf '\n== Review clustering: validating existing checkpoint ==\n'
else
  printf '\n== Review clustering ==\n'
  print_cmd "${REVIEW_CLUSTER_CMD[@]}"
  "${REVIEW_CLUSTER_CMD[@]}"
fi
"$PY" - "$REVIEW_CLUSTER_PATH" "$ELIGIBLE_ROWS" <<'PY'
import csv
import json
import sys
from pathlib import Path
import numpy as np
import pyarrow.parquet as pq

root, expected_rows = Path(sys.argv[1]), int(sys.argv[2])
required = ["centroids.npy", "cluster_summary.csv", "cluster_samples.csv",
            "cluster_samples.parquet", "run_config.json", "assignments"]
missing = [name for name in required if not (root / name).exists()]
if missing:
    raise SystemExit(f"missing review-cluster outputs: {missing}")
config = json.loads((root / "run_config.json").read_text(encoding="utf-8"))
if config.get("completed_rows") != expected_rows or config.get("clusters") != min(50, expected_rows):
    raise SystemExit("review-cluster configuration mismatch")
centroids = np.load(root / "centroids.npy", allow_pickle=False)
if centroids.shape != (min(50, expected_rows), 384) or not np.isfinite(centroids).all():
    raise SystemExit(f"invalid centroids: {centroids.shape}")
assignment_rows = sum(
    pq.ParquetFile(path).metadata.num_rows for path in (root / "assignments").glob("part-*.parquet")
)
if assignment_rows != expected_rows:
    raise SystemExit(f"assignment row mismatch: {assignment_rows}")
with (root / "cluster_summary.csv").open(newline="", encoding="utf-8") as fp:
    summary = list(csv.DictReader(fp))
if len(summary) != min(50, expected_rows) or sum(int(row["review_count"]) for row in summary) != expected_rows:
    raise SystemExit("cluster summary mismatch")
print(f"Validated review clusters: {len(summary)} clusters, {assignment_rows:,} assignments")
PY

CURRENT_STAGE="aspect extraction"
EXTRACTION_PATH="$ASPECT_ROOT/$SLUG"
EXTRACTION_COMPLETE="$("$PY" - "$EXTRACTION_PATH/summary.json" <<'PY'
import json
import sys
from pathlib import Path
path = Path(sys.argv[1])
if not path.is_file():
    print("no")
else:
    data = json.loads(path.read_text(encoding="utf-8"))
    print("yes" if data.get("processed_unique_reviews") == data.get("sampled_unique_reviews") else "no")
PY
)"
if [[ "$EXTRACTION_COMPLETE" == "yes" ]]; then
  printf '\n== Aspect extraction: complete checkpoint reused ==\n'
else
  printf '\n== Aspect extraction (paid, resumable) ==\n'
  print_cmd "${EXTRACT_CMD_BASE[@]}"
  "${EXTRACT_CMD_BASE[@]}"
fi
"$PY" - "$EXTRACTION_PATH" <<'PY'
import json
import sys
from pathlib import Path
import pyarrow.parquet as pq

root = Path(sys.argv[1])
summary = json.loads((root / "summary.json").read_text(encoding="utf-8"))
if summary["processed_unique_reviews"] != summary["sampled_unique_reviews"]:
    raise SystemExit("extraction remains incomplete; rerun the operator command to resume")
reviews = pq.read_table(root / "review_extractions.parquet").to_pylist()
aspects = pq.read_table(root / "review_aspects.parquet").to_pylist()
behaviors = pq.read_table(root / "review_behavioral_signals.parquet").to_pylist()
if len(reviews) != summary["processed_unique_reviews"] or len(aspects) != summary["aspect_rows"]:
    raise SystemExit("extraction artifact count mismatch")
bad_aspects = [
    row["review_key"] for row in aspects
    if row["evidence"] not in (row.get("text") or "") and row["evidence"] not in (row.get("title") or "")
]
bad_behaviors = [
    row["review_key"] for row in behaviors
    if row["evidence"] not in (row.get("text") or "") and row["evidence"] not in (row.get("title") or "")
]
if bad_aspects or bad_behaviors:
    raise SystemExit("accepted evidence is not an exact source substring")
print(
    "Extraction complete: "
    f"{summary['processed_unique_reviews']:,} reviews, {summary['aspect_rows']:,} aspects, "
    f"{summary['requests_total']:,} checkpointed requests, "
    f"{summary['input_tokens_total'] + summary['output_tokens_total']:,} checkpointed tokens"
)
PY

CURRENT_STAGE="aspect embeddings"
ASPECT_INPUT="$EXTRACTION_PATH/review_aspects.parquet"
ASPECT_EMBED_CMD[3]="$ASPECT_INPUT"
printf '\n== Aspect embeddings ==\n'
print_cmd "${ASPECT_EMBED_CMD[@]}"
"${ASPECT_EMBED_CMD[@]}"

CURRENT_STAGE="aspect clustering"
if [[ -e "$ASPECT_CLUSTER_ROOT" ]]; then
  printf '\n== Aspect clustering: validating existing checkpoint ==\n'
else
  printf '\n== Aspect clustering ==\n'
  print_cmd "${ASPECT_CLUSTER_CMD[@]}"
  "${ASPECT_CLUSTER_CMD[@]}"
fi
"$PY" - "$ASPECT_INPUT" "$ASPECT_EMBED_ROOT" "$ASPECT_CLUSTER_ROOT" <<'PY'
import json
import sys
from pathlib import Path
import pyarrow.parquet as pq

source, embeddings, root = map(Path, sys.argv[1:])
manifest = json.loads((embeddings / "manifest.json").read_text(encoding="utf-8"))
if manifest.get("status") != "complete":
    raise SystemExit("aspect embeddings are incomplete")
required = ["aspect_clusters.parquet", "cluster_summary.csv", "representative_aspects.csv",
            "representative_aspects.parquet", "noise_aspects.parquet", "run_config.json"]
missing = [name for name in required if not (root / name).is_file()]
if missing:
    raise SystemExit(f"missing aspect-cluster outputs: {missing}")
source_rows = pq.read_table(source).to_pylist()
cluster_rows = pq.read_table(root / "aspect_clusters.parquet").to_pylist()
source_ids = {f"{row['review_key']}:{row['aspect_index']}" for row in source_rows}
cluster_ids = {row["aspect_id"] for row in cluster_rows}
if len(source_rows) != manifest["aspect_count"] or source_ids != cluster_ids:
    raise SystemExit("aspect mapping is incomplete")
print(f"Validated aspect mapping: {len(cluster_rows):,} aspects")
PY

CURRENT_STAGE="global refinement"
REFINEMENT_COMPLETE="$("$PY" - "$REFINE_ROOT/refinement_report.json" <<'PY'
import json
import sys
from pathlib import Path
path = Path(sys.argv[1])
print("yes" if path.is_file() and json.loads(path.read_text(encoding="utf-8")).get("strategy") == "global" else "no")
PY
)"
if [[ "$REFINEMENT_COMPLETE" == "yes" ]]; then
  printf '\n== Global refinement: complete checkpoint reused ==\n'
elif [[ -f "$REFINE_ROOT/run_config.json" ]]; then
  printf '\n== Global refinement: resuming paid checkpoint ==\n'
  print_cmd "${REFINE_CMD_BASE[@]}" --resume
  "${REFINE_CMD_BASE[@]}" --resume
else
  printf '\n== Global refinement dry run ==\n'
  print_cmd "${REFINE_CMD_BASE[@]}" --dry-run
  "${REFINE_CMD_BASE[@]}" --dry-run
  printf '\n== Global refinement (paid) ==\n'
  print_cmd "${REFINE_CMD_BASE[@]}"
  "${REFINE_CMD_BASE[@]}"
fi

CURRENT_STAGE="final validation"
"$PY" - "$RUN_ROOT" "$SLUG" <<'PY'
import json
import sys
from pathlib import Path
import pyarrow.parquet as pq

run, slug = Path(sys.argv[1]), sys.argv[2]
embedding = json.loads((run / "review-embeddings/apps" / slug / "manifest.json").read_text())
review_config = json.loads((run / "review-clusters" / slug / "run_config.json").read_text())
summary = json.loads((run / "aspects" / slug / "summary.json").read_text())
aspect_manifest = json.loads((run / "aspect-embeddings/manifest.json").read_text())
if embedding["completed_rows"] != embedding["row_count"]:
    raise SystemExit("review embeddings incomplete")
if review_config["completed_rows"] != embedding["row_count"]:
    raise SystemExit("review clusters incomplete")
if summary["processed_unique_reviews"] != summary["sampled_unique_reviews"]:
    raise SystemExit("extraction incomplete")
if aspect_manifest.get("status") != "complete" or aspect_manifest["aspect_count"] != summary["aspect_rows"]:
    raise SystemExit("aspect embeddings incomplete")
refined = run / "refined-topics"
required = ["run_config.json", "checkpoint.jsonl", "canonical_topics.json",
            "cluster_mapping.parquet", "refined_aspects.parquet", "refinement_report.json",
            "global_refinement_response.json", "validation_report.json",
            "topic_catalog.md", "topic_catalog.csv", "cluster_profiles.json"]
missing = [name for name in required if not (refined / name).is_file()]
if missing:
    raise SystemExit(f"missing refinement outputs: {missing}")
report = json.loads((refined / "refinement_report.json").read_text())
validation = json.loads((refined / "validation_report.json").read_text())
source_rows = pq.read_table(run / "aspect-clusters/aspect_clusters.parquet").to_pylist()
refined_rows = pq.read_table(refined / "refined_aspects.parquet").to_pylist()
if validation.get("coverage_errors"):
    raise SystemExit(f"refinement coverage errors: {validation['coverage_errors']}")
if {row["aspect_id"] for row in source_rows} != {row["aspect_id"] for row in refined_rows}:
    raise SystemExit("refined aspect mapping is incomplete")
print(
    "Final gates PASS: "
    f"{report['canonical_topics']} topics, {report['api_requests']} refinement requests, "
    f"{report['input_tokens'] + report['output_tokens']:,} refinement tokens, "
    f"estimated refinement cost ${report['estimated_api_cost_usd']:.6f}"
)
PY

CURRENT_STAGE="manual review packet"
"$PY" - "$RUN_ROOT" "$APP" <<'PY'
import csv
import json
import sys
from pathlib import Path
import pyarrow.parquet as pq

run, app = Path(sys.argv[1]), sys.argv[2]
refined = run / "refined-topics"
canonical = json.loads((refined / "canonical_topics.json").read_text(encoding="utf-8"))
rows = pq.read_table(run / "aspect-clusters/aspect_clusters.parquet").to_pylist()
by_cluster = {}
for row in rows:
    by_cluster.setdefault(int(row["aspect_cluster_id"]), []).append(row)
with (run / "aspect-clusters/cluster_summary.csv").open(newline="", encoding="utf-8") as fp:
    summaries = {int(row["aspect_cluster_id"]): row for row in csv.DictReader(fp)}

def clean(value):
    return " ".join(str(value or "").split()).replace("|", "\\|")

flagged = (
    [("split", item) for item in canonical.get("clusters_needing_split", [])]
    + [("review", item) for item in canonical.get("clusters_needing_review", [])]
)
lines = [
    f"# {app} semantic review packet", "",
    "Read-only handoff from validated artifacts. Recommendations are **agent analysis, not human adjudication**.",
    "Counts are sampled-review or extracted-aspect counts, not population prevalence.", "",
    "## Flagged clusters", "",
    f"- {len(canonical.get('clusters_needing_split', []))} need split.",
    f"- {len(canonical.get('clusters_needing_review', []))} need review.", "",
]
for kind, item in flagged:
    cluster_id = int(item["cluster_id"])
    summary = summaries[cluster_id]
    lines.extend([
        f"## Cluster {cluster_id} — needs {kind}", "",
        f"- **Working label/category:** “{clean(summary['example_description'])}”; `{summary['top_category']}`.",
        f"- **Size:** {summary['aspect_observations']} aspects from {summary['unique_reviews']} sampled reviews.",
        f"- **Why:** {clean(item['reason'])}",
        "- **Representative exact evidence:**",
    ])
    seen = set()
    picked = []
    for row in sorted(
        by_cluster[cluster_id],
        key=lambda value: float(value.get("cluster_membership_strength") or 0),
        reverse=True,
    ):
        description = clean(row.get("description")).casefold()
        if description in seen:
            continue
        seen.add(description)
        picked.append(row)
        if len(picked) == 4:
            break
    for row in picked:
        lines.append(
            f"  - `{row['aspect_id']}` / review `{row['review_key']}`: "
            f"“{clean(row.get('evidence'))}” — {clean(row.get('description'))}."
        )
    if kind == "split":
        lines.extend([
            "- **Agent recommendation:** approve a member-level split in principle; do not map the cluster wholesale.",
            "- **Concrete candidate topics:**",
        ])
        for topic in item.get("suggested_subtopics", []):
            lines.append(f"  1. **{clean(topic)}**")
        lines.append(
            "  Map only members whose exact evidence supports a candidate; route outliers to existing topics or retain `needs_review`."
        )
    else:
        lines.extend([
            "- **Agent recommendation:** do not create a broad topic; route supported members individually and retain ambiguous members as `needs_review`.",
            "- **Concrete mapping:** leave the source cluster unmapped until member-level human adjudication.",
        ])
    lines.append("")

with (refined / "topic_catalog.csv").open(newline="", encoding="utf-8") as fp:
    catalog = list(csv.DictReader(fp))
top = sorted(catalog, key=lambda row: (-int(row["unique_sampled_reviews"]), row["topic_id"]))[:10]
lines.extend([
    "## Ten largest artifact-supported findings", "",
    "Distinct sampled-review counts; reviews may appear in multiple topics and counts are not population prevalence.", "",
])
for number, row in enumerate(top, 1):
    lines.append(
        f"{number}. **{clean(row['canonical_name'])}** — "
        f"{row['unique_sampled_reviews']} sampled reviews; `{row['relevance_status']}`."
    )
lines.extend([
    "", "## Human review checklist", "",
    "Confirm every mapping against exact evidence, preserve provenance and sampling fields, and recompute catalogs after approved changes.",
])
(refined / "manual_review_packet.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
print(f"Manual review packet: {refined / 'manual_review_packet.md'}")
PY

CURRENT_STAGE="completion summary"
"$PY" - "$RUN_ROOT" "$SLUG" <<'PY'
import json
import sys
from pathlib import Path
run, slug = Path(sys.argv[1]), sys.argv[2]
summary = json.loads((run / "aspects" / slug / "summary.json").read_text())
report = json.loads((run / "refined-topics/refinement_report.json").read_text())
print("\nCOMPLETE")
print(f"Reviews extracted: {summary['processed_unique_reviews']:,}")
print(f"Aspects: {summary['aspect_rows']:,}")
print(f"Extraction checkpoint tokens: {summary['input_tokens_total'] + summary['output_tokens_total']:,}")
print(f"Canonical topics: {report['canonical_topics']:,}")
print(f"Refinement tokens: {report['input_tokens'] + report['output_tokens']:,}")
print(f"Estimated refinement cost: ${report['estimated_api_cost_usd']:.6f}")
print(f"Topic catalog: {run / 'refined-topics/topic_catalog.md'}")
print(f"Manual review: {run / 'refined-topics/manual_review_packet.md'}")
PY

