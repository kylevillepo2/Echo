<script lang="ts">
	import { fmtCount } from '#lib/utils/format';

	let { points, label, unit = 'reviews', mode = 'bar' }: {
		points: { month: string; value: number | null; partial: boolean; low: boolean }[];
		label: string;
		unit?: 'reviews' | '%';
		mode?: 'bar' | 'line';
	} = $props();
	let active = $state<string | null>(null);
	const W = 340;
	const H = 135;
	const pad = { l: 30, r: 10, t: 15, b: 24 };
	const max = $derived(Math.max(1, ...points.flatMap((point) => point.value === null ? [] : [point.value])));
	const geometry = $derived(points.map((point, index) => ({
		...point,
		x: pad.l + (index / Math.max(1, points.length - 1)) * (W - pad.l - pad.r),
		y: point.value === null ? null : pad.t + (1 - point.value / max) * (H - pad.t - pad.b)
	})));
	const path = $derived.by(() => {
		let connected = false;
		return geometry.map((point) => {
			if (point.y === null) { connected = false; return ''; }
			const command = connected ? 'L' : 'M';
			connected = true;
			return `${command}${point.x},${point.y}`;
		}).join(' ');
	});
	const selected = $derived(points.find((point) => point.month === active));
	const valueLabel = (value: number | null) => value === null ? 'No data' : unit === '%' ? `${value.toFixed(1)}%` : `${fmtCount(value)} reviews`;
	const monthLabel = (month: string) => new Date(`${month}-01T00:00:00Z`).toLocaleDateString('en-US', { month: 'short', year: 'numeric', timeZone: 'UTC' });
</script>

<div class="chart">
	<svg viewBox="0 0 {W} {H}" role="img" aria-label={label}>
		<line x1={pad.l} x2={W - pad.r} y1={H - pad.b} y2={H - pad.b} class="baseline" />
		<text x="1" y={pad.t + 3} class="axis">{unit === '%' ? `${max.toFixed(0)}%` : fmtCount(max)}</text>
		<text x="18" y={H - pad.b} class="axis">0</text>
		{#if mode === 'line'}<path d={path} class="series" />{/if}
		{#each geometry as point, index (point.month)}
			<g
				class="point" class:partial={point.partial || point.low}
				role="button" tabindex="0"
				aria-label="{monthLabel(point.month)}: {valueLabel(point.value)}{point.partial ? ', partial month' : ''}{point.low ? ', low review volume' : ''}"
				onpointerenter={() => (active = point.month)} onpointerleave={() => (active = null)}
				onfocus={() => (active = point.month)} onblur={() => (active = null)}
				onclick={() => (active = point.month)}
				onkeydown={(event) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); active = point.month; } }}
			>
				<title>{monthLabel(point.month)}: {valueLabel(point.value)}{point.partial ? ' — partial month' : ''}{point.low ? ' — low review volume' : ''}</title>
				<rect x={point.x - 6} y={pad.t} width="12" height={H - pad.t - pad.b} fill="transparent" />
				{#if point.y !== null}
					{#if mode === 'bar'}
						<rect class="bar" x={point.x - 3.5} y={point.y} width="7" height={Math.max(1, H - pad.b - point.y)} rx="1" />
					{:else}
						<circle class="dot" cx={point.x} cy={point.y} r={active === point.month ? 3.5 : 2} />
					{/if}
				{/if}
			</g>
			{#if index === 0 || index === Math.floor(points.length / 2) || index === points.length - 1}
				<text x={point.x} y={H - 6} text-anchor={index === 0 ? 'start' : index === points.length - 1 ? 'end' : 'middle'} class="axis">{monthLabel(point.month)}</text>
			{/if}
		{/each}
	</svg>
	<p class="chart-note" aria-live="polite">
		{#if selected}
			{monthLabel(selected.month)} · {valueLabel(selected.value)}{selected.partial ? ' · partial month' : ''}{selected.low ? ' · low review volume' : ''}
		{:else}
			Faint marks indicate partial or low-volume months. Hover or focus a month for values.
		{/if}
	</p>
</div>

<style>
	svg { display: block; width: 100%; overflow: visible; }
	.baseline { stroke: var(--line); }
	.axis { fill: var(--muted); font-family: var(--mono); font-size: 8px; }
	.series { fill: none; stroke: var(--cyan); stroke-width: 1.8; stroke-linecap: round; stroke-linejoin: round; }
	.bar { fill: var(--lime); opacity: 0.8; }
	.dot { fill: var(--cyan); }
	.point { cursor: pointer; outline: none; }
	.point.partial .bar, .point.partial .dot { opacity: 0.3; }
	.point:focus-visible .bar, .point:hover .bar { fill: var(--text); opacity: 1; }
	.point:focus-visible .dot { fill: var(--text); }
	.chart-note { min-height: 28px; margin: 6px 0 0; font-size: 9px; line-height: 1.5; color: var(--muted); }
</style>
