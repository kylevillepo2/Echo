<script lang="ts">
	import { studio, type ReviewSort } from '#lib/state/studio.svelte';
	import type { AppNode, SearchHit, Theme } from '#lib/api/types';
	import ReceptionRing from './ReceptionRing.svelte';
	import Sparkline from './Sparkline.svelte';
	import MomentumChart from './MomentumChart.svelte';
	import Stars from './Stars.svelte';
	import ThemeBar from './ThemeBar.svelte';
	import ReviewCard from './ReviewCard.svelte';
	import AppFlows from './AppFlows.svelte';
	import { fmtCount, fmtDate, fmtDelta, fmtDeltaPct, fmtLag, fmtPct, fmtR, fmtRate } from '#lib/utils/format';
	import { platformLabel, receptionColor } from '#lib/utils/palette';

	const app = $derived(studio.selectedApp);
	const category = $derived(studio.selectedCategory);
	const downloads = $derived(app ? studio.downloadsFor(app.id) : undefined);
	const signals = $derived(app?.signals);

	/* ------------------------- review search ------------------------ */

	let reviewQuery = $state('');
	let hits = $state<SearchHit[] | null>(null);
	let searching = $state(false);
	let timer: ReturnType<typeof setTimeout> | undefined;
	let lastAppId: string | null = null;

	$effect(() => {
		const id = studio.selectedApp?.id ?? null;
		if (id !== lastAppId) {
			lastAppId = id;
			reviewQuery = '';
			hits = null;
			searching = false;
			if (timer) clearTimeout(timer);
		}
	});

	function onReviewSearch(value: string) {
		reviewQuery = value;
		if (timer) clearTimeout(timer);
		if (!value.trim()) {
			hits = null;
			searching = false;
			return;
		}
		searching = true;
		const appId = app?.id;
		timer = setTimeout(async () => {
			const results = await studio.searchReviews(value, { appId, limit: 30 });
			if (reviewQuery.trim() === value.trim()) {
				hits = results;
				searching = false;
			}
		}, 320);
	}

	/* --------------------------- derived ---------------------------- */

	const distribution = $derived(app ? [...app.distribution].sort((a, b) => b.stars - a.stars) : []);
	const distributionTotal = $derived(
		distribution.reduce((sum, bucket) => sum + bucket.count, 0) || 1
	);

	const themeMax = $derived(
		app
			? Math.max(
					0.01,
					...app.themes.positive.map((t) => t.share),
					...app.themes.negative.map((t) => t.share)
				)
			: 1
	);

	const categoryThemes = $derived.by(() => {
		const empty = { positive: [] as Theme[], negative: [] as Theme[], max: 1 };
		if (!category) return empty;
		const map = new Map<string, Theme>();
		for (const owned of studio.categoryApps) {
			for (const theme of [...owned.themes.positive, ...owned.themes.negative]) {
				const existing = map.get(theme.id);
				if (existing) existing.count += theme.count;
				else
					map.set(theme.id, {
						...theme,
						examples: [...theme.examples],
						appIds: [...theme.appIds]
					});
			}
		}
		const all = [...map.values()].sort((a, b) => b.count - a.count);
		const positive = all.filter((t) => t.kind === 'positive').slice(0, 3);
		const negative = all.filter((t) => t.kind === 'negative').slice(0, 3);
		return {
			positive,
			negative,
			max: Math.max(0.01, ...all.map((t) => t.count / Math.max(1, category.reviewCount)))
		};
	});

	const similar = $derived(
		(app?.similar ?? [])
			.map((entry) => ({
				score: entry.score,
				app: studio.apps.find((candidate) => candidate.id === entry.appId)
			}))
			.filter((entry): entry is { score: number; app: AppNode } => Boolean(entry.app))
	);

	const sourceSplit = $derived.by(() => {
		if (!app) return [];
		const entries = Object.entries(app.sources).filter(([, count]) => count > 0);
		const total = entries.reduce((sum, [, count]) => sum + count, 0) || 1;
		return entries.map(([id, count]) => ({
			id,
			label: id === 'gplay' ? 'Google Play' : id === 'appstore' ? 'App Store' : id,
			share: count / total
		}));
	});

	const ranked = $derived([...studio.visibleApps].sort((a, b) => b.reception - a.reception));
	const best = $derived(ranked.slice(0, 3));
	const worst = $derived(ranked.slice(-3).reverse());

	const trendFirst = $derived(app?.trend[0]?.date ?? '');
	const trendLast = $derived(app?.trend[app.trend.length - 1]?.date ?? '');
	const downloadsFirst = $derived(downloads?.weekly[0]?.date ?? '');
	const downloadsLast = $derived(downloads?.weekly[downloads.weekly.length - 1]?.date ?? '');

	function setTab(tab: typeof studio.inspectorTab) {
		studio.inspectorTab = tab;
	}

	function scorePct(score: number): number {
		return Math.round(Math.max(0, Math.min(1, score)) * 100);
	}
</script>

<aside class="inspector" aria-label="Inspector">
	{#if app}
		<header class="head" style:--accent={app.accent ?? 'var(--lime)'}>
			<div class="eyebrow">
				<button class="category-link" onclick={() => studio.setCategoryFilter(app.categoryId)}>
					{app.categoryName}
				</button>
				<span class="slash">/</span>
				<span>app</span>
			</div>
			<div class="title-row">
				<h2>{app.name}</h2>
				<button class="close" onclick={() => studio.closeInspector()} aria-label="Close inspector">×</button>
			</div>
			<div class="meta-row">
				<span class="chip">{platformLabel(app.platform)}</span>
				<span class="chip">{app.subcategory}</span>
				<span class="rating"><Stars rating={app.rating} size={10} showValue /></span>
			</div>
		</header>

		<nav class="tabs" aria-label="Inspector sections">
			<button class:active={studio.inspectorTab === 'flows'} onclick={() => setTab('flows')}>
				Flows
			</button>
			<button class:active={studio.inspectorTab === 'overview'} onclick={() => setTab('overview')}>
				Overview
			</button>
			<button class:active={studio.inspectorTab === 'reviews'} onclick={() => setTab('reviews')}>
				Reviews <span class="tab-count">{fmtCount(app.reviewCount)}</span>
			</button>
		</nav>

		<div class="body scroll">
			{#if studio.inspectorTab === 'overview'}
				{#if downloads}
					<section class="block">
						<div class="block-head">
							<span class="label-dim">Downloads · 26 weeks</span>
							<span class="est-chip" title="Modelled from public Play install counts">est.</span>
						</div>
						<div class="dl-head">
							<span class="dl-rate num">{fmtRate(downloads.ratePerDay)}</span>
							<span
								class="delta"
								class:up={downloads.rateDelta >= 0}
								class:down={downloads.rateDelta < 0}
							>
								{fmtDeltaPct(downloads.rateDelta)} <span class="unit">4w</span>
							</span>
						</div>
						<div class="dl-meta">
							<span class="num">{fmtCount(downloads.installs)}</span> lifetime installs
							{#if downloads.installsLabel}
								<span class="dot-sep">·</span><span>Play {downloads.installsLabel}</span>
							{/if}
						</div>
						<MomentumChart
							weekly={downloads.weekly}
							reviews={signals?.weekly ?? []}
							color={receptionColor(app.reception)}
							id="dl-{app.id}"
						/>
						<div class="axis">
							<span>{fmtDate(downloadsFirst)}</span>
							<span>{fmtDate(downloadsLast)}</span>
						</div>
					</section>
				{/if}

				<section class="block">
					<div class="block-head">
						<span class="label-dim">Signals · loved</span>
						<span class="num soft">{app.themes.positive.length}</span>
					</div>
					{#each app.themes.positive.slice(0, 4) as theme (theme.id)}
						<ThemeBar
							label={theme.label}
							share={theme.share}
							count={theme.count}
							kind="positive"
							max={themeMax}
							impact={theme.impact}
							active={studio.themeFilter === theme.id}
							onclick={() => studio.toggleTheme(theme.id)}
						/>
					{:else}
						<p class="none">No strong positive themes detected.</p>
					{/each}
				</section>

				<section class="block">
					<div class="block-head">
						<span class="label-dim">Signals · friction</span>
						<span class="num soft">{app.themes.negative.length}</span>
					</div>
					{#each app.themes.negative.slice(0, 4) as theme (theme.id)}
						<ThemeBar
							label={theme.label}
							share={theme.share}
							count={theme.count}
							kind="negative"
							max={themeMax}
							impact={theme.impact}
							active={studio.themeFilter === theme.id}
							onclick={() => studio.toggleTheme(theme.id)}
						/>
					{:else}
						<p class="none">No recurring complaints detected.</p>
					{/each}
				</section>

				<section class="block">
					<div class="block-head">
						<span class="label-dim">Rating trend · 26 weeks</span>
						<span class="num soft">{app.rating.toFixed(2)} avg</span>
					</div>
					<Sparkline
						points={app.trend}
						height={64}
						color={receptionColor(app.reception)}
						id="trend-{app.id}"
					/>
					<div class="axis">
						<span>{fmtDate(trendFirst)}</span>
						<span>{fmtDate(trendLast)}</span>
					</div>
				</section>

				<section class="block">
					<div class="block-head">
						<span class="label-dim">Star distribution</span>
						<span class="num soft">{fmtCount(distributionTotal)} sampled</span>
					</div>
					<div class="distribution">
						{#each distribution as bucket}
							{@const pct = bucket.count / distributionTotal}
							<div class="dist-row">
								<span class="star-key num">{bucket.stars}★</span>
								<div class="dist-track">
									<i
										style:width="{pct * 100}%"
										style:background={bucket.stars >= 4
											? 'var(--pos)'
											: bucket.stars === 3
												? 'var(--amber)'
												: 'var(--neg)'}
									></i>
								</div>
								<span class="dist-pct num">{Math.round(pct * 100)}%</span>
							</div>
						{/each}
					</div>
				</section>

				<section class="block">
					<div class="block-head">
						<span class="label-dim">Sources</span>
						<span class="num soft">{sourceSplit.length} feeds</span>
					</div>
					<div class="sources-bar">
						{#each sourceSplit as source, index}
							<i
								style:width="{source.share * 100}%"
								style:background={index === 0 ? 'var(--lime)' : 'var(--cyan)'}
							></i>
						{/each}
					</div>
					<div class="sources-legend">
						{#each sourceSplit as source, index}
							<span>
								<i
									class="sq"
									style:background={index === 0 ? 'var(--lime)' : 'var(--cyan)'}
								></i>
								{source.label} {fmtPct(source.share, 0)}
							</span>
						{/each}
					</div>
				</section>

				{#if similar.length}
					<section class="block">
						<div class="block-head">
							<span class="label-dim">Semantically similar</span>
						</div>
						{#each similar.slice(0, 3) as entry (entry.app.id)}
							<button class="similar-mini" onclick={() => studio.select('app', entry.app.id)}>
								<span class="sim-dot" style:background={receptionColor(entry.app.reception)}></span>
								<span class="sim-name">{entry.app.name}</span>
								<span class="sim-category">{entry.app.categoryName}</span>
								<span class="sim-pct num">{scorePct(entry.score)}%</span>
							</button>
						{/each}
					</section>
				{/if}

				{#if signals}
					<section class="block">
						<div class="block-head">
							<span class="label-dim">What moves installs</span>
							<span class="num soft">r · lag</span>
						</div>
						<div class="signal-list">
							<div class="signal-row">
								<span class="signal-dot neg"></span>
								<span class="signal-name">Negative reviews</span>
								<span
									class="signal-r num"
									class:pos={signals.sentiment.r >= 0}
									class:neg={signals.sentiment.r < 0}>{fmtR(signals.sentiment.r)}</span
								>
								<span class="signal-lag num">{fmtLag(signals.sentiment.lag)}</span>
							</div>
							{#each signals.drivers as driver (driver.id)}
								<button
									class="signal-row is-driver"
									class:active={studio.themeFilter === driver.id}
									onclick={() => studio.toggleTheme(driver.id)}
									title="Filter apps by {driver.label}"
								>
									<span
										class="signal-dot"
										class:pos={driver.kind === 'positive'}
										class:neg={driver.kind === 'negative'}
									></span>
									<span class="signal-name">{driver.label}</span>
									<span
										class="signal-r num"
										class:pos={driver.r >= 0}
										class:neg={driver.r < 0}>{fmtR(driver.r)}</span
									>
									<span class="signal-lag num">{fmtLag(driver.lag)}</span>
								</button>
							{/each}
						</div>
						<p class="signal-note">Weekly Pearson r against downloads. <b>leads</b> means reviews moved first. Correlation does not establish causation.</p>
					</section>
				{/if}
			{:else if studio.inspectorTab === 'reviews'}
				<div class="review-controls">
					<div class="search-box">
						<svg width="12" height="12" viewBox="0 0 14 14" fill="none" aria-hidden="true">
							<circle cx="6" cy="6" r="4.4" stroke="currentColor" stroke-width="1.2" />
							<path d="M9.4 9.4 12.5 12.5" stroke="currentColor" stroke-width="1.2" />
						</svg>
						<input
							type="search"
							placeholder="Search these reviews by meaning…"
							aria-label="Semantic search within {app.name} reviews"
							value={reviewQuery}
							oninput={(event) => onReviewSearch(event.currentTarget.value)}
						/>
						{#if searching}
							<span class="searching">···</span>
						{:else if reviewQuery}
							<button class="clear" onclick={() => onReviewSearch('')} aria-label="Clear search">×</button>
						{/if}
					</div>

					<div class="filter-row">
						<div class="pills" role="group" aria-label="Filter by stars">
							<button
								class:active={studio.starFilter === null}
								onclick={() => (studio.starFilter = null)}
							>
								All
							</button>
							{#each [5, 4, 3, 2, 1] as stars}
								<button
									class:active={studio.starFilter === stars}
									onclick={() => (studio.starFilter = studio.starFilter === stars ? null : stars)}
								>
									{stars}★
								</button>
							{/each}
						</div>
						<select
							class="sort"
							aria-label="Sort reviews"
							value={studio.reviewSort}
							onchange={(event) => (studio.reviewSort = event.currentTarget.value as ReviewSort)}
						>
							<option value="recent">Newest</option>
							<option value="lowest">Lowest</option>
							<option value="highest">Highest</option>
						</select>
					</div>

					<div class="pills senti-pills" role="group" aria-label="Filter by sentiment">
						{#each ['all', 'positive', 'neutral', 'negative'] as option}
							<button
								class:active={studio.sentimentFilter === option}
								class:pos={option === 'positive'}
								class:neg={option === 'negative'}
								onclick={() => (studio.sentimentFilter = option as typeof studio.sentimentFilter)}
							>
								{option}
							</button>
						{/each}
					</div>

					<div class="list-meta">
						<span class="label-dim">
							{#if hits !== null}
								{hits.length} semantic matches
							{:else}
								{studio.reviewCountLabel}
							{/if}
						</span>
						<span class="label-dim">sample</span>
					</div>
				</div>

				<div class="review-list">
					{#if hits !== null}
						{#if hits.length === 0}
							<div class="no-hits">
								<p>No reviews matched “{reviewQuery}”.</p>
								<button class="btn is-sm" onclick={() => onReviewSearch('')}>Reset search</button>
							</div>
						{:else}
							{#each hits as hit (hit.id)}
								<ReviewCard review={hit} score={hit.score} query={reviewQuery} />
							{/each}
						{/if}
					{:else if studio.reviewsLoading}
						<div class="skeleton">
							{#each [1, 2, 3, 4] as row (row)}
								<div class="sk-line w40"></div>
								<div class="sk-line w90"></div>
								<div class="sk-line w70"></div>
							{/each}
						</div>
					{:else}
						{#each studio.filteredReviews as review (review.id)}
							<ReviewCard {review} />
						{:else}
							<div class="no-hits"><p>No reviews match these filters.</p></div>
						{/each}
					{/if}
				</div>
			{:else if studio.inspectorTab === 'flows'}
				<AppFlows appId={app.id} appName={app.name} />
			{/if}
		</div>
	{:else if category}
		<header class="head" style:--accent={category.accent}>
			<div class="eyebrow">
				<span class="accent-square" style:background={category.accent}></span>
				<span>category cluster</span>
			</div>
			<div class="title-row">
				<h2>{category.name}</h2>
				<button class="close" onclick={() => studio.closeInspector()} aria-label="Close inspector">×</button>
			</div>
			<div class="meta-row">
				<span class="chip">{category.appIds.length} apps</span>
				<span class="rating"><Stars rating={category.rating} size={10} showValue /></span>
				<button class="cluster-exit" onclick={() => studio.clearCategoryFilter()}>
					show all clusters
				</button>
			</div>
		</header>

		<div class="body scroll">
			<div class="hero">
				<ReceptionRing score={category.reception} size={102} />
				<div class="hero-side">
					<div class="hero-top">
						<span class="label-dim">Cluster reception</span>
						<span
							class="delta"
							class:up={category.receptionDelta >= 0}
							class:down={category.receptionDelta < 0}
						>
							{fmtDelta(category.receptionDelta)} <span class="unit">pts</span>
						</span>
					</div>
					<div class="stats-grid">
						<div>
							<span class="label-dim">Reviews</span>
							<b class="num">{fmtCount(category.reviewCount)}</b>
						</div>
						<div>
							<span class="label-dim">Apps</span>
							<b class="num">{category.appIds.length}</b>
						</div>
						<div>
							<span class="label-dim">Avg rating</span>
							<b class="num">{category.rating.toFixed(2)}</b>
						</div>
					</div>
				</div>
			</div>

			<p class="pane-note">{category.blurb}. Click an app to open its reviews.</p>

			<section class="block">
				<div class="block-head">
					<span class="label-dim">Apps in this cluster</span>
					<span class="num soft">click to inspect</span>
				</div>
				<div class="cluster-apps">
					{#each studio.categoryApps as owned (owned.id)}
						<button class="cluster-app" onclick={() => studio.select('app', owned.id)}>
							<span class="cluster-app-dot" style:background={owned.accent}></span>
							<span class="cluster-app-name">{owned.name}</span>
							<span class="cluster-app-rating num">{owned.rating.toFixed(1)}★</span>
							<span class="cluster-app-meter">
								<i
									style:width="{owned.reception}%"
									style:background={receptionColor(owned.reception)}
								></i>
							</span>
							<span class="cluster-app-score num" style:color={receptionColor(owned.reception)}>
								{owned.reception}
							</span>
						</button>
					{/each}
				</div>
			</section>

			<section class="block">
				<div class="block-head">
					<span class="label-dim">Cluster signals · loved</span>
				</div>
				{#each categoryThemes.positive as theme (theme.id)}
					<ThemeBar
						label={theme.label}
						share={theme.count / Math.max(1, category.reviewCount)}
						count={theme.count}
						kind="positive"
						max={categoryThemes.max}
						impact={theme.impact}
						active={studio.themeFilter === theme.id}
						onclick={() => studio.toggleTheme(theme.id)}
					/>
				{:else}
					<p class="none">No strong positive themes across the cluster.</p>
				{/each}
			</section>

			<section class="block">
				<div class="block-head">
					<span class="label-dim">Cluster signals · friction</span>
				</div>
				{#each categoryThemes.negative as theme (theme.id)}
					<ThemeBar
						label={theme.label}
						share={theme.count / Math.max(1, category.reviewCount)}
						count={theme.count}
						kind="negative"
						max={categoryThemes.max}
						impact={theme.impact}
						active={studio.themeFilter === theme.id}
						onclick={() => studio.toggleTheme(theme.id)}
					/>
				{:else}
					<p class="none">No recurring complaints across the cluster.</p>
				{/each}
			</section>
		</div>
	{:else}
		<div class="empty">
			<div class="empty-top">
				<span class="label">Inspector</span>
				<button class="close" onclick={() => studio.closeInspector()} aria-label="Close inspector">×</button>
			</div>

			<div class="empty-body">
				<div class="emblem" aria-hidden="true">
					<svg width="58" height="58" viewBox="0 0 58 58" fill="none">
						<rect x="3" y="18" width="16" height="16" stroke="var(--cyan)" stroke-width="1.2" />
						<circle cx="41" cy="26" r="8" stroke="var(--lime)" stroke-width="1.2" />
						<circle cx="41" cy="26" r="13" stroke="var(--lime)" stroke-width="0.8" stroke-dasharray="2 3" />
						<path d="M19 26h14" stroke="var(--line-bright)" stroke-width="1" stroke-dasharray="3 3" />
					</svg>
				</div>
				<h2>Unwrap a node</h2>
				<p>
					Click an app circle to inspect it, or click a category cluster to open its flows.
				</p>
				<div class="steps">
					<span><b>01</b> hover a node to preview</span>
					<span><b>02</b> click to inspect</span>
					<span><b>03</b> ⌘K to search by meaning</span>
				</div>

				{#if best.length}
					<div class="rank-lists">
						<div class="rank-block">
							<span class="label-dim">Highest reception</span>
							{#each best as entry (entry.id)}
								<button class="rank-row" onclick={() => studio.select('app', entry.id)}>
									<span class="rank-name">{entry.name}</span>
									<span class="rank-score num" style:color={receptionColor(entry.reception)}>
										{entry.reception}
									</span>
								</button>
							{/each}
						</div>
						<div class="rank-block">
							<span class="label-dim">Needs attention</span>
							{#each worst as entry (entry.id)}
								<button class="rank-row" onclick={() => studio.select('app', entry.id)}>
									<span class="rank-name">{entry.name}</span>
									<span class="rank-score num" style:color={receptionColor(entry.reception)}>
										{entry.reception}
									</span>
								</button>
							{/each}
						</div>
					</div>
				{/if}
			</div>
		</div>
	{/if}
</aside>

<style>
	.inspector {
		width: var(--inspector-w);
		flex: none;
		display: flex;
		flex-direction: column;
		min-height: 0;
		background: var(--panel);
		border-left: 1px solid var(--line);
	}

	.head {
		flex: none;
		padding: 12px 14px 11px;
		border-bottom: 1px solid var(--line);
		position: relative;
	}
	.head::before {
		content: '';
		position: absolute;
		left: 0;
		top: 0;
		bottom: 0;
		width: 2px;
		background: var(--accent);
		opacity: 0.9;
	}
	.eyebrow {
		display: flex;
		align-items: center;
		gap: 5px;
		font-family: var(--mono);
		font-size: 8.5px;
		letter-spacing: 0.12em;
		text-transform: uppercase;
		color: var(--dim);
		margin-bottom: 5px;
	}
	.category-link {
		color: var(--muted);
		font-family: var(--mono);
		font-size: 8.5px;
		letter-spacing: 0.12em;
		text-transform: uppercase;
		text-decoration: underline;
		text-underline-offset: 2px;
		text-decoration-color: var(--line-strong);
	}
	.category-link:hover {
		color: var(--lime);
	}
	.slash {
		color: var(--faint);
	}
	.accent-square {
		width: 7px;
		height: 7px;
		border-radius: 1px;
	}
	.title-row {
		display: flex;
		align-items: flex-start;
		gap: 8px;
	}
	h2 {
		margin: 0;
		font-size: 19px;
		font-weight: 600;
		letter-spacing: -0.015em;
		line-height: 1.2;
		flex: 1;
	}
	.close {
		width: 22px;
		height: 22px;
		display: grid;
		place-items: center;
		font-size: 17px;
		line-height: 1;
		color: var(--dim);
		border: 1px solid transparent;
		border-radius: 2px;
		flex: none;
	}
	.close:hover {
		color: var(--text);
		border-color: var(--line-strong);
	}
	.meta-row {
		display: flex;
		align-items: center;
		gap: 5px;
		flex-wrap: wrap;
		margin-top: 8px;
	}
	.meta-row .chip {
		height: 19px;
		font-size: 8.5px;
	}
	.cluster-exit {
		margin-left: auto;
		font-family: var(--mono);
		font-size: 8px;
		letter-spacing: 0.06em;
		text-transform: uppercase;
		color: var(--lime);
		text-decoration: underline;
		text-underline-offset: 2px;
	}
	.cluster-exit:hover {
		color: var(--text);
	}
	.rating {
		margin-left: 2px;
	}

	.tabs {
		flex: none;
		display: flex;
		border-bottom: 1px solid var(--line);
	}
	.tabs button {
		flex: 1;
		height: 34px;
		display: flex;
		align-items: center;
		justify-content: center;
		gap: 5px;
		font-family: var(--mono);
		font-size: 9.5px;
		letter-spacing: 0.07em;
		text-transform: uppercase;
		color: var(--dim);
		border-bottom: 1px solid transparent;
		margin-bottom: -1px;
		transition: color var(--fast);
	}
	.tabs button:hover {
		color: var(--text-2);
	}
	.tabs button.active {
		color: var(--text);
		border-bottom-color: var(--lime);
	}
	.tab-count {
		font-size: 8px;
		color: var(--faint);
	}

	.body {
		flex: 1;
		min-height: 0;
		overflow-y: auto;
	}

	.hero {
		display: flex;
		align-items: center;
		gap: 14px;
		padding: 14px;
		border-bottom: 1px solid var(--line);
	}
	.hero-side {
		flex: 1;
		min-width: 0;
	}
	.hero-top {
		display: flex;
		align-items: baseline;
		justify-content: space-between;
		gap: 8px;
		margin-bottom: 8px;
	}
	.delta {
		font-family: var(--mono);
		font-size: 10.5px;
		font-weight: 500;
		white-space: nowrap;
	}
	.delta.up {
		color: var(--pos);
	}
	.delta.down {
		color: var(--neg);
	}
	.unit {
		font-size: 8px;
		color: var(--dim);
		font-weight: 400;
	}
	.dl-head {
		display: flex;
		align-items: baseline;
		justify-content: space-between;
		gap: 8px;
	}
	.dl-rate {
		font-size: 21px;
		font-weight: 600;
		letter-spacing: -0.02em;
		color: var(--text);
	}
	.dl-meta {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 5px;
		margin: 2px 0 9px;
		font-family: var(--mono);
		font-size: 8.5px;
		color: var(--dim);
	}
	.dot-sep {
		color: var(--faint);
	}
	.est-chip {
		padding: 1px 5px;
		border: 1px solid color-mix(in srgb, var(--amber) 35%, var(--line));
		border-radius: 2px;
		background: color-mix(in srgb, var(--amber) 8%, transparent);
		font-family: var(--mono);
		font-size: 8px;
		letter-spacing: 0.08em;
		text-transform: uppercase;
		color: var(--amber);
		cursor: help;
	}

	.signal-list {
		display: flex;
		flex-direction: column;
		gap: 1px;
	}
	.signal-row {
		width: 100%;
		display: flex;
		align-items: center;
		gap: 6px;
		padding: 5px 6px;
		text-align: left;
		border: 1px solid transparent;
		border-radius: 2px;
		transition:
			background var(--fast),
			border-color var(--fast);
	}
	.signal-row.is-driver:hover {
		background: var(--panel-2);
		border-color: var(--line);
	}
	.signal-row.active {
		border-color: color-mix(in srgb, var(--lime) 45%, transparent);
		background: color-mix(in srgb, var(--lime) 5%, transparent);
	}
	.signal-dot {
		width: 4px;
		height: 4px;
		border-radius: 50%;
		flex: none;
		background: var(--muted);
	}
	.signal-dot.pos {
		background: var(--pos);
	}
	.signal-dot.neg {
		background: var(--neg);
	}
	.signal-name {
		flex: 1;
		min-width: 0;
		font-size: 11.5px;
		color: var(--text-2);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.signal-r {
		width: 34px;
		text-align: right;
		font-size: 9.5px;
		color: var(--muted);
	}
	.signal-r.pos {
		color: var(--pos);
	}
	.signal-r.neg {
		color: var(--neg);
	}
	.signal-lag {
		width: 54px;
		text-align: right;
		font-size: 8px;
		color: var(--faint);
	}
	.signal-note {
		margin: 7px 0 0;
		font-family: var(--mono);
		font-size: 8px;
		line-height: 1.5;
		color: var(--faint);
	}
	.signal-note b {
		font-weight: 500;
		color: var(--muted);
	}

	.block {
		padding: 12px 14px;
		border-bottom: 1px solid var(--line);
	}
	.block-head {
		display: flex;
		align-items: center;
		justify-content: space-between;
		margin-bottom: 8px;
	}
	.soft {
		font-size: 8.5px;
		color: var(--dim);
	}
	.axis {
		display: flex;
		justify-content: space-between;
		margin-top: 3px;
		font-family: var(--mono);
		font-size: 8px;
		color: var(--faint);
	}
	.distribution {
		display: flex;
		flex-direction: column;
		gap: 5px;
	}
	.dist-row {
		display: flex;
		align-items: center;
		gap: 7px;
	}
	.star-key {
		width: 20px;
		font-size: 8.5px;
		color: var(--muted);
	}
	.dist-track {
		flex: 1;
		height: 5px;
		background: var(--panel-3);
		border-radius: 1px;
		overflow: hidden;
	}
	.dist-track i {
		display: block;
		height: 100%;
		transition: width 600ms var(--ease);
	}
	.dist-pct {
		width: 28px;
		text-align: right;
		font-size: 8.5px;
		color: var(--dim);
	}

	.sources-bar {
		display: flex;
		height: 5px;
		gap: 1px;
		overflow: hidden;
		background: var(--panel-3);
	}
	.sources-bar i {
		display: block;
		height: 100%;
	}
	.sources-legend {
		display: flex;
		gap: 14px;
		margin-top: 6px;
		font-family: var(--mono);
		font-size: 8px;
		color: var(--dim);
	}
	.sources-legend span {
		display: inline-flex;
		align-items: center;
		gap: 4px;
	}
	.sq {
		width: 5px;
		height: 5px;
		display: inline-block;
	}

	.none {
		margin: 0;
		font-size: 10.5px;
		color: var(--faint);
		font-style: italic;
	}

	.similar-mini {
		width: 100%;
		display: flex;
		align-items: center;
		gap: 7px;
		padding: 6px 7px;
		border: 1px solid transparent;
		border-radius: 2px;
		text-align: left;
	}
	.similar-mini:hover {
		background: var(--panel-2);
		border-color: var(--line);
	}
	.sim-dot {
		width: 5px;
		height: 5px;
		border-radius: 50%;
		flex: none;
	}
	.sim-category {
		font-family: var(--mono);
		font-size: 8px;
		color: var(--dim);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
		max-width: 92px;
	}
	.sim-pct {
		font-family: var(--mono);
		font-size: 8.5px;
		color: var(--lime);
		margin-left: auto;
	}

	.review-controls {
		padding: 10px 12px 8px;
		border-bottom: 1px solid var(--line);
		position: sticky;
		top: 0;
		background: var(--panel);
		z-index: 2;
	}
	.search-box {
		position: relative;
		display: flex;
		align-items: center;
		color: var(--dim);
	}
	.search-box svg {
		position: absolute;
		left: 9px;
		pointer-events: none;
	}
	.search-box input {
		width: 100%;
		height: 30px;
		padding: 0 30px;
		background: var(--bg-soft);
		border: 1px solid var(--line);
		border-radius: 2px;
		font-family: var(--mono);
		font-size: 10px;
		color: var(--text);
	}
	.search-box input::placeholder {
		color: var(--dim);
	}
	.search-box input:focus {
		outline: none;
		border-color: var(--lime-dim);
	}
	.search-box input::-webkit-search-cancel-button {
		display: none;
	}
	.searching {
		position: absolute;
		right: 9px;
		font-family: var(--mono);
		font-size: 10px;
		color: var(--lime);
		letter-spacing: 0.1em;
	}
	.clear {
		position: absolute;
		right: 5px;
		width: 20px;
		height: 20px;
		display: grid;
		place-items: center;
		font-size: 14px;
		color: var(--muted);
	}
	.clear:hover {
		color: var(--text);
	}

	.filter-row {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 8px;
		margin-top: 8px;
	}
	.pills {
		display: flex;
		gap: 2px;
		flex-wrap: wrap;
	}
	.pills button {
		height: 21px;
		padding: 0 6px;
		font-family: var(--mono);
		font-size: 8.5px;
		color: var(--dim);
		border: 1px solid var(--line);
		border-radius: 2px;
		background: var(--bg-soft);
		transition:
			color var(--fast),
			border-color var(--fast);
	}
	.pills button:hover {
		color: var(--text-2);
		border-color: var(--line-strong);
	}
	.pills button.active {
		color: var(--text);
		border-color: var(--line-bright);
		background: var(--panel-3);
	}
	.pills.senti-pills {
		margin-top: 6px;
	}
	.pills.senti-pills button {
		flex: 1;
		text-transform: capitalize;
	}
	.pills.senti-pills button.pos.active {
		color: var(--pos);
		border-color: color-mix(in srgb, var(--pos) 40%, var(--line));
	}
	.pills.senti-pills button.neg.active {
		color: var(--neg);
		border-color: color-mix(in srgb, var(--neg) 40%, var(--line));
	}
	.sort {
		height: 22px;
		background: var(--bg-soft);
		border: 1px solid var(--line);
		border-radius: 2px;
		font-family: var(--mono);
		font-size: 8.5px;
		color: var(--muted);
		padding: 0 4px;
		cursor: pointer;
	}
	.list-meta {
		display: flex;
		justify-content: space-between;
		margin-top: 8px;
		padding-top: 7px;
		border-top: 1px solid var(--line);
	}

	.no-hits {
		padding: 26px 16px;
		text-align: center;
		font-size: 11.5px;
		color: var(--dim);
	}
	.no-hits p {
		margin: 0 0 8px;
	}

	.skeleton {
		padding: 14px;
		display: flex;
		flex-direction: column;
		gap: 7px;
	}
	.sk-line {
		height: 8px;
		background: var(--panel-3);
		border-radius: 2px;
		animation: pulse 1.4s ease-in-out infinite;
	}
	.w40 {
		width: 40%;
	}
	.w70 {
		width: 70%;
	}
	.w90 {
		width: 90%;
		margin-bottom: 8px;
	}
	@keyframes pulse {
		50% {
			opacity: 0.4;
		}
	}

	.pane-note {
		margin: 0 0 4px;
		font-size: 10.5px;
		line-height: 1.5;
		color: var(--dim);
	}
	.sim-name {
		font-size: 12px;
		font-weight: 500;
		color: var(--text);
		flex: 1;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.stats-grid {
		display: grid;
		grid-template-columns: repeat(3, 1fr);
		gap: 8px;
	}
	.stats-grid > div {
		display: flex;
		flex-direction: column;
		gap: 2px;
	}
	.stats-grid b {
		font-size: 14px;
		font-weight: 500;
		color: var(--text);
	}

	.cluster-apps {
		display: flex;
		flex-direction: column;
		gap: 2px;
	}
	.cluster-app {
		display: flex;
		align-items: center;
		gap: 7px;
		padding: 6px 7px;
		border: 1px solid transparent;
		border-radius: 2px;
		text-align: left;
	}
	.cluster-app:hover {
		background: var(--panel-2);
		border-color: var(--line);
	}
	.cluster-app-dot {
		width: 5px;
		height: 5px;
		border-radius: 50%;
		flex: none;
	}
	.cluster-app-name {
		flex: 1;
		font-size: 11.5px;
		color: var(--text-2);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.cluster-app-rating {
		font-size: 8.5px;
		color: var(--dim);
	}
	.cluster-app-meter {
		width: 40px;
		height: 3px;
		background: var(--panel-3);
		flex: none;
	}
	.cluster-app-meter i {
		display: block;
		height: 100%;
	}
	.cluster-app-score {
		width: 22px;
		text-align: right;
		font-size: 9px;
		font-weight: 500;
	}

	.empty {
		display: flex;
		flex-direction: column;
		height: 100%;
	}
	.empty-top {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 10px 14px;
		border-bottom: 1px solid var(--line);
	}
	.empty-body {
		flex: 1;
		overflow-y: auto;
		padding: 26px 18px 20px;
	}
	.emblem {
		width: 74px;
		height: 74px;
		display: grid;
		place-items: center;
		border: 1px solid var(--line);
		background:
			linear-gradient(135deg, rgba(200, 255, 60, 0.05), transparent 60%),
			var(--bg-soft);
		margin-bottom: 14px;
	}
	.empty-body h2 {
		font-size: 18px;
		margin: 0 0 6px;
	}
	.empty-body > p {
		margin: 0 0 16px;
		font-size: 12px;
		line-height: 1.55;
		color: var(--muted);
		max-width: 280px;
	}
	.steps {
		display: flex;
		flex-direction: column;
		gap: 5px;
		margin-bottom: 22px;
	}
	.steps span {
		font-family: var(--mono);
		font-size: 9px;
		color: var(--dim);
		letter-spacing: 0.02em;
	}
	.steps b {
		color: var(--lime);
		font-weight: 500;
		margin-right: 6px;
	}
	.rank-lists {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: 14px;
		padding-top: 14px;
		border-top: 1px solid var(--line);
	}
	.rank-block {
		display: flex;
		flex-direction: column;
		gap: 3px;
		min-width: 0;
	}
	.rank-block .label-dim {
		margin-bottom: 4px;
	}
	.rank-row {
		display: flex;
		align-items: center;
		gap: 6px;
		padding: 4px 5px;
		border-radius: 2px;
		text-align: left;
	}
	.rank-row:hover {
		background: var(--panel-2);
	}
	.rank-name {
		font-size: 10.5px;
		color: var(--text-2);
		flex: 1;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.rank-score {
		font-size: 9px;
		font-weight: 500;
	}

	@media (max-width: 1180px) {
		.inspector {
			position: absolute;
			top: var(--header-h);
			bottom: var(--status-h);
			right: 0;
			z-index: 26;
			width: min(396px, 94vw);
			box-shadow: -24px 0 60px rgba(0, 0, 0, 0.55);
		}
	}
</style>
