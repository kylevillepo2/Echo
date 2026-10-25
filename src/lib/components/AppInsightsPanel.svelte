<script lang="ts">
	import { studio } from '#lib/state/studio.svelte';
	import InsightOverview from './InsightOverview.svelte';
	import InsightReviews from './InsightReviews.svelte';
	let { view }: { view: 'overview' | 'reviews' } = $props();
	const entry = $derived(studio.selectedInsightEntry);
	const data = $derived(studio.selectedInsights);
</script>

{#if entry}
	{#if data}
		{#if view === 'overview'}<InsightOverview {data} {entry} />{:else}<InsightReviews {data} />{/if}
	{:else if studio.insightStatus[entry.id] === 'error'}
		<section class="notice" role="alert">
			<h3>Couldn’t load exported analytics</h3>
			<p>{studio.insightErrors[entry.id]}</p>
			<p>Demo analytics are not substituted for this app.</p>
			<button class="btn" onclick={() => studio.loadInsights(entry, true)}>Retry analytics</button>
		</section>
	{:else}
		<section class="notice" role="status" aria-busy="true"><p>Loading {entry.name} analytics…</p></section>
	{/if}
{/if}

<style>
	.notice { padding: 18px 14px; }
	h3 { font-size: 14px; font-weight: 500; margin: 0 0 8px; }
	p { font-size: 11px; line-height: 1.6; color: var(--muted); overflow-wrap: anywhere; }
</style>
