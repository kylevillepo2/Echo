/** Contract for the final topic-insights-v1 exports (not the demo theme model). */
export interface InsightStarBucket {
	stars: 1 | 2 | 3 | 4 | 5;
	count: number;
}

export interface InsightMonth {
	month: string;
	review_count: number;
	partial_month: boolean;
	partial_reasons: string[];
	insufficient_review_volume: boolean;
}

export interface InsightTopicMonth {
	month: string;
	review_count: number;
	total_app_reviews: number;
	percentage_of_monthly_reviews: number | null;
	average_stars: number | null;
	rated_review_count: number;
	change_percentage_points: number | null;
	partial_month: boolean;
	insufficient_review_volume: boolean;
}

export interface InsightExample {
	review_key: string;
	feedback_id: string;
	data_source: string;
	snippet: string;
	cosine_similarity: number;
}

export interface InsightTopic {
	topic_id: string;
	name: string;
	definition: string;
	parent_category_id: string;
	parent_category_name: string;
	rank_by_review_count: number;
	review_count: number;
	percentage_of_all_reviews: number;
	average_stars: number | null;
	rated_review_count: number;
	missing_rating_count: number;
	star_distribution: InsightStarBucket[];
	mean_accepted_cosine_similarity: number | null;
	missing_date_count: number;
	monthly: InsightTopicMonth[];
	trend: {
		label: 'increasing' | 'decreasing' | 'stable' | 'insufficient_data';
		change_percentage_points: number | null;
		latest_complete_month: string | null;
		previous_complete_month: string | null;
	};
	representative_reviews: InsightExample[];
}

export interface AppInsights {
	schema_version: 'topic-insights-v1';
	generated_at: string;
	app: { id: string; name: string; source_app_id: string; pipeline_run_slug: string };
	tagging: {
		method: string;
		topic_representation: string;
		embedding_model: string;
		taxonomy_version: string;
		global_cosine_threshold: number;
		topic_ids_are_app_scoped: boolean;
	};
	summary: {
		total_reviews: number;
		reviews_with_topics: number;
		tagging_coverage_percent: number;
		average_stars: number | null;
		rated_review_count: number;
		missing_rating_count: number;
		star_distribution: InsightStarBucket[];
		earliest_review_date: string | null;
		latest_review_date: string | null;
		missing_date_count: number;
	};
	monthly_reviews: InsightMonth[];
	topics: InsightTopic[];
	metadata: {
		denominator: string;
		review_unit: string;
		similarity_interpretation: string;
		validation_limitation: string;
		coverage_limitation: string;
		taxonomy_scope: string;
		trend_rule: {
			minimum_monthly_reviews: number;
			minimum_topic_mentions_across_two_months: number;
			minimum_change_percentage_points: number;
		};
	};
}

export interface InsightCatalogEntry {
	id: string;
	name: string;
	filename: string;
	reviewCount: number;
	topicCount: number;
	checksPassed: boolean;
	warnings: string[];
}

const aliases: Record<string, string> = {
	bofa: 'bank-of-america-mobile-banking',
	'capital-one': 'capital-one-mobile',
	'credit-karma': 'intuit-credit-karma'
};

export function findInsightEntry(app: { id: string; name: string }, catalog: InsightCatalogEntry[]) {
	const name = app.name.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
	return catalog.find((entry) => entry.id === app.id || entry.id === aliases[app.id] || entry.id === name);
}

function record(value: unknown, label: string): Record<string, unknown> {
	if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error(`Invalid ${label}`);
	return value as Record<string, unknown>;
}

function array(value: unknown, label: string): unknown[] {
	if (!Array.isArray(value)) throw new Error(`Invalid ${label}`);
	return value;
}

function text(value: unknown, label: string): asserts value is string {
	if (typeof value !== 'string' || !value.trim()) throw new Error(`Invalid ${label}`);
}

function number(value: unknown, label: string, nullable = false): void {
	if (nullable && value === null) return;
	if (typeof value !== 'number' || !Number.isFinite(value)) throw new Error(`Invalid ${label}`);
}

function count(value: unknown, label: string): asserts value is number {
	if (typeof value !== 'number' || !Number.isSafeInteger(value) || value < 0) throw new Error(`Invalid ${label}`);
}

function monthId(value: unknown): asserts value is string {
	text(value, 'month');
	if (!/^\d{4}-(0[1-9]|1[0-2])$/.test(value)) throw new Error('Invalid month identifier');
}

function rating(value: unknown, label: string): void {
	number(value, label, true);
	if (value !== null && ((value as number) < 1 || (value as number) > 5)) throw new Error(`Invalid ${label}`);
}

function percentage(value: unknown, label: string, nullable = false): void {
	number(value, label, nullable);
	if (value !== null && ((value as number) < 0 || (value as number) > 100)) throw new Error(`Invalid ${label}`);
}

function distribution(value: unknown, expected: number): void {
	const buckets = array(value, 'star distribution');
	const seen = new Set<number>();
	let total = 0;
	for (const value of buckets) {
		const bucket = record(value, 'star bucket');
		count(bucket.stars, 'stars');
		count(bucket.count, 'star count');
		if (bucket.stars < 1 || bucket.stars > 5 || seen.has(bucket.stars)) throw new Error('Invalid star buckets');
		seen.add(bucket.stars);
		total += bucket.count;
	}
	if (total !== expected) throw new Error('Star counts do not reconcile with rated reviews');
}

/** The report is the catalog. Never use its machine-local absolute output paths as URLs. */
export function parseInsightCatalog(value: unknown): InsightCatalogEntry[] {
	const report = record(value, 'insights catalog');
	if (report.schema_version !== 'topic-insights-v1') throw new Error('Unsupported insights catalog schema');
	const seen = new Set<string>();
	const rows = array(report.apps, 'insights catalog apps');
	count(report.app_count, 'catalog app count');
	if (rows.length !== report.app_count) throw new Error('Catalog app count does not reconcile');
	const entries = rows.map((value) => {
		const app = record(value, 'catalog app');
		text(app.app, 'app name');
		text(app.output, 'export filename');
		const filename = app.output.split(/[\\/]/).at(-1)!;
		if (!/^[a-z0-9]+(?:-[a-z0-9]+)*\.json$/.test(filename)) throw new Error('Unsafe insights filename');
		const id = filename.slice(0, -5);
		if (seen.has(id)) throw new Error('Duplicate insights app');
		seen.add(id);
		count(app.total_reviews, 'app review count');
		count(app.approved_topic_count, 'topic count');
		const checks = record(app.checks, 'aggregation checks');
		return {
			id, name: app.app, filename, reviewCount: app.total_reviews, topicCount: app.approved_topic_count,
			checksPassed: ['app_review_reconciliation', 'topic_review_reconciliation', 'tagged_count_reconciliation', 'rating_reconciliation'].every((key) => checks[key] === true) &&
				Object.values(checks).every((check) => check === true || (Array.isArray(check) && !check.length)),
			warnings: array(app.warnings, 'catalog warnings').filter((warning): warning is string => typeof warning === 'string')
		};
	});
	count(report.total_reviews, 'catalog review total');
	if (entries.reduce((sum, entry) => sum + entry.reviewCount, 0) !== report.total_reviews) throw new Error('Catalog review totals do not reconcile');
	return entries;
}

/** Validate the export boundary, including IDs, null ratings and count reconciliation. */
export function parseAppInsights(value: unknown, entry: InsightCatalogEntry): AppInsights {
	const data = record(value, 'app insights');
	if (data.schema_version !== 'topic-insights-v1') throw new Error('Unsupported app insights schema');
	const app = record(data.app, 'app identity');
	if (app.id !== entry.id) throw new Error('Insights file does not match the requested app');
	for (const field of ['id', 'name', 'source_app_id', 'pipeline_run_slug']) text(app[field], `app ${field}`);
	text(data.generated_at, 'export timestamp');
	const tagging = record(data.tagging, 'tagging');
	for (const field of ['method', 'topic_representation', 'embedding_model', 'taxonomy_version']) text(tagging[field], field);
	number(tagging.global_cosine_threshold, 'cosine threshold');
	const summary = record(data.summary, 'summary');
	for (const field of ['total_reviews', 'reviews_with_topics', 'rated_review_count', 'missing_rating_count', 'missing_date_count']) count(summary[field], field);
	if (summary.total_reviews !== entry.reviewCount || (summary.reviews_with_topics as number) > entry.reviewCount) throw new Error('Insights totals do not match the catalog');
	if ((summary.rated_review_count as number) + (summary.missing_rating_count as number) !== entry.reviewCount) throw new Error('Rating totals do not reconcile');
	rating(summary.average_stars, 'average stars');
	percentage(summary.tagging_coverage_percent, 'tagging coverage');
	distribution(summary.star_distribution, summary.rated_review_count as number);
	const months = array(data.monthly_reviews, 'monthly reviews');
	let monthlyTotal = summary.missing_date_count as number;
	const monthIds = new Set<string>();
	for (const value of months) {
		const month = record(value, 'review month');
		monthId(month.month);
		if (monthIds.has(month.month)) throw new Error('Duplicate review month');
		monthIds.add(month.month);
		count(month.review_count, 'monthly review count');
		if (typeof month.partial_month !== 'boolean' || typeof month.insufficient_review_volume !== 'boolean') throw new Error('Invalid coverage flags');
		monthlyTotal += month.review_count;
	}
	if (monthlyTotal !== entry.reviewCount) throw new Error('Monthly review counts do not reconcile');
	const topics = array(data.topics, 'topics');
	if (topics.length !== entry.topicCount) throw new Error('Topic count does not match the catalog');
	const ids = new Set<string>();
	for (const value of topics) {
		const topic = record(value, 'topic');
		for (const field of ['topic_id', 'name', 'definition', 'parent_category_id', 'parent_category_name']) text(topic[field], field);
		const id = topic.topic_id as string;
		if (ids.has(id)) throw new Error('Duplicate topic ID within an app');
		ids.add(id);
		for (const field of ['review_count', 'rated_review_count', 'missing_rating_count', 'missing_date_count', 'rank_by_review_count']) count(topic[field], field);
		percentage(topic.percentage_of_all_reviews, 'topic share');
		rating(topic.average_stars, 'topic average stars');
		number(topic.mean_accepted_cosine_similarity, 'topic similarity', true);
		if ((topic.rated_review_count as number) + (topic.missing_rating_count as number) !== topic.review_count) throw new Error('Topic rating totals do not reconcile');
		distribution(topic.star_distribution, topic.rated_review_count as number);
		let total = topic.missing_date_count as number;
		const topicMonths = new Set<string>();
		for (const value of array(topic.monthly, 'topic months')) {
			const month = record(value, 'topic month');
			monthId(month.month);
			if (topicMonths.has(month.month)) throw new Error('Duplicate topic month');
			topicMonths.add(month.month);
			count(month.review_count, 'topic monthly count');
			percentage(month.percentage_of_monthly_reviews, 'monthly topic share', true);
			rating(month.average_stars, 'monthly topic rating');
			if (typeof month.partial_month !== 'boolean' || typeof month.insufficient_review_volume !== 'boolean') throw new Error('Invalid topic coverage flags');
			total += month.review_count;
		}
		if (total !== topic.review_count) throw new Error('Monthly topic counts do not reconcile');
		const trend = record(topic.trend, 'topic trend');
		if (!['increasing', 'decreasing', 'stable', 'insufficient_data'].includes(String(trend.label))) throw new Error('Unknown topic trend');
		number(trend.change_percentage_points, 'topic trend change', true);
		for (const value of array(topic.representative_reviews, 'representative reviews')) {
			const review = record(value, 'review excerpt');
			for (const field of ['review_key', 'feedback_id', 'data_source', 'snippet']) text(review[field], field);
			number(review.cosine_similarity, 'review similarity');
		}
	}
	const metadata = record(data.metadata, 'methodology');
	for (const field of ['denominator', 'review_unit', 'similarity_interpretation', 'validation_limitation', 'coverage_limitation', 'taxonomy_scope']) text(metadata[field], field);
	record(metadata.trend_rule, 'trend rule');
	return data as unknown as AppInsights;
}

/** A topic key must never merge identical topic-0001 IDs from different apps. */
export function insightTopicKey(appId: string, topicId: string): string {
	return `${appId}:${topicId}`;
}

/** Export dates are calendar dates, not midnight instants to shift into the browser's timezone. */
export function insightDateLabel(value: string | null): string {
	if (!value) return 'Unknown date';
	const date = new Date(value.length === 10 ? `${value}T00:00:00Z` : value);
	return Number.isNaN(date.getTime()) ? value : date.toLocaleDateString('en-US', {
		month: 'short', day: 'numeric', year: 'numeric', timeZone: 'UTC'
	});
}

export interface InsightReviewSample extends InsightExample {
	topics: { id: string; name: string }[];
}

/** A review may be representative of multiple topics; show it once with all its tags. */
export function insightReviewSamples(data: AppInsights): InsightReviewSample[] {
	const samples = new Map<string, InsightReviewSample>();
	for (const topic of data.topics) {
		for (const review of topic.representative_reviews) {
			const existing = samples.get(review.review_key);
			const tag = { id: insightTopicKey(data.app.id, topic.topic_id), name: topic.name };
			if (existing) {
				if (!existing.topics.some((topic) => topic.id === tag.id)) existing.topics.push(tag);
				if (review.snippet.length > existing.snippet.length) existing.snippet = review.snippet;
			} else samples.set(review.review_key, { ...review, topics: [tag] });
		}
	}
	return [...samples.values()];
}
