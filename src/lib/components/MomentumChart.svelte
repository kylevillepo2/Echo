<script lang="ts">
	import type { SignalWeek } from '#lib/api/types';
	import type { DownloadPoint } from '#lib/data/downloads';
	import { fmtCount, fmtDate, fmtRate } from '#lib/utils/format';

	let {
		weekly,
		reviews = [],
		width = 320,
		height = 82,
		color = 'var(--lime)',
		id = 'momentum'
	}: {
		weekly: DownloadPoint[];
		reviews?: SignalWeek[];
		width?: number;
		height?: number;
		color?: string;
		id?: string;
	} = $props();

	const pad = 6;
	let hovered = $state<number | null>(null);

	const geometry = $derived.by(() => {
		const n = weekly.length;
		if (n < 2) {
			return { bars: [], line: '', area: '', points: [], innerW: width - pad * 2 };
		}
		const innerW = width - pad * 2;
		const innerH = height - pad * 2;
		const maxDownloads = Math.max(...weekly.map((point) => point.downloads), 1);
		const maxReviews = Math.max(...reviews.map((point) => point.reviews), 1);

		const bars = weekly.map((point, index) => {
			const slot = innerW / n;
			const barH = Math.max(1, (point.downloads / maxDownloads) * innerH);
			return {
				x: pad + index * slot + slot * 0.18,
				y: height - pad - barH,
				w: Math.max(1.5, slot * 0.64),
				h: barH,
				index
			};
		});

		const points = reviews.map((point, index) => ({
			x: pad + (index / Math.max(1, reviews.length - 1)) * innerW,
			y: pad + (1 - point.reviews / maxReviews) * innerH
		}));
		const line = points
			.map((point, index) => `${index === 0 ? 'M' : 'L'}${point.x.toFixed(1)},${point.y.toFixed(1)}`)
			.join(' ');
		const area = points.length
			? `${line} L${points[points.length - 1].x.toFixed(1)},${height - pad} L${points[0].x.toFixed(1)},${height - pad} Z`
			: '';

		return { bars, line, area, points, innerW };
	});

	const activeIndex = $derived(hovered ?? weekly.length - 1);
	const activePoint = $derived(weekly[activeIndex]);
	const activeReview = $derived(reviews[activeIndex]);

	function onPointerMove(event: PointerEvent) {
		const rect = (event.currentTarget as SVGSVGElement).getBoundingClientRect();
		const x = ((event.clientX - rect.left) / rect.width) * width;
		const index = Math.floor(((x - pad) / geometry.innerW) * weekly.length);
		hovered = Math.max(0, Math.min(weekly.length - 1, index));
	}
</script>

<div class="momentum">
	<div class="readout num">
		{#if activePoint}
			<span>{fmtDate(activePoint.date)}</span>
			<span class="dl">{fmtRate(activePoint.downloads)}</span>
			{#if activeReview}
				<span class="rev">{fmtCount(activeReview.reviews)} reviews</span>
			{/if}
		{/if}
	</div>

	<svg
		width="100%"
		height={height}
		viewBox="0 0 {width} {height}"
		preserveAspectRatio="none"
		role="img"
		aria-label="Weekly downloads and review volume"
		onpointermove={onPointerMove}
		onpointerleave={() => (hovered = null)}
	>
		<defs>
			<linearGradient id="{id}-rev" x1="0" y1="0" x2="0" y2="1">
				<stop offset="0%" stop-color="var(--cyan)" stop-opacity="0.18" />
				<stop offset="100%" stop-color="var(--cyan)" stop-opacity="0" />
			</linearGradient>
		</defs>

		{#each geometry.bars as bar (bar.index)}
			<rect
				x={bar.x}
				y={bar.y}
				width={bar.w}
				height={bar.h}
				rx="0.8"
				fill={color}
				opacity={hovered === null || hovered === bar.index ? 0.58 : 0.28}
			/>
		{/each}

		{#if geometry.area}
			<path d={geometry.area} fill="url(#{id}-rev)" />
			<path
				d={geometry.line}
				fill="none"
				stroke="var(--cyan)"
				stroke-width="1.4"
				stroke-linejoin="round"
				stroke-linecap="round"
				vector-effect="non-scaling-stroke"
			/>
			{#if geometry.points[activeIndex]}
				<circle
					cx={geometry.points[activeIndex].x}
					cy={geometry.points[activeIndex].y}
					r="2.4"
					fill="var(--cyan)"
				/>
			{/if}
		{/if}

		{#if hovered !== null && geometry.bars[hovered]}
			<line
				x1={geometry.bars[hovered].x + geometry.bars[hovered].w / 2}
				x2={geometry.bars[hovered].x + geometry.bars[hovered].w / 2}
				y1={pad}
				y2={height - pad}
				stroke="var(--line-bright)"
				stroke-width="0.7"
				stroke-dasharray="2 2"
				vector-effect="non-scaling-stroke"
			/>
		{/if}
	</svg>

	<div class="legend">
		<span class="key dl"></span><span>downloads</span>
		{#if reviews.length}
			<span class="key rev"></span><span>review volume</span>
		{/if}
		<span class="hint">hover for weeks</span>
	</div>
</div>

<style>
	.momentum {
		position: relative;
	}
	.readout {
		display: flex;
		align-items: baseline;
		gap: 7px;
		min-height: 14px;
		margin-bottom: 3px;
		font-size: 8px;
		color: var(--faint);
		white-space: nowrap;
		overflow: hidden;
	}
	.readout .dl {
		color: var(--text-2);
	}
	.readout .rev {
		color: var(--cyan);
	}
	svg {
		display: block;
		overflow: visible;
		touch-action: none;
	}
	.legend {
		display: flex;
		align-items: center;
		gap: 5px;
		margin-top: 4px;
		font-family: var(--mono);
		font-size: 8px;
		color: var(--faint);
	}
	.key {
		width: 7px;
		height: 7px;
		border-radius: 1px;
		display: inline-block;
	}
	.key.dl {
		background: var(--lime);
		opacity: 0.6;
	}
	.key.rev {
		background: var(--cyan);
		border-radius: 50%;
		width: 5px;
		height: 5px;
		margin-left: 6px;
	}
	.hint {
		margin-left: auto;
		color: var(--faint);
	}
</style>
