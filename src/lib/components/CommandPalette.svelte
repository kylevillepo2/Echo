<script lang="ts">
	import { onMount, tick } from 'svelte';
	import { studio } from '#lib/state/studio.svelte';
	import type { SearchHit } from '#lib/api/types';
	import { fmtCount, relTime, truncate } from '#lib/utils/format';
	import { receptionColor } from '#lib/utils/palette';
	import Stars from './Stars.svelte';

	type Mode = 'reviews' | 'entities';
	type EntityRow = {
		kind: 'app' | 'category';
		id: string;
		name: string;
		sub: string;
		reception: number;
		accent: string;
	};

	let query = $state('');
	let mode = $state<Mode>('reviews');
	let results = $state<SearchHit[]>([]);
	let loading = $state(false);
	let active = $state(0);
	let inputEl = $state<HTMLInputElement>();
	let token = 0;
	let timer: ReturnType<typeof setTimeout> | undefined;

	const suggestions = [
		'battery drain',
		'crashes after update',
		'blocked ads',
		'privacy and tracking',
		'sync problems',
		'too many notifications'
	];

	const entities = $derived.by(() => {
		const q = query.trim().toLowerCase();
		const apps: EntityRow[] = studio.apps
			.filter(
				(app) =>
					!q ||
					app.name.toLowerCase().includes(q) ||
					app.categoryName.toLowerCase().includes(q)
			)
			.sort((a, b) => (q ? a.name.localeCompare(b.name) : studio.metricValue(b) - studio.metricValue(a)))
			.slice(0, 8)
			.map((app) => ({
				kind: 'app',
				id: app.id,
				name: app.name,
				sub: `${app.categoryName} · ${
					studio.metric === 'downloads'
						? studio.metricLabelFor(app)
						: `${fmtCount(app.reviewCount)} reviews`
				}`,
				reception: app.reception,
				accent: app.accent ?? '#c8ff3c'
			}));

		const categories: EntityRow[] = studio.categories
			.filter((category) => q && category.name.toLowerCase().includes(q))
			.slice(0, 4)
			.map((category) => ({
				kind: 'category',
				id: category.id,
				name: category.name,
				sub: studio.categoryMetricLabel(category),
				reception: category.reception,
				accent: category.accent
			}));

		return [...apps, ...categories];
	});

	const activeCount = $derived(mode === 'reviews' ? results.length : entities.length);

	onMount(() => {
		inputEl?.focus();
	});

	$effect(() => {
		// reset selection when the query or mode changes
		query;
		mode;
		active = 0;
	});

	$effect(() => {
		const q = query;
		if (mode !== 'reviews') return;

		if (timer) clearTimeout(timer);
		if (!q.trim()) {
			results = [];
			loading = false;
			return;
		}

		const request = ++token;
		loading = true;
		timer = setTimeout(async () => {
			const hits = await studio.searchReviews(q, { limit: 14 });
			if (request === token) {
				results = hits;
				loading = false;
				active = 0;
			}
		}, 280);

		return () => {
			if (timer) clearTimeout(timer);
		};
	});

	function close() {
		studio.closePalette();
	}

	function choose(index: number) {
		if (mode === 'reviews') {
			const hit = results[index];
			if (hit) studio.select('app', hit.appId);
		} else {
			const row = entities[index];
			if (row) openRow(row);
		}
	}

	function openRow(row: EntityRow) {
		if (row.kind === 'category') {
			studio.setCategoryFilter(row.id);
			studio.closePalette();
		} else {
			studio.select('app', row.id);
		}
	}

	function setMode(next: Mode) {
		mode = next;
	}

	function onKeydown(event: KeyboardEvent) {
		if (event.key === 'Escape') {
			event.preventDefault();
			close();
			return;
		}
		if (event.key === 'ArrowDown') {
			event.preventDefault();
			active = Math.min(active + 1, Math.max(0, activeCount - 1));
			void scrollActive();
			return;
		}
		if (event.key === 'ArrowUp') {
			event.preventDefault();
			active = Math.max(0, active - 1);
			void scrollActive();
			return;
		}
		if (event.key === 'Enter') {
			event.preventDefault();
			choose(active);
		}
	}

	async function scrollActive() {
		await tick();
		document.getElementById(`palette-item-${active}`)?.scrollIntoView({ block: 'nearest' });
	}
</script>

<svelte:window onkeydown={onKeydown} />

<div
	class="backdrop"
	role="presentation"
	onclick={(event) => {
		if (event.target === event.currentTarget) close();
	}}
>
	<div class="palette" role="dialog" aria-modal="true" aria-label="Search reviews and apps">
		<div class="input-row">
			<svg width="15" height="15" viewBox="0 0 16 16" fill="none" aria-hidden="true">
				<circle cx="6.8" cy="6.8" r="4.8" stroke="currentColor" stroke-width="1.3" />
				<path d="M10.6 10.6 14 14" stroke="currentColor" stroke-width="1.3" />
			</svg>
			<input
				bind:this={inputEl}
				bind:value={query}
				onkeydown={onKeydown}
				placeholder="Search reviews by meaning, or jump to an app…"
				aria-label="Search reviews by meaning"
				spellcheck="false"
			/>
			{#if query}
				<button class="clear" onclick={() => (query = '')} aria-label="Clear query">×</button>
			{/if}
			<kbd>esc</kbd>
		</div>

		<div class="mode-row">
			<div class="modes" role="tablist" aria-label="Search mode">
				<button
					role="tab"
					aria-selected={mode === 'reviews'}
					class:active={mode === 'reviews'}
					onclick={() => setMode('reviews')}
				>
					Reviews
				</button>
				<button
					role="tab"
					aria-selected={mode === 'entities'}
					class:active={mode === 'entities'}
					onclick={() => setMode('entities')}
				>
					Apps & categories
				</button>
			</div>
			<span class="index-meta">
				{studio.isLive ? 'live index' : 'demo index'} · 768-d · cosine
			</span>
		</div>

		<div class="results">
			{#if mode === 'reviews'}
				{#if !query.trim()}
					<div class="section">
						<span class="label">Try asking</span>
						<div class="suggestions">
							{#each suggestions as suggestion}
								<button class="suggestion" onclick={() => (query = suggestion)}>
									{suggestion}
								</button>
							{/each}
						</div>
					</div>
					<div class="section">
						<span class="label">Jump to</span>
						{#each entities.slice(0, 6) as row, index (row.kind + row.id)}
							<button
								id="palette-item-{index}"
								class="entity"
								class:active={active === index}
								onclick={() => openRow(row)}
								onpointerenter={() => (active = index)}
							>
								<span class="dot" style:background={row.accent}></span>
								<span class="entity-name">{row.name}</span>
								<span class="entity-sub">{row.sub}</span>
								<span class="entity-score num" style:color={receptionColor(row.reception)}>
									{row.reception}
								</span>
							</button>
						{/each}
					</div>
				{:else if loading && results.length === 0}
					<div class="loading">
						<span class="pulse"></span>
						searching the vector index…
					</div>
				{:else if results.length === 0}
					<div class="empty">
						<p>No semantic matches.</p>
						<span>Try a shorter phrase, or switch to Apps & categories.</span>
					</div>
				{:else}
					<div class="section">
						<div class="section-head">
							<span class="label">Semantic matches</span>
							<span class="count num">{results.length}</span>
						</div>
						{#each results as hit, index (hit.id)}
							<button
								id="palette-item-{index}"
								class="hit"
								class:active={active === index}
								onclick={() => studio.select('app', hit.appId)}
								onpointerenter={() => (active = index)}
							>
								<div class="hit-top">
									<span class="hit-app">{hit.appName}</span>
									<Stars rating={hit.stars} size={9} />
									<span class="hit-date">{relTime(hit.date)}</span>
									<span class="hit-score num"
										>{Math.round(Math.max(0, Math.min(1, hit.score)) * 100)}%</span
									>
								</div>
								<p>{truncate(hit.text, 170)}</p>
							</button>
						{/each}
					</div>
				{/if}
			{:else}
				{#if entities.length === 0}
					<div class="empty">
						<p>No apps or categories match.</p>
						<span>Try a different name.</span>
					</div>
				{:else}
					<div class="section">
						<div class="section-head">
							<span class="label">{query.trim() ? 'Matches' : `Top by ${studio.metric === 'downloads' ? 'downloads' : 'review volume'}`}</span>
							<span class="count num">{entities.length}</span>
						</div>
						{#each entities as row, index (row.kind + row.id)}
							<button
								id="palette-item-{index}"
								class="entity"
								class:active={active === index}
								onclick={() => openRow(row)}
								onpointerenter={() => (active = index)}
							>
								<span class="dot" style:background={row.accent}></span>
								<span class="entity-kind">{row.kind === 'app' ? 'APP' : 'CO'}</span>
								<span class="entity-name">{row.name}</span>
								<span class="entity-sub">{row.sub}</span>
								<span class="entity-score num" style:color={receptionColor(row.reception)}>
									{row.reception}
								</span>
							</button>
						{/each}
					</div>
				{/if}
			{/if}
		</div>

		<footer class="palette-foot">
			<span><kbd>↑</kbd><kbd>↓</kbd> navigate</span>
			<span><kbd>↵</kbd> inspect</span>
			<span><kbd>esc</kbd> close</span>
			<span class="spacer"></span>
			<span class="source">
				<i class="dot" class:live={studio.isLive}></i>
				{studio.sourceLabel}
			</span>
		</footer>
	</div>
</div>

<style>
	.backdrop {
		position: fixed;
		inset: 0;
		z-index: 100;
		background: rgba(4, 4, 6, 0.68);
		backdrop-filter: blur(3px);
		display: flex;
		align-items: flex-start;
		justify-content: center;
		padding-top: 11vh;
	}

	.palette {
		width: min(640px, 92vw);
		max-height: 68vh;
		display: flex;
		flex-direction: column;
		background: var(--panel);
		border: 1px solid var(--line-bright);
		border-radius: 3px;
		box-shadow:
			0 0 0 1px rgba(0, 0, 0, 0.4),
			0 40px 120px rgba(0, 0, 0, 0.7);
		overflow: hidden;
	}

	.input-row {
		display: flex;
		align-items: center;
		gap: 10px;
		padding: 0 14px;
		height: 50px;
		border-bottom: 1px solid var(--line);
		color: var(--dim);
		flex: none;
	}
	.input-row input {
		flex: 1;
		height: 100%;
		background: transparent;
		border: 0;
		outline: none;
		font-family: var(--sans);
		font-size: 15px;
		color: var(--text);
	}
	.input-row input::placeholder {
		color: var(--dim);
	}
	.input-row input::-webkit-search-cancel-button {
		display: none;
	}
	.clear {
		width: 22px;
		height: 22px;
		display: grid;
		place-items: center;
		font-size: 16px;
		color: var(--muted);
		border: 1px solid var(--line);
		border-radius: 2px;
	}
	.clear:hover {
		color: var(--text);
	}
	kbd {
		font-family: var(--mono);
		font-size: 8px;
		color: var(--muted);
		border: 1px solid var(--line);
		border-radius: 2px;
		padding: 1px 4px;
		background: var(--bg-soft);
	}

	.mode-row {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 7px 12px;
		border-bottom: 1px solid var(--line);
		flex: none;
	}
	.modes {
		display: flex;
		gap: 2px;
	}
	.modes button {
		height: 23px;
		padding: 0 9px;
		font-family: var(--mono);
		font-size: 9px;
		letter-spacing: 0.06em;
		text-transform: uppercase;
		color: var(--dim);
		border: 1px solid transparent;
		border-radius: 2px;
	}
	.modes button:hover {
		color: var(--text-2);
	}
	.modes button.active {
		color: var(--lime);
		border-color: color-mix(in srgb, var(--lime) 28%, var(--line));
		background: color-mix(in srgb, var(--lime) 6%, transparent);
	}
	.index-meta {
		font-family: var(--mono);
		font-size: 8px;
		color: var(--faint);
		letter-spacing: 0.04em;
	}

	.results {
		flex: 1;
		overflow-y: auto;
		padding: 6px 8px 10px;
		min-height: 120px;
	}
	.section {
		padding: 4px 2px;
	}
	.section-head {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 6px 8px;
	}
	.section > .label {
		display: block;
		padding: 6px 8px 7px;
	}
	.count {
		font-size: 8px;
		color: var(--dim);
	}

	.suggestions {
		display: flex;
		flex-wrap: wrap;
		gap: 5px;
		padding: 0 4px;
	}
	.suggestion {
		height: 25px;
		padding: 0 9px;
		border: 1px solid var(--line);
		border-radius: 2px;
		font-family: var(--mono);
		font-size: 9.5px;
		color: var(--muted);
		background: var(--bg-soft);
	}
	.suggestion:hover {
		color: var(--lime);
		border-color: var(--lime-dim);
	}

	.entity,
	.hit {
		width: 100%;
		display: flex;
		align-items: center;
		gap: 8px;
		padding: 7px 8px;
		border: 1px solid transparent;
		border-radius: 2px;
		text-align: left;
	}
	.entity.active,
	.hit.active {
		background: var(--panel-3);
		border-color: var(--line);
	}
	.dot {
		width: 5px;
		height: 5px;
		border-radius: 50%;
		flex: none;
	}
	.entity-kind {
		font-family: var(--mono);
		font-size: 7.5px;
		color: var(--faint);
		letter-spacing: 0.08em;
	}
	.entity-name {
		font-size: 12px;
		color: var(--text);
		flex: none;
	}
	.entity-sub {
		font-family: var(--mono);
		font-size: 8.5px;
		color: var(--dim);
		flex: 1;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.entity-score {
		font-size: 9.5px;
		font-weight: 500;
	}

	.hit {
		flex-direction: column;
		align-items: stretch;
		gap: 4px;
		padding: 9px 9px 10px;
	}
	.hit-top {
		display: flex;
		align-items: center;
		gap: 7px;
	}
	.hit-app {
		font-size: 11px;
		font-weight: 500;
		color: var(--text);
	}
	.hit-date {
		margin-left: auto;
		font-family: var(--mono);
		font-size: 8px;
		color: var(--dim);
	}
	.hit-score {
		font-family: var(--mono);
		font-size: 8.5px;
		color: var(--lime);
	}
	.hit p {
		margin: 0;
		font-size: 11px;
		line-height: 1.5;
		color: var(--muted);
		display: -webkit-box;
		-webkit-line-clamp: 2;
		line-clamp: 2;
		-webkit-box-orient: vertical;
		overflow: hidden;
	}
	.hit.active p {
		color: var(--text-2);
	}

	.loading {
		display: flex;
		align-items: center;
		gap: 9px;
		padding: 26px 14px;
		font-family: var(--mono);
		font-size: 9.5px;
		color: var(--dim);
		letter-spacing: 0.04em;
	}
	.pulse {
		width: 6px;
		height: 6px;
		border-radius: 50%;
		background: var(--lime);
		animation: blink 900ms ease-in-out infinite;
	}
	@keyframes blink {
		50% {
			opacity: 0.15;
		}
	}
	.empty {
		padding: 30px 16px;
		text-align: center;
	}
	.empty p {
		margin: 0 0 4px;
		font-size: 12px;
		color: var(--text-2);
	}
	.empty span {
		font-size: 10px;
		color: var(--dim);
	}

	.palette-foot {
		flex: none;
		display: flex;
		align-items: center;
		gap: 14px;
		padding: 8px 12px;
		border-top: 1px solid var(--line);
		background: var(--bg-soft);
		font-family: var(--mono);
		font-size: 8px;
		color: var(--dim);
	}
	.palette-foot span {
		display: inline-flex;
		align-items: center;
		gap: 3px;
	}
	.spacer {
		flex: 1;
	}
	.source {
		gap: 5px !important;
	}
	.source .dot {
		background: var(--amber);
	}
	.source .dot.live {
		background: var(--pos);
	}

	@media (max-width: 720px) {
		.backdrop {
			padding-top: 0;
			align-items: stretch;
		}
		.palette {
			width: 100%;
			max-height: none;
			height: 100%;
			border: 0;
			border-radius: 0;
		}
		.index-meta {
			display: none;
		}
	}
</style>
