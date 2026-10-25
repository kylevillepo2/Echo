# Unwrap — download dataset

Generated **2026-10-24** for **59 apps** across 13 categories.

> **What is real vs modelled.** Lifetime installs come from the public Google Play install bracket. The 26-week weekly series and the daily rate are **modelled** — neither store publishes download history, and a real rate needs repeated snapshots over time. Every figure is marked `confidence: "estimated"`.

## Coverage

- Apps with a Play install anchor: **59/59**
- Apps with an App Store rating count: **59/59**
- Total lifetime installs (modelled): **17.01B**
- Total modelled rate: **5,455,156 downloads/day**

## Sources

- Google Play (public install bracket + ratings) — https://play.google.com
- Apple iTunes Search API (US rating count) — https://itunes.apple.com

## Method

Lifetime installs from the published Google Play install bracket (lower bound + a seeded in-bracket factor) or the App Store rating count. The 26-week series and daily rate are modelled from app age and category growth, not observed snapshots.

In short:

1. Map each demo app to a Play package and an App Store track ID (`mapping.json`).
2. Pull the public Play install bracket (`minInstalls`/`maxInstalls`) and ratings count.
3. Pull the US App Store `userRatingCount` from the iTunes Search API.
4. Estimate lifetime installs from the Play bracket (lower bound + a seeded in-bracket factor).
5. Model the last 26 weeks as `lifetime installs × clamp(182 / ageDays × categoryGrowth, 0.02, 0.20)`, shaped by deterministic growth + noise.
6. Derive `ratePerDay` and `rateDelta` from that series.

## Top 15 by modelled rate

| # | App | Category | Installs | Rate/day | 4w Δ |
|---:|---|---|---:|---:|---:|
| 1 | Temu | Shopping & Rewards | 1.09B | 995,100 | +8.3% |
| 2 | CapCut | Photo & Video | 1.16B | 631,049 | +11.8% |
| 3 | Picsart | Photo & Video | 1.33B | 321,020 | +5.5% |
| 4 | Spotify | Music | 1.20B | 313,320 | +5.2% |
| 5 | Remini | Photo & Video | 577.6M | 285,539 | +5.1% |
| 6 | Pinterest | Social & Community | 1.06B | 262,284 | +4.9% |
| 7 | LinkedIn | Work & Productivity | 1.39B | 258,752 | -1.5% |
| 8 | Zoom | Work & Productivity | 1.21B | 256,527 | +0.6% |
| 9 | Magic Tiles 3 | Games | 622.5M | 214,501 | +11.0% |
| 10 | PayPal | Finance & Banking | 550.0M | 212,781 | +11.1% |
| 11 | Uber | Travel & Delivery | 1.06B | 209,951 | +1.0% |
| 12 | Discord | Social & Community | 587.5M | 180,540 | +9.0% |
| 13 | Duolingo | Learning & Reading | 671.9M | 156,309 | -1.8% |
| 14 | Tinder | Dating | 550.0M | 124,791 | +5.4% |
| 15 | Opera | Utilities & Browsers | 559.6M | 106,624 | +6.7% |

## By category

| Category | Apps | Installs | Rate/day |
|---|---:|---:|---:|
| Photo & Video | 4 | 3.19B | 1,311,260 |
| Shopping & Rewards | 6 | 1.38B | 1,089,131 |
| Social & Community | 5 | 1.86B | 560,701 |
| Work & Productivity | 3 | 2.73B | 536,156 |
| Music | 3 | 1.45B | 373,955 |
| Finance & Banking | 10 | 1.01B | 323,874 |
| Games | 3 | 849.3M | 272,454 |
| Travel & Delivery | 6 | 1.32B | 269,111 |
| Learning & Reading | 5 | 939.9M | 209,420 |
| Utilities & Browsers | 4 | 851.8M | 174,333 |
| Dating | 3 | 676.7M | 160,450 |
| Health & Family | 4 | 396.0M | 91,416 |
| TV | 3 | 354.4M | 82,895 |

## All 59 apps

| App | Category | Installs | Rate/day | 4w Δ | Source | iOS ratings | Android ratings |
|---|---|---:|---:|---:|---|---:|---:|
| Temu | Shopping & Rewards | 1.09B | 995,100 | +8.3% | play | 2,241,545 | 13,056,046 |
| CapCut | Photo & Video | 1.16B | 631,049 | +11.8% | play | 1,124,843 | 13,111,585 |
| Picsart | Photo & Video | 1.33B | 321,020 | +5.5% | play | 1,196,343 | 12,116,380 |
| Spotify | Music | 1.20B | 313,320 | +5.2% | play | 42,741,753 | 36,532,990 |
| Remini | Photo & Video | 577.6M | 285,539 | +5.1% | play | 357,440 | 5,897,887 |
| Pinterest | Social & Community | 1.06B | 262,284 | +4.9% | play | 5,805,149 | 11,682,891 |
| LinkedIn | Work & Productivity | 1.39B | 258,752 | -1.5% | play | 645,146 | 3,522,960 |
| Zoom | Work & Productivity | 1.21B | 256,527 | +0.6% | play | 3,256,958 | 4,594,482 |
| Magic Tiles 3 | Games | 622.5M | 214,501 | +11.0% | play | 845,112 | 3,559,709 |
| PayPal | Finance & Banking | 550.0M | 212,781 | +11.1% | play | 6,299,171 | 3,741,568 |
| Uber | Travel & Delivery | 1.06B | 209,951 | +1.0% | play | 17,120,084 | 20,222,472 |
| Discord | Social & Community | 587.5M | 180,540 | +9.0% | play | 3,576,331 | 7,089,187 |
| Duolingo | Learning & Reading | 671.9M | 156,309 | -1.8% | play | 5,530,055 | 51,265,721 |
| Tinder | Dating | 550.0M | 124,791 | +5.4% | play | 1,756,651 | 9,264,564 |
| Opera | Utilities & Browsers | 559.6M | 106,624 | +6.7% | play | 263,475 | 5,541,746 |
| PhotoRoom | Photo & Video | 121.8M | 73,652 | +13.9% | play | 230,865 | 4,028,973 |
| Character.ai | Social & Community | 65.3M | 67,862 | +4.9% | play | 560,287 | 2,452,254 |
| Sweatcoin | Shopping & Rewards | 137.1M | 54,482 | +2.2% | play | 401,322 | 3,156,383 |
| Reddit | Social & Community | 128.4M | 43,110 | -0.2% | play | 3,511,323 | 4,880,202 |
| Brave | Utilities & Browsers | 139.8M | 41,765 | +31.2% | play | 667,943 | 3,934,145 |
| Flo | Health & Family | 136.3M | 40,115 | +3.5% | play | 2,004,734 | 5,157,572 |
| Audiomack | Music | 135.2M | 37,490 | +10.3% | play | 2,022,681 | 9,190,984 |
| Kolibri Games | Games | 106.1M | 34,052 | +1.7% | play | 865,909 | 5,866,908 |
| Tubi | TV | 115.9M | 31,413 | -6.8% | play | 1,281,758 | 2,624,152 |
| Cash App | Finance & Banking | 136.0M | 31,234 | +8.0% | play | 8,771,856 | 4,506,898 |
| Bumble | Dating | 112.9M | 31,186 | +8.7% | play | 1,768,550 | 1,632,021 |
| eBay | Shopping & Rewards | 123.2M | 28,671 | +16.6% | play | 4,969,500 | 5,025,912 |
| Airbnb | Travel & Delivery | 131.0M | 27,640 | +5.2% | play | 703,110 | 1,978,783 |
| Crunchyroll | TV | 128.5M | 26,647 | +5.5% | play | 1,519,538 | 4,437,189 |
| Audible | Learning & Reading | 131.9M | 26,608 | +6.7% | play | 5,615,473 | 1,767,552 |
| Life360 | Health & Family | 130.7M | 24,990 | +5.8% | play | 3,136,694 | 2,480,975 |
| Roku | TV | 110.0M | 24,835 | +3.6% | play | 6,324,635 | 4,750,219 |
| Chess.com | Games | 120.7M | 23,901 | +3.3% | play | 853,404 | 3,450,305 |
| Weather Channel | Utilities & Browsers | 139.6M | 23,370 | -7.1% | play | 6,096,297 | 3,610,740 |
| SoundCloud | Music | 110.4M | 23,145 | +2.0% | play | 2,056,431 | 7,666,309 |
| My Fitness Pal | Health & Family | 117.4M | 22,365 | +6.7% | play | 2,383,181 | 2,919,837 |
| Bank of America Mobile Banking | Finance & Banking | 55.0M | 21,677 | +3.6% | play | 5,025,270 | 1,202,201 |
| Wattpad | Learning & Reading | 118.8M | 21,483 | +15.5% | play | 706,070 | 5,020,240 |
| Indeed | Work & Productivity | 125.1M | 20,877 | +5.2% | play | 4,097,778 | 14,157,776 |
| DoorDash | Travel & Delivery | 54.6M | 14,602 | -3.4% | play | 23,467,803 | 6,273,897 |
| Intuit Credit Karma | Finance & Banking | 61.3M | 13,494 | -1.5% | play | 7,769,280 | 3,245,784 |
| Coinbase | Finance & Banking | 56.7M | 12,453 | +6.6% | play | 1,797,988 | 929,704 |
| Ticketmaster | Travel & Delivery | 54.8M | 11,961 | +5.7% | play | 4,234,291 | 204,968 |
| Venmo | Finance & Banking | 62.8M | 11,495 | -5.5% | play | 15,473,456 | 925,489 |
| Capital One Mobile | Finance & Banking | 57.1M | 11,291 | +16.9% | play | 11,228,348 | 1,717,128 |
| Lemon8 | Social & Community | 12.9M | 6,905 | -4.4% | play | 282,358 | 303,605 |
| Hinge | Dating | 13.8M | 4,473 | +9.1% | play | 1,133,661 | 492,951 |
| Fetch | Shopping & Rewards | 10.7M | 4,161 | +7.6% | play | 7,795,063 | 1,711,647 |
| Better Me | Health & Family | 11.6M | 3,946 | +5.8% | play | 714,067 | 661,334 |
| Libby | Learning & Reading | 11.3M | 3,606 | +0.9% | play | 4,581,904 | 756,681 |
| Dave | Finance & Banking | 11.4M | 3,554 | +1.2% | play | 926,929 | 637,244 |
| Shopify | Shopping & Rewards | 10.8M | 3,415 | +10.7% | play | 42,981 | 74,178 |
| Depop | Shopping & Rewards | 11.1M | 3,302 | +0.5% | play | 1,056,870 | 154,295 |
| Chime | Finance & Banking | 12.5M | 3,002 | +6.9% | play | 1,629,962 | 1,134,200 |
| Robinhood | Finance & Banking | 10.9M | 2,893 | +3.7% | play | 4,892,125 | 600,058 |
| MyRadar | Utilities & Browsers | 12.8M | 2,574 | +1.1% | play | 1,086,025 | 341,395 |
| Spark Driver | Travel & Delivery | 5.5M | 2,532 | -6.9% | play | 313,059 | 184,742 |
| UPS | Travel & Delivery | 12.8M | 2,425 | +5.8% | play | 1,226,737 | 330,219 |
| Hoopla | Learning & Reading | 6.0M | 1,414 | +3.9% | play | 1,393,114 | 219,572 |

## Mapping notes

- `Chime` — Play search ranked a 10k-install impostor first; mapped to `com.onedebit.chime`.
- `MyRadar` — the App Store result was the paid Pro app; mapped to the free `MyRadar Accurate Weather Radar`.
- `Opera` — Play search returned the beta channel first; mapped to `com.opera.browser`.
- `The Weather Channel` and `Brave` — the iTunes search endpoint rate-limited during the bulk run; filled from a direct lookup.
- `Kolibri Games` — this is a publisher, so the data is for its game **Idle Miner Tycoon**.
- Play installs are global lifetime installs. App Store rating counts are US-only. Do not read the two columns as directly comparable.

## What would make the rate real

The model becomes measured data with almost no schema change: run `04-fetch-play.mjs` daily, append the install/rating counts to a snapshot table, and replace `ratePerDay` with `Δinstalls` over the window. Android becomes measured immediately; iOS stays estimated (rating-count delta × category multiplier) because Apple never publishes units for third-party apps.

## Rerun

```sh
cd scripts/downloads
node 01-apps.mjs      # extract the apps from mock.ts
node 02-match.mjs     # search both stores (rate-limited)
node 03-mapping.mjs   # apply overrides → mapping.json
node 04-fetch-play.mjs# fetch Play details (cached)
node 05-build.mjs     # model + write out/downloads.json
node 06-report.mjs    # this report
```
