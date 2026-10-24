# Unwrap API contract

Unwrap talks to a backend through the `UnwrapApi` interface in [`src/lib/api/types.ts`](src/lib/api/types.ts). The demo corpus and the live HTTP adapter both implement it, so the UI behaves identically in either mode.

Set the backend base URL with `VITE_API_BASE`, or connect at runtime through **Data source → Live API**. The base path is prefixed to every route below.

```
GET {base}/health
GET {base}/graph
GET {base}/apps/:appId/reviews
GET {base}/search
```

All responses are JSON. CORS must allow the app origin. Requests time out after 20 seconds. Non-2xx responses are treated as errors and the first 160 characters of the response body are shown to the user.

---

## Enums

| Type | Values |
|---|---|
| `Platform` | `"ios"`, `"android"`, `"both"` |
| `Sentiment` | `"positive"`, `"neutral"`, `"negative"` |
| `SourceId` | `"gplay"`, `"appstore"`, or any string |
| `Theme.kind` | `"positive"`, `"negative"` |
| Star rating | integer `1`–`5` |
| Similarity score | number `0`–`1` |

---

## `GET /health`

Liveness probe used by the **Test** button in the connection dialog.

```json
{
  "ok": true,
  "detail": "index ready · 5,529,110 reviews"
}
```

Both fields are optional. Any 2xx JSON response is considered reachable unless `ok` is explicitly `false`.

---

## `GET /graph`

Returns the whole visualisation payload: corpus metadata, category clusters, app nodes, and similarity edges.

```json
{
  "meta": {
    "label": "App Store Feedback · Multi-category Corpus",
    "generatedAt": "2026-10-24T09:00:00.000Z",
    "reviewCount": 5529110,
    "sampled": 9000,
    "appCount": 60,
    "categoryCount": 12,
    "embeddingDim": 768,
    "embeddingModel": "text-embedding-3-small",
    "avgRating": 4.31,
    "window": {
      "from": "2026-04-27T00:00:00.000Z",
      "to": "2026-10-24T00:00:00.000Z"
    },
    "sources": [
      { "id": "gplay", "name": "Google Play", "count": 4011200 },
      { "id": "appstore", "name": "App Store", "count": 1517910 }
    ]
  },
  "categories": [
    {
      "id": "finance",
      "name": "Finance & Banking",
      "blurb": "Banking, payments and investing.",
      "appIds": ["cash-app", "paypal"],
      "rating": 4.45,
      "reviewCount": 576000,
      "reception": 83,
      "receptionDelta": 0.6,
      "accent": "#ff4f7e"
    }
  ],
  "apps": [
    {
      "id": "cash-app",
      "name": "Cash App",
      "categoryId": "finance",
      "categoryName": "Finance & Banking",
      "platform": "both",
      "subcategory": "Payments",
      "rating": 4.5,
      "reviewCount": 105000,
      "reception": 84,
      "receptionDelta": 1.4,
      "sentiment": { "positive": 84000, "neutral": 17850, "negative": 3150 },
      "distribution": [
        { "stars": 1, "count": 0 },
        { "stars": 2, "count": 3150 },
        { "stars": 3, "count": 17850 },
        { "stars": 4, "count": 45150 },
        { "stars": 5, "count": 38850 }
      ],
      "trend": [
        { "date": "2026-10-05", "rating": 4.42, "volume": 4100 },
        { "date": "2026-10-12", "rating": 4.5, "volume": 4380 }
      ],
      "themes": {
        "positive": [
          {
            "id": "design",
            "label": "Design",
            "kind": "positive",
            "count": 30450,
            "share": 0.29,
            "examples": ["It looks great without getting in the way."],
            "appIds": ["cash-app"]
          }
        ],
        "negative": [
          {
            "id": "fees",
            "label": "Fees",
            "kind": "negative",
            "count": 5250,
            "share": 0.05,
            "examples": ["The fees are ridiculous."],
            "appIds": ["cash-app"]
          }
        ]
      },
      "similar": [
        { "appId": "paypal", "score": 0.91 },
        { "appId": "venmo", "score": 0.88 }
      ],
      "sources": { "gplay": 73500, "appstore": 31500 },
      "position": { "x": 0.32, "y": -0.18 },
      "accent": "#00d54b",
      "version": "4.5.0"
    }
  ],
  "edges": [
    { "source": "cash-app", "target": "paypal", "score": 0.91 },
    { "source": "cash-app", "target": "venmo", "score": 0.88 }
  ],
  "themes": []
}
```

### Field notes

- **`categories`** are the clusters on the map. `appIds` must reference app IDs. `accent` should be a CSS colour (hex is used throughout the demo). `reception` is `0–100`; `receptionDelta` is in points.
- **`apps`** are the nodes. `reviewCount` controls node size. `position` is optional; when absent the client runs its own force layout. `accent` is optional and overrides the category colour for that node.
- **`sentiment`** counts should add up to `reviewCount`. The inspector derives percentages from them.
- **`distribution`** should contain five buckets with `stars` from `1` to `5`.
- **`trend`** is expected to be weekly-ish; the sparkline uses the order provided. `date` should be ISO-8601.
- **`themes`** on an app power the inspector signals and the theme ledger. `share` is `0–1`.
- **`similar`** powers the “Similar apps” tab. `score` is cosine similarity.
- **`edges`** power the similarity lines. Cross-category edges are styled differently. Edges with missing endpoints are ignored.
- **Top-level `themes`** is optional. If omitted or empty, the client computes a corpus-wide rollup from every app’s themes.

---

## `GET /apps/:appId/reviews`

Returns sampled reviews for one app.

### Query parameters

| Name | Type | Default | Notes |
|---|---|---|---|
| `limit` | integer | `120` | The UI requests `160` |
| `offset` | integer | `0` | Optional pagination offset |
| `stars` | integer `1–5` | — | Exact star filter |
| `sentiment` | `positive` \| `neutral` \| `negative` | — | Exact sentiment filter |

The response may be a bare array or an object with a `reviews` key:

```json
{
  "reviews": [
    {
      "id": "rev_01",
      "appId": "cash-app",
      "appName": "Cash App",
      "categoryId": "finance",
      "stars": 5,
      "date": "2026-10-23T18:42:00.000Z",
      "title": "Design",
      "text": "It looks great without getting in the way.",
      "source": "gplay",
      "version": "4.5.0",
      "sentiment": "positive",
      "themeIds": ["design"]
    }
  ]
}
```

The client also accepts the bare array form:

```json
[
  {
    "id": "rev_01",
    "appId": "cash-app",
    "appName": "Cash App",
    "categoryId": "finance",
    "stars": 5,
    "date": "2026-10-23T18:42:00.000Z",
    "title": "Design",
    "text": "It looks great without getting in the way.",
    "source": "gplay",
    "sentiment": "positive"
  }
]
```

`version` and `themeIds` are optional. `sentiment` should be present; the review card uses it for the tag colour. `stars` and `date` drive the local sort and star filters.

---

## `GET /search`

Semantic review search across the corpus.

### Query parameters

| Name | Type | Default | Notes |
|---|---|---|---|
| `q` | string | — | Required; empty queries return no hits |
| `appId` | string | — | Restrict to one app |
| `minStars` | integer `1–5` | — | Minimum star rating |
| `limit` | integer | `24` | Maximum number of hits |

The response may be a bare array or an object with a `hits` key. Every hit is a review plus a similarity `score`:

```json
{
  "hits": [
    {
      "id": "rev_01",
      "appId": "cash-app",
      "appName": "Cash App",
      "categoryId": "finance",
      "stars": 5,
      "date": "2026-10-23T18:42:00.000Z",
      "title": "Design",
      "text": "It looks great without getting in the way.",
      "source": "gplay",
      "version": "4.5.0",
      "sentiment": "positive",
      "themeIds": ["design"],
      "score": 0.87
    }
  ]
}
```

`score` is required on search hits and should be `0–1`. The UI sorts by the order returned.

---

## Errors

Return a non-2xx status with a short text or JSON body. The client shows:

```
{status} {statusText} — {first 160 chars of body}
```

in the connection dialog and status bar.

---

## TypeScript source of truth

The full interfaces are in [`src/lib/api/types.ts`](src/lib/api/types.ts):

- `GraphPayload`, `CorpusMeta`, `Category`, `AppNode`, `GraphEdge`
- `Review`, `SearchHit`, `ReviewQuery`, `SearchOptions`
- `UnwrapApi`

If your routes or field names differ, adapt only [`src/lib/api/http.ts`](src/lib/api/http.ts) and keep the rest of the UI unchanged.
