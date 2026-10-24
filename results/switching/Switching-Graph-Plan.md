# App Switching Graph — Plan

**Scope:** this doc covers only the switching graph: which apps users leave, where they go, why, and how that changes over time.
Other parts of the project (general complaints/themes per app, and download/user data) are owned by teammates. See "Hand-offs" below for where they connect.

## Goal
Build a directed graph of user movement between apps, using reviews that mention another app. Start with **music** (Spotify, Audiomack, SoundCloud), then expand to other clusters.

## Why an LLM on every candidate review
- Only reviews that name another app can produce an edge. In music that's **12,380 reviews**, small enough to label all of them (no sampling).
- Keywords can't tell direction: "better than Spotify" in an Audiomack review means the user is *staying*. The LLM labels the direction; code builds the edges.

## Pipeline
1. **Candidates:** reviews of Spotify / Audiomack / SoundCloud that name one of 17 music apps.
   (Spotify 6,076 · SoundCloud 3,347 · Audiomack 2,957)
2. **LLM label per mentioned app**, relative to the reviewed app:
   - Edges: `left_for`, `leaving_for`, `came_from`, `returned_from`, `prefers_reviewed`, `prefers_mentioned`
   - No edge: `uses_both`, `neutral_comparison`, `not_a_switch_reference`
   - Plus **reasons** (price, ads, free-tier limits, catalog, bugs, recommendations, indie artists, ...), a confidence, and an exact **evidence quote**.
3. **Validate:** drop labels whose evidence quote isn't in the review text.
4. **Edges (in code):** actual switch = 1.0 · threatened switch = 0.5 · preference = 0.25 · low confidence dropped.
5. **Monthly aggregation**, normalized per 10k reviews of the app whose reviews produced the edge.

## Graph design
- **Solid nodes:** Spotify, Audiomack, SoundCloud. Both directions are observed, so **net flow** between them is reliable (the headline result).
- **Hollow nodes:** Apple Music, YouTube Music, Pandora, Boomplay, etc. Only seen through the three apps' reviews, so flows are one-sided/undercounted.
- Edge thickness = normalized weight; color = top reason; month slider for the time view.
- Click an edge → real review quotes behind it.

## Model & cost
- Pilot: 200 reviews on **GPT-6 Luna** and **GPT-5.4 mini**. Compare agreement, read disagreements, pick one.
- Full run ≈ 19M input + 2M output tokens → about **$3 (Luna)** or **$11–22 (5.4 mini)**.

## Files
| File | What it is |
|---|---|
| `scripts/music_edge_extraction.py` | Prompt, JSON schema, app aliases, validation, edge rules |
| `scripts/run_music_edges.py` | Runner: `candidates` → `pilot` → `full` → `edges` (resumable, stdlib only) |
| `out/music_candidates.jsonl` | The 12,380 reviews to label |
| `out/app_month_counts.csv` | Reviews per app per month (normalization) |
| `out/music_edges_monthly.csv` | **Graph input:** month, source, target, kind, weight, normalized weight |
| `out/music_edges.csv` | One row per edge with reasons + evidence quote |
| `out/music_mentions.csv` | Every label, including non-edge mentions |

## Run
```bash
python3 scripts/run_music_edges.py candidates
python3 scripts/run_music_edges.py pilot --n 200 --models gpt-6-luna,gpt-5.4-mini
python3 scripts/run_music_edges.py full --model <chosen>
python3 scripts/run_music_edges.py edges --model <chosen>
```
API key in `.env` as `OPENAI_API_KEY=...` (never commit it).

## Next steps
1. Fix the API key, rerun the pilot, choose a model.
2. Full music run → build the interactive graph.
3. Expand to clusters where both sides are in the dataset: payments (Venmo, Cash App, PayPal, Chime), dating (Tinder, Bumble, Hinge), browsers (Brave, Opera), delivery (Uber, DoorDash). Each needs its own app/alias list and reason taxonomy.

## Hand-offs with teammates
- **Complaints/themes team:** node details on click (what people say about each app). Their topics can also be compared with our edge *reasons*, e.g. do "price" switches spike when price complaints spike?
- **Downloads/users team:** our monthly net flows can be plotted against their download or user numbers per app and month. Key to join on: `app_name` + `month` (YYYY-MM).

## Caveats
- Flows to apps outside the dataset are one-sided.
- Plain "YouTube" mentions are often about videos/podcasts; spot-check them.
- Review counts ≠ user counts; always show normalized numbers.
- ~4.3k candidates have unknown language; kept, with lower confidence when unclear.
