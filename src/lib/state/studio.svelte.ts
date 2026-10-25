import { createApi, ENV_BASE, normaliseGraph, rollupThemes, type ApiMode } from '#lib/api';
import type { AppNode, Category, GraphPayload, Review, SearchHit, Theme } from '#lib/api/types';
import { downloadStats, type DownloadStats } from '#lib/data/downloads';
import { flowNode } from '#lib/data/flows';
import { flowsState } from '#lib/state/flows.svelte';
import { fetchAppInsights, fetchInsightCatalog } from '#lib/api/insights';
import { findInsightEntry, type AppInsights, type InsightCatalogEntry } from '#lib/data/insights';
import { fmtCount, fmtRate } from '#lib/utils/format';

const browser = typeof window !== 'undefined';

export type ColourMode = 'category' | 'reception' | 'platform';
export type MetricMode = 'reviews' | 'downloads';
export type ReviewSort = 'recent' | 'lowest' | 'highest';
export type SentimentFilter = 'all' | 'positive' | 'neutral' | 'negative';
export type InspectorTab = 'overview' | 'reviews' | 'flows';

const LS_MODE = 'unwrap:mode';
const LS_BASE = 'unwrap:base';
const LS_METRIC = 'unwrap:metric';

function appHasTheme(app: AppNode, themeId: string): boolean {
	return (
		app.themes.positive.some((t) => t.id === themeId) ||
		app.themes.negative.some((t) => t.id === themeId)
	);
}

function themeInApp(app: AppNode, themeId: string): Theme | undefined {
	return [...app.themes.positive, ...app.themes.negative].find((t) => t.id === themeId);
}

class StudioState {
	mode = $state<ApiMode>('demo');
	apiBase = $state('');
	graph = $state.raw<GraphPayload | null>(null);
	loading = $state(true);
	error = $state<string | null>(null);
	syncedAt = $state<number | null>(null);

	colourMode = $state<ColourMode>('category');
	metric = $state<MetricMode>('reviews');
	query = $state('');
	themeFilter = $state<string | null>(null);
	categoryFilter = $state<string | null>(null);
	zoomingCategory = $state<string | null>(null);

	selected = $state<{ kind: 'app'; id: string } | null>(null);
	hoveredId = $state<string | null>(null);

	reviews = $state.raw<Review[]>([]);
	reviewsLoading = $state(false);
	reviewSort = $state<ReviewSort>('recent');
	starFilter = $state<number | null>(null);
	sentimentFilter = $state<SentimentFilter>('all');

	paletteOpen = $state(false);
	connectOpen = $state(false);
	helpOpen = $state(false);
	inspectorOpen = $state(true);
	inspectorTab = $state<InspectorTab>('overview');
	insightCatalog = $state.raw<InsightCatalogEntry[]>([]);
	insightCatalogError = $state<string | null>(null);
	insightData = $state.raw<Record<string, AppInsights>>({});
	insightStatus = $state<Record<string, 'loading' | 'ready' | 'error'>>({});
	insightErrors = $state<Record<string, string>>({});
	insightTopic = $state<{ appId: string; topicId: string } | null>(null);

	private api = createApi('demo', '');
	private reviewCache = new Map<string, Review[]>();
	private requestId = 0;
	private initialised = false;
	private insightCatalogPromise: Promise<void> | undefined;
	private insightRequests = new Map<string, Promise<void>>();

	/* ---------------------------- derived ---------------------------- */

	get categories(): Category[] {
		const apps = this.apps;
		return (this.graph?.categories ?? []).map((category) => ({
			...category,
			reviewCount: apps.filter((app) => app.categoryId === category.id).reduce((sum, app) => sum + app.reviewCount, 0)
		}));
	}

	get apps(): AppNode[] {
		return (this.graph?.apps ?? []).map((app) => {
			const entry = findInsightEntry(app, this.insightCatalog);
			if (!entry) return app;
			const data = this.insightData[entry.id];
			return {
				...app,
				insightsId: entry.id,
				reviewCount: entry.reviewCount,
				rating: data?.summary.average_stars ?? app.rating,
				distribution: data?.summary.star_distribution ?? [],
				// These exports do not provide sentiment, shared themes, install correlations or rating time series.
				themes: { positive: [], negative: [] },
				signals: undefined,
				trend: [],
				similar: [],
				sources: {}
			};
		});
	}

	get meta() {
		if (!this.graph) return null;
		return { ...this.graph.meta, reviewCount: this.apps.reduce((sum, app) => sum + app.reviewCount, 0) };
	}

	get themes(): Theme[] {
		if (!this.graph) return [];
		if (this.insightCatalog.length) return rollupThemes(this.apps.filter((app) => !app.insightsId));
		return this.graph.themes?.length ? this.graph.themes : rollupThemes(this.graph.apps);
	}

	get positiveThemes(): Theme[] {
		return this.themes.filter((t) => t.kind === 'positive').sort((a, b) => b.count - a.count);
	}

	get negativeThemes(): Theme[] {
		return this.themes.filter((t) => t.kind === 'negative').sort((a, b) => b.count - a.count);
	}

	get selectedApp(): AppNode | undefined {
		return this.selected?.kind === 'app'
			? this.apps.find((a) => a.id === this.selected!.id)
			: undefined;
	}

	get selectedInsightEntry(): InsightCatalogEntry | undefined {
		const app = this.selectedApp;
		return app ? findInsightEntry(app, this.insightCatalog) : undefined;
	}

	get selectedInsights(): AppInsights | undefined {
		const entry = this.selectedInsightEntry;
		return entry ? this.insightData[entry.id] : undefined;
	}

	ratingFor(app: AppNode): number | null {
		return app.insightsId ? this.insightData[app.insightsId]?.summary.average_stars ?? null : app.rating;
	}

	async loadInsightCatalog(retry = false): Promise<void> {
		if (retry) this.insightCatalogPromise = undefined;
		if (!this.insightCatalogPromise) {
			this.insightCatalogPromise = (async () => {
				try {
					this.insightCatalog = await fetchInsightCatalog();
					this.insightCatalogError = null;
				} catch (error) {
					this.insightCatalogError = error instanceof Error ? error.message : String(error);
				}
			})();
		}
		await this.insightCatalogPromise;
		if (retry && this.selectedInsightEntry) await this.loadInsights(this.selectedInsightEntry);
	}

	async loadInsights(entry: InsightCatalogEntry, retry = false): Promise<void> {
		if (this.insightData[entry.id] && !retry) return;
		const pending = this.insightRequests.get(entry.id);
		if (pending) return pending;
		this.insightStatus[entry.id] = 'loading';
		delete this.insightErrors[entry.id];
		const request = (async () => {
			try {
				const data = await fetchAppInsights(entry);
				this.insightData = { ...this.insightData, [entry.id]: data };
				this.insightStatus[entry.id] = 'ready';
			} catch (error) {
				this.insightErrors[entry.id] = error instanceof Error ? error.message : String(error);
				this.insightStatus[entry.id] = 'error';
			} finally {
				this.insightRequests.delete(entry.id);
			}
		})();
		this.insightRequests.set(entry.id, request);
		return request;
	}

	get selectedCategory(): Category | undefined {
		return this.categoryFilter
			? this.categories.find((c) => c.id === this.categoryFilter)
			: undefined;
	}

	get selectedName(): string {
		return this.selectedApp?.name ?? this.selectedCategory?.name ?? '';
	}

	get categoryApps(): AppNode[] {
		const category = this.selectedCategory;
		if (!category) return [];
		return this.apps
			.filter((a) => a.categoryId === category.id)
			.sort((a, b) => this.metricValue(b) - this.metricValue(a));
	}

	/* --------------------------- downloads --------------------------- */

	get metricTitle(): string {
		return this.metric === 'downloads' ? 'downloads' : 'reviews';
	}

	get metricUnit(): string {
		return this.metric === 'downloads' ? '/day' : 'reviews';
	}

	metricValue(app: AppNode): number {
		if (this.metric === 'downloads') return downloadStats(app.id)?.ratePerDay ?? 0;
		return app.reviewCount;
	}

	metricLabelFor(app: AppNode): string {
		if (this.metric === 'downloads') {
			const stats = downloadStats(app.id);
			return stats ? fmtRate(stats.ratePerDay) : '—';
		}
		return fmtCount(app.reviewCount);
	}

	downloadsFor(appId: string): DownloadStats | undefined {
		return downloadStats(appId);
	}

	categoryDownloads(categoryId: string): { installs: number; ratePerDay: number } {
		let installs = 0;
		let ratePerDay = 0;
		for (const app of this.apps) {
			if (app.categoryId !== categoryId) continue;
			const stats = downloadStats(app.id);
			if (!stats) continue;
			installs += stats.installs;
			ratePerDay += stats.ratePerDay;
		}
		return { installs, ratePerDay };
	}

	categoryMetricLabel(category: Category): string {
		if (this.metric === 'downloads') {
			return `${fmtRate(this.categoryDownloads(category.id).ratePerDay)} · ${category.appIds.length} apps`;
		}
		return `${fmtCount(category.reviewCount)} reviews · ${category.appIds.length} apps`;
	}

	get visibleRatePerDay(): number {
		return this.visibleApps.reduce(
			(sum, app) => sum + (downloadStats(app.id)?.ratePerDay ?? 0),
			0
		);
	}

	get totalRatePerDay(): number {
		return this.apps.reduce((sum, app) => sum + (downloadStats(app.id)?.ratePerDay ?? 0), 0);
	}

	setMetric(metric: MetricMode) {
		this.metric = metric;
		if (browser) localStorage.setItem(LS_METRIC, metric);
	}

	toggleMetric() {
		this.setMetric(this.metric === 'reviews' ? 'downloads' : 'reviews');
	}

	get mapApps(): AppNode[] {
		const q = this.query.trim().toLowerCase();
		const theme = this.themeFilter;

		return this.apps.filter((app) => {
			if (theme && !appHasTheme(app, theme)) return false;
			if (q) {
				const hit =
					app.name.toLowerCase().includes(q) ||
					app.categoryName.toLowerCase().includes(q) ||
					app.subcategory.toLowerCase().includes(q);
				if (!hit) return false;
			}
			return true;
		});
	}

	get visibleApps(): AppNode[] {
		return this.mapApps.filter((app) => !this.categoryFilter || app.categoryId === this.categoryFilter);
	}

	get visibleCategories(): Category[] {
		const ids = new Set(this.visibleApps.map((a) => a.categoryId));
		return this.categories.filter((c) => ids.has(c.id));
	}

	get visibleEdges() {
		const ids = new Set(this.visibleApps.map((a) => a.id));
		return (this.graph?.edges ?? []).filter((e) => ids.has(e.source) && ids.has(e.target));
	}

	get hasFilters(): boolean {
		return Boolean(this.query.trim() || this.themeFilter || this.categoryFilter);
	}

	get filterCount(): number {
		return (
			(this.query.trim() ? 1 : 0) +
			(this.themeFilter ? 1 : 0) +
			(this.categoryFilter ? 1 : 0)
		);
	}

	get filteredReviews(): Review[] {
		let list = this.reviews;
		if (this.starFilter) list = list.filter((r) => r.stars === this.starFilter);
		if (this.sentimentFilter !== 'all') {
			list = list.filter((r) => r.sentiment === this.sentimentFilter);
		}
		const sorted = [...list];
		if (this.reviewSort === 'recent') {
			sorted.sort((a, b) => new Date(b.date).getTime() - new Date(a.date).getTime());
		} else if (this.reviewSort === 'lowest') {
			sorted.sort((a, b) => a.stars - b.stars);
		} else {
			sorted.sort((a, b) => b.stars - a.stars);
		}
		return sorted;
	}

	get reviewCountLabel(): string {
		return this.filteredReviews.length === this.reviews.length
			? `${this.reviews.length} sampled`
			: `${this.filteredReviews.length} of ${this.reviews.length}`;
	}

	themeFor(app: AppNode, id: string): Theme | undefined {
		return themeInApp(app, id);
	}

	themeById(id: string): Theme | undefined {
		return this.themes.find((t) => t.id === id);
	}

	appsForTheme(id: string): AppNode[] {
		return this.apps
			.filter((a) => appHasTheme(a, id))
			.sort((a, b) => (themeInApp(b, id)?.share ?? 0) - (themeInApp(a, id)?.share ?? 0));
	}

	appsForCategory(id: string): AppNode[] {
		return this.apps
			.filter((a) => a.categoryId === id)
			.sort((a, b) => b.reviewCount - a.reviewCount);
	}

	/* ----------------------------- boot ------------------------------ */

	async init() {
		if (this.initialised) return;
		this.initialised = true;

		if (browser) {
			const savedMode = localStorage.getItem(LS_MODE) as ApiMode | null;
			const savedBase = localStorage.getItem(LS_BASE) ?? '';
			const savedMetric = localStorage.getItem(LS_METRIC) as MetricMode | null;
			if (savedMetric === 'reviews' || savedMetric === 'downloads') this.metric = savedMetric;
			if (savedMode === 'live' && savedBase) {
				this.mode = 'live';
				this.apiBase = savedBase;
			} else if (!savedMode && ENV_BASE) {
				this.mode = 'live';
				this.apiBase = ENV_BASE;
			}
			this.inspectorOpen = window.innerWidth >= 1180;
		} else if (ENV_BASE) {
			this.mode = 'live';
			this.apiBase = ENV_BASE;
		}

		this.api = createApi(this.mode, this.apiBase);
		await this.loadGraph();
	}

	async loadGraph() {
		const request = ++this.requestId;
		this.loading = true;
		this.error = null;

		try {
			const [payload] = await Promise.all([this.api.getGraph(), this.loadInsightCatalog()]);
			if (request !== this.requestId) return;
			this.graph = normaliseGraph(payload);
			this.syncedAt = Date.now();
			this.reviewCache.clear();
			if (this.categoryFilter && !this.categories.some((c) => c.id === this.categoryFilter)) {
				this.categoryFilter = null;
			}
			if (this.selected) {
				const stillExists = this.apps.some((a) => a.id === this.selected!.id);
				if (!stillExists) {
					this.selected = null;
					this.reviews = [];
				} else {
					void this.loadReviews(this.selected.id);
				}
			}
		} catch (error) {
			if (request !== this.requestId) return;
			this.error = error instanceof Error ? error.message : String(error);
			if (!this.graph) this.graph = null;
		} finally {
			if (request === this.requestId) this.loading = false;
		}
	}

	async setMode(mode: ApiMode, baseUrl: string) {
		this.zoomingCategory = null;
		this.mode = mode;
		this.apiBase = baseUrl.trim();
		this.api = createApi(mode, this.apiBase);
		this.selected = null;
		this.reviews = [];
		this.reviewCache.clear();
		this.graph = null;
		this.themeFilter = null;
		this.categoryFilter = null;
		this.query = '';
		if (browser) {
			localStorage.setItem(LS_MODE, mode);
			localStorage.setItem(LS_BASE, this.apiBase);
		}
		await this.loadGraph();
	}

	async testConnection(baseUrl: string) {
		const api = createApi('live', baseUrl);
		return api.health();
	}

	/* --------------------------- selection --------------------------- */

	select(kind: 'app', id: string) {
		flowsState.clearSelection();
		this.selected = { kind, id };
		this.insightTopic = null;
		if (this.categoryFilter) flowsState.selectApp(id);
		this.inspectorOpen = true;
		this.inspectorTab = (flowNode(id)?.edgeCount ?? 0) > 0 ? 'flows' : 'overview';
		this.paletteOpen = false;
		void this.loadReviews(id);
	}

	selectFlowApp(id: string) {
		if (this.apps.some((app) => app.id === id)) {
			this.select('app', id);
			return;
		}
		// Outside apps have flow evidence, but no app-level metadata or reviews.
		this.clearSelection();
		flowsState.selectApp(id);
		this.inspectorOpen = true;
		this.paletteOpen = false;
	}

	appHasReviews(id: string): boolean {
		return (this.apps.find((app) => app.id === id)?.reviewCount ?? 0) > 0 ||
			(flowNode(id)?.totalVolume ?? 0) > 0;
	}

	async loadReviews(appId: string) {
		const app = this.apps.find((app) => app.id === appId);
		const entry = app ? findInsightEntry(app, this.insightCatalog) : undefined;
		if (entry) {
			// Representative snippets have no per-review stars/dates; never replace them with synthetic reviews.
			this.reviews = [];
			this.reviewsLoading = false;
			await this.loadInsights(entry);
			return;
		}
		const cached = this.reviewCache.get(appId);
		if (cached) {
			this.reviews = cached;
			return;
		}

		this.reviewsLoading = true;
		try {
			const list = await this.api.getReviews(appId, { limit: 160 });
			this.reviewCache.set(appId, list);
			if (this.selected?.kind === 'app' && this.selected.id === appId) {
				this.reviews = list;
			}
		} catch (error) {
			this.error = error instanceof Error ? error.message : String(error);
		} finally {
			this.reviewsLoading = false;
		}
	}

	clearSelection() {
		flowsState.clearSelection();
		this.selected = null;
		this.insightTopic = null;
		this.reviews = [];
		this.starFilter = null;
		this.sentimentFilter = 'all';
		this.inspectorTab = 'overview';
	}

	closeInspector() {
		if (browser && window.innerWidth < 1180) {
			this.inspectorOpen = false;
		} else {
			this.clearSelection();
		}
	}

	/* ---------------------------- filters ---------------------------- */

	toggleTheme(id: string) {
		this.themeFilter = this.themeFilter === id ? null : id;
	}

	setCategoryFilter(id: string | null) {
		if (id && id !== this.categoryFilter) {
			this.zoomingCategory = id;
			return;
		}
		this.zoomingCategory = null;
		this.categoryFilter = this.categoryFilter === id ? null : id;
		if (this.categoryFilter) {
			const app = this.selectedApp;
			if (app && app.categoryId !== this.categoryFilter) this.clearSelection();
		}
	}

	finishClusterZoom(id: string) {
		if (this.zoomingCategory !== id) return;
		this.zoomingCategory = null;
		this.categoryFilter = id;
		this.clearSelection();
	}

	clearCategoryFilter() {
		this.zoomingCategory = null;
		this.categoryFilter = null;
	}

	clearFilters() {
		this.zoomingCategory = null;
		this.query = '';
		this.themeFilter = null;
		this.categoryFilter = null;
	}

	/* ----------------------------- search ---------------------------- */

	async searchReviews(
		query: string,
		options: { appId?: string; minStars?: number; limit?: number } = {}
	): Promise<SearchHit[]> {
		if (!query.trim()) return [];
		try {
			const hits = await this.api.searchReviews(query, options);
			// Demo search cannot manufacture evidence for apps backed by real exports.
			return this.mode === 'demo'
				? hits.filter((hit) => !this.apps.find((app) => app.id === hit.appId)?.insightsId)
				: hits;
		} catch (error) {
			this.error = error instanceof Error ? error.message : String(error);
			return [];
		}
	}

	openPalette() {
		this.paletteOpen = true;
	}

	closePalette() {
		this.paletteOpen = false;
	}

	toggleInspector() {
		this.inspectorOpen = !this.inspectorOpen;
	}

	get isLive(): boolean {
		return this.mode === 'live';
	}

	get sourceLabel(): string {
		return this.isLive ? 'Live corpus' : 'Demo corpus';
	}
}

export const studio = new StudioState();
