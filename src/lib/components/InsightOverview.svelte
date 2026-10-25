<script lang="ts">
	import { tick } from 'svelte';
	import { studio } from '#lib/state/studio.svelte';
	import { insightDateLabel, insightReviewSamples, insightTopicKey, type AppInsights, type InsightCatalogEntry, type InsightTopic } from '#lib/data/insights';
	import { fmtFull } from '#lib/utils/format';
	import { topicAverageLabel, topicRatingGroup, topicRatingGroups, type TopicRatingGroup } from '#lib/utils/topic-rating';
	import InsightChart from './InsightChart.svelte';
	import InsightDistribution from './InsightDistribution.svelte';
	import InsightExamples from './InsightExamples.svelte';

	let { data, entry }: { data: AppInsights; entry: InsightCatalogEntry } = $props();
	let query = $state('');
	let group = $state('all');
	let sort = $state('mentions');
	let expandedGroups = $state<TopicRatingGroup[]>([]);
	let detail = $state<HTMLElement>();
	let lastApp = '';
	$effect(() => {
		if (data.app.id !== lastApp) {
			lastApp = data.app.id;
			query = ''; group = 'all'; sort = 'mentions'; expandedGroups = [];
		}
	});
	const groups = $derived([...new Set(data.topics.map((topic) => topic.parent_category_name))].sort());
	const topics = $derived(data.topics.filter((topic) =>
		(group === 'all' || topic.parent_category_name === group) &&
		`${topic.name} ${topic.definition} ${topic.parent_category_name}`.toLowerCase().includes(query.trim().toLowerCase())
	).sort((a, b) => {
		if (sort === 'rating') return (a.average_stars ?? Infinity) - (b.average_stars ?? Infinity) || b.review_count - a.review_count;
		if (sort === 'change') return (b.trend.change_percentage_points ?? -Infinity) - (a.trend.change_percentage_points ?? -Infinity) || b.review_count - a.review_count;
		return b.review_count - a.review_count || a.topic_id.localeCompare(b.topic_id);
	}));
	const ratingGroups = $derived(topicRatingGroups.map((bucket) => ({
		...bucket, topics: topics.filter((topic) => topicRatingGroup(topic) === bucket.id)
	})));
	const selected = $derived(studio.insightTopic?.appId === data.app.id
		? data.topics.find((topic) => topic.topic_id === studio.insightTopic?.topicId) : undefined);
	const selectedRatingGroup = $derived(selected ? topicRatingGroups.find((bucket) => bucket.id === topicRatingGroup(selected)) : undefined);
	const samples = $derived(insightReviewSamples(data));
	const topicSamples = $derived(selected ? samples.filter((sample) => sample.topics.some((topic) => topic.id === insightTopicKey(data.app.id, selected.topic_id))) : []);
	const monthLabel = (month: string | null) => month ? new Date(`${month}-01T00:00:00Z`).toLocaleDateString('en-US', { month: 'short', year: 'numeric', timeZone: 'UTC' }) : '—';

	function trendLabel(topic: InsightTopic): string {
		if (topic.trend.label === 'insufficient_data') return 'Not enough data';
		if (topic.trend.label === 'stable') return 'Stable';
		const change = topic.trend.change_percentage_points;
		return `${topic.trend.label === 'increasing' ? '↑' : '↓'} ${Math.abs(change ?? 0).toFixed(1)} pp`;
	}

	async function openTopic(topic: InsightTopic) {
		studio.insightTopic = { appId: data.app.id, topicId: topic.topic_id };
		await tick();
		detail?.scrollIntoView({ behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth', block: 'start' });
	}
</script>

<section class="export-note" aria-label="Insights export coverage">
	<span class="label">Imported review analytics</span>
	{#if entry.checksPassed === false}<p class="validation-warning" role="alert">Some export aggregation checks did not pass. Treat these counts as provisional.</p>{/if}
	<p><b class="num">{fmtFull(data.summary.total_reviews)}</b> reviews · {data.topics.length} app-specific topics</p>
	<p>{insightDateLabel(data.summary.earliest_review_date)} – {insightDateLabel(data.summary.latest_review_date)}</p>
	<p>{fmtFull(data.summary.reviews_with_topics)} reviews matched topics ({data.summary.tagging_coverage_percent.toFixed(1)}%). Shares use <b>all app reviews</b>, including untagged reviews. Topics can overlap.</p>
</section>

<section class="block topics-block" aria-label="Exported review topics">
	<div class="block-head"><span class="label-dim">Signals · review topics</span><span class="num soft">{topics.length} topics</span></div>
	<p class="note">Grouped by matching reviews’ average rating: positive 4★+, negative below 3★, mixed 3–under 4★. This is rating-based, not text sentiment; small samples can skew averages. Select a topic for its trend and reviews.</p>
	<input class="input" type="search" aria-label="Search review topics" placeholder="Search topics…" bind:value={query} />
	<div class="filters">
		<select aria-label="Filter topic category" bind:value={group}>
			<option value="all">All topic categories</option>
			{#each groups as name (name)}<option value={name}>{name}</option>{/each}
		</select>
		<select aria-label="Sort review topics" bind:value={sort}>
			<option value="mentions">Most mentioned</option><option value="rating">Lowest average rating</option><option value="change">Largest share increase</option>
		</select>
	</div>
	{#if topics.length}
		{#each ratingGroups.filter((bucket) => bucket.topics.length || bucket.id === 'positive' || bucket.id === 'negative') as bucket (bucket.id)}
			<section class="rating-group" aria-label={bucket.label} style:--topic-color={bucket.color}>
				<div class="rating-group-head"><h4>{bucket.label}</h4><span class="soft num">{bucket.topics.length} topics</span></div>
				<p class="rating-range">{bucket.range}</p>
				<div class="topic-list">
					{#each expandedGroups.includes(bucket.id) ? bucket.topics : bucket.topics.slice(0, 5) as topic (insightTopicKey(data.app.id, topic.topic_id))}
						<button class="topic" class:active={selected?.topic_id === topic.topic_id} onclick={() => openTopic(topic)} aria-label="View topic: {topic.name}" aria-expanded={selected?.topic_id === topic.topic_id} aria-controls="insight-topic-detail">
							<span class="topic-top"><span>{topic.name}</span><span class="num share">{topic.percentage_of_all_reviews.toFixed(1)}%</span></span>
							<span class="track"><i style:width="{Math.min(100, topic.percentage_of_all_reviews)}%"></i></span>
							<span class="topic-meta"><span>{fmtFull(topic.review_count)} reviews · {topicAverageLabel(topic)}</span><span>{trendLabel(topic)}</span></span>
							<span class="parent">{topic.parent_category_name}</span>
						</button>
					{:else}<p class="note">No {bucket.id} topics match these filters.</p>{/each}
				</div>
				{#if bucket.topics.length > 5}
					<button class="link expand" onclick={() => (expandedGroups = expandedGroups.includes(bucket.id) ? expandedGroups.filter((id) => id !== bucket.id) : [...expandedGroups, bucket.id])}>{expandedGroups.includes(bucket.id) ? 'Show fewer topics' : `Show all ${bucket.topics.length} ${bucket.id} topics`}</button>
				{/if}
			</section>
		{/each}
	{:else}<p class="note" role="status">No topics match these filters.</p>{/if}
</section>

{#if selected}
	<section class="block topic-detail" id="insight-topic-detail" bind:this={detail} aria-label="Topic details" style:--topic-color={selectedRatingGroup?.color}>
		<div class="block-head"><span class="label-dim">Selected topic</span><button class="link" onclick={() => (studio.insightTopic = null)}>Close topic</button></div>
		<h3>{selected.name}</h3>
		<p class="rating-classification" style:color={selectedRatingGroup?.color}>{selectedRatingGroup?.label} · {topicAverageLabel(selected)}</p>
		<p class="definition">{selected.definition}</p>
		<p class="topic-stats"><b>{fmtFull(selected.review_count)}</b> matching reviews · <b>{selected.percentage_of_all_reviews.toFixed(1)}%</b> of all app reviews</p>
		{#if selected.trend.label === 'insufficient_data'}
			<p class="notice">Not enough complete-month data to report a reliable trend.</p>
		{:else}
			<p class="notice">{trendLabel(selected)} · share changed by {selected.trend.change_percentage_points === null ? '—' : `${selected.trend.change_percentage_points > 0 ? '+' : ''}${selected.trend.change_percentage_points.toFixed(2)}`} percentage points from {monthLabel(selected.trend.previous_complete_month)} to {monthLabel(selected.trend.latest_complete_month)}. Partial months are excluded from this comparison.</p>
		{/if}
		<h4>Monthly share of app reviews</h4>
		<InsightChart points={selected.monthly.map((month) => ({ month: month.month, value: month.percentage_of_monthly_reviews, partial: month.partial_month, low: month.insufficient_review_volume }))} label="Monthly review share for {selected.name}" unit="%" mode="line" />
		<h4>Ratings in matching reviews</h4>
		<InsightDistribution buckets={selected.star_distribution} ratedCount={selected.rated_review_count} missingCount={selected.missing_rating_count} />
		<div class="block-head excerpt-head"><h4>Representative review excerpts</h4><button class="link" onclick={() => (studio.inspectorTab = 'reviews')}>View in Reviews →</button></div>
		<InsightExamples samples={topicSamples} />
	</section>
{/if}

<section class="block">
	<div class="block-head"><span class="label-dim">Monthly review volume</span><span class="soft">Exported counts</span></div>
	<InsightChart points={data.monthly_reviews.map((month) => ({ month: month.month, value: month.review_count, partial: month.partial_month, low: month.insufficient_review_volume }))} label="Monthly exported reviews for {data.app.name}" />
</section>

<section class="block">
	<div class="block-head"><span class="label-dim">Star distribution</span><span class="soft">Exported ratings</span></div>
	<InsightDistribution buckets={data.summary.star_distribution} ratedCount={data.summary.rated_review_count} missingCount={data.summary.missing_rating_count} />
</section>

<section class="block methodology">
	<details>
		<summary>Source, coverage and limitations</summary>
		<p>Generated {insightDateLabel(data.generated_at)} (UTC) · schema {data.schema_version}.</p>
		<p>{data.metadata.validation_limitation} {data.metadata.coverage_limitation}</p>
		<p>{data.metadata.taxonomy_scope} Topic IDs are scoped to this app, not shared with other apps.</p>
		<p>Semantic topic matching with {data.tagging.embedding_model}; cosine threshold {data.tagging.global_cosine_threshold}. Similarity is not a probability, confidence score or sentiment measurement.</p>
		<p>Trend rules: at least {data.metadata.trend_rule.minimum_monthly_reviews} monthly app reviews, {data.metadata.trend_rule.minimum_topic_mentions_across_two_months} topic mentions across the compared months, and a {data.metadata.trend_rule.minimum_change_percentage_points}-percentage-point change to label a change increasing or decreasing.</p>
		<p>{entry.checksPassed === true ? 'Export aggregation checks passed; this is not human verification of topic assignments.' : entry.checksPassed === false ? 'Warning: one or more export aggregation checks did not pass.' : 'This file is not covered by the latest aggregation report. Schema and count reconciliation are checked independently when the app file loads.'}</p>
		{#each entry.warnings as warning (warning)}<p>{warning}</p>{/each}
	</details>
	<p class="notice">Downloads, install-impact correlations, switching flows, and full dated review records are not included in this export. Demo versions of those analytics are not substituted here.</p>
</section>

<style>
	.block { padding: 12px 14px; border-bottom: 1px solid var(--line); }
	.block-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-bottom: 8px; }
	.soft { font-size: 9px; color: var(--muted); }
	.export-note { padding: 12px 14px; background: color-mix(in srgb, var(--cyan) 4%, var(--panel)); border-bottom: 1px solid var(--line); }
	.export-note .label { color: var(--cyan); }
	.export-note p { margin: 6px 0 0; font-size: 10.5px; color: var(--muted); line-height: 1.5; }
	.export-note p.validation-warning { color: var(--amber); }
	b { color: var(--text-2); font-weight: 500; }
	.note, .notice { font-size: 10px; line-height: 1.55; color: var(--muted); margin: 5px 0 10px; }
	.notice { margin-top: 9px; }
	.input { width: 100%; height: 30px; font-size: 11px; }
	.filters { display: flex; gap: 6px; margin: 7px 0; }
	select { min-width: 0; flex: 1; padding: 6px; border: 1px solid var(--line); border-radius: 2px; background: var(--panel-2); color: var(--text-2); font-size: 9px; }
	.topic-list { display: flex; flex-direction: column; gap: 4px; }
	.rating-group { margin-top: 16px; padding-top: 12px; border-top: 1px solid var(--line); }
	.rating-group-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
	.rating-group-head h4 { margin: 0; color: var(--topic-color); }
	.rating-range { margin: 3px 0 5px; color: var(--muted); font: 9px var(--mono); }
	.rating-classification { margin: 5px 0; font: 9px var(--mono); }
	.topic { padding: 8px 6px; border: 1px solid transparent; border-radius: 3px; text-align: left; }
	.topic:hover, .topic.active { background: var(--panel-2); border-color: var(--line-strong); }
	.topic-top, .topic-meta { display: flex; justify-content: space-between; gap: 8px; }
	.topic-top { font-size: 11.5px; color: var(--text-2); }
	.share { flex: none; color: var(--topic-color, var(--cyan)); font-size: 10px; }
	.track { display: block; height: 3px; background: var(--panel-3); margin: 6px 0; }
	.track i { display: block; height: 100%; background: var(--topic-color, var(--cyan)); }
	.topic-meta { flex-wrap: wrap; font-size: 9px; color: var(--muted); }
	.parent { display: block; margin-top: 4px; font: 8px var(--mono); color: var(--dim); }
	.link { color: var(--cyan); font: 9px var(--mono); text-align: left; }
	.link:hover { color: var(--text); }
	.expand { margin: 10px 6px 2px; }
	.topic-detail { border-left: 2px solid var(--topic-color, var(--cyan)); }
	h3 { margin: 4px 0; font-size: 16px; font-weight: 500; }
	h4 { margin: 14px 0 8px; font-size: 11px; font-weight: 500; }
	.definition, .topic-stats { font-size: 11px; line-height: 1.6; color: var(--text-2); }
	.excerpt-head { align-items: baseline; margin-top: 8px; }
	summary { cursor: pointer; font: 10px var(--mono); color: var(--text-2); }
	.methodology p { font-size: 10px; line-height: 1.6; color: var(--muted); overflow-wrap: anywhere; }
</style>
