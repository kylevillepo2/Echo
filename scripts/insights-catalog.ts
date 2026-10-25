import { existsSync, readFileSync, readdirSync, writeFileSync } from 'node:fs';
import { basename, dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import type { Plugin } from 'vite';
import { parseAppInsights, parseInsightCatalog, type AppInsights, type InsightCatalogEntry } from '../src/lib/data/insights.ts';

const defaultDirectory = fileURLToPath(new URL('../static/data/insights/', import.meta.url));

/** Discover every app file. A validation report may describe only the latest pipeline run. */
export function buildInsightCatalog(directory = defaultDirectory) {
	let reportDate: string | undefined;
	let reportWarning: string | undefined;
	let reported = new Map<string, InsightCatalogEntry>();
	const reportPath = resolve(directory, 'aggregation_validation_report.json');
	if (existsSync(reportPath)) {
		try {
			const report = JSON.parse(readFileSync(reportPath, 'utf8'));
			reportDate = report.generated_at;
			reported = new Map(parseInsightCatalog(report).map((entry) => [entry.filename, entry]));
		} catch {
			reportWarning = 'The latest aggregation report could not be read; app files were checked independently.';
		}
	}
	const entries: InsightCatalogEntry[] = [];
	for (const filename of readdirSync(directory).sort()) {
		if (filename === 'catalog.json' || !/^[a-z0-9]+(?:-[a-z0-9]+)*\.json$/.test(filename)) continue;
		const value = JSON.parse(readFileSync(resolve(directory, filename), 'utf8')) as AppInsights;
		if (value?.schema_version !== 'topic-insights-v1' || value.app?.id !== filename.slice(0, -5) || typeof value.app?.name !== 'string' || !Array.isArray(value.topics) || !Number.isSafeInteger(value.summary?.total_reviews)) {
			throw new Error(`Invalid app insights export: ${filename}`);
		}
		const report = reported.get(filename);
		const currentReport = report && reportDate === value.generated_at && report.reviewCount === value.summary.total_reviews && report.topicCount === value.topics.length;
		const entry: InsightCatalogEntry = {
			id: value.app.id,
			name: value.app.name,
			filename,
			reviewCount: value.summary.total_reviews,
			topicCount: value.topics.length,
			checksPassed: currentReport ? report.checksPassed : null,
			warnings: currentReport ? report.warnings : reportWarning ? [reportWarning] : []
		};
		try {
			parseAppInsights(value, entry);
		} catch (error) {
			throw new Error(`${filename}: ${error instanceof Error ? error.message : String(error)}`);
		}
		entries.push(entry);
	}
	return {
		schema_version: 'topic-insights-catalog-v1' as const,
		app_count: entries.length,
		total_reviews: entries.reduce((sum, entry) => sum + entry.reviewCount, 0),
		apps: entries
	};
}

function writeCatalog(directory: string) {
	const path = resolve(directory, 'catalog.json');
	const content = `${JSON.stringify(buildInsightCatalog(directory), null, 2)}\n`;
	if (!existsSync(path) || readFileSync(path, 'utf8') !== content) writeFileSync(path, content);
}

/** Generate a lightweight static index before dev/build, and keep additions discoverable in dev. */
export function insightsCatalogPlugin(directory = defaultDirectory): Plugin {
	const root = resolve(directory);
	return {
		name: 'unwrap-insights-catalog',
		enforce: 'pre',
		config() { writeCatalog(root); },
		configureServer(server) {
			let timer: ReturnType<typeof setTimeout> | undefined;
			const update = (path: string) => {
				if (dirname(resolve(path)) !== root || !path.endsWith('.json') || basename(path) === 'catalog.json') return;
				clearTimeout(timer);
				timer = setTimeout(() => {
					try {
						writeCatalog(root);
						server.ws.send({ type: 'full-reload' });
					} catch (error) {
						const message = error instanceof Error ? error.message : String(error);
						server.config.logger.error(message);
						server.ws.send({ type: 'error', err: { message, stack: '' } });
					}
				}, 100);
			};
			server.watcher.add(root);
			for (const event of ['add', 'change', 'unlink']) server.watcher.on(event, update);
			server.httpServer?.once('close', () => {
				clearTimeout(timer);
				for (const event of ['add', 'change', 'unlink']) server.watcher.off(event, update);
			});
		}
	};
}
