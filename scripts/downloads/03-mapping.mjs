/* Turn the search candidates into a reviewed mapping. Overrides live here. */
import { readFileSync, writeFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const apps = JSON.parse(readFileSync(resolve(here, 'apps.json'), 'utf8'));
const matches = JSON.parse(readFileSync(resolve(here, 'raw/matches.json'), 'utf8'));

/* Brave came from a direct lookup after the search endpoint rate-limited us. */
matches.brave.ios = [
	{
		trackId: 1052879175,
		bundleId: 'com.brave.ios.browser',
		title: 'Brave Browser & Search Engine',
		developer: 'Brave Software, Inc.',
		ratings: 667943,
		released: '2016-02-19T18:55:32Z',
		score: 2
	}
];

/* The Weather Channel came from a direct search after the retry was rate-limited. */
matches['weather-channel'].ios = [
	{
		trackId: 295646461,
		bundleId: 'com.weather.TWC',
		title: 'The Weather Channel - Radar',
		developer: 'The Weather Channel',
		ratings: 6096297,
		average: 4.76281,
		released: '2008-11-09T00:02:43Z',
		score: 2
	}
];

const PLAY_TITLE = { opera: 'Opera: Private Web Browser' };
const IOS_TITLE = { myradar: 'MyRadar Accurate Weather Radar' };
/* Search ranked a 10k-install impostor above the real banking app. */
const PLAY_APPID = { chime: 'com.onedebit.chime' };

function pick(list, title, appId) {
	if (!list.length) return null;
	if (appId) {
		const exact = list.find((x) => x.appId === appId);
		if (exact) return exact;
	}
	if (title) {
		const found = list.find((x) => x.title.includes(title));
		if (found) return found;
	}
	return list[0];
}

const mapping = [];
for (const app of apps) {
	const row = matches[app.id];
	const play = pick(row.play, PLAY_TITLE[app.id], PLAY_APPID[app.id]);
	const ios = pick(row.ios, IOS_TITLE[app.id]);
	const notes = [];
	if (app.id === 'kolibri-games') notes.push('publisher; app = Idle Miner Tycoon');
	if (app.id === 'hoopla') notes.push('duplicate of hoopla-digital');
	if (!ios) notes.push('iOS match missing');
	if (!play) notes.push('Play match missing');

	mapping.push({
		id: app.id,
		name: app.name,
		categoryId: app.categoryId,
		platform: app.platform,
		volume: app.volume,
		play: play
			? { appId: play.appId, title: play.title, developer: play.developer }
			: null,
		ios: ios
			? {
					trackId: ios.trackId,
					bundleId: ios.bundleId,
					title: ios.title,
					developer: ios.developer,
					ratings: ios.ratings,
					average: ios.average,
					released: ios.released
				}
			: null,
		notes: notes.join('; ')
	});
}

writeFileSync(resolve(here, 'mapping.json'), JSON.stringify(mapping, null, 2) + '\n');

const pad = (s, n) => String(s ?? '—').slice(0, n).padEnd(n);
console.log(`${pad('app', 22)}${pad('play', 34)}${pad('ios', 34)}notes`);
for (const m of mapping) {
	console.log(
		`${pad(m.id, 22)}${pad(m.play?.title, 34)}${pad(m.ios?.title, 34)}${m.notes}`
	);
}
console.log(`\n${mapping.filter((m) => m.play).length}/60 play, ${mapping.filter((m) => m.ios).length}/60 ios`);
