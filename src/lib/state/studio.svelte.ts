import { createApi, ENV_BASE, normaliseGraph, rollupThemes, type ApiMode } from '#lib/api';
import type { AppNode, Category, GraphPayload, Review, SearchHit, Theme } from '#lib/api/types';
import { downloadStats, type DownloadStats } from '#lib/data/downloads';
import { fmtCount, fmtRate } from '#lib/utils/format';

const browser = typeof window !== 'undefined';

export type View = 'network' | 'themes' | 'flows';
export type ColourMode = 'category' | 'reception' | 'platform';
export type MetricMode = 'reviews' | 'downloads';
export type ReviewSort = 'recent' | 'lowest' | 'highest';
export type SentimentFilter = 'all' | 'positive' | 'neutral' | 'negative';
export type InspectorTab = 'overview' | 'reviews' | 'similar';

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

	view = $state<View>('network');
	colourMode = $state<ColourMode>('category');
	metric = $state<MetricMode>('reviews');
	query = $state('');
	themeFilter = $state<string | null>(null);
	categoryFilter = $state<string | null>(null);

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
	sidebarOpen = $state(true);
	inspectorTab = $state<InspectorTab>('overview');

	private api = createApi('demo', '');
	private reviewCache = new Map<string, Review[]>();
	private requestId = 0;
	private initialised = false;

	/* ---------------------------- derived ---------------------------- */

	get categories(): Category[] {
		return this.graph?.categories ?? [];
	}

	get apps(): AppNode[] {
		return this.graph?.apps ?? [];
	}

	get meta() {
		return this.graph?.meta ?? null;
	}

	get themes(): Theme[] {
		if (!this.graph) return [];
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

	get visibleApps(): AppNode[] {
		const q = this.query.trim().toLowerCase();
		const theme = this.themeFilter;
		const category = this.categoryFilter;

		return this.apps.filter((app) => {
			if (category && app.categoryId !== category) return false;
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
			this.sidebarOpen = window.innerWidth >= 980;
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
			const payload = await this.api.getGraph();
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
		this.selected = { kind, id };
		this.inspectorOpen = true;
		this.inspectorTab = 'overview';
		this.paletteOpen = false;
		if (browser && window.innerWidth < 980) this.sidebarOpen = false;
		void this.loadReviews(id);
	}

	async loadReviews(appId: string) {
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
		this.selected = null;
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

	setView(view: View) {
		this.view = view;
	}

	toggleTheme(id: string) {
		this.themeFilter = this.themeFilter === id ? null : id;
	}

	setCategoryFilter(id: string | null) {
		this.categoryFilter = this.categoryFilter === id ? null : id;
		if (this.categoryFilter) {
			const app = this.selectedApp;
			if (app && app.categoryId !== this.categoryFilter) this.clearSelection();
			if (this.view === 'themes') this.view = 'network';
			if (browser && window.innerWidth < 980) this.sidebarOpen = false;
		}
	}

	clearCategoryFilter() {
		this.categoryFilter = null;
	}

	clearFilters() {
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
			return await this.api.searchReviews(query, options);
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

	toggleSidebar() {
		this.sidebarOpen = !this.sidebarOpen;
	}

	get isLive(): boolean {
		return this.mode === 'live';
	}

	get sourceLabel(): string {
		return this.isLive ? 'Live corpus' : 'Demo corpus';
	}
}

export const studio = new StudioState();
