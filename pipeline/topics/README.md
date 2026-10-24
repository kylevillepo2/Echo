# Review topics (Spotify so far)

**Question:** what are people actually complaining about or praising in an app's reviews?

## Steps (run in this order, from the workspace folder)

| # | Script | What it does | Output folder |
|---|---|---|---|
| 2 | `embed_reviews.py` | Turns each review into a vector (`all-MiniLM-L6-v2`) so similar reviews sit close together | `embeddings/spotify/` |
| 3 | `cluster_reviews.py` | Groups the 184k Spotify reviews into **200 topics** (k-means). Reviews under 4 words ("great app", 28%) go to topic `-1` | `clusters/spotify/` |
| – | `assign_clusters.py` | Puts new reviews into the existing topics | – |
| 4 | `sample_reviews.py` | Picks a few reviews from each topic for the LLM | `samples/spotify_pilot/` |
| 5 | `extract_aspects.py` | LLM pulls out each **specific thing** a review talks about (e.g. "ads after every song") | `extractions/spotify/` |
| 6–7 | `cluster_aspects.py` | Merges different wordings of the same complaint into one aspect | `aspects/spotify/` |
| – | `compare_embeddings.py` | Checks our embeddings against Derek's script (sanity check) | – |

(Step 1 is cleaning the data, which produced `reviews-clean.csv`.)

## Outputs in this repo (`outputs/spotify/`)

| File | What it is |
|---|---|
| `cluster_summary.csv` | One row per topic: size, average stars, % 1★/5★, keywords, 3 example reviews |
| `cluster_labels.csv` | Each topic labeled as a real `topic`, `filler`, or `non_english` |
| `aspect_cluster_summary.csv` | One row per specific complaint/praise: name, how many reviews, how many negative/positive, example quote |
| `feature_map.csv` | Feature names merged to one canonical name (e.g. "ai" → "AI DJ") |

## What it shows so far

- Most Spotify reviews are short and positive ("love it, best app").
- About **a third of the reviews that were sorted into topics** are in topics averaging under 2.5★. The main complaints are **free tier limits** (can't pick songs, forced shuffle, skip limits), **ads**, **price and billing**, **bugs after updates**, and **login problems**.
- The same reasons come up in the switching graph, so the two methods agree.

**Watch out:** the Spotify reviews here only cover **Aug 2024 to Apr 2025**.
