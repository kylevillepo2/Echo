<script lang="ts">
	import { onDestroy, onMount, type Snippet } from 'svelte';
	import { slide } from 'svelte/transition';
	import { studio } from '#lib/state/studio.svelte';
	import { flowsState } from '#lib/state/flows.svelte';
	import { allMonthIds, flowNode, fmtMonth } from '#lib/data/flows';
	import TimelineChart from './TimelineChart.svelte';
	let { children }: { children: Snippet } = $props();
	let reducedMotion = $state(false);
	const active = $derived(Boolean(studio.categoryFilter));
	const hasData = $derived(studio.categoryApps.some((app) => flowNode(app.id)?.observed));
	const months = $derived(allMonthIds.map((month) => flowsState.monthInfo(month)));
	const context = $derived(flowsState.selection?.type === 'app'
		? flowNode(flowsState.selection.id)?.name ?? studio.selectedApp?.name ?? 'App'
		: flowsState.selection?.type === 'edge'
			? `${flowNode(flowsState.selection.s)?.name ?? flowsState.selection.s} → ${flowNode(flowsState.selection.t)?.name ?? flowsState.selection.t}`
			: studio.selectedCategory?.name ?? 'Industry');
	const coveredApps = $derived([...(flowsState.timelineScope ?? [])].map((id) => flowNode(id)).filter((app) => app?.observed).map((app) => app!.name));
	const annotation = $derived(flowsState.period === 'all' ? undefined : flowsState.annotations.find((event) => flowsState.periodMonths.includes(event.month)));
	const periodLabel = $derived(flowsState.period === 'all'
		? allMonthIds.length ? `${fmtMonth(allMonthIds[0], true)} – ${fmtMonth(allMonthIds.at(-1)!, true)}` : 'All months'
		: flowsState.periodLabel);
	onMount(() => {
		const motion = window.matchMedia('(prefers-reduced-motion: reduce)');
		const update = () => (reducedMotion = motion.matches); update();
		motion.addEventListener('change', update); return () => motion.removeEventListener('change', update);
	});
	onDestroy(() => flowsState.stop());
	function choose(period: string) { flowsState.stop(); flowsState.setPeriod(period); }
</script>

<section class="flow-workspace" aria-label="Industry landscape">
	{#if active}
		<header class="toolbar">
			<button class="back" onclick={() => studio.clearCategoryFilter()} aria-label="Back to app landscape">←</button>
			<h2>{studio.selectedCategory?.name ?? 'Industry'}</h2>
		</header>
	{/if}
	<div class="canvas-slot">
		{@render children()}
		{#if active && hasData && !flowsState.availableArrows.length}
			<div class="empty-note" role="status">No clear switching direction for this period.</div>
		{/if}
	</div>
	{#if active && hasData}
		<footer class="timeline" transition:slide={{ duration: reducedMotion ? 0 : 260 }}>
			<div class="timeline-top">
				<div class="period-controls">
					<button class="all-months" class:active={flowsState.period === 'all'} aria-pressed={flowsState.period === 'all'} onclick={() => choose('all')}>All months</button>
					<span class="current" aria-live="polite">{periodLabel}</span>
				</div>
				<span class="timeline-context" title={coveredApps.join(', ')}>{context} · reported switches</span>
			</div>
			<TimelineChart points={months.map((month) => ({ month: month.month, count: flowsState.activity[month.month] ?? 0, partial: !month.full, note: month.note }))} period={flowsState.period} rangeEnd={flowsState.rangeEnd} onSelect={(start, end) => flowsState.setRange(start, end)} onClear={() => choose('all')} />
			{#if annotation}<p class="event-note"><b>{annotation.label}</b> · {annotation.detail}</p>{/if}
		</footer>
	{/if}
</section>

<style>
	.flow-workspace, .canvas-slot { flex: 1; min-width: 0; min-height: 0; display: flex; flex-direction: column; }
	.canvas-slot { position: relative; }
	.toolbar { flex: none; height: 54px; display: flex; align-items: center; gap: 12px; padding: 0 20px; border-bottom: 1px solid var(--line); background: var(--bg); }
	h2 { margin: 0; font-size: 16px; font-weight: 650; color: white; }
	.back { width: 28px; height: 28px; border: 1px solid var(--line); border-radius: 7px; color: var(--text-2); }
	.back:hover { color: white; background: var(--panel-2); }
	.timeline { flex: none; border-top: 1px solid var(--line); background: var(--panel); padding: 12px 20px 9px; }
	.timeline-top { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
	.period-controls { display: flex; align-items: center; gap: 12px; min-width: 0; }
	.all-months { flex: none; padding: 7px 10px; border: 1px solid var(--line-strong); border-radius: 7px; font-size: 11px; color: var(--muted); }
	.all-months.active { background: var(--lime); color: var(--bg); border-color: var(--lime); }
	.current { font-size: 10px; color: var(--text-2); white-space: nowrap; }
	.timeline-context { font-size: 10px; color: var(--muted); text-align: right; }
	.event-note { margin: 6px 0 0; color: var(--muted); font-size: 10px; line-height: 1.5; }
	.event-note b { color: white; }
	.empty-note { position: absolute; left: 18px; top: 15px; font-size: 11px; color: var(--muted); pointer-events: none; }
	@media(max-width:760px) { .timeline-top { align-items: flex-start; flex-direction: column; gap: 8px; } .timeline-context { font-size: 9px; text-align: left; } .timeline { padding: 10px 12px 7px; } .current { font-size: 9px; } }
</style>
