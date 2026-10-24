<script lang="ts">
	import { studio } from '#lib/state/studio.svelte';
	import { fmtCount } from '#lib/utils/format';
	const meta = $derived(studio.meta);
</script>

<footer class="statusbar">
	<div class="group">
		<span class="mode" class:live={studio.isLive}>
			<i class="dot"></i>
			{studio.isLive ? 'LIVE' : 'DEMO'}
		</span>
		<span class="sep"></span>
		<span><b class="num">{meta?.categoryCount ?? '—'}</b> categories</span>
		<span><b class="num">{meta?.appCount ?? '—'}</b> apps</span>
		<span><b class="num">{fmtCount(meta?.reviewCount ?? 0)}</b> reviews indexed</span>
		<span class="hide-sm"><b class="num">{fmtCount(studio.visibleRatePerDay)}</b> downloads/day</span>
		<span class="sep hide-sm"></span>
		<span class="hide-sm">
			{meta?.embeddingDim ?? '—'}-d · {meta?.embeddingModel ?? 'embedding model'}
		</span>
		{#if studio.hasFilters}
			<span class="sep"></span>
			<span class="filtered"><b class="num">{studio.visibleApps.length}</b> in view</span>
		{/if}
	</div>

	<div class="keys">
		{#if studio.error}
			<span class="error" title={studio.error}>connection error</span>
		{/if}
		{#if !studio.categoryFilter}
			<span class="metric-toggle" role="group" aria-label="Size nodes by">
				<span class="metric-label">size</span>
				<button class:active={studio.metric === 'reviews'} onclick={() => studio.setMetric('reviews')}>
					reviews
				</button>
				<button
					class:active={studio.metric === 'downloads'}
					onclick={() => studio.setMetric('downloads')}
				>
					downloads
				</button>
			</span>
		{/if}
		<span class="hide-sm"><kbd>⌘K</kbd> search</span>
		<span class="hide-sm"><kbd>esc</kbd> close</span>
		<span class="live-line" class:live={studio.isLive}>
			{studio.isLive ? 'VECTOR STORE CONNECTED' : 'SEEDED DEMO DATA'}
		</span>
	</div>
</footer>

<style>
	.statusbar {
		height: var(--status-h);
		flex: none;
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 14px;
		padding: 0 12px;
		border-top: 1px solid var(--line);
		background: var(--bg-soft);
		font-family: var(--mono);
		font-size: 9px;
		letter-spacing: 0.04em;
		color: var(--dim);
		white-space: nowrap;
		overflow: hidden;
	}
	.group {
		display: flex;
		align-items: center;
		gap: 10px;
		min-width: 0;
		overflow: hidden;
	}
	.group b {
		font-weight: 500;
		color: var(--muted);
	}
	.mode {
		display: inline-flex;
		align-items: center;
		gap: 5px;
		color: var(--amber);
		letter-spacing: 0.1em;
	}
	.mode.live {
		color: var(--pos);
	}
	.dot {
		width: 5px;
		height: 5px;
		border-radius: 50%;
		background: currentColor;
	}
	.sep {
		width: 1px;
		height: 11px;
		background: var(--line);
	}
	.filtered {
		color: var(--lime);
	}
	.keys {
		display: flex;
		align-items: center;
		gap: 12px;
		flex: none;
	}
	.metric-toggle {
		display: inline-flex;
		align-items: center;
		gap: 1px;
		padding: 1px;
		border: 1px solid var(--line);
		border-radius: 2px;
		background: var(--panel);
	}
	.metric-label {
		padding: 0 5px;
		color: var(--faint);
		font-size: 8px;
		letter-spacing: 0.08em;
		text-transform: uppercase;
	}
	.metric-toggle button {
		padding: 2px 6px;
		border-radius: 1px;
		font-family: var(--mono);
		font-size: 8px;
		letter-spacing: 0.05em;
		color: var(--dim);
		transition:
			background var(--fast),
			color var(--fast);
	}
	.metric-toggle button:hover {
		color: var(--text-2);
	}
	.metric-toggle button.active {
		background: color-mix(in srgb, var(--lime) 12%, transparent);
		color: var(--lime);
	}
	kbd {
		font-family: var(--mono);
		font-size: 8px;
		color: var(--muted);
		border: 1px solid var(--line);
		border-radius: 2px;
		padding: 1px 3px;
		margin-right: 3px;
		background: var(--panel);
	}
	.live-line {
		color: var(--dim);
		letter-spacing: 0.1em;
		font-size: 8px;
	}
	.live-line.live {
		color: var(--pos);
	}
	.error {
		color: var(--neg);
	}
	@media (max-width: 1080px) {
		.hide-sm {
			display: none;
		}
	}
	@media (max-width: 720px) {
		.keys {
			display: none;
		}
	}
</style>
