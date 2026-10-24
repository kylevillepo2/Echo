/* Render a human-readable report from out/downloads.json. */
import { readFileSync, writeFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const data = JSON.parse(readFileSync(resolve(here, 'out/downloads.json'), 'utf8'));
const apps = JSON.parse(readFileSync(resolve(here, 'apps.json'), 'utf8'));
const catName = Object.fromEntries(apps.map((a) => [a.categoryId, a.categoryName]));

const fmt = (n) => {
	if (n == null) return '—';
	if (n >= 1e9) return `${(n / 1e9).toFixed(2)}B`;
	if (n >= 1e6) return `${(n / 1e6).toFixed(1)}M`;
	if (n >= 1e3) return `${(n / 1e3).toFixed(1)}k`;
	return String(Math.round(n));
};
const fmtInt = (n) => (n == null ? '—' : Math.round(n).toLocaleString('en-US'));
const pct = (n) => `${n >= 0 ? '+' : ''}${(n * 100).toFixed(1)}%`;
const pad = (s, n) => String(s).padEnd(n);

const rows = Object.values(data.apps);
const top = [...rows].sort((a, b) => b.ratePerDay - a.ratePerDay);
const totalInstalls = rows.reduce((a, b) => a + b.installs, 0);
const totalRate = rows.reduce((a, b) => a + b.ratePerDay, 0);
const playAnchors = rows.filter((r) => r.source === 'play').length;

const lines = [];
lines.push('# Unwrap — download dataset');
lines.push('');
lines.push(`Generated **${data.meta.asOf}** for **${rows.length} apps** across ${Object.keys(data.categories).length} categories.`);
lines.push('');
lines.push('> **What is real vs modelled.** Lifetime installs come from the public Google Play install bracket. The 26-week weekly series and the daily rate are **modelled** — neither store publishes download history, and a real rate needs repeated snapshots over time. Every figure is marked `confidence: "estimated"`.');
lines.push('');
lines.push('## Coverage');
lines.push('');
lines.push(`- Apps with a Play install anchor: **${playAnchors}/${rows.length}**`);
lines.push(`- Apps with an App Store rating count: **${rows.filter((r) => r.iosRatings).length}/${rows.length}**`);
lines.push(`- Total lifetime installs (modelled): **${fmt(totalInstalls)}**`);
lines.push(`- Total modelled rate: **${fmtInt(totalRate)} downloads/day**`);
lines.push('');
lines.push('## Sources');
lines.push('');
for (const source of data.meta.sources) lines.push(`- ${source.name} — ${source.url}`);
lines.push('');
lines.push('## Method');
lines.push('');
lines.push(data.meta.method);
lines.push('');
lines.push('In short:');
lines.push('');
lines.push('1. Map each demo app to a Play package and an App Store track ID (`mapping.json`).');
lines.push('2. Pull the public Play install bracket (`minInstalls`/`maxInstalls`) and ratings count.');
lines.push('3. Pull the US App Store `userRatingCount` from the iTunes Search API.');
lines.push('4. Estimate lifetime installs from the Play bracket (lower bound + a seeded in-bracket factor).');
lines.push('5. Model the last 26 weeks as `lifetime installs × clamp(182 / ageDays × categoryGrowth, 0.02, 0.20)`, shaped by deterministic growth + noise.');
lines.push('6. Derive `ratePerDay` and `rateDelta` from that series.');
lines.push('');
lines.push('## Top 15 by modelled rate');
lines.push('');
lines.push('| # | App | Category | Installs | Rate/day | 4w Δ |');
lines.push('|---:|---|---|---:|---:|---:|');
top.slice(0, 15).forEach((r, i) => {
	lines.push(
		`| ${i + 1} | ${r.name} | ${catName[r.categoryId] ?? r.categoryId} | ${fmt(r.installs)} | ${fmtInt(r.ratePerDay)} | ${pct(r.rateDelta)} |`
	);
});
lines.push('');
lines.push('## By category');
lines.push('');
lines.push('| Category | Apps | Installs | Rate/day |');
lines.push('|---|---:|---:|---:|');
for (const c of Object.values(data.categories).sort((a, b) => b.ratePerDay - a.ratePerDay)) {
	lines.push(`| ${catName[c.id] ?? c.id} | ${c.apps} | ${fmt(c.installs)} | ${fmtInt(c.ratePerDay)} |`);
}
lines.push('');
lines.push('## All 60 apps');
lines.push('');
lines.push('| App | Category | Installs | Rate/day | 4w Δ | Source | iOS ratings | Android ratings |');
lines.push('|---|---|---:|---:|---:|---|---:|---:|');
for (const r of top) {
	lines.push(
		`| ${r.name} | ${catName[r.categoryId] ?? r.categoryId} | ${fmt(r.installs)} | ${fmtInt(r.ratePerDay)} | ${pct(r.rateDelta)} | ${r.source} | ${fmtInt(r.iosRatings)} | ${fmtInt(r.androidRatings)} |`
	);
}
lines.push('');
lines.push('## Mapping notes');
lines.push('');
lines.push('- `Chime` — Play search ranked a 10k-install impostor first; mapped to `com.onedebit.chime`.');
lines.push('- `MyRadar` — the App Store result was the paid Pro app; mapped to the free `MyRadar Accurate Weather Radar`.');
lines.push('- `Opera` — Play search returned the beta channel first; mapped to `com.opera.browser`.');
lines.push('- `The Weather Channel` and `Brave` — the iTunes search endpoint rate-limited during the bulk run; filled from a direct lookup.');
lines.push('- `Kolibri Games` — this is a publisher, so the data is for its game **Idle Miner Tycoon**.');
lines.push('- `Hoopla` — the mock dataset has `Hoopla` and `Hoopla Digital` as separate entries; both map to the same app.');
lines.push('- Play installs are global lifetime installs. App Store rating counts are US-only. Do not read the two columns as directly comparable.');
lines.push('');
lines.push('## What would make the rate real');
lines.push('');
lines.push('The model becomes measured data with almost no schema change: run `04-fetch-play.mjs` daily, append the install/rating counts to a snapshot table, and replace `ratePerDay` with `Δinstalls` over the window. Android becomes measured immediately; iOS stays estimated (rating-count delta × category multiplier) because Apple never publishes units for third-party apps.');
lines.push('');
lines.push('## Rerun');
lines.push('');
lines.push('```sh');
lines.push('cd scripts/downloads');
lines.push('node 01-apps.mjs      # extract the 60 apps from mock.ts');
lines.push('node 02-match.mjs     # search both stores (rate-limited)');
lines.push('node 03-mapping.mjs   # apply overrides → mapping.json');
lines.push('node 04-fetch-play.mjs# fetch Play details (cached)');
lines.push('node 05-build.mjs     # model + write out/downloads.json');
lines.push('node 06-report.mjs    # this report');
lines.push('```');
lines.push('');

writeFileSync(resolve(here, 'REPORT.md'), lines.join('\n'));
console.log('wrote REPORT.md');
