# Company workflow operator

The reusable operator is:

`/Users/test/Documents/ChatGPT/Unwrapathon/review_parsing/run_company.sh`

Run it from `review_parsing/`:

```bash
cd "/Users/test/Documents/ChatGPT/Unwrapathon/review_parsing"

# Validate the exact CSV label, population, environment, paths, and commands.
# This creates no run directory and makes no API call.
./run_company.sh "CapCut" --plan
./run_company.sh "Remini" --plan

# Run or safely resume the complete local and paid workflow.
./run_company.sh "CapCut" --paid
./run_company.sh "Remini" --paid
```

Neither embeddings nor paid work starts unless `--paid` is explicit. A paid run uses English reviews only, performs unbounded resumable extraction, and runs paid global refinement. On failure, rerun the exact resume command printed by the script; extraction and refinement reuse their existing checkpoints and completed local stages are validated before reuse.

Defaults can be overridden with `--input PATH`, `--run-root PATH`, and `--date-tag TAG`. The default output is:

```text
pipeline-runs/<safe-app>-english-full-<date-tag>/
```

Principal results are under `aspects/<source-generated-slug>/`, `aspect-clusters/`, and `refined-topics/`. The final catalog is `refined-topics/topic_catalog.md`, and the semantic handoff is `refined-topics/manual_review_packet.md`. Sampled-review counts in those files are not population prevalence.
