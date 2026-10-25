/* Build the download dataset: real public anchors + a modelled recent series. */
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const mapping = JSON.parse(readFileSync(resolve(here, 'mapping.json'), 'utf8'));
const play = JSON.parse(readFileSync(resolve(here, 'raw/play-details.json'), 'utf8'));

const DAY = 86_400_000;
const WEEKS = 26;
const now = Date.now();

/* Category tuning: how much of lifetime installs landed in the last 26 weeks,
   and how iOS rating counts map to installs when Play is unavailable. */
const CATEGORY = {
	social: { growth: 1.3, iosPerRating: 70 },
	music: { growth: 1.2, iosPerRating: 60 },
	tv: { growth: 1.2, iosPerRating: 60 },
	learning: { growth: 1.15, iosPerRating: 70 },
	shopping: { growth: 1.4, iosPerRating: 60 },
	finance: { growth: 1.1, iosPerRating: 80 },
	health: { growth: 1.15, iosPerRating: 75 },
	photo: { growth: 1.3, iosPerRating: 60 },
	dating: { growth: 1.1, iosPerRating: 80 },
	travel: { growth: 1.15, iosPerRating: 70 },
	games: { growth: 1.2, iosPerRating: 55 },
	work: { growth: 1.05, iosPerRating: 75 },
	utilities: { growth: 1.1, iosPerRating: 70 }
};

function mulberry32(seed) {
	return function rand() {
		seed |= 0;
		seed = (seed + 0x6d2b79f5) | 0;
		let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
		t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
		return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
	};
}

function hash(str) {
	let h = 2166136261;
	for (let i = 0; i < str.length; i++) {
		h ^= str.charCodeAt(i);
		h = Math.imul(h, 16777619);
	}
	return h >>> 0;
}

function parseDate(value) {
	if (!value) return null;
	if (typeof value === 'number') return new Date(value);
	const d = new Date(value);
	return Number.isNaN(d.getTime()) ? null : d;
}

const round = (n, step) => Math.round(n / step) * step;
const clamp = (n, lo, hi) => Math.min(hi, Math.max(lo, n));

const out = {
	meta: {
		asOf: new Date(now).toISOString().slice(0, 10),
		generatedAt: new Date(now).toISOString(),
		appCount: mapping.length,
		country: 'us',
		method:
			'Lifetime installs from the published Google Play install bracket (lower bound + a seeded in-bracket factor) or the App Store rating count. The 26-week series and daily rate are modelled from app age and category growth, not observed snapshots.',
		sources: [
			{
				id: 'gplay',
				name: 'Google Play (public install bracket + ratings)',
				url: 'https://play.google.com'
			},
			{
				id: 'appstore',
				name: 'Apple iTunes Search API (US rating count)',
				url: 'https://itunes.apple.com'
			}
		],
		confidence: 'estimated'
	},
	apps: {}
};

const summary = [];

for (const app of mapping) {
	const p = app.play?.appId ? play[app.play.appId] : null;
	const cfg = CATEGORY[app.categoryId] ?? CATEGORY.utilities;

	const released = parseDate(p?.released) ?? parseDate(app.ios?.released);
	const ageDays = released ? Math.max(365, Math.round((now - released.getTime()) / DAY)) : 3650;

	let installs = 0;
	let installsLow = null;
	let installsHigh = null;
	let installsLabel = null;
	let source = 'estimate';
	let installsConfidence = 'estimated';

	if (p?.minInstalls) {
		installsLow = p.minInstalls;
		installsHigh = p.maxInstalls ?? p.minInstalls * 1.6;
		/* Google's maxInstalls is a generous upper bound, so the bracket midpoint
		   overshoots for 1B+ apps. Pick a seeded point just above the published
		   lower bound instead, so equal brackets don't produce identical totals. */
		const factor = 1.06 + mulberry32(hash(`${app.id}:installs`))() * 0.34;
		installs = installsLow * Math.min(factor, Math.max(1.1, installsHigh / installsLow));
		installsLabel = p.installs ?? null;
		source = 'play';
		installsConfidence = 'bracket';
	} else if (app.ios?.ratings) {
		installs = app.ios.ratings * cfg.iosPerRating;
		source = 'appstore';
	}

	/* A slice of lifetime installs for the last 26 weeks. Older apps get a
	   smaller slice; high-growth categories get a larger one. */
	const recentShare = clamp((182 / ageDays) * cfg.growth, 0.02, 0.2);
	const recentTotal = Math.max(1000, installs * recentShare);

	/* Shape the weekly series: gentle growth + deterministic noise, normalised
	   so the sum is exactly the modelled recent total. */
	const rand = mulberry32(hash(app.id));
	const weights = [];
	for (let i = 0; i < WEEKS; i++) {
		const t = i / (WEEKS - 1);
		const trend = 0.8 + t * 0.4;
		const noise = 0.88 + rand() * 0.24;
		weights.push(trend * noise);
	}
	const weightSum = weights.reduce((a, b) => a + b, 0);

	const weekly = weights.map((weight, i) => {
		const date = new Date(now - (WEEKS - 1 - i) * 7 * DAY);
		return {
			date: date.toISOString().slice(0, 10),
			downloads: Math.max(100, round((weight / weightSum) * recentTotal, 100))
		};
	});

	/* Renormalise after rounding so the series matches the rate. */
	const weeklySum = weekly.reduce((a, b) => a + b.downloads, 0);
	const scale = recentTotal / weeklySum;
	for (const point of weekly) point.downloads = Math.max(100, round(point.downloads * scale, 100));

	/* Give each series one or two demand shocks. These are what the review
	   themes are later sampled around, so the correlation view has a story. */
	const eventRand = mulberry32(hash(`${app.id}:events`));
	const events = [];
	if (eventRand() < 0.72) {
		const week = 6 + Math.floor(eventRand() * 13);
		const factor = 0.72 + eventRand() * 0.16;
		weekly[week].downloads = Math.max(100, round(weekly[week].downloads * factor, 100));
		if (week + 1 < WEEKS) {
			weekly[week + 1].downloads = Math.max(
				100,
				round(weekly[week + 1].downloads * (factor + 0.05), 100)
			);
		}
		events.push({ week, kind: 'dip', factor: Number(factor.toFixed(2)) });
	}
	if (eventRand() < 0.65) {
		const week = 4 + Math.floor(eventRand() * 16);
		const factor = 1.18 + eventRand() * 0.2;
		weekly[week].downloads = Math.max(100, round(weekly[week].downloads * factor, 100));
		events.push({ week, kind: 'spike', factor: Number(factor.toFixed(2)) });
	}

	const finalSum = weekly.reduce((a, b) => a + b.downloads, 0);
	const actualShare = finalSum / installs;

	const last4 = weekly.slice(-4).reduce((a, b) => a + b.downloads, 0);
	const prev4 = weekly.slice(-8, -4).reduce((a, b) => a + b.downloads, 0);
	const rateDelta = prev4 > 0 ? Number((last4 / prev4 - 1).toFixed(3)) : 0;
	const ratePerDay = Math.round(finalSum / (WEEKS * 7));

	out.apps[app.id] = {
		id: app.id,
		name: app.name,
		categoryId: app.categoryId,
		platform: app.platform,
		installs: round(installs, 1000),
		installsLow,
		installsHigh,
		installsLabel,
		iosRatings: app.ios?.ratings ?? null,
		androidRatings: p?.ratings ?? null,
		iosAverage: app.ios?.average ?? null,
		androidAverage: p?.score ? Number(p.score.toFixed(2)) : null,
		ageDays,
		recentShare: Number(actualShare.toFixed(3)),
		ratePerDay,
		rateDelta,
		source,
		installsConfidence,
		confidence: 'estimated',
		asOf: out.meta.asOf,
		weekly,
		events,
		provenance: {
			playAppId: app.play?.appId ?? null,
			playTitle: p?.title ?? app.play?.title ?? null,
			playDeveloper: p?.developer ?? app.play?.developer ?? null,
			playUrl: p?.url ?? null,
			iosTrackId: app.ios?.trackId ?? null,
			iosTitle: app.ios?.title ?? null,
			iosDeveloper: app.ios?.developer ?? null
		},
		notes: app.notes || undefined
	};

	summary.push({
		id: app.id,
		name: app.name,
		category: app.categoryId,
		installs: out.apps[app.id].installs,
		ratePerDay,
		rateDelta,
		source,
		iosRatings: out.apps[app.id].iosRatings,
		androidRatings: out.apps[app.id].androidRatings
	});
}

/* Category rollups help the sidebar without recomputing in the UI. */
out.categories = {};
for (const app of Object.values(out.apps)) {
	const c = (out.categories[app.categoryId] ??= {
		id: app.categoryId,
		apps: 0,
		installs: 0,
		ratePerDay: 0
	});
	c.apps++;
	c.installs += app.installs;
	c.ratePerDay += app.ratePerDay;
}
for (const c of Object.values(out.categories)) c.ratePerDay = Math.round(c.ratePerDay);

mkdirSync(resolve(here, 'out'), { recursive: true });
writeFileSync(resolve(here, 'out/downloads.json'), JSON.stringify(out, null, 2) + '\n');

/* Keep the raw counters too. Tomorrow's run can diff against this file to get a
   measured rate instead of the model. */
const snapshot = { asOf: out.meta.asOf, capturedAt: out.meta.generatedAt, apps: {} };
for (const app of mapping) {
	const p = app.play?.appId ? play[app.play.appId] : null;
	snapshot.apps[app.id] = {
		playAppId: app.play?.appId ?? null,
		playInstalls: p?.installs ?? null,
		playMinInstalls: p?.minInstalls ?? null,
		playMaxInstalls: p?.maxInstalls ?? null,
		playRatings: p?.ratings ?? null,
		iosTrackId: app.ios?.trackId ?? null,
		iosRatings: app.ios?.ratings ?? null,
		iosAverage: app.ios?.average ?? null,
		released: p?.released ?? app.ios?.released ?? null
	};
}
writeFileSync(
	resolve(here, `out/snapshot-${out.meta.asOf}.json`),
	JSON.stringify(snapshot, null, 2) + '\n'
);

const csv = [
	'id,name,category,installs,rate_per_day,rate_delta,source,ios_ratings,android_ratings',
	...summary.map((r) =>
		[
			r.id,
			`"${r.name.replace(/"/g, '""')}"`,
			r.category,
			r.installs,
			r.ratePerDay,
			r.rateDelta,
			r.source,
			r.iosRatings ?? '',
			r.androidRatings ?? ''
		].join(',')
	)
].join('\n');
writeFileSync(resolve(here, 'out/downloads.csv'), csv + '\n');

const top = [...summary].sort((a, b) => b.ratePerDay - a.ratePerDay).slice(0, 10);
const totalRate = summary.reduce((a, b) => a + b.ratePerDay, 0);
console.log(`built ${summary.length} apps`);
console.log(`total modelled rate: ${totalRate.toLocaleString()} downloads/day`);
console.log('\ntop by modelled rate/day:');
for (const r of top) {
	console.log(
		`  ${r.name.padEnd(26)} ${Math.round(r.installs / 1e6)}M installs  ${r.ratePerDay.toLocaleString().padStart(10)}/day  ${(r.rateDelta * 100).toFixed(1)}%`
	);
}
