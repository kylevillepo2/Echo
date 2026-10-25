<script lang="ts">
	import { studio } from '#lib/state/studio.svelte';
	import { insightReviewSamples, insightTopicKey, type AppInsights } from '#lib/data/insights';
	import { fmtFull } from '#lib/utils/format';
	import InsightExamples from './InsightExamples.svelte';

	let { data }: { data: AppInsights } = $props();
	let query = $state('');
	let source = $state('all');
	const samples = $derived(insightReviewSamples(data));
	const topicKey = $derived(studio.insightTopic?.appId === data.app.id ? insightTopicKey(data.app.id, studio.insightTopic.topicId) : 'all');
	const filtered = $derived(samples.filter((sample) =>
		(topicKey === 'all' || sample.topics.some((topic) => topic.id === topicKey)) &&
		(source === 'all' || sample.data_source === source) &&
		`${sample.snippet} ${sample.topics.map((topic) => topic.name).join(' ')}`.toLowerCase().includes(query.trim().toLowerCase())
	));
	const sources = $derived([...new Set(samples.map((sample) => sample.data_source))]);
	let lastApp = '';
	$effect(() => { if (lastApp !== data.app.id) { lastApp = data.app.id; query = ''; source = 'all'; } });

	function selectTopic(key: string) {
		const topic = data.topics.find((topic) => insightTopicKey(data.app.id, topic.topic_id) === key);
		studio.insightTopic = topic ? { appId: data.app.id, topicId: topic.topic_id } : null;
	}
</script>

<section class="review-controls" aria-label="Exported review samples">
	<h3>What customers are saying</h3>
	<input class="input" type="search" aria-label="Search saved review excerpts" placeholder="Search saved excerpts…" bind:value={query} />
	<div class="filters">
		<select aria-label="Filter review topic" value={topicKey} onchange={(event) => selectTopic(event.currentTarget.value)}>
			<option value="all">All topics</option>
			{#each data.topics as topic (insightTopicKey(data.app.id, topic.topic_id))}<option value={insightTopicKey(data.app.id, topic.topic_id)}>{topic.name}</option>{/each}
		</select>
		<select aria-label="Filter review source" bind:value={source}>
			<option value="all">All sources</option>
			{#each sources as id (id)}<option value={id}>{id === 'gplay' ? 'Google Play' : id === 'appstore' ? 'App Store' : id}</option>{/each}
		</select>
	</div>
	<div class="count" role="status">{filtered.length} of {samples.length} saved excerpts{topicKey !== 'all' ? ' · topic filter active' : ''}</div>
	{#if topicKey !== 'all'}<button class="clear" onclick={() => (studio.insightTopic = null)}>Clear topic filter</button>{/if}
	<details><summary>About these comments</summary><p>{fmtFull(samples.length)} representative excerpts from {fmtFull(data.summary.total_reviews)} reviews. Individual dates, ratings and full text are not included in this export.</p></details>
</section>

<div class="review-list"><InsightExamples samples={filtered} onTopic={selectTopic} /></div>

<style>
	.review-controls { padding: 12px 14px; border-bottom: 1px solid var(--line); }
	h3 { color: white; font-size: 14px; font-weight: 700; margin: 0 0 12px; }
	details { margin-top: 10px; font-size: 9px; color: var(--muted); }
	summary { cursor: pointer; }
	p { color: var(--muted); font-size: 10.5px; line-height: 1.6; }
	.input { width: 100%; height: 30px; font-size: 11px; }
	.filters { display: flex; gap: 6px; margin-top: 7px; }
	select { flex: 1; min-width: 0; padding: 6px; font-size: 9px; background: var(--panel-2); color: var(--text-2); border: 1px solid var(--line); border-radius: 2px; }
	.count { margin-top: 9px; color: var(--muted); font: 9px var(--mono); }
	.clear { margin-top: 8px; font: 9px var(--mono); color: var(--cyan); }
	.review-list { padding: 12px 14px; }
</style>
