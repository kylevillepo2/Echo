<script lang="ts">
	import type { InsightReviewSample } from '#lib/data/insights';
	let { samples, onTopic }: { samples: InsightReviewSample[]; onTopic?: (key: string) => void } = $props();
</script>

<div class="examples">
	{#each samples as sample (sample.review_key)}
		<article class="insight-review">
			<header>
				<span>{sample.data_source === 'gplay' ? 'Google Play' : sample.data_source === 'appstore' ? 'App Store' : sample.data_source}</span>
			</header>
			<p>“{sample.snippet}”</p>
			<footer>
				{#each sample.topics as topic (topic.id)}
					{#if onTopic}
						<button onclick={() => onTopic?.(topic.id)}>{topic.name}</button>
					{:else}
						<span class="tag">{topic.name}</span>
					{/if}
				{/each}
			</footer>
		</article>
	{:else}
		<p class="empty" role="status">No representative excerpts were included for this selection.</p>
	{/each}
</div>

<style>
	.examples { display: flex; flex-direction: column; gap: 9px; }
	.insight-review { padding: 11px; border: 1px solid var(--line); border-radius: 3px; background: var(--bg-soft); }
	header { display: flex; flex-wrap: wrap; justify-content: space-between; gap: 5px; color: var(--muted); font: 8px var(--mono); }
	p { margin: 8px 0; font-size: 12px; line-height: 1.55; overflow-wrap: anywhere; }
	footer { display: flex; flex-wrap: wrap; gap: 4px; }
	button, .tag { max-width: 100%; padding: 3px 5px; border: 1px solid var(--line); border-radius: 2px; font: 8px var(--mono); color: var(--muted); text-align: left; overflow-wrap: anywhere; }
	button:hover { color: var(--lime); border-color: var(--line-strong); }
	.empty { margin: 0; color: var(--muted); font-size: 11px; }
</style>
