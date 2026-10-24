/* ============================================================
   Live backend adapter.

   Expected endpoints (all JSON, CORS enabled):

     GET  {base}/health
     GET  {base}/graph
     GET  {base}/apps/:appId/reviews?limit=&stars=&sentiment=
     GET  {base}/search?q=&appId=&minStars=&limit=

   See API.md for response shapes. Adjust only this file if your
   routes differ — the rest of the UI stays untouched.
   ============================================================ */

import type {
	GraphPayload,
	Review,
	ReviewQuery,
	SearchHit,
	SearchOptions,
	UnwrapApi
} from './types';

export class HttpApi implements UnwrapApi {
	private base: string;

	constructor(baseUrl: string) {
		let base = baseUrl.trim().replace(/\/+$/, '');
		if (base && !/^https?:\/\//i.test(base)) base = `http://${base}`;
		this.base = base;
	}

	private async request<T>(path: string, params?: Record<string, string | number | undefined>) {
		const url = new URL(`${this.base}${path}`);
		if (params) {
			for (const [key, value] of Object.entries(params)) {
				if (value !== undefined && value !== '') url.searchParams.set(key, String(value));
			}
		}

		const res = await fetch(url.toString(), {
			headers: { accept: 'application/json' },
			signal: AbortSignal.timeout(20_000)
		});

		if (!res.ok) {
			const body = await res.text().catch(() => '');
			throw new Error(`${res.status} ${res.statusText}${body ? ` — ${body.slice(0, 160)}` : ''}`);
		}
		return (await res.json()) as T;
	}

	async getGraph(): Promise<GraphPayload> {
		return this.request<GraphPayload>('/graph');
	}

	async getReviews(appId: string, query: ReviewQuery = {}): Promise<Review[]> {
		const data = await this.request<Review[] | { reviews: Review[] }>(
			`/apps/${encodeURIComponent(appId)}/reviews`,
			{
				limit: query.limit ?? 120,
				offset: query.offset,
				stars: query.stars,
				sentiment: query.sentiment
			}
		);
		return Array.isArray(data) ? data : data.reviews;
	}

	async searchReviews(query: string, options: SearchOptions = {}): Promise<SearchHit[]> {
		if (!query.trim()) return [];
		const data = await this.request<SearchHit[] | { hits: SearchHit[] }>('/search', {
			q: query,
			appId: options.appId,
			minStars: options.minStars,
			limit: options.limit ?? 24
		});
		return Array.isArray(data) ? data : data.hits;
	}

	async health() {
		try {
			const detail = await this.request<{ ok?: boolean; detail?: string }>('/health');
			return { ok: detail.ok !== false, detail: detail.detail };
		} catch (error) {
			return { ok: false, detail: error instanceof Error ? error.message : 'unreachable' };
		}
	}
}
