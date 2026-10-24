<script lang="ts">
	let {
		rating,
		size = 11,
		showValue = false
	}: { rating: number; size?: number; showValue?: boolean } = $props();

	const filled = $derived(Math.round(rating));
</script>

<span class="stars" style:font-size="{size}px" aria-label="{rating.toFixed(1)} out of 5 stars">
	{#each [1, 2, 3, 4, 5] as star}
		<span class="star" class:on={star <= filled}>★</span>
	{/each}
	{#if showValue}
		<span class="val num">{rating.toFixed(1)}</span>
	{/if}
</span>

<style>
	.stars {
		display: inline-flex;
		align-items: center;
		gap: 1px;
		line-height: 1;
		letter-spacing: -0.02em;
	}
	.star {
		color: var(--faint);
	}
	.star.on {
		color: var(--amber);
	}
	.val {
		margin-left: 6px;
		font-size: 0.85em;
		color: var(--text-2);
	}
</style>
