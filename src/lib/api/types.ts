/* ============================================================
   UNWRAP — shared types.

   This is the contract between the UI and your backend.
   Demo data in `mock.ts` and the live adapter in `http.ts`
   both implement `UnwrapApi`.

   The graph is organised by app category (not publisher):
   each cluster is a category, each node is an app.
   ============================================================ */

export type Platform = 'ios' | 'android' | 'both';
export type Sentiment = 'positive' | 'neutral' | 'negative';
export type SourceId = 'gplay' | 'appstore' | string;

export interface Theme {
	/** stable slug, e.g. "ad-blocking" */
	id: string;
	label: string;
	kind: 'positive' | 'negative';
	/** number of reviews that mention this theme (in the corpus, not just the sample) */
	count: number;
	/** 0..1 share of reviews that mention it */
	share: number;
	/** representative review snippets */
	examples: string[];
	/** apps where this theme shows up */
	appIds: string[];
	/** correlation between weekly theme mentions and weekly downloads */
	impact?: ThemeImpact;
}

export type SignalConfidence = 'low' | 'moderate' | 'strong';

export interface ThemeImpact {
	/** Pearson r on the weekly series, -1..1 */
	r: number;
	/** positive = theme mentions lead downloads by this many weeks */
	lag: number;
	/** paired weeks behind the correlation */
	n: number;
	/** reviews mentioning the theme */
	mentions: number;
	confidence: SignalConfidence;
}

export interface CorrelationSignal {
	id: string;
	label: string;
	kind: 'positive' | 'negative' | 'neutral';
	/** Pearson r on the weekly series, -1..1 */
	r: number;
	/** positive = signal leads downloads by this many weeks */
	lag: number;
	n: number;
	mentions: number;
	confidence: SignalConfidence;
}

export interface SignalWeek {
	date: string;
	reviews: number;
	positive: number;
	negative: number;
	rating: number;
}

export interface AppSignals {
	weekly: SignalWeek[];
	/** review volume vs downloads */
	volume: CorrelationSignal;
	/** negative-review share vs downloads */
	sentiment: CorrelationSignal;
	/** themes ranked by their signed relationship with downloads */
	drivers: CorrelationSignal[];
}

export interface SentimentBreakdown {
	positive: number;
	neutral: number;
	negative: number;
}

export interface StarBucket {
	stars: 1 | 2 | 3 | 4 | 5;
	count: number;
}

export interface TrendPoint {
	/** ISO date, start of the bucket (week by default) */
	date: string;
	rating: number;
	volume: number;
}

export interface SimilarApp {
	appId: string;
	/** cosine similarity 0..1 */
	score: number;
}

export interface AppNode {
	id: string;
	/** Canonical ID of an available topic-insights-v1 export, independent of demo IDs. */
	insightsId?: string;
	name: string;
	/** category cluster this app belongs to */
	categoryId: string;
	categoryName: string;
	platform: Platform;
	/** short descriptor shown under the app name, e.g. "Banking" */
	subcategory: string;
	/** mean star rating, 1..5 */
	rating: number;
	reviewCount: number;
	/** 0..100 composite reception score */
	reception: number;
	/** change in reception vs the previous period, in points */
	receptionDelta: number;
	sentiment: SentimentBreakdown;
	distribution: StarBucket[];
	trend: TrendPoint[];
	themes: { positive: Theme[]; negative: Theme[] };
	similar: SimilarApp[];
	sources: Record<string, number>;
	/** weekly review signals + correlation against downloads (demo data only) */
	signals?: AppSignals;
	/** optional precomputed 2D projection from the backend (UMAP / PCA) */
	position?: { x: number; y: number };
	/** optional brand colour override */
	accent?: string;
	version?: string;
}

export interface Category {
	id: string;
	name: string;
	/** one-line description of what belongs in this cluster */
	blurb: string;
	appIds: string[];
	rating: number;
	reviewCount: number;
	reception: number;
	receptionDelta: number;
	accent: string;
}

export interface GraphEdge {
	source: string;
	target: string;
	/** similarity 0..1 */
	score: number;
}

export interface CorpusMeta {
	label: string;
	generatedAt: string;
	/** total reviews indexed in the vector store */
	reviewCount: number;
	/** reviews available through the review endpoint (demo shows a sample) */
	sampled: number;
	appCount: number;
	categoryCount: number;
	embeddingDim: number;
	embeddingModel: string;
	avgRating: number;
	window: { from: string; to: string };
	sources: { id: string; name: string; count: number }[];
}

export interface GraphPayload {
	meta: CorpusMeta;
	categories: Category[];
	apps: AppNode[];
	edges: GraphEdge[];
	/** optional global theme rollup — computed client-side when omitted */
	themes?: Theme[];
}

export interface Review {
	id: string;
	appId: string;
	appName: string;
	categoryId: string;
	stars: number;
	date: string;
	title: string;
	text: string;
	source: SourceId;
	version?: string;
	sentiment: Sentiment;
	/** semantic similarity 0..1, present on search hits */
	score?: number;
	themeIds?: string[];
}

export interface SearchHit extends Review {
	score: number;
}

export interface ReviewQuery {
	limit?: number;
	stars?: number;
	sentiment?: Sentiment;
	offset?: number;
}

export interface SearchOptions {
	appId?: string;
	limit?: number;
	/** only include reviews at or above this star rating */
	minStars?: number;
}

export interface UnwrapApi {
	getGraph(): Promise<GraphPayload>;
	getReviews(appId: string, query?: ReviewQuery): Promise<Review[]>;
	searchReviews(query: string, options?: SearchOptions): Promise<SearchHit[]>;
	health(): Promise<{ ok: boolean; detail?: string }>;
}
