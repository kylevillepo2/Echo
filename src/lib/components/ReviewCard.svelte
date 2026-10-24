<script lang="ts">
	import type { Review } from '#lib/api/types';
	import { studio } from '#lib/state/studio.svelte';
	import { fmtDate, relTime } from '#lib/utils/format';
	import Stars from './Stars.svelte';

	let {
		review,
		score,
		query = ''
	}: { review: Review; score?: number; query?: string } = $props();

	const themes = $derived(
		(review.themeIds ?? [])
			.map((id) => studio.themeById(id))
			.filter((t): t is NonNullable<typeof t> => Boolean(t))
	);

	const sourceLabel = $derived(
		review.source === 'gplay' ? 'Google Play' : review.source === 'appstore' ? 'App Store' : review.source
	);

	/** split text into highlighted / plain runs without using {@html} */
	const segments = $derived.by(() => {
		const words = query.trim().toLowerCase().split(/\s+/).filter((w) => w.length > 2);
		if (!words.length) return [{ text: review.text, hit: false }];

		const escaped = words.map((w) => w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'));
		const re = new RegExp(`(${escaped.join('|')})`, 'gi');
		const parts = review.text.split(re);
		return parts.map((text) => ({
			text,
			hit: words.includes(text.toLowerCase())
		}));
	});
</script>

<article class="review" class:has-score={score !== undefined}>
	<header>
		<Stars rating={review.stars} size={10} />
		<span class="date" title={fmtDate(review.date, 'long')}>{relTime(review.date)}</span>
		<span class="source">{sourceLabel}</span>
		{#if score !== undefined}
			<span class="score num">{Math.round(Math.max(0, Math.min(1, score)) * 100)}% match</span>
		{/if}
	</header>

	{#if review.title}
		<h4>{review.title}</h4>
	{/if}

	<p>
		{#each segments as seg}
			{#if seg.hit}<mark>{seg.text}</mark>{:else}{seg.text}{/if}
		{/each}
	</p>

	<footer>
		{#each themes as theme}
			<span class="chip" class:is-pos={theme.kind === 'positive'} class:is-neg={theme.kind === 'negative'}>
				{theme.label}
			</span>
		{/each}
		{#if review.version}<span class="ver">{review.version}</span>{/if}
	</footer>
</article>

<style>
	.review {
		padding: 12px 14px;
		border-bottom: 1px solid var(--line);
		transition: background var(--fast);
	}
	.review:hover {
		background: var(--bg-soft);
	}
	header {
		display: flex;
		align-items: center;
		gap: 8px;
		margin-bottom: 6px;
	}
	.date {
		font-family: var(--mono);
		font-size: 9.5px;
		color: var(--dim);
	}
	.source {
		font-family: var(--mono);
		font-size: 8.5px;
		letter-spacing: 0.06em;
		text-transform: uppercase;
		color: var(--dim);
		border: 1px solid var(--line);
		padding: 1px 4px;
		border-radius: 2px;
	}
	.score {
		margin-left: auto;
		font-size: 9.5px;
		color: var(--lime);
		background: color-mix(in srgb, var(--lime) 9%, transparent);
		border: 1px solid color-mix(in srgb, var(--lime) 25%, transparent);
		padding: 1px 5px;
		border-radius: 2px;
	}
	h4 {
		margin: 0 0 3px;
		font-size: 12.5px;
		font-weight: 600;
		color: var(--text);
	}
	p {
		margin: 0;
		font-size: 12.5px;
		line-height: 1.55;
		color: var(--text-2);
	}
	mark {
		background: color-mix(in srgb, var(--lime) 22%, transparent);
		color: var(--text);
		padding: 0 1px;
		border-radius: 1px;
	}
	footer {
		display: flex;
		align-items: center;
		flex-wrap: wrap;
		gap: 5px;
		margin-top: 8px;
	}
	footer .chip {
		height: 18px;
		font-size: 8.5px;
	}
	.ver {
		margin-left: auto;
		font-family: var(--mono);
		font-size: 9px;
		color: var(--dim);
	}
	.has-score p {
		color: var(--text);
	}
</style>
