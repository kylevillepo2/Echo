# Switching graph

**Question:** when someone reviewing Spotify, SoundCloud or Audiomack mentions another music app, are they leaving for it, coming from it, or just comparing?

## How it works

1. **Find candidates.** These are reviews of the 3 music apps that name one of 17 music apps. That gives **12,380 reviews**.
2. **Label each mention with an LLM** (`gpt-6-luna`; the full run cost about $2.30). Labels: `left_for`, `leaving_for`, `came_from`, `returned_from`, `prefers_reviewed`, `prefers_mentioned`, or no edge (`uses_both`, `neutral_comparison`, `not_a_switch_reference`). Each label also gets a **reason** (price, ads, free tier limits, catalog, bugs…) and an **exact quote**. Any label whose quote isn't in the review is dropped.
3. **Build edges in code.** Weights: actual switch = 1.0, threatened switch = 0.5, preference = 0.25.
4. **Normalize** to switches per 10k reviews per month, so bigger apps don't win just by having more reviews.
5. **Export** to `src/lib/data/flows.json` for the Flows view.

We have reviews for Spotify, SoundCloud and Audiomack, so flows **between those three** are seen from both sides. Apple Music, YouTube Music and the rest only show up as mentions in those three apps' reviews, so their flows are one-sided.

## Files

| File | What it does |
|---|---|
| `music_edge_extraction.py` | Prompt, app aliases, label/reason lists, quote check, edge weights |
| `run_music_edges.py` | Runner: `candidates` → `pilot` → `full` → `edges` (resumable) |
| `export_flows.py` | Writes `src/lib/data/flows.json` from the edge CSVs |
| `outputs/music_edges_monthly.csv` | Snapshot: month, source, target, kind, weight, weight per 10k reviews |
| `outputs/app_month_counts.csv` | Snapshot: reviews per app per month (for normalizing). **Downloads team: join on `app_name` + `month`** |
| `outputs/pilot_disagreements.csv` | Where the two models disagreed in the 200-review pilot |

## Re-running (from the workspace folder)

```sh
python3 unwrapathon/pipeline/switching/run_music_edges.py candidates
python3 unwrapathon/pipeline/switching/run_music_edges.py full --model gpt-6-luna   # needs OPENAI_API_KEY in .env
python3 unwrapathon/pipeline/switching/run_music_edges.py edges --model gpt-6-luna
python3 unwrapathon/pipeline/switching/export_flows.py
```

**Next:** do the same for payments (Venmo, Cash App, PayPal, Chime), dating (Tinder, Bumble, Hinge), browsers (Brave, Opera) and delivery (Uber, DoorDash).
