import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import test from 'node:test';

const read = (path) => JSON.parse(readFileSync(new URL(path, import.meta.url), 'utf8'));
const logos = read('../src/lib/data/app-logos.json');
const sources = read('../static/logos/sources.json');
const apps = read('./downloads/mapping.json');

test('every primary app has local artwork from its mapped App Store ID', () => {
	for (const app of apps) {
		assert(logos[app.id], app.id);
		assert.equal(sources[app.id].kind, 'app-store');
		assert.equal(sources[app.id].trackId, app.ios.trackId);
	}
});

test('logo paths are local assets and every referenced file exists', () => {
	for (const path of Object.values(logos)) {
		assert(/^logos\/[a-z0-9-]+\.(png|jpg|svg|webp|ico|gif)$/.test(path));
		const file = new URL(`../static/${path}`, import.meta.url);
		assert(existsSync(file));
		assert(readFileSync(file).length > 100);
	}
});
