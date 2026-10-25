import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const read = (path) => JSON.parse(readFileSync(new URL(path, import.meta.url), 'utf8'));
const downloads = read('../src/lib/data/downloads.json');
const mapping = read('./downloads/mapping.json');
const apps = read('./downloads/apps.json');

test('Music, TV and audiobooks are categorized consistently', () => {
	const expected = {
		spotify: 'music', soundcloud: 'music', audiomack: 'music',
		crunchyroll: 'tv', tubi: 'tv', roku: 'tv', audible: 'learning'
	};
	for (const [id, category] of Object.entries(expected)) {
		assert.equal(downloads.apps[id].categoryId, category);
		assert.equal(mapping.find((app) => app.id === id)?.categoryId, category);
		assert.equal(apps.find((app) => app.id === id)?.categoryId, category);
	}
	assert.equal(Object.keys(downloads.apps).length, 60);
	assert.equal(Object.keys(downloads.categories).length, 13);
	assert(!downloads.categories.entertainment);
});

test('category totals reconcile with their apps after the split', () => {
	for (const id of ['music', 'tv', 'learning']) {
		const owned = Object.values(downloads.apps).filter((app) => app.categoryId === id);
		assert.deepEqual(downloads.categories[id], {
			id, apps: owned.length,
			installs: owned.reduce((sum, app) => sum + app.installs, 0),
			ratePerDay: owned.reduce((sum, app) => sum + app.ratePerDay, 0)
		});
	}
	assert.deepEqual(downloads, read('./downloads/out/downloads.json'));
});
