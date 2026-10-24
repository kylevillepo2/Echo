/* Fetch Play details for every mapped package. Cached to raw/play-details.json. */
import { readFileSync, writeFileSync, existsSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import gplay from 'google-play-scraper';

const here = dirname(fileURLToPath(import.meta.url));
const mapping = JSON.parse(readFileSync(resolve(here, 'mapping.json'), 'utf8'));
const cachePath = resolve(here, 'raw/play-details.json');
const cache = existsSync(cachePath) ? JSON.parse(readFileSync(cachePath, 'utf8')) : {};

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

for (const [i, row] of mapping.entries()) {
	if (!row.play?.appId) continue;
	if (cache[row.play.appId]?.title) {
		console.log(`${String(i + 1).padStart(2)}/60 ${row.id} cached`);
		continue;
	}
	try {
		const a = await gplay.app({ appId: row.play.appId, country: 'us', lang: 'en' });
		cache[row.play.appId] = {
			appId: a.appId,
			title: a.title,
			developer: a.developer,
			installs: a.installs,
			minInstalls: a.minInstalls,
			maxInstalls: a.maxInstalls,
			ratings: a.ratings,
			reviews: a.reviews,
			score: a.score,
			released: a.released,
			updated: a.updated,
			version: a.version,
			genre: a.genre,
			url: a.url
		};
		console.log(
			`${String(i + 1).padStart(2)}/60 ${row.id.padEnd(20)} ${a.installs} | ratings ${a.ratings}`
		);
	} catch (error) {
		console.log(`${String(i + 1).padStart(2)}/60 ${row.id.padEnd(20)} ERROR ${error.message}`);
	}
	await sleep(400);
}

writeFileSync(cachePath, JSON.stringify(cache, null, 2) + '\n');
console.log(`\n${Object.keys(cache).length} play records cached`);
