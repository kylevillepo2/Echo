<script lang="ts">
	import { fmtMonth } from '#lib/data/flows';
	import { fmtCount } from '#lib/utils/format';
	import { timelineIndex, timelineWindow, shiftTimelineWindow } from '#lib/utils/timeline';
	let { points, period, rangeEnd, onSelect, onClear }: {
		points: { month: string; count: number; partial: boolean; note: string }[];
		period: string;
		rangeEnd: string | null;
		onSelect: (start: string, end: string) => void;
		onClear: () => void;
	} = $props();
	let surface: HTMLDivElement;
	const uid = $props.id();
	let pointerId = $state<number | null>(null);
	let hovered = $state<number | null>(null);
	let anchor = 0;
	let initial: [number, number] = [0, 0];
	let mode: 'new' | 'move' | 'start' | 'end' = 'new';
	const selected = $derived(points.findIndex((point) => point.month === period));
	const selectedEnd = $derived(rangeEnd ? points.findIndex((point) => point.month === rangeEnd) : selected);
	const bounds = $derived(timelineWindow(selected, selectedEnd, points.length));
	const maximum = $derived(Math.max(...points.map((point) => point.count), 1));
	const x = (index: number) => points.length <= 1 ? 500 : index / (points.length - 1) * 1000;
	const y = (count: number) => 68 - count / maximum * 56;
	const path = $derived(points.map((point, index) => `${index ? 'L' : 'M'}${x(index)},${y(point.count)}`).join(' '));
	// Half a month on either side gives even a single month a real, draggable box.
	const left = $derived(Math.max(0, (bounds[0] - 0.5) / Math.max(points.length - 1, 1) * 100));
	const right = $derived(Math.min(100, (bounds[1] + 0.5) / Math.max(points.length - 1, 1) * 100));
	const chosen = $derived(selected < 0 ? [] : points.slice(bounds[0], bounds[1] + 1));
	const total = $derived(chosen.reduce((sum, point) => sum + point.count, 0));
	const label = $derived(selected < 0 ? 'All months' : bounds[0] === bounds[1]
		? fmtMonth(points[bounds[0]].month, true)
		: `${fmtMonth(points[bounds[0]].month, true)} – ${fmtMonth(points[bounds[1]].month, true)}`);
	function indexAt(event: PointerEvent) {
		const box = surface.getBoundingClientRect();
		return timelineIndex(event.clientX, box.left, box.width, points.length);
	}
	function select(start: number, end: number) {
		const [a, b] = timelineWindow(start, end, points.length);
		if (points[a] && points[b] && (points[a].month !== period || points[b].month !== (rangeEnd ?? period))) onSelect(points[a].month, points[b].month);
	}
	function start(event: PointerEvent) {
		if (!points.length || !event.isPrimary || event.button !== 0) return;
		event.preventDefault();
		anchor = indexAt(event);
		initial = [...bounds];
		const target = event.target instanceof HTMLElement ? event.target.closest<HTMLElement>('[data-drag]') : null;
		mode = target?.dataset.drag as typeof mode ?? 'new';
		pointerId = event.pointerId;
		surface.setPointerCapture(event.pointerId);
		surface.focus({ preventScroll: true });
		hovered = null;
		if (mode === 'new') select(anchor, anchor);
	}
	function move(event: PointerEvent) {
		if (!points.length) return;
		const index = indexAt(event);
		if (pointerId !== event.pointerId) { hovered = index; return; }
		if (mode === 'move') select(...shiftTimelineWindow(initial[0], initial[1], index - anchor, points.length));
		else if (mode === 'start') select(Math.min(index, initial[1]), initial[1]);
		else if (mode === 'end') select(initial[0], Math.max(index, initial[0]));
		else select(anchor, index);
	}
	function finish(event: PointerEvent) {
		if (pointerId !== event.pointerId) return;
		if (event.type === 'pointerup') move(event);
		pointerId = null;
		hovered = null;
		if (surface.hasPointerCapture(event.pointerId)) surface.releasePointerCapture(event.pointerId);
	}
	function keydown(event: KeyboardEvent) {
		if (!points.length) return;
		if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); onClear(); return; }
		const delta = ['ArrowRight', 'ArrowUp'].includes(event.key) ? 1 : ['ArrowLeft', 'ArrowDown'].includes(event.key) ? -1 : 0;
		if (!delta && event.key !== 'Home' && event.key !== 'End') return;
		event.preventDefault(); event.stopPropagation(); hovered = null;
		if (event.key === 'Home') select(0, event.shiftKey ? bounds[1] : 0);
		else if (event.key === 'End') select(event.shiftKey ? bounds[0] : points.length - 1, points.length - 1);
		else if (event.shiftKey) select(bounds[0], Math.max(bounds[0], bounds[1] + delta));
		else select(...shiftTimelineWindow(...bounds, delta, points.length));
	}
</script>

<div class="chart-wrap">
	<span class="sr-only" id="{uid}-help">Hold and drag to select a time window. Drag the box to move it or its edges to resize. Arrow keys move the window; Shift and arrow keys resize. Escape resets to all months.</span>
	<div class="readout" aria-hidden="true">{#if selected >= 0}<b>{label}</b> · {fmtCount(total)} switches{chosen.some((point) => point.partial) ? ' · limited coverage' : ''}{:else if hovered !== null}<b>{fmtMonth(points[hovered].month)}</b> · {fmtCount(points[hovered].count)} switches{:else}Hold and drag to select a time window{/if}</div>
	<div bind:this={surface} class="scrub-chart" class:dragging={pointerId !== null} role="slider" tabindex="0" aria-label="Switching timeline range" aria-describedby="{uid}-help" aria-orientation="horizontal" aria-valuemin="0" aria-valuemax={Math.max(points.length - 1, 0)} aria-valuenow={Math.max(selected, 0)} aria-valuetext={selected < 0 ? 'All months' : `${label}, ${total} reported switches`} onpointerdown={start} onpointermove={move} onpointerup={finish} onpointercancel={finish} onlostpointercapture={() => { pointerId = null; hovered = null; }} onpointerleave={() => { if (pointerId === null) hovered = null; }} onkeydown={keydown}>
		<svg class="line-chart" viewBox="0 0 1000 80" preserveAspectRatio="none" aria-hidden="true">
			<path class="grid" d="M0 12H1000 M0 40H1000 M0 68H1000" />
			{#if points.length}<path class="area" d="{path} L1000,68 L0,68 Z" /><path class="trend" d={path} />{/if}
		</svg>
		{#each points as point, index (point.month)}
			<span class="point" class:partial={point.partial} class:chosen={selected >= 0 && index >= bounds[0] && index <= bounds[1]} style:left="{x(index) / 10}%" style:top="{y(point.count) / 80 * 100}%"></span>
		{/each}
		{#if selected >= 0}
			<div class="range-box" data-drag="move" style:left="{left}%" style:width="{right - left}%" aria-hidden="true">
				<span class="range-edge start" data-drag="start"></span>
				<span class="range-edge end" data-drag="end"></span>
			</div>
		{/if}
	</div>
	<div class="axis" aria-hidden="true">{#each points as point, index (point.month)}<span class:minor={index % 3 !== 0 && index !== points.length - 1} class:chosen={selected >= 0 && (index === bounds[0] || index === bounds[1])}>{index === 0 || point.month.endsWith('-01') || index === points.length - 1 ? fmtMonth(point.month, true) : fmtMonth(point.month).slice(0, 3)}</span>{/each}</div>
</div>

<style>
	.sr-only { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden; clip-path: inset(50%); white-space: nowrap; }
	.chart-wrap { margin: 8px 7px 0; }
	.readout { min-height: 21px; font-size: 10px; color: var(--muted); }
	.readout b { color: white; font-weight: 600; }
	.scrub-chart { height: 80px; position: relative; touch-action: none; user-select: none; cursor: crosshair; outline-offset: 5px; border-radius: 3px; }
	.scrub-chart.dragging, .dragging .range-box { cursor: grabbing; }
	.line-chart { display: block; width: 100%; height: 100%; overflow: visible; pointer-events: none; }
	.grid { stroke: var(--line); stroke-width: 1; fill: none; vector-effect: non-scaling-stroke; }
	.area { fill: var(--lime); opacity: 0.045; }
	.trend { fill: none; stroke: var(--lime); stroke-width: 2; stroke-linejoin: round; stroke-linecap: round; vector-effect: non-scaling-stroke; }
	.point { position: absolute; width: 4px; height: 4px; transform: translate(-50%, -50%); border-radius: 50%; background: var(--lime); pointer-events: none; }
	.point.partial { background: var(--panel); border: 1px solid var(--lime); }
	.point.chosen { background: white; border-color: white; }
	.range-box { position: absolute; top: 0; bottom: 0; border: 1px solid var(--lime); border-radius: 5px; background: #c8ff3c1c; box-shadow: 0 0 0 1px #08080a66; cursor: grab; min-width: 3px; }
	.range-edge { position: absolute; top: -3px; bottom: -3px; width: 16px; cursor: ew-resize; touch-action: none; }
	.range-edge::after { content: ''; position: absolute; left: 6px; top: 50%; transform: translateY(-50%); width: 3px; height: 23px; background: var(--lime); border: 1px solid var(--panel); border-radius: 3px; box-shadow: 0 0 0 1px var(--lime); }
	.range-edge.start { left: -8px; } .range-edge.end { right: -8px; }
	.axis { display: flex; justify-content: space-between; gap: 0; margin-top: 8px; color: var(--muted); font: 8px var(--mono); }
	.axis span { flex: 1; text-align: center; white-space: nowrap; }
	.axis span:first-child { text-align: left; } .axis span:last-child { text-align: right; }
	.axis .minor { visibility: hidden; } .axis .chosen { visibility: visible; color: white; }
	@media(max-width:760px) { .axis span { display: none; } .axis span:nth-child(6n + 1), .axis span:last-child { display: block; } .axis { font-size: 7px; } .readout { font-size: 9px; } }
</style>
