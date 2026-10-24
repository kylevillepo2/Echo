/* Retry the iTunes searches that hit the rate limit (403/429). Slow on purpose. */
import { readFileSync, writeFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const path = resolve(here, 'raw/matches.json');
const matches = JSON.parse(readFileSync(path, 'utf8'));

const RETRY = {
	zoom: 'Zoom Workplace',
	'weather-channel': 'The Weather Channel',
	opera: 'Opera Browser',
	brave: 'Brave Private Web Browser'
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
	let hit = 0;
	for (const token of q) if (t.has(token)) hit++;
	return hit / Math.max(1, q.size) + (norm(query) === norm(title) ? 1 : 0);
}

for (const [id, term] of Object.entries(RETRY)) {
	const url = new URL('https://itunes.apple.com/search');
	url.searchParams.set('term', term);
	url.searchParams.set('entity', 'software');
	url.searchParams.set('country', 'us');
	url.searchParams.set('limit', '8');
	const res = await fetch(url, { headers: { accept: 'application/json' } });
	console.log(id, res.status);
	if (!res.ok) {
		console.log('  retry later:', await res.text().catch(() => ''));
		await new Promise((r) => setTimeout(r, 8000));
		continue;
	}
	const data = await res.json();
	matches[id].ios = (data.results ?? []).map((x) => ({
		trackId: x.trackId,
		bundleId: x.bundleId,
		title: x.trackName,
		developer: x.sellerName,
		ratings: x.userRatingCount,
		average: x.averageUserRating,
		released: x.releaseDate,
		score: score(term, x.trackName)
	}));
	matches[id].ios.sort((a, b) => b.score - a.score);
	matches[id].errors = [];
	console.log('  →', matches[id].ios.slice(0, 3).map((x) => `${x.title} :: ${x.developer}`));
	await new Promise((r) => setTimeout(r, 6000));
}

writeFileSync(path, JSON.stringify(matches, null, 2) + '\n');
console.log('updated raw/matches.json');
