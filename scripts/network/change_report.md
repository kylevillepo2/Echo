# Switching balance changes

Old bucket names are translated to the new labels below, so simple renaming is not counted as a change.

**33 existing apps changed bucket.** The former pooled Uber node is replaced by two market nodes and is listed separately.

Balance of switches reported in reviews, between apps both in our dataset. Not a measure of user growth.

There are **2,382 eligible switch reports**. The other **6,786 reports** remain context and do not affect balance.

The switch and return kinds each count as a report in their stated direction, including on the outgoing side. Reports are deduplicated by review/pair/month/kind. Buckets use unrounded scores; the minimum remains 20 eligible reports.

| App | Previous bucket | New bucket | Reports in | Reports out | Score |
|---|---|---|---:|---:|---:|
| Airbnb | Strongly negative | Too few reports | 0 | 0 | — |
| Bank of America Mobile Banking | Negative switching balance | Strongly negative | 4 | 37 | -0.8049 |
| Bumble | Mixed | Negative switching balance | 49 | 76 | -0.2160 |
| CapCut | Strongly negative | Too few reports | 2 | 13 | -0.7333 |
| Capital One Mobile | Mixed | Positive switching balance | 21 | 11 | +0.3125 |
| Cash App | Mixed | Negative switching balance | 185 | 294 | -0.2276 |
| Character.ai | Mixed | Too few reports | 0 | 0 | — |
| Chess.com | Strongly negative | Too few reports | 0 | 0 | — |
| Crunchyroll | Positive switching balance | Too few reports | 1 | 2 | -0.3333 |
| Dave | Negative switching balance | Too few reports | 8 | 11 | -0.1579 |
| Depop | Mixed | Positive switching balance | 23 | 12 | +0.3143 |
| Discord | Positive switching balance | Too few reports | 7 | 2 | +0.5556 |
| DoorDash | Negative switching balance | Mixed | 231 | 321 | -0.1630 |
| Duolingo | Negative switching balance | Too few reports | 0 | 0 | — |
| Fetch | Mixed | Too few reports | 0 | 0 | — |
| Flo | Negative switching balance | Too few reports | 0 | 0 | — |
| Indeed | Positive switching balance | Too few reports | 8 | 3 | +0.4545 |
| Lemon8 | Positive switching balance | Mixed | 26 | 35 | -0.1475 |
| Life360 | Mixed | Too few reports | 0 | 0 | — |
| Magic Tiles 3 | Positive switching balance | Too few reports | 0 | 0 | — |
| My Fitness Pal | Negative switching balance | Too few reports | 0 | 1 | -1.0000 |
| MyRadar | Positive switching balance | Too few reports | 10 | 4 | +0.4286 |
| Opera | Positive switching balance | Negative switching balance | 27 | 60 | -0.3793 |
| Picsart | Mixed | Too few reports | 12 | 3 | +0.6000 |
| Pinterest | Positive switching balance | Mixed | 35 | 27 | +0.1290 |
| Reddit | Positive switching balance | Too few reports | 2 | 6 | -0.5000 |
| Roku | Positive switching balance | Too few reports | 0 | 1 | -1.0000 |
| Spotify | Mixed | Strongly negative | 86 | 293 | -0.5462 |
| Ticketmaster | Strongly negative | Too few reports | 0 | 0 | — |
| Tinder | Strongly negative | Negative switching balance | 31 | 89 | -0.4833 |
| Tubi | Mixed | Too few reports | 3 | 1 | +0.5000 |
| Wattpad | Strongly negative | Too few reports | 0 | 0 | — |
| Weather Channel | Strongly negative | Too few reports | 4 | 10 | -0.4286 |

## Uber split

| Market | Bucket | Eligible reports in | Eligible reports out | Review count with market attribution |
|---|---|---:|---:|---:|
| Uber (Rides) | Too few reports | 0 | 0 | 7,433 |
| Uber Eats | Mixed | 321 | 231 | 944 |

The pooled Uber corpus contains 756,905 reviews: 7,433 could be assigned to rides and 944 to delivery using extracted competitor mentions. The remaining 748,528 are unassigned (including mixed-market reviews); they are not duplicated across market nodes.

Uber (Rides) has zero eligible balance reports because its counterpart apps in these switch reports are outside our dataset. Its large contextual flow to Lyft therefore does not contribute to its balance. Uber Eats ↔ DoorDash is within scope.

## New top flows

These are customer switch reports with forced moves excluded. “Within balance scope” means both endpoints belong to the dataset.

| Source | Target | Switch reports | Within balance scope |
|---|---|---:|---|
| Uber (Rides) | Lyft | 766 | No |
| Chrome | Brave | 416 | No |
| DoorDash | Uber Eats | 321 | Yes |
| Uber Eats | DoorDash | 231 | Yes |
| Spotify | SoundCloud | 179 | Yes |
| Character.ai | Chai | 156 | No |
| Lyft | Uber (Rides) | 148 | No |
| Chai | Character.ai | 140 | No |
| Chrome | Opera | 139 | No |
| Cash App | Venmo | 127 | Yes |

## Top Uber-market flows

| Source | Target | Switch reports |
|---|---|---:|
| Uber (Rides) | Lyft | 766 |
| DoorDash | Uber Eats | 321 |
| Uber Eats | DoorDash | 231 |
| Lyft | Uber (Rides) | 148 |
| Uber (Rides) | Bolt | 69 |
| Uber (Rides) | DiDi | 22 |
| Uber (Rides) | inDrive | 21 |
| Bolt | Uber (Rides) | 15 |
| Uber (Rides) | Waymo | 14 |
| Uber Eats | Grubhub | 8 |
| inDrive | Uber (Rides) | 8 |
| DiDi | Uber (Rides) | 5 |

## Skype cutoff

Outgoing Skype reports before 2025-02 are no longer marked as forced moves. Three actual switch reports were restored: two in 2024-10 and one in 2024-07. Reports from 2025-02 onward remain excluded. Skype is outside our dataset, so the restored reports affect contextual flows rather than balance.

## Verification

Exporter tests cover both CSV schemas, both-endpoint scope, role and forced-move filtering, duplicate reports, the Skype boundary, Uber market attribution, bucket boundaries, missing stats, and exact all-time/yearly stats/export agreement. The artifact remains below 2 MB.
