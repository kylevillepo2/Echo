<script lang="ts">
	import { studio } from '#lib/state/studio.svelte';
	import { rollupThemes } from '#lib/api';
	import type { Theme } from '#lib/api/types';
	import { fmtCount, fmtLag, fmtPct, fmtR } from '#lib/utils/format';

	let sortMode = $state<'mentions' | 'impact'>('mentions');

	const scopedThemes = $derived(rollupThemes(studio.visibleApps));
	const positive = $derived(
		scopedThemes
			.filter((t) => t.kind === 'positive')
			.sort((a, b) =>
				sortMode === 'impact' ? impactScore(b) - impactScore(a) : b.count - a.count
			)
	);
	const negative = $derived(
		scopedThemes
			.filter((t) => t.kind === 'negative')
			.sort((a, b) =>
				sortMode === 'impact' ? impactScore(b) - impactScore(a) : b.count - a.count
			)
	);

	function impactScore(theme: Theme): number {
		if (!theme.impact) return -Infinity;
		return theme.kind === 'positive' ? theme.impact.r : -theme.impact.r;
	}

	const totals = $derived.by(() => {
		let positive = 0;
		let neutral = 0;
		let negative = 0;
		let reviews = 0;
		for (const app of studio.visibleApps) {
			positive += app.sentiment.positive;
			neutral += app.sentiment.neutral;
			negative += app.sentiment.negative;
			reviews += app.reviewCount;
		}
		return { positive, neutral, negative, reviews };
	});

	const posPct = $derived(totals.reviews ? totals.positive / totals.reviews : 0);
	const neuPct = $derived(totals.reviews ? totals.neutral / totals.reviews : 0);
	const negPct = $derived(totals.reviews ? totals.negative / totals.reviews : 0);

	const categoryChip = $derived(studio.selectedCategory);
</script>

<section class="themes scroll" aria-label="Theme ledger">
	<header class="head">
		<div class="head-left">
			<span class="label">Theme ledger</span>
			<h1>What people talk about</h1>
			<p>
				Clustered themes across <b class="num">{studio.visibleApps.length}</b> apps and
				<b class="num">{fmtCount(totals.reviews)}</b> reviews.
				{#if categoryChip}Scoped to <b>{categoryChip.name}</b>.{/if}
			</p>
		</div>

		<div class="head-right">
			<div class="sort-toggle" role="group" aria-label="Sort themes">
				<span class="label-dim">sort</span>
				<button
					class:active={sortMode === 'mentions'}
					onclick={() => (sortMode = 'mentions')}
				>
					mentions
				</button>
				<button
					class:active={sortMode === 'impact'}
					onclick={() => (sortMode = 'impact')}
				>
					download impact
				</button>
			</div>
			<button class="btn is-ghost is-sm" onclick={() => studio.setView('network')}>
				Open network →
			</button>
		</div>
	</header>

	<div class="mood panel">
		<div class="mood-top">
			<span class="label-dim">Corpus mood</span>
			<div class="mood-legend">
				<span class="mkey pos">{fmtPct(posPct, 1)} positive</span>
				<span class="mkey neu">{fmtPct(neuPct, 1)} neutral</span>
				<span class="mkey neg">{fmtPct(negPct, 1)} negative</span>
			</div>
		</div>
		<div class="mood-bar" role="img" aria-label="Sentiment split across the visible corpus">
			<i class="pos" style:width="{posPct * 100}%"></i>
			<i class="neu" style:width="{neuPct * 100}%"></i>
			<i class="neg" style:width="{negPct * 100}%"></i>
		</div>
		<div class="mood-foot">
			<span class="num">{fmtCount(totals.positive)} positive</span>
			<span class="num">{fmtCount(totals.negative)} negative</span>
			<span class="muted">derived from star ratings + sampled sentiment</span>
		</div>
	</div>

	<p class="impact-note">
		<b>Download impact</b> correlates each theme's weekly mentions with the modelled weekly
		downloads. <span class="pos">Positive r</span> means mentions rise with installs;
		<span class="neg">negative r</span> means they rise when installs fall. “leads” means the
		theme moved first.
	</p>

	<div class="columns">
		<section class="column">
			<header class="col-head">
				<div class="col-title">
					<span class="marker pos"></span>
					<span class="label">What lands</span>
				</div>
				<span class="col-count num">{positive.length} themes</span>
			</header>
			<div class="cards">
				{#each positive as theme, index (theme.id)}
					<button
						class="card"
						class:active={studio.themeFilter === theme.id}
						onclick={() => studio.toggleTheme(theme.id)}
					>
						<div class="card-top">
							<span class="rank num">{String(index + 1).padStart(2, '0')}</span>
							<span class="name">{theme.label}</span>
							<span class="mentions num">{fmtCount(theme.count)}</span>
						</div>
						<div class="bar">
							<i
								class="pos"
								style:width="{Math.min(100, (theme.share / (positive[0]?.share || 1)) * 100)}%"
							></i>
						</div>
						<p class="quote">“{theme.examples[0] ?? 'No representative quote.'}”</p>
						<footer>
							<span class="share num">{fmtPct(theme.share, 1)} of reviews</span>
							{#if theme.impact}
								<span
									class="impact num"
									class:pos={theme.impact.r >= 0}
									class:neg={theme.impact.r < 0}
									title="Weekly correlation with downloads · {theme.impact.confidence} confidence · {theme.impact.mentions} mentions"
								>
									r {fmtR(theme.impact.r)} · {fmtLag(theme.impact.lag)}
								</span>
							{/if}
							<span class="apps">{theme.appIds.length} apps</span>
							<span class="drill">filter →</span>
						</footer>
					</button>
				{/each}
			</div>
		</section>

		<section class="column">
			<header class="col-head">
				<div class="col-title">
					<span class="marker neg"></span>
					<span class="label">What grates</span>
				</div>
				<span class="col-count num">{negative.length} themes</span>
			</header>
			<div class="cards">
				{#each negative as theme, index (theme.id)}
					<button
						class="card"
						class:active={studio.themeFilter === theme.id}
						onclick={() => studio.toggleTheme(theme.id)}
					>
						<div class="card-top">
							<span class="rank num">{String(index + 1).padStart(2, '0')}</span>
							<span class="name">{theme.label}</span>
							<span class="mentions num">{fmtCount(theme.count)}</span>
						</div>
						<div class="bar">
							<i
								class="neg"
								style:width="{Math.min(100, (theme.share / (negative[0]?.share || 1)) * 100)}%"
							></i>
						</div>
						<p class="quote">“{theme.examples[0] ?? 'No representative quote.'}”</p>
						<footer>
							<span class="share num">{fmtPct(theme.share, 1)} of reviews</span>
							{#if theme.impact}
								<span
									class="impact num"
									class:pos={theme.impact.r >= 0}
									class:neg={theme.impact.r < 0}
									title="Weekly correlation with downloads · {theme.impact.confidence} confidence · {theme.impact.mentions} mentions"
								>
									r {fmtR(theme.impact.r)} · {fmtLag(theme.impact.lag)}
								</span>
							{/if}
							<span class="apps">{theme.appIds.length} apps</span>
							<span class="drill">filter →</span>
						</footer>
					</button>
				{/each}
			</div>
		</section>
	</div>

	{#if positive.length === 0 && negative.length === 0}
		<div class="empty">
			<p>No themes for this selection.</p>
			<button class="btn is-sm" onclick={() => studio.clearFilters()}>Clear filters</button>
		</div>
	{/if}
</section>

<style>
	.themes {
		flex: 1;
		min-width: 0;
		overflow-y: auto;
		padding: 22px 24px 44px;
	}

	.head {
		display: flex;
		align-items: flex-end;
		justify-content: space-between;
		gap: 20px;
		margin-bottom: 18px;
	}
	.head-left h1 {
		margin: 6px 0 6px;
		font-size: 26px;
		font-weight: 600;
		letter-spacing: -0.02em;
	}
	.head-left p {
		margin: 0;
		font-size: 12.5px;
		color: var(--muted);
	}
	.head-left p b {
		color: var(--text-2);
		font-weight: 500;
	}
	.head-right {
		display: flex;
		align-items: center;
		justify-content: flex-end;
		flex-wrap: wrap;
		gap: 10px;
	}
	.sort-toggle {
		display: inline-flex;
		align-items: center;
		gap: 1px;
		padding: 1px;
		border: 1px solid var(--line);
		border-radius: 2px;
		background: var(--panel);
	}
	.sort-toggle .label-dim {
		padding: 0 5px;
		font-size: 8px;
	}
	.sort-toggle button {
		padding: 4px 7px;
		border-radius: 1px;
		font-family: var(--mono);
		font-size: 8px;
		letter-spacing: 0.05em;
		text-transform: uppercase;
		color: var(--dim);
		transition:
			background var(--fast),
			color var(--fast);
	}
	.sort-toggle button:hover {
		color: var(--text-2);
	}
	.sort-toggle button.active {
		background: color-mix(in srgb, var(--lime) 12%, transparent);
		color: var(--lime);
	}
	.impact-note {
		max-width: 780px;
		margin: -10px 0 20px;
		font-family: var(--mono);
		font-size: 9px;
		line-height: 1.65;
		color: var(--faint);
	}
	.impact-note b {
		font-weight: 500;
		color: var(--muted);
	}
	.impact-note .pos {
		color: var(--pos);
	}
	.impact-note .neg {
		color: var(--neg);
	}

	.mood {
		padding: 12px 14px 10px;
		margin-bottom: 22px;
	}
	.mood-top {
		display: flex;
		align-items: center;
		justify-content: space-between;
		margin-bottom: 8px;
	}
	.mood-legend {
		display: flex;
		gap: 14px;
		font-family: var(--mono);
		font-size: 9px;
	}
	.mkey.pos {
		color: var(--pos);
	}
	.mkey.neu {
		color: var(--muted);
	}
	.mkey.neg {
		color: var(--neg);
	}
	.mood-bar {
		display: flex;
		height: 10px;
		background: var(--panel-3);
		border-radius: 1px;
		overflow: hidden;
		gap: 2px;
	}
	.mood-bar i {
		display: block;
		height: 100%;
		transition: width 600ms var(--ease);
	}
	.mood-bar .pos {
		background: var(--pos);
	}
	.mood-bar .neu {
		background: var(--line-bright);
	}
	.mood-bar .neg {
		background: var(--neg);
	}
	.mood-foot {
		display: flex;
		align-items: center;
		gap: 14px;
		margin-top: 8px;
		font-family: var(--mono);
		font-size: 8.5px;
		color: var(--dim);
	}
	.mood-foot .muted {
		margin-left: auto;
		color: var(--faint);
	}

	.columns {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: 18px;
		align-items: start;
	}
	.column {
		min-width: 0;
	}
	.col-head {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding-bottom: 8px;
		border-bottom: 1px solid var(--line);
		margin-bottom: 10px;
	}
	.col-title {
		display: flex;
		align-items: center;
		gap: 7px;
	}
	.marker {
		width: 6px;
		height: 6px;
		border-radius: 50%;
	}
	.marker.pos {
		background: var(--pos);
	}
	.marker.neg {
		background: var(--neg);
	}
	.col-count {
		font-size: 8.5px;
		color: var(--dim);
	}

	.cards {
		display: flex;
		flex-direction: column;
		gap: 6px;
	}
	.card {
		width: 100%;
		text-align: left;
		padding: 10px 12px;
		background: var(--panel);
		border: 1px solid var(--line);
		border-radius: 2px;
		transition:
			border-color var(--fast),
			background var(--fast);
	}
	.card:hover {
		border-color: var(--line-strong);
		background: var(--panel-2);
	}
	.card.active {
		border-color: var(--lime);
		box-shadow: inset 2px 0 0 var(--lime);
	}
	.card-top {
		display: flex;
		align-items: baseline;
		gap: 8px;
	}
	.rank {
		font-size: 8.5px;
		color: var(--faint);
	}
	.name {
		font-size: 13px;
		font-weight: 500;
		color: var(--text);
		flex: 1;
	}
	.mentions {
		font-size: 9px;
		color: var(--muted);
	}
	.bar {
		height: 3px;
		background: var(--panel-3);
		margin: 7px 0 8px;
		border-radius: 1px;
		overflow: hidden;
	}
	.bar i {
		display: block;
		height: 100%;
	}
	.bar .pos {
		background: var(--pos);
	}
	.bar .neg {
		background: var(--neg);
	}
	.quote {
		margin: 0;
		font-size: 11.5px;
		line-height: 1.5;
		color: var(--text-2);
		display: -webkit-box;
		-webkit-line-clamp: 2;
		line-clamp: 2;
		-webkit-box-orient: vertical;
		overflow: hidden;
	}
	footer {
		display: flex;
		align-items: center;
		gap: 10px;
		margin-top: 8px;
		font-family: var(--mono);
		font-size: 8px;
		color: var(--dim);
	}
	.apps {
		color: var(--faint);
	}
	.impact {
		color: var(--muted);
		white-space: nowrap;
	}
	.impact.pos {
		color: var(--pos);
	}
	.impact.neg {
		color: var(--neg);
	}
	.drill {
		margin-left: auto;
		color: var(--dim);
		opacity: 0;
		transition: opacity var(--fast);
	}
	.card:hover .drill {
		opacity: 1;
		color: var(--lime);
	}

	.empty {
		padding: 40px;
		text-align: center;
		color: var(--dim);
	}

	@media (max-width: 1060px) {
		.columns {
			grid-template-columns: 1fr;
		}
	}
	@media (max-width: 720px) {
		.themes {
			padding: 16px 14px 40px;
		}
		.head-left h1 {
			font-size: 21px;
		}
		.mood-legend {
			gap: 8px;
			font-size: 8px;
		}
		.mood-foot .muted {
			display: none;
		}
	}
</style>
