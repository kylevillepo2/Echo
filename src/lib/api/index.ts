import { HttpApi } from './http';
import { MockApi } from './mock';
import type { GraphPayload, Theme, UnwrapApi } from './types';
import { mergeImpact } from '#lib/utils/correlation';

export type ApiMode = 'demo' | 'live';

/* Set VITE_API_BASE in .env to point the app at your backend by default. */
export const ENV_BASE =
	((import.meta.env as Record<string, string | undefined> | undefined)?.VITE_API_BASE as
		| string
		| undefined) ?? '';

export function createApi(mode: ApiMode, baseUrl: string): UnwrapApi {
	if (mode === 'live' && baseUrl.trim()) return new HttpApi(baseUrl.trim());
	return new MockApi();
}

/** Compute a corpus-wide theme rollup when the backend does not send one. */
export function rollupThemes(apps: GraphPayload['apps']): Theme[] {
	const map = new Map<string, Theme>();
	const totalReviews = apps.reduce((sum, a) => sum + a.reviewCount, 0) || 1;

	for (const app of apps) {
		for (const theme of [...app.themes.positive, ...app.themes.negative]) {
			const existing = map.get(theme.id);
			if (existing) {
				existing.count += theme.count;
				existing.appIds.push(app.id);
				existing.examples.push(...theme.examples);
				existing.impact = mergeImpact(existing.impact, theme.impact);
			} else {
				map.set(theme.id, {
					...theme,
					examples: [...theme.examples],
					appIds: [app.id]
				});
			}
		}
	}

	for (const theme of map.values()) {
		theme.share = Math.min(1, theme.count / totalReviews);
		theme.examples = [...new Set(theme.examples)].slice(0, 4);
		theme.appIds = [...new Set(theme.appIds)];
	}
	return [...map.values()].sort((a, b) => b.count - a.count);
}

export function normaliseGraph(graph: GraphPayload): GraphPayload {
	if (graph.themes?.length) return graph;
	return { ...graph, themes: rollupThemes(graph.apps) };
}
