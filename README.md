# Echo

**Mapping where app users say they go when they leave, from 5.5 million app-store reviews.**

**[Try Echo live →](https://unwrapathon.vercel.app)** — hosted on Vercel. No installation or API key required.

Built at **Unwrapathon 2026** by a team of four. Echo turns unstructured app reviews into an interactive map of competitive switching: which apps reviewers say they left, which alternatives they chose, why they moved, and how those reports changed month to month.

A low rating tells you someone is unhappy. Echo helps answer the next question: **where did they go, and what pushed them there?** Examples include reviewers reporting moves from Uber to Lyft over wait times and from Chrome to Brave over ads. Each connection links back to review evidence.

## What you can explore

- **Competitive switching:** inspect directed connections between apps, with separate layers for reported switches/returns, switching intent, and preference.
- **Reasons and evidence:** inspect the reasons behind a connection and the original review excerpts supporting it.
- **Changes over time:** filter monthly flows and compare review-volume-normalized switching signals.
- **Category drill-downs:** focus a category and explore its apps and competing alternatives.
- **App topics:** inspect exported topic shares, rating distributions, monthly coverage, and representative reviews where topic data is available.

The hosted app loads bundled data exports in your browser. No API key or Python pipeline is required to explore it.

## Project at a glance

| Measure | Hackathon scope / result |
| --- | --- |
| Source corpus | Approximately 5.5 million app-store reviews |
| Frontend app catalog | 60 apps across 12 category clusters |
| Initial music analysis | 12,380 candidate reviews |
| Expanded labeling run | Approximately 83,000 candidate reviews |
| Reported labeling runtime | Reduced from about 10 hours to under 1 hour |
| Reported expanded-run cost | $10.61, with zero failed requests |
| Human validation | 60 independently labeled reviews across rides, browsers, and payments |
| Direction + relationship-type agreement | 50/60, or 83% (95% Wilson interval: 72–91%) |

Runtime and cost describe the team's hackathon run, not a benchmark or a current API price estimate. The model labels candidate reviews that mention competitors; it does **not** send the entire 5.5-million-review corpus to an LLM.

## Explore Echo

Open **[unwrapathon.vercel.app](https://unwrapathon.vercel.app)** to use the deployed app.

Select a category to focus the map, select an app to inspect its connections and available topic insights, and select a connection to read its supporting evidence. The category flow workspace provides period and relationship-layer controls.

Useful shortcuts:

| Shortcut | Action |
| --- | --- |
| `⌘K` / `Ctrl+K` | Open search |
| `/` | Open search when not typing in a field |
| `Esc` | Close overlays or clear the current selection/focus |
| `I` | Toggle the inspector |

Some interface labels and internal filenames still use the original hackathon name, **Unwrap**.

## How the switching pipeline works

1. **Find candidates.** Scan the review corpus for competitor names using category-specific app aliases. Reviews with no relevant competitor mention do not need LLM labeling.
2. **Label mentions.** An LLM identifies the relationship to each competitor, reasons, and a verbatim evidence quote. Labels distinguish actual switches, returns, intent, preferences, and comparisons that should not create an arrow.
3. **Validate evidence.** Reject extracted labels whose supporting quote cannot be matched to the source review, with normalization for typography such as curly apostrophes.
4. **Build graph edges in code.** Deterministic rules convert labels into directions and relationship types. Actual switches, threatened switches, and preferences remain distinct.
5. **Apply reporting rules.** Separate occupational roles where relevant, exclude configured forced migrations, deduplicate reports, and disambiguate markets such as Uber rides versus Uber Eats.
6. **Aggregate and export.** Produce monthly edges, rates per 10,000 source-app reviews, reasons, and representative evidence for the frontend.

The LLM labels the language; code decides how those labels become graph data. This makes the transformation inspectable and reproducible from saved labels without another model call.

### Reviewed apps versus mentioned competitors

The 60-app catalog is not the size of the competitor-name dictionary or the switching graph. Competitors outside the reviewed corpus can appear as graph endpoints because reviewers mention moving to or from them.

For a reviewed app, we can inspect its own reviews. For a mentioned-only competitor, we see only what reviewers of other apps say about it. Those connections are useful context, but their coverage is one-sided. Expanding the alias dictionary adds possible competitors; it does not add those competitors' own review corpora.

### What the numbers mean

Echo measures **switching reports in reviews**, not verified user migrations, churn, market share, or user growth. A reviewer can describe an intention or preference without actually switching, and review authors are not a representative sample of all users.

Monthly rates use the volume of reviews from the app whose corpus supplied the report. The switching-balance score uses only eligible actual switch/return reports between apps that are both in the dataset:

```text
balance = (incoming reports - outgoing reports)
          / (incoming reports + outgoing reports)
```

Outside competitors remain visible context but do not contribute to this balance. Scores are null when there are no eligible reports; fewer than 20 eligible reports is marked as insufficient evidence. See the [network data documentation](scripts/network/README.md) for eligibility rules, buckets, and denominator details.

## Validation

The team created a blind 60-review validation set covering rides, browsers, and payments. Human labels were completed before comparing them with the model's output.

| Metric | Agreement | 95% Wilson interval |
| --- | --- | --- |
| Exact relationship label | 49/60 (82%) | 70–89% |
| Direction, including no-edge decisions | 51/60 (85%) | 74–92% |
| Edge versus no edge | 53/60 (88%) | 78–94% |
| Direction + relationship type | 50/60 (83%) | 72–91% |

Two cases reversed the direction of an edge. Other disagreements included whether an edge should exist or whether the statement described an actual switch, intent, or preference. The 83% result is **direction plus type agreement**, not direction-only accuracy.

This is a small, selected validation set across three domains, not an estimate of performance across every app or category.

Reproduce the scoring from the repository root:

```sh
python3 results/switching/validation/score_validation.py
```

See the [validation instructions](results/switching/validation/README.md) for the label definitions and blind-labeling procedure.

## AI-assisted engineering workflow

Kyle built the switching pipeline and integrated it into a teammate's existing SvelteKit/TypeScript frontend, using Claude Code and Codex as coding agents. The four-person team also contributed the app interface, topic-analysis pipeline, and supporting analytics.

The workflow combined agent implementation with human engineering decisions:

- **Bounded parallel tasks:** separate agents handled pipeline work, stats, and frontend integration, with folder boundaries and shared API budgets.
- **Pilots before large runs:** a 200-review pilot compared two models; disagreement review informed model selection before spending on the larger run.
- **Review and debugging:** output inspection caught valid quotes being dropped because of curly apostrophes, and substring matching that found “ally bank” inside “especially banking.”
- **Performance and recovery:** batching 10 reviews per request and increasing concurrency reduced the reported run from about 10 hours to under an hour. Saved progress supports resuming interrupted runs.
- **Integration checks:** export tests check filtering, deduplication, and agreement between stats and frontend data. Feature branches, pull requests, and conflict resolution supported work across four contributors.

The reported batch size describes the optimized hackathon run; current CLI defaults may differ.

## Local development

To run your own development copy, use Node.js 24, the version used during development, and npm. From the repository root:

```sh
npm install
npm run dev
```

Open <http://localhost:5173>. This is the local development server; the hosted app is available at [unwrapathon.vercel.app](https://unwrapathon.vercel.app).

### Development checks

From the repository root:

```sh
npm run check
node --test scripts/*.test.mjs
python3 -m unittest discover -s scripts/network -p 'test_*.py'
npm run build
```

Preview the production build with `npm run preview`. Topic export discovery and validation are documented in [INSIGHTS.md](INSIGHTS.md).

## Re-running the data pipeline

Large raw inputs and intermediate labeling outputs are not included in Git. The bundled frontend exports are enough to run the app, but a full data rebuild requires the original review CSV, saved music-stage labels, and the relevant intermediate outputs.

The switching scripts expect this layout:

```text
Unwrapathon/
├── .env                         # OPENAI_API_KEY; never commit
├── data/
│   └── reviews-clean.csv
├── out/                         # Candidate, label, and aggregate outputs
└── unwrapathon/                 # This repository
```

From the **parent workspace directory**, build candidates without making model calls:

```sh
python3 unwrapathon/pipeline/switching/run_all_switches.py candidates
python3 unwrapathon/pipeline/switching/run_all_switches.py report
```

With the API key configured, run a pilot and inspect the results before labeling the full candidate set. These commands make paid API calls:

```sh
python3 unwrapathon/pipeline/switching/run_all_switches.py pilot --n 200 --batch 10 --workers 24
python3 unwrapathon/pipeline/switching/run_all_switches.py full --batch 10 --workers 24 --max-cost 15
```

`--max-cost` is an estimated budget guard checked between chunks, not a guaranteed billing cap. Coordinate concurrency when sharing an API key. The all-app pipeline reuses music labels; follow the [music pipeline instructions](pipeline/switching/README.md) if those outputs are missing. Use `--help` for the current CLI options.

For graph rebuilding, role labeling, correction rules, and export prerequisites, see the [pipeline overview](pipeline/README.md) and [network export guide](scripts/network/README.md). The [topic-analysis pipeline](review_parsing/README.md) has its own dependencies and execution instructions.

## Repository guide

| Path | Purpose |
| --- | --- |
| `src/lib/components/` | Interactive map, flow workspace, inspectors, and charts |
| `src/lib/state/` | App selection, category scope, and flow state |
| `src/lib/data/flows.json` | Bundled switching data used by the flow interface |
| `src/lib/data/network.json` | Compact switch-report network export |
| `static/data/insights/` | App-specific topic exports, loaded on demand |
| `pipeline/switching/` | Candidate selection, LLM labeling, corrections, and aggregation |
| `review_parsing/` | Review embeddings, aspect extraction, topic refinement, and aggregation |
| `scripts/network/` | Network exporter and consistency tests |
| `results/switching/validation/` | Human labels, model labels, and scoring script |
| `INSIGHTS.md` | Topic export integration and data semantics |
| `API.md` | Optional live-backend contract |

## Stack and data modes

**Frontend:** Svelte 5, SvelteKit 3, TypeScript, and Vite 8, with custom SVG/CSS charts and graph layout. **Switching pipeline:** Python standard library and OpenAI-compatible API requests. The separate topic pipeline uses embedding and clustering dependencies documented in its own setup guide.

The default **Demo** mode loads bundled exports without a backend. Switching reports and available topic exports come from the processing pipelines. Uncovered app panels and parts of the map retain generated demo metadata; not every displayed rating, trend, or similarity is a measured result. Covered topic panels avoid substituting synthetic analytics for missing export fields; see [INSIGHTS.md](INSIGHTS.md).

An optional **Live API** mode supports a backend through the data-source dialog or `VITE_API_BASE`. See [API.md](API.md) for the contract. Live mode requires a separately running compatible backend.
