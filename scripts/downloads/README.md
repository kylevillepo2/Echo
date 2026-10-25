# Download data for Unwrap

Public download data for the 60 apps in the demo graph. Built for the hackathon: real public anchors, a modelled recent series, no backend.

## What's here

| File | Purpose |
|---|---|
| `apps.json` / `apps.csv` | The 60 apps extracted from `src/lib/api/mock.ts` |
| `mapping.json` | Reviewed mapping: app → Play package + App Store track ID |
| `raw/matches.json` | Raw search results from both stores (audit trail) |
| `raw/play-details.json` | Cached Play metadata (installs, ratings, release date) |
| `out/downloads.json` | **The dataset.** 60 apps, 26 weekly points each, rate/day, delta, provenance |
| `out/downloads.csv` | Flat summary for spreadsheets |
| `REPORT.md` | Human-readable coverage, method, full table, caveats |

A copy of the dataset lives at `src/lib/data/downloads.json` so the app can import it directly.

## Coverage

- 60/60 apps mapped to Google Play and the App Store.
- 60/60 have a Play install anchor and a US App Store rating count.
- Every app has 26 weekly download points, `ratePerDay`, and `rateDelta`.

## What is real vs modelled

**Real (public, fetched today):**

- Google Play install bracket (`installs`, `minInstalls`, `maxInstalls`)
- Google Play ratings count
- App Store `userRatingCount` (US storefront)
- Release dates, used to derive app age

**Modelled:**

- The 26-week weekly series
- `ratePerDay` and `rateDelta`

Neither store publishes download history, and a real daily rate needs at least two snapshots separated by time. The model allocates a plausible slice of lifetime installs to the last 26 weeks (`clamp(182 / ageDays × categoryGrowth, 0.02, 0.20)`) and shapes it with deterministic growth + noise. Everything is marked `confidence: "estimated"`.

## Dataset shape

```json
{
  "meta": { "asOf": "2026-10-24", "appCount": 60, "method": "…", "sources": [] },
  "categories": { "social": { "apps": 5, "installs": 0, "ratePerDay": 0 } },
  "apps": {
    "spotify": {
      "installs": 1201000000,
      "installsLow": 1000000000,
      "installsHigh": 3172798659,
      "installsLabel": "1,000,000,000+",
      "iosRatings": 42741753,
      "androidRatings": 36532990,
      "ageDays": 4533,
      "recentShare": 0.048,
      "ratePerDay": 317843,
      "rateDelta": 0.052,
      "source": "play",
      "installsConfidence": "bracket",
      "confidence": "estimated",
      "asOf": "2026-10-24",
      "weekly": [{ "date": "2026-05-02", "downloads": 1801400 }],
      "provenance": { "playAppId": "com.spotify.music", "iosTrackId": 324684580 }
    }
  }
}
```

## Rerun the pipeline

```sh
cd scripts/downloads
node 01-apps.mjs       # extract apps from mock.ts
node 02-match.mjs      # search both stores (slow: iTunes rate limit)
node 02b-retry.mjs     # retry any iTunes 403/429
node 03-mapping.mjs    # apply reviewed overrides → mapping.json
node 04-fetch-play.mjs # Play details (cached in raw/)
node 05-build.mjs      # model + write out/downloads.json
node 06-report.mjs     # regenerate REPORT.md
```

`google-play-scraper` is the only dependency (`npm install` in this folder). The iTunes Search API needs no key.

## Using it in the app

```ts
import downloads from '#lib/data/downloads.json';
const stats = downloads.apps[app.id as keyof typeof downloads.apps];
```

The intended UI wiring is:

- `Size by: reviews | downloads` toggle; node radius `sqrt(metric / max)`.
- Inspector block: weekly bars, `ratePerDay`, `rateDelta`, and an `est.` chip.
- Sidebar / command palette: sort and label by the active metric.
- Help dialog: one line explaining that the rate is modelled from public install counts.

## Notes and gotchas

- `Chime` was initially matched to a 10k-install impostor; corrected to `com.onedebit.chime`.
- `MyRadar` initially matched the paid Pro app; corrected to the free listing.
- `Opera` initially matched the beta channel; corrected to the stable package.
- `Kolibri Games` is a publisher; its data is for **Idle Miner Tycoon**.
- Play installs are **global** lifetime installs. App Store rating counts are **US-only**. Don't compare the two columns directly.
- Scraping Play is against its terms; fine for a hackathon demo, not for production. For production, use App Store Connect / Play Console reports for owned apps, or a paid provider for third-party estimates.

## Making the rate real later

The schema already has the fields you need. Run `04-fetch-play.mjs` daily, append `(app_id, captured_at, installs, ratings)` to a snapshot table, and compute `ratePerDay` from deltas instead of the model. Android becomes measured; iOS stays estimated (rating-count delta × category multiplier) because Apple never publishes units for third-party apps.
