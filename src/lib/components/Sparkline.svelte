<script lang="ts">
	import type { TrendPoint } from '#lib/api/types';

	let {
		points,
		width = 320,
		height = 62,
		color = 'var(--lime)',
		showVolume = true,
		id = 'spark'
	}: {
		points: TrendPoint[];
		width?: number;
		height?: number;
		color?: string;
		showVolume?: boolean;
		id?: string;
	} = $props();

	const pad = 6;

	const geometry = $derived.by(() => {
		if (!points || points.length < 2) {
			return { line: '', area: '', last: null as { x: number; y: number } | null, bars: [] };
		}
		const values = points.map((p) => p.rating);
		const min = Math.min(...values);
		const max = Math.max(...values);
		const span = Math.max(0.2, max - min);
		const innerH = height - pad * 2;
		const innerW = width - pad * 2;

		const coords = points.map((p, i) => {
			const x = pad + (i / (points.length - 1)) * innerW;
			const y = pad + (1 - (p.rating - min) / span) * innerH;
			return { x, y };
		});

		const line = coords
			.map((c, i) => `${i === 0 ? 'M' : 'L'}${c.x.toFixed(1)},${c.y.toFixed(1)}`)
			.join(' ');
		const area = `${line} L${coords[coords.length - 1].x.toFixed(1)},${height} L${coords[0].x.toFixed(1)},${height} Z`;

		const maxVol = Math.max(...points.map((p) => p.volume), 1);
		const bars = points.map((p, i) => ({
			x: pad + (i / (points.length - 1)) * innerW - 1,
			h: Math.max(1, (p.volume / maxVol) * 12),
			opacity: 0.06 + (i / points.length) * 0.12
		}));

		return { line, area, last: coords[coords.length - 1], bars };
	});
</script>

<svg
	width="100%"
	height={height}
	viewBox="0 0 {width} {height}"
	preserveAspectRatio="none"
	role="img"
	aria-label="Rating trend, {points.length} weeks"
	class="spark"
>
	<defs>
		<linearGradient id="{id}-fill" x1="0" y1="0" x2="0" y2="1">
			<stop offset="0%" stop-color={color} stop-opacity="0.22" />
			<stop offset="100%" stop-color={color} stop-opacity="0" />
		</linearGradient>
	</defs>

	{#if showVolume}
		{#each geometry.bars as bar, i (i)}
			<rect
				x={bar.x}
				y={height - bar.h}
				width="2.5"
				height={bar.h}
				fill="var(--text)"
				opacity={bar.opacity}
			/>
		{/each}
	{/if}

	<path d={geometry.area} fill="url(#{id}-fill)" />
	<path
		d={geometry.line}
		fill="none"
		stroke={color}
		stroke-width="1.6"
		stroke-linejoin="round"
		stroke-linecap="round"
		vector-effect="non-scaling-stroke"
	/>

	{#if geometry.last}
		<circle cx={geometry.last.x} cy={geometry.last.y} r="2.6" fill={color} />
		<circle cx={geometry.last.x} cy={geometry.last.y} r="5" fill={color} opacity="0.18" />
	{/if}
</svg>

<style>
	.spark {
		display: block;
		overflow: visible;
	}
</style>
