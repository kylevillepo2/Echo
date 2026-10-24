<script lang="ts">
	import type { ThemeImpact } from '#lib/api/types';
	import { fmtCount, fmtLag, fmtR } from '#lib/utils/format';

	let {
		label,
		share,
		count,
		kind,
		max = 1,
		active = false,
		impact,
		onclick
	}: {
		label: string;
		share: number;
		count: number;
		kind: 'positive' | 'negative';
		max?: number;
		active?: boolean;
		impact?: ThemeImpact;
		onclick?: () => void;
	} = $props();

	const color = $derived(kind === 'positive' ? 'var(--pos)' : 'var(--neg)');
	const width = $derived(Math.min(100, (share / Math.max(0.001, max)) * 100));
</script>

<button class="theme-bar" class:active onclick={onclick} title="Filter the corpus by {label}">
	<div class="row">
		<span class="dot" style:background={color}></span>
		<span class="name">{label}</span>
		<span class="pct num">{Math.round(share * 100)}%</span>
	</div>
	<div class="meter" style:color={color}>
		<i style:width="{width}%"></i>
	</div>
	<div class="sub">
		<span>{fmtCount(count)} mentions</span>
		{#if impact}
			<span
				class="impact num"
				class:pos={impact.r >= 0}
				class:neg={impact.r < 0}
				title="Weekly correlation with downloads · {impact.confidence} confidence · {impact.mentions} mentions"
			>
				r {fmtR(impact.r)} · {fmtLag(impact.lag)}
			</span>
		{:else if active}
			<span class="on" style:color={color}>filtering</span>
		{/if}
	</div>
</button>

<style>
	.theme-bar {
		width: 100%;
		text-align: left;
		padding: 6px 6px 7px;
		border: 1px solid transparent;
		border-radius: 2px;
		transition:
			background var(--fast),
			border-color var(--fast);
	}
	.theme-bar:hover {
		background: var(--panel-2);
		border-color: var(--line);
	}
	.theme-bar.active {
		border-color: color-mix(in srgb, var(--lime) 45%, transparent);
		background: color-mix(in srgb, var(--lime) 5%, transparent);
	}
	.row {
		display: flex;
		align-items: center;
		gap: 6px;
	}
	.dot {
		width: 4px;
		height: 4px;
		border-radius: 50%;
		flex: none;
	}
	.name {
		font-size: 11.5px;
		color: var(--text-2);
		flex: 1;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.pct {
		font-size: 9.5px;
		color: var(--muted);
	}
	.meter {
		height: 3px;
		background: var(--panel-3);
		margin: 5px 0 4px;
		border-radius: 1px;
		overflow: hidden;
	}
	.meter i {
		display: block;
		height: 100%;
		background: currentColor;
		transition: width 520ms var(--ease);
	}
	.sub {
		display: flex;
		justify-content: space-between;
		font-family: var(--mono);
		font-size: 8px;
		color: var(--faint);
	}
	.on {
		font-size: 8px;
		letter-spacing: 0.06em;
		text-transform: uppercase;
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
</style>
