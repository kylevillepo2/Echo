<script lang="ts">
	import { studio, type ColourMode } from '#lib/state/studio.svelte';
	import GraphCanvas from './GraphCanvas.svelte';

	const modes: { id: ColourMode; label: string }[] = [
		{ id: 'category', label: 'Category' },
		{ id: 'reception', label: 'Reception' },
		{ id: 'platform', label: 'Platform' }
	];

	const themeChip = $derived(studio.themeFilter ? studio.themeById(studio.themeFilter) : null);
	const categoryChip = $derived(studio.selectedCategory);
</script>

<section class="network" aria-label="Semantic network">
	<header class="toolbar">
		<div class="left">
			<span class="label">Semantic map</span>
			<span class="stats num">
				{studio.visibleApps.length} apps · {studio.visibleCategories.length} categories ·
				{studio.visibleEdges.length} links
			</span>
		</div>

		<div class="filter-row">
			{#if themeChip}
				<button
					class="chip"
					class:is-pos={themeChip.kind === 'positive'}
					class:is-neg={themeChip.kind === 'negative'}
					onclick={() => studio.toggleTheme(themeChip.id)}
				>
					{themeChip.label} <span class="x">×</span>
				</button>
			{/if}
			{#if categoryChip}
				<button class="chip" onclick={() => studio.clearCategoryFilter()}>
					{categoryChip.name} <span class="x">×</span>
				</button>
			{/if}
			{#if studio.query}
				<button class="chip" onclick={() => (studio.query = '')}>
					“{studio.query}” <span class="x">×</span>
				</button>
			{/if}
			{#if studio.hasFilters}
				<button class="clear" onclick={() => studio.clearFilters()}>clear all</button>
			{/if}
		</div>

		<div class="right">
			<span class="label-dim">Colour by</span>
			<div class="seg" role="group" aria-label="Colour nodes by">
				{#each modes as mode}
					<button
						class:active={studio.colourMode === mode.id}
						onclick={() => (studio.colourMode = mode.id)}
						aria-pressed={studio.colourMode === mode.id}
					>
						{mode.label}
					</button>
				{/each}
			</div>
		</div>
	</header>

	<GraphCanvas />
</section>

<style>
	.network {
		flex: 1;
		min-width: 0;
		display: flex;
		flex-direction: column;
		min-height: 0;
	}

	.toolbar {
		height: 42px;
		flex: none;
		display: flex;
		align-items: center;
		gap: 14px;
		padding: 0 14px;
		border-bottom: 1px solid var(--line);
		background: var(--panel);
	}
	.left {
		display: flex;
		align-items: baseline;
		gap: 10px;
		min-width: 0;
	}
	.stats {
		font-size: 9px;
		color: var(--dim);
		letter-spacing: 0.02em;
		white-space: nowrap;
	}
	.filter-row {
		display: flex;
		align-items: center;
		gap: 5px;
		min-width: 0;
		overflow: hidden;
	}
	.filter-row .chip {
		height: 20px;
		cursor: pointer;
	}
	.x {
		color: var(--dim);
		margin-left: 1px;
	}
	.clear {
		font-family: var(--mono);
		font-size: 8.5px;
		letter-spacing: 0.06em;
		color: var(--dim);
		text-transform: uppercase;
		text-decoration: underline;
		text-underline-offset: 2px;
		white-space: nowrap;
	}
	.clear:hover {
		color: var(--text);
	}

	.right {
		margin-left: auto;
		display: flex;
		align-items: center;
		gap: 8px;
		flex: none;
	}
	.seg {
		display: flex;
		border: 1px solid var(--line);
		border-radius: 2px;
		overflow: hidden;
	}
	.seg button {
		height: 23px;
		padding: 0 9px;
		font-family: var(--mono);
		font-size: 8.5px;
		letter-spacing: 0.06em;
		text-transform: uppercase;
		color: var(--dim);
		border-right: 1px solid var(--line);
		transition:
			background var(--fast),
			color var(--fast);
	}
	.seg button:last-child {
		border-right: 0;
	}
	.seg button:hover {
		color: var(--text-2);
		background: var(--panel-2);
	}
	.seg button.active {
		background: var(--panel-3);
		color: var(--lime);
	}

	@media (max-width: 1180px) {
		.stats {
			display: none;
		}
	}
	@media (max-width: 860px) {
		.filter-row {
			display: none;
		}
	}
	@media (max-width: 720px) {
		.right .label-dim {
			display: none;
		}
		.seg button {
			padding: 0 7px;
			font-size: 8px;
		}
	}
</style>
