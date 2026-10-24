# Pipeline (Python)

The Python side of the project. It turns the raw review CSV into the data the front end shows.

| Folder | What it answers | What the front end uses |
|---|---|---|
| [`switching/`](switching/) | Which apps users **leave**, where they **go**, and **why** | `src/lib/data/flows.json`, shown in the **Flows** view (press `3`) |
| [`topics/`](topics/) | What people **talk about** in an app's reviews (Spotify so far) | Nothing yet. The summaries are in `topics/outputs/` |

## Folder layout on your laptop

The big data files are **not in git** because they're too large. The scripts expect the repo to sit inside a workspace folder like this:

```
Unwrapathon/                 <- workspace (not a git repo)
├── .env                     <- OPENAI_API_KEY=...  (never commit)
├── data/
│   ├── app-store-feedback.csv   raw export from the organizers (1.3 GB)
│   └── reviews-clean.csv        cleaned version every script reads (1 GB)
├── out/                     <- switching outputs (written by switching/ scripts)
├── embeddings/  clusters/  samples/  extractions/  aspects/   <- topics outputs
└── unwrapathon/             <- THIS REPO
```

Ask Kyle for `reviews-clean.csv` if you need to re-run anything. **You don't need any of it to run the front end.**

## Setup

```sh
python3 -m venv .venv && source .venv/bin/activate
pip install -r unwrapathon/pipeline/requirements.txt
```

Run every command from the **workspace folder** (the one that contains `data/`), not from inside the repo.
