<script lang="ts">
	import type { InsightStarBucket } from '#lib/data/insights';
	import { fmtFull } from '#lib/utils/format';
	let { buckets, ratedCount, missingCount = 0 }: { buckets: InsightStarBucket[]; ratedCount: number; missingCount?: number } = $props();
</script>

<div class="distribution" aria-label="Exported star distribution">
	{#each [...buckets].sort((a, b) => b.stars - a.stars) as bucket (bucket.stars)}
		<div class="row">
			<span class="num">{bucket.stars}★</span>
			<span class="track"><i style:width="{ratedCount ? bucket.count / ratedCount * 100 : 0}%"></i></span>
			<span class="count num" title="{fmtFull(bucket.count)} rated reviews">{ratedCount ? (bucket.count / ratedCount * 100).toFixed(1) : '0.0'}%</span>
		</div>
	{/each}
	<p>{fmtFull(ratedCount)} rated reviews{missingCount ? ` · ${fmtFull(missingCount)} without a rating` : ''}</p>
</div>

<style>
	.distribution { display: flex; flex-direction: column; gap: 6px; }
	.row { display: grid; grid-template-columns: 22px 1fr 48px; align-items: center; gap: 8px; font-size: 10px; color: var(--muted); }
	.track { height: 5px; background: var(--panel-3); }
	.track i { display: block; height: 100%; background: var(--cyan); }
	.count { text-align: right; }
	p { margin: 2px 0 0; font-size: 9px; color: var(--dim); }
</style>
