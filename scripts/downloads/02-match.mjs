/* Search both stores for each app and keep candidates. No app details fetched yet. */
import { readFileSync, writeFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import gplay from 'google-play-scraper';

const here = dirname(fileURLToPath(import.meta.url));
const apps = JSON.parse(readFileSync(resolve(here, 'apps.json'), 'utf8'));

/* Search terms for names that are aliases / punctuation-sensitive. */
const TERMS = {
	'character-ai': 'Character AI',
	'better-me': 'BetterMe',
	'weather-channel': 'The Weather Channel',
	'kolibri-games': 'Idle Miner Tycoon',
	'my-fitness-pal': 'MyFitnessPal',
	'capital-one': 'Capital One Mobile',
	bofa: 'Bank of America',
	'credit-karma': 'Credit Karma',
	ups: 'UPS Mobile',
	'fetch': 'Fetch Rewards',
	dave: 'Dave Banking',
	flo: 'Flo Period Tracker',
	photoroom: 'PhotoRoom AI Photo Editor',
	libby: 'Libby OverDrive',
	opera: 'Opera Browser',
	brave: 'Brave Private Web Browser',
	myradar: 'MyRadar Weather Radar',
	zoom: 'Zoom Workplace',
	indeed: 'Indeed Job Search',
	'magic-tiles-3': 'Magic Tiles 3',
	'spark-driver': 'Spark Driver',
	roku: 'The Roku App',
	temu: 'Temu',
	'hoopla': 'hoopla digital'
};

const norm = (s) =>
	String(s ?? '')
		.toLowerCase()
		.replace(/[^a-z0-9 ]+/g, ' ')
		.replace(/\b(the|app|official|mobile|for|and|by)\b/g, ' ')
		.replace(/\s+/g, ' ')
		.trim();

function score(query, title) {
	const q = new Set(norm(query).split(' ').filter(Boolean));
	const t = new Set(norm(title).split(' ').filter(Boolean));
	if (!q.size || !t.size) return 0;
	let hit = 0;
	for (const token of q) if (t.has(token)) hit++;
	const coverage = hit / q.size;
	const exact = norm(query) === norm(title) ? 1 : 0;
	const starts = norm(title).startsWith(norm(query)) ? 0.15 : 0;
	return coverage + exact + starts;
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const results = {};
for (const [i, app] of apps.entries()) {
	const term = TERMS[app.id] ?? app.name;
	const row = { id: app.id, name: app.name, term, play: [], ios: [], errors: [] };

	try {
		const list = await gplay.search({ term, num: 6, country: 'us', lang: 'en' });
		row.play = list.map((x) => ({
			appId: x.appId,
			title: x.title,
			developer: x.developer,
			score: score(term, x.title)
		}));
	} catch (error) {
		row.errors.push(`play: ${error.message}`);
	}

	try {
		const url = new URL('https://itunes.apple.com/search');
		url.searchParams.set('term', term);
		url.searchParams.set('entity', 'software');
		url.searchParams.set('country', 'us');
		url.searchParams.set('limit', '6');
		const res = await fetch(url, { headers: { accept: 'application/json' } });
		if (!res.ok) throw new Error(`itunes ${res.status}`);
		const data = await res.json();
		row.ios = (data.results ?? []).map((x) => ({
			trackId: x.trackId,
			bundleId: x.bundleId,
			title: x.trackName,
			developer: x.sellerName,
			ratings: x.userRatingCount,
			released: x.releaseDate,
			score: score(term, x.trackName)
		}));
	} catch (error) {
		row.errors.push(`ios: ${error.message}`);
	}

	row.play.sort((a, b) => b.score - a.score);
	row.ios.sort((a, b) => b.score - a.score);
	results[app.id] = row;

	console.log(
		`${String(i + 1).padStart(2)}/${apps.length} ${app.name.padEnd(30)} ` +
			`play=${row.play[0]?.title ?? '—'} | ios=${row.ios[0]?.title ?? '—'}`
	);
	await sleep(250);
}

writeFileSync(resolve(here, 'raw/matches.json'), JSON.stringify(results, null, 2) + '\n');
console.log('\nwrote raw/matches.json');
