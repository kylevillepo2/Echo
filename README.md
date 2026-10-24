# Unwrap

**Review intelligence for app stores.** Unwrap turns app-store review corpora into a semantic map: apps are grouped into category clusters, sized by review volume, and scored by user reception. From there you can inspect an app, read its reviews, compare similar apps, or search the whole corpus by meaning.

Built for the hackathon demo with **SvelteKit 3 + Svelte 5 runes + TypeScript + Vite 8**. All charts, the force layout, and the design system are custom — no chart or UI component libraries.

---

## Demo corpus

The offline demo is seeded from the supplied app export:

| | |
|---|---|
| Apps | **60** |
| Category clusters | **12** |
| Indexed reviews | **5,529,110** |
| Sampled reviews available in the UI | **9,000** |
| Embedding model | `text-embedding-3-small` · **768 dimensions** |

Category clusters are semantic groups, **not publishers**:

`Social & Community` · `Entertainment` · `Learning & Reading` · `Shopping & Rewards` · `Finance & Banking` · `Health & Family` · `Photo & Video` · `Dating` · `Travel & Delivery` · `Games` · `Work & Productivity` · `Utilities & Browsers`

Review volumes and app names come from the export. Ratings, platform splits, trends, themes, and similarity edges are plausible demo metadata generated locally so the interface can be explored without a backend.

---

## Quick start

```sh
npm install
npm run dev
```

Open <http://localhost:5173>. The app starts in **Demo** mode, so no backend is required.

```sh
npm run check     # svelte-check (TypeScript + Svelte diagnostics)
npm run build     # production build
npm run preview   # preview the build
```

Node 20+ is recommended. The project was developed on Node 24.

The Python review processing pipeline is in [`review_parsing/`](review_parsing/README.md). Its setup, input requirements, and one-app command are documented there.

---

## Using the interface

| Action | Result |
|---|---|
| Click a **category hull** | Focus that cluster and narrow the map to its apps |
| Click **All category clusters** | Clear the focus and return to the overview |
| Click an **app node** | Open its overview, reviews, and similar apps in the inspector |
| `Esc` | Close a dialog, or clear the current app selection |
| Drag a node | Pin it; double-click to release it |
| Scroll / drag | Zoom / pan the map |
| `⌘K` / `Ctrl+K` | Search apps, categories, and reviews by meaning |
| `Themes` tab | Corpus-wide positive and negative theme ledger |
| `Category` / `Reception` / `Platform` | Recolour the map |
| **Data source** (top bar) | Switch between the demo corpus and a live API |

The sidebar lists every category with its app count and average reception, and expands to show the apps in that category. On narrow screens the sidebar and inspector collapse into drawers.

---

## Live backend

Click **Data source → Live API**, enter a base URL, and connect. You can also set a default base URL for first load:

```sh
cp .env.example .env
# edit VITE_API_BASE
```

```dotenv
VITE_API_BASE=http://localhost:8000/api
```

`VITE_API_BASE` is only read at startup. A connection made through the dialog is remembered in `localStorage` and takes precedence on later visits. Switch back to **Demo** in the same dialog to clear it.

The UI only needs four endpoints. The full request/response contract is in [`API.md`](./API.md):

```
GET /health
GET /graph
GET /apps/:appId/reviews
GET /search
```

The HTTP adapter lives in [`src/lib/api/http.ts`](src/lib/api/http.ts). If your routes differ, change that file only — the rest of the UI talks to the `UnwrapApi` interface in [`src/lib/api/types.ts`](src/lib/api/types.ts).

CORS must allow the app origin. Requests time out after 20 seconds and non-2xx responses surface in the connection dialog and status bar.

---

## Project structure

```
src/
  routes/
    +page.svelte              app shell, layout, global overlays
    +layout.svelte            favicon + global CSS
  lib/
    api/
      types.ts                UnwrapApi contract and payload types
      index.ts                API factory, theme rollup, graph normalisation
      mock.ts                 60-app demo corpus and generated reviews
      http.ts                 live backend adapter
    components/
      GraphCanvas.svelte      force layout, category hulls, SVG map
      Sidebar.svelte          category list and app drill-down
      Inspector.svelte        app detail and cluster summary
      NetworkView.svelte      graph toolbar and colour modes
      ThemesView.svelte       positive/negative theme ledger
      CommandPalette.svelte   app/category/review search
      ReviewCard.svelte       review result card
      ...                     charts, dialogs, status bar
    state/
      studio.svelte.ts        central runes store
    utils/
      force.ts                custom force simulation
      palette.ts              category accents and reception colours
      format.ts               number/date formatting
  app.css                     design tokens and global styles
```

---

## Design notes

- **Category clusters** use deterministic packed anchors, circular hulls, and per-category accents. Selecting a cluster keeps its apps in place and spreads them for readability.
- **Reception** is a 0–100 composite of star rating, sentiment, and recent trend. It drives the ring around each node and the inspector gauge.
- **Graph state** is kept in `$state.raw` and updated with a tick counter, so the force simulation does not pay for reactive proxies on every frame.
- **No external UI libraries**: the design system, force simulation, sparklines, star bars, and distribution charts are all local SVG/CSS.
- **Demo and live data share the same contract**, so every view works identically in both modes.

---

## Deployment

The project currently uses `@sveltejs/adapter-auto`. If you deploy somewhere adapter-auto does not detect, install the matching adapter (or `@sveltejs/adapter-static` for a fully static build) and update `vite.config.ts`. The app has no server-side data dependencies; all corpus access happens in the browser.

`npm run check` and `npm run build` print a `tsconfig_extends_missing` warning. The root `tsconfig.json` intentionally inlines the compiler options instead of extending `$app/tsconfig` to avoid an Oxc/Vite 8 transform crash in this setup.
