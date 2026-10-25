import assert from 'node:assert/strict';
import { EventEmitter } from 'node:events';
import { mkdtempSync, readFileSync, rmSync, unlinkSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { buildInsightCatalog, insightsCatalogPlugin } from './insights-catalog.ts';

const source = (name) => readFileSync(new URL(`../static/data/insights/${name}`, import.meta.url), 'utf8');

test('adding and removing app files updates discovery independently of a partial report', () => {
	const directory = mkdtempSync(join(tmpdir(), 'unwrap-insights-catalog-'));
	try {
		writeFileSync(join(directory, 'aggregation_validation_report.json'), source('aggregation_validation_report.json'));
		writeFileSync(join(directory, 'chime.json'), source('chime.json'));
		assert.deepEqual(buildInsightCatalog(directory).apps.map((app) => app.id), ['chime']);
		writeFileSync(join(directory, 'paypal.json'), source('paypal.json'));
		assert.deepEqual(buildInsightCatalog(directory).apps.map((app) => app.id), ['chime', 'paypal']);
		unlinkSync(join(directory, 'paypal.json'));
		assert.deepEqual(buildInsightCatalog(directory).apps.map((app) => app.id), ['chime']);
	} finally { rmSync(directory, { recursive: true, force: true }); }
});

test('the dev watcher regenerates the derived catalog without rewriting input files', async () => {
	const directory = mkdtempSync(join(tmpdir(), 'unwrap-insights-watch-'));
	const close = new EventEmitter();
	try {
		const chime = source('chime.json');
		const report = source('aggregation_validation_report.json');
		writeFileSync(join(directory, 'chime.json'), chime);
		writeFileSync(join(directory, 'aggregation_validation_report.json'), report);
		const plugin = insightsCatalogPlugin(directory);
		plugin.config();
		const watcher = new EventEmitter();
		watcher.add = () => {};
		let reload;
		plugin.configureServer({
			watcher, httpServer: close,
			config: { logger: { error(message) { assert.fail(message); } } },
			ws: { send(message) { assert.equal(message.type, 'full-reload'); reload?.(); } }
		});
		const readCatalog = () => JSON.parse(readFileSync(join(directory, 'catalog.json'), 'utf8'));
		assert.equal(readCatalog().app_count, 1);
		const added = new Promise((resolve) => { reload = resolve; });
		writeFileSync(join(directory, 'paypal.json'), source('paypal.json'));
		watcher.emit('add', join(directory, 'paypal.json'));
		await added;
		assert.equal(readCatalog().app_count, 2);
		const removed = new Promise((resolve) => { reload = resolve; });
		unlinkSync(join(directory, 'paypal.json'));
		watcher.emit('unlink', join(directory, 'paypal.json'));
		await removed;
		assert.equal(readCatalog().app_count, 1);
		assert.equal(readFileSync(join(directory, 'chime.json'), 'utf8'), chime);
		assert.equal(readFileSync(join(directory, 'aggregation_validation_report.json'), 'utf8'), report);
		close.emit('close');
		assert.equal(watcher.listenerCount('add'), 0);
	} finally { close.emit('close'); rmSync(directory, { recursive: true, force: true }); }
});
