import { asset } from '$app/paths';
import { parseAppInsights, parseInsightCatalog, type InsightCatalogEntry } from '#lib/data/insights';

export async function fetchInsightCatalog() {
	const response = await fetch(asset('data/insights/catalog.json' as Parameters<typeof asset>[0]), { cache: 'no-cache' });
	if (!response.ok) throw new Error(`Could not load the insights catalog (HTTP ${response.status})`);
	return parseInsightCatalog(await response.json());
}

export async function fetchAppInsights(entry: InsightCatalogEntry) {
	const response = await fetch(asset(`data/insights/${entry.filename}` as Parameters<typeof asset>[0]), { cache: 'no-cache' });
	if (!response.ok) throw new Error(`Could not load ${entry.name} analytics (HTTP ${response.status})`);
	return parseAppInsights(await response.json(), entry);
}
