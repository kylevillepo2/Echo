<script lang="ts">
	import { studio } from '#lib/state/studio.svelte';
	import { receptionColor } from '#lib/utils/palette';

	let expanded = $state<Set<string>>(new Set());

	const visibleByCategory = $derived.by(() => {
		const map = new Map<string, typeof studio.visibleApps>();
		for (const app of studio.visibleApps) {
			const list = map.get(app.categoryId) ?? [];
			list.push(app);
			map.set(app.categoryId, list);
		}
		for (const list of map.values()) {
			list.sort((a, b) => studio.metricValue(b) - studio.metricValue(a));
		}
		return map;
	});

	function toggleExpanded(id: string) {
		const next = new Set(expanded);
		if (next.has(id)) next.delete(id);
		else next.add(id);
		expanded = next;
	}

	function isExpanded(id: string): boolean {
		return studio.categoryFilter === id || expanded.has(id);
	}

	const themeChip = $derived(studio.themeFilter ? studio.themeById(studio.themeFilter) : null);
	const categoryChip = $derived(studio.selectedCategory);
</script>

<aside class="sidebar" aria-label="App categories and apps">
	<div class="head">
		<span class="label">Corpus</span>
		<span class="count num">{studio.visibleApps.length}/{studio.meta?.appCount ?? 0}</span>
	</div>

	<div class="search-wrap">
		<svg width="12" height="12" viewBox="0 0 14 14" fill="none" aria-hidden="true">
			<circle cx="6" cy="6" r="4.4" stroke="currentColor" stroke-width="1.2" />
			<path d="M9.4 9.4 12.5 12.5" stroke="currentColor" stroke-width="1.2" />
		</svg>
		<input
			class="input filter-input"
			type="search"
			placeholder="Filter apps or categories"
			aria-label="Filter apps or categories"
			bind:value={studio.query}
		/>
		{#if studio.query}
			<button class="clear" onclick={() => (studio.query = '')} aria-label="Clear filter">×</button>
		{/if}
	</div>

	{#if themeChip || categoryChip || studio.query}
		<div class="active-filters">
			{#if themeChip}
				<button
					class="chip"
					class:is-pos={themeChip.kind === 'positive'}
					class:is-neg={themeChip.kind === 'negative'}
					onclick={() => studio.toggleTheme(themeChip.id)}
				>
					{themeChip.label}
					<span class="x">×</span>
				</button>
			{/if}
			{#if categoryChip}
				<button class="chip" onclick={() => studio.clearCategoryFilter()}>
					{categoryChip.name}
					<span class="x">×</span>
				</button>
			{/if}
			<button class="clear-all" onclick={() => studio.clearFilters()}>clear</button>
		</div>
	{/if}

	<div class="list scroll">
		{#if studio.categoryFilter}
			<button class="all-clusters" onclick={() => studio.clearCategoryFilter()}>
				<span class="back">←</span>
				<span>All category clusters</span>
				<span class="num">{studio.categories.length}</span>
			</button>
		{/if}

		{#each studio.visibleCategories as category (category.id)}
			<div
				class="category"
				class:selected={studio.categoryFilter === category.id}
				style:--accent={category.accent}
			>
				<div class="category-row">
					<button
						class="category-main"
						onclick={() => studio.setCategoryFilter(category.id)}
						aria-label="Focus {category.name} cluster"
						aria-pressed={studio.categoryFilter === category.id}
					>
						<span class="swatch"></span>
						<span class="category-text">
							<span class="cname">{category.name}</span>
							<span class="cmeta">
								{studio.categoryMetricLabel(category)}
							</span>
						</span>
						<span class="cscore num" style:color={receptionColor(category.reception)}>
							{category.reception}
						</span>
					</button>
					<button
						class="expander"
						onclick={() => toggleExpanded(category.id)}
						aria-label={isExpanded(category.id) ? `Collapse ${category.name}` : `Expand ${category.name}`}
						aria-expanded={isExpanded(category.id)}
					>
						<span class:rotated={!isExpanded(category.id)}>▾</span>
					</button>
				</div>

				{#if isExpanded(category.id)}
					<div class="apps">
						{#each visibleByCategory.get(category.id) ?? [] as app (app.id)}
							<button
								class="app-row"
								class:selected={studio.selected?.kind === 'app' && studio.selected.id === app.id}
								onclick={() => studio.select('app', app.id)}
							>
								<span class="app-dot" style:background={app.accent}></span>
								<span class="app-name">{app.name}</span>
								{#if studio.metric === 'downloads'}
									<span class="app-metric num" title="{studio.metricLabelFor(app)} downloads">
										{studio.metricLabelFor(app)}
									</span>
								{:else}
									<span class="app-rating num">{app.rating.toFixed(1)}</span>
								{/if}
								<span class="app-meter" title="Reception {app.reception}/100">
									<i
										style:width="{app.reception}%"
										style:background={receptionColor(app.reception)}
									></i>
								</span>
							</button>
						{/each}
					</div>
				{/if}
			</div>
		{/each}

		{#if studio.visibleCategories.length === 0}
			<div class="empty">
				<p>No apps match this filter.</p>
				<button class="btn is-sm" onclick={() => studio.clearFilters()}>Clear filters</button>
			</div>
		{/if}
	</div>

	<div class="foot">
		<div class="foot-top">
			<span class="label-dim">Data source</span>
			<span class="foot-mode" class:live={studio.isLive}>
				{studio.isLive ? 'LIVE API' : 'DEMO SEED'}
			</span>
		</div>
		<button class="btn connect" onclick={() => (studio.connectOpen = true)}>
			<svg width="11" height="11" viewBox="0 0 12 12" fill="none" aria-hidden="true">
				<path d="M4.5 3.5 2 6l2.5 2.5M7.5 3.5 10 6 7.5 8.5" stroke="currentColor" stroke-width="1.1" />
			</svg>
			{studio.isLive ? 'Manage connection' : 'Connect your API'}
		</button>
	</div>
</aside>

<style>
	.sidebar {
		width: var(--sidebar-w);
		flex: none;
		display: flex;
		flex-direction: column;
		min-height: 0;
		border-right: 1px solid var(--line);
		background: var(--panel);
	}

	.head {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 11px 12px 8px;
	}
	.count {
		font-size: 9.5px;
		color: var(--dim);
	}

	.search-wrap {
		position: relative;
		margin: 0 10px 8px;
		color: var(--dim);
	}
	.search-wrap svg {
		position: absolute;
		left: 9px;
		top: 50%;
		transform: translateY(-50%);
		pointer-events: none;
	}
	.filter-input {
		height: 30px;
		padding-left: 26px;
		font-family: var(--mono);
		font-size: 10.5px;
		background: var(--bg-soft);
	}
	.filter-input::-webkit-search-cancel-button {
		display: none;
	}
	.clear {
		position: absolute;
		right: 6px;
		top: 50%;
		transform: translateY(-50%);
		width: 18px;
		height: 18px;
		display: grid;
		place-items: center;
		font-size: 14px;
		color: var(--muted);
		border-radius: 2px;
	}
	.clear:hover {
		color: var(--text);
		background: var(--panel-3);
	}

	.active-filters {
		display: flex;
		align-items: center;
		flex-wrap: wrap;
		gap: 4px;
		padding: 0 10px 8px;
	}
	.active-filters .chip {
		height: 20px;
		gap: 5px;
		cursor: pointer;
	}
	.x {
		color: var(--dim);
		font-size: 11px;
		line-height: 1;
	}
	.clear-all {
		font-family: var(--mono);
		font-size: 9px;
		letter-spacing: 0.06em;
		color: var(--dim);
		text-decoration: underline;
		text-underline-offset: 2px;
		margin-left: 2px;
	}
	.clear-all:hover {
		color: var(--text);
	}

	.list {
		flex: 1;
		min-height: 0;
		padding-bottom: 8px;
	}

	.all-clusters {
		width: 100%;
		display: flex;
		align-items: center;
		gap: 7px;
		padding: 8px 12px;
		border-bottom: 1px solid var(--line);
		font-family: var(--mono);
		font-size: 9px;
		letter-spacing: 0.04em;
		color: var(--muted);
		text-align: left;
	}
	.all-clusters:hover {
		color: var(--text);
		background: var(--panel-2);
	}
	.all-clusters .back {
		color: var(--lime);
	}
	.all-clusters .num {
		margin-left: auto;
		color: var(--faint);
	}

	.category {
		border-bottom: 1px solid var(--line);
	}
	.category-row {
		display: flex;
		align-items: stretch;
	}
	.category-main {
		flex: 1;
		display: flex;
		align-items: center;
		gap: 8px;
		padding: 9px 4px 9px 12px;
		text-align: left;
		min-width: 0;
		transition: background var(--fast);
	}
	.category-main:hover {
		background: var(--panel-2);
	}
	.category.selected .category-main {
		background: color-mix(in srgb, var(--accent) 9%, var(--panel));
		box-shadow: inset 2px 0 0 var(--accent);
	}
	.swatch {
		width: 7px;
		height: 7px;
		background: var(--accent);
		flex: none;
		border-radius: 1px;
	}
	.category-text {
		display: flex;
		flex-direction: column;
		min-width: 0;
		flex: 1;
	}
	.cname {
		font-size: 12px;
		font-weight: 500;
		color: var(--text-2);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.category.selected .cname {
		color: var(--text);
	}
	.cmeta {
		font-family: var(--mono);
		font-size: 8.5px;
		color: var(--dim);
		margin-top: 2px;
		letter-spacing: 0.02em;
	}
	.cscore {
		font-family: var(--mono);
		font-size: 11px;
		font-weight: 600;
		flex: none;
	}
	.expander {
		width: 26px;
		display: grid;
		place-items: center;
		color: var(--dim);
		font-size: 9px;
	}
	.expander:hover {
		color: var(--text);
	}
	.expander span {
		display: block;
		transition: transform var(--fast);
	}
	.expander span.rotated {
		transform: rotate(-90deg);
	}

	.apps {
		padding: 1px 0 5px;
	}
	.app-row {
		width: 100%;
		display: flex;
		align-items: center;
		gap: 7px;
		padding: 5px 12px 5px 26px;
		text-align: left;
		transition: background var(--fast);
	}
	.app-row:hover {
		background: var(--bg-soft);
	}
	.app-row.selected {
		background: color-mix(in srgb, var(--lime) 8%, var(--panel));
	}
	.app-row.selected .app-name {
		color: var(--text);
	}
	.app-dot {
		width: 4px;
		height: 4px;
		border-radius: 50%;
		flex: none;
		opacity: 0.85;
	}
	.app-name {
		font-size: 11.5px;
		color: var(--muted);
		flex: 1;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.app-rating {
		font-size: 9px;
		color: var(--dim);
	}
	.app-metric {
		font-size: 8px;
		color: var(--dim);
		letter-spacing: -0.02em;
	}
	.app-meter {
		width: 26px;
		height: 3px;
		background: var(--panel-3);
		border-radius: 1px;
		overflow: hidden;
		flex: none;
	}
	.app-meter i {
		display: block;
		height: 100%;
	}

	.empty {
		padding: 26px 16px;
		text-align: center;
	}
	.empty p {
		margin: 0 0 10px;
		font-size: 11.5px;
		color: var(--dim);
	}

	.foot {
		flex: none;
		border-top: 1px solid var(--line);
		padding: 10px;
		background: var(--bg-soft);
	}
	.foot-top {
		display: flex;
		align-items: center;
		justify-content: space-between;
		margin-bottom: 7px;
	}
	.foot-mode {
		font-family: var(--mono);
		font-size: 8.5px;
		letter-spacing: 0.1em;
		color: var(--amber);
	}
	.foot-mode.live {
		color: var(--pos);
	}
	.connect {
		width: 100%;
		justify-content: flex-start;
		gap: 7px;
		height: 28px;
		background: transparent;
		border-color: var(--line);
		color: var(--muted);
	}
	.connect:hover {
		color: var(--text);
		border-color: var(--line-bright);
	}

	@media (max-width: 980px) {
		.sidebar {
			position: absolute;
			top: var(--header-h);
			bottom: var(--status-h);
			left: 0;
			z-index: 25;
			width: 288px;
			box-shadow: 24px 0 60px rgba(0, 0, 0, 0.55);
		}
	}
</style>
