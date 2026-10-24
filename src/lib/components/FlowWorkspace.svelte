<script lang="ts">
	import { onDestroy, onMount, type Snippet } from 'svelte';
	import { slide } from 'svelte/transition';
	import { studio } from '#lib/state/studio.svelte';
	import { flowsState } from '#lib/state/flows.svelte';
	import {
		allMonthIds, coverageMonths, flowAnnotations, flowMonth, flowMonths,
		flowNodes, fmtMonth, monthlyActivity
	} from '#lib/data/flows';

	let { children }: { children: Snippet } = $props();
	let reducedMotion = $state(false);
	const active = $derived(Boolean(studio.categoryFilter));
	const hasData = $derived(studio.categoryApps.some((app) => flowNodes.some((node) => node.observed && node.id === app.id)));
	const arrowCount = $derived(flowsState.availableArrows.length);
	const visibleCount = $derived(flowsState.visibleArrows.length);
	const coverageIndex = $derived(coverageMonths.indexOf(flowsState.period));
	const monthInfo = $derived(flowsState.period === 'all' ? undefined : flowMonth(flowsState.period));
	const annotation = $derived(flowAnnotations.find((item) => item.month === flowsState.period));
	const periodLabel = $derived(flowsState.period === 'all'
		? `All months · ${fmtMonth(allMonthIds[0], true)}–${fmtMonth(allMonthIds.at(-1)!, true)}`
		: fmtMonth(flowsState.period));
	const maxActivity = Math.max(...Object.values(monthlyActivity), 1);
	const partialCount = flowMonths.filter((month) => !month.full).length;

	onMount(() => {
		const motion = window.matchMedia('(prefers-reduced-motion: reduce)');
		const update = () => (reducedMotion = motion.matches);
		update();
		motion.addEventListener('change', update);
		return () => motion.removeEventListener('change', update);
	});
	onDestroy(() => flowsState.stop());

	function pickMonth(id: string) {
		flowsState.stop();
		flowsState.setPeriod(flowsState.period === id ? 'all' : id);
	}
</script>

<section class="flow-workspace" aria-label="Network and cluster flows">
	{#if active}
		<header class="toolbar">
			<div class="left">
				<button class="back" onclick={() => studio.clearCategoryFilter()} aria-label="Back to cluster map">←</button>
				<span class="label">{studio.selectedCategory?.name ?? 'Cluster'} flows</span>
				{#if hasData}
					<span class="stats num">{flowNodes.length} flow apps · {visibleCount}/{arrowCount} routes · {periodLabel}</span>
				{:else}
					<span class="stats num">{studio.categoryApps.length} apps · reception {studio.selectedCategory?.reception ?? '—'}</span>
				{/if}
			</div>
			{#if hasData}
				<div class="right">
					<div class="seg" role="group" aria-label="Edge types">
						<button class:active={flowsState.showSwitches} aria-pressed={flowsState.showSwitches} onclick={() => (flowsState.showSwitches = !flowsState.showSwitches)} title="Users who said they left one app for another, or came back">
							<i class="sw solid"></i>Switches + returns
						</button>
						<button class:active={flowsState.showIntents} aria-pressed={flowsState.showIntents} onclick={() => (flowsState.showIntents = !flowsState.showIntents)} title="Users who said they are about to switch">
							<i class="sw dashed"></i>Intents
						</button>
						<button class:active={flowsState.showPreferences} aria-pressed={flowsState.showPreferences} onclick={() => (flowsState.showPreferences = !flowsState.showPreferences)} title="Comparisons that favour one app, with no stated move">
							<i class="sw faint"></i>Preferences
						</button>
					</div>
					<div class="seg" role="group" aria-label="Direction mode">
						<button class:active={flowsState.netMode} aria-pressed={flowsState.netMode} onclick={() => (flowsState.netMode = !flowsState.netMode)} title="One arrow per pair of apps, pointing in the net direction">Net flow</button>
					</div>
				</div>
			{/if}
		</header>
	{/if}

	<!-- This canvas slot is never keyed or replaced when cluster focus changes. -->
	<div class="canvas-slot">
		{@render children()}
		{#if active && hasData && annotation}
			<div class="callout"><span class="label">{fmtMonth(annotation.month)} · {annotation.label}</span><p>{annotation.detail}</p></div>
		{/if}
		{#if active && hasData && flowsState.isPartial && monthInfo}
			<div class="callout partial-note"><span class="label">Partial month</span><p>{monthInfo.note}. Flows seen in that app’s reviews are missing or noisy, so compare with care.</p></div>
		{/if}
		{#if active && hasData && arrowCount === 0}
			<div class="empty-note" role="status">
				<span class="label">{flowsState.layers.size === 0 ? 'No edge types selected' : `No flows in ${periodLabel}`}</span>
				<p>Try another month or turn on switches, intents or preferences.</p>
			</div>
		{/if}
	</div>

	{#if active && hasData}
		<footer class="timeline" transition:slide={{ duration: reducedMotion ? 0 : 350 }}>
			<div class="controls">
				<button class="btn is-sm play" onclick={() => flowsState.togglePlay()} aria-label={flowsState.playing ? 'Pause' : 'Play month by month'}>
					{#if flowsState.playing}
						<svg width="10" height="10" viewBox="0 0 10 10" aria-hidden="true"><path d="M2 1h2v8H2zM6 1h2v8H6z" fill="currentColor" /></svg>
					{:else}
						<svg width="10" height="10" viewBox="0 0 10 10" aria-hidden="true"><path d="M2 1l7 4-7 4z" fill="currentColor" /></svg>
					{/if}
					{flowsState.playing ? 'Pause' : 'Play'}
				</button>
				<button class="btn is-sm" class:is-active={flowsState.period === 'all'} onclick={() => { flowsState.stop(); flowsState.setPeriod('all'); }}>All months</button>
				<input class="slider" type="range" min="0" max={coverageMonths.length - 1} step="1" value={coverageIndex === -1 ? 0 : coverageIndex} class:off={coverageIndex === -1} oninput={(event) => { flowsState.stop(); flowsState.setPeriod(coverageMonths[Number(event.currentTarget.value)]); }} aria-label="Month within full-coverage period" />
				<span class="current num">{flowsState.period === 'all' ? 'All months' : fmtMonth(flowsState.period)}</span>
			</div>
			<div class="strip" role="group" aria-label="Months">
				{#each flowMonths as month (month.month)}
					{@const ann = flowAnnotations.find((item) => item.month === month.month)}
					{@const activity = monthlyActivity[month.month] ?? 0}
					<button class="cell" class:partial={!month.full} class:selected={flowsState.period === month.month} onclick={() => pickMonth(month.month)} title="{fmtMonth(month.month)}{month.full ? '' : ` — partial: ${month.note}`} · {activity} switch/intent mentions">
						{#if ann}<span class="ann">{ann.label}</span>{/if}
						<span class="bar" style:height="{4 + (activity / maxActivity) * 26}px"></span>
						<span class="mlabel">{month.month.endsWith('-01') || month.month === flowMonths[0].month ? fmtMonth(month.month, true) : fmtMonth(month.month).slice(0, 1)}</span>
					</button>
				{/each}
			</div>
			<div class="strip-note">
				<span><i class="key full"></i>full coverage {fmtMonth(coverageMonths[0], true)}–{fmtMonth(coverageMonths.at(-1)!, true)} (slider + play)</span>
				<span><i class="key partial"></i>{partialCount} partial months: Spotify reviews only run Aug ’24–Apr ’25; Audiomack starts Sep ’24</span>
				<span class="dimtext">bars = switch + intent mentions per month (raw count)</span>
			</div>
		</footer>
	{/if}
</section>

<style>
	.flow-workspace, .canvas-slot {
		flex: 1;
		min-width: 0;
		min-height: 0;
		display: flex;
		flex-direction: column;
	}
	.canvas-slot { position: relative; }
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
	.left, .right { display: flex; align-items: center; gap: 10px; min-width: 0; }
	.left .label { white-space: nowrap; }
	.right { margin-left: auto; flex: none; gap: 8px; }
	.stats { font-size: 9px; color: var(--dim); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
	.back { width: 24px; height: 24px; flex: none; border: 1px solid var(--line); border-radius: 2px; color: var(--muted); font-family: var(--mono); }
	.back:hover { color: var(--lime); border-color: var(--line-strong); background: var(--panel-2); }
	.seg { display: flex; border: 1px solid var(--line); border-radius: 2px; overflow: hidden; }
	.seg button { display: flex; align-items: center; gap: 6px; height: 23px; padding: 0 9px; font-family: var(--mono); font-size: 8.5px; letter-spacing: 0.06em; text-transform: uppercase; color: var(--dim); border-right: 1px solid var(--line); transition: background var(--fast), color var(--fast); }
	.seg button:last-child { border-right: 0; }
	.seg button:hover { color: var(--text-2); background: var(--panel-2); }
	.seg button.active { background: var(--panel-3); color: var(--lime); }
	.sw { width: 12px; height: 0; border-top: 2px solid currentColor; }
	.sw.dashed { border-top-style: dashed; }
	.sw.faint { opacity: 0.4; }
	.callout, .empty-note { position: absolute; left: 14px; top: 12px; max-width: 330px; padding: 9px 11px; background: color-mix(in srgb, var(--panel) 90%, transparent); border: 1px solid var(--line-strong); border-left: 2px solid var(--lime); border-radius: 2px; backdrop-filter: blur(6px); pointer-events: none; }
	.callout .label { color: var(--lime); }
	.partial-note { left: auto; right: 14px; border-left-color: var(--amber); }
	.partial-note .label { color: var(--amber); }
	.callout p, .empty-note p { margin: 4px 0 0; font-size: 11.5px; line-height: 1.45; color: var(--text-2); }
	.timeline { flex: none; border-top: 1px solid var(--line); background: var(--panel); padding: 8px 14px; }
	.controls { display: flex; align-items: center; gap: 8px; }
	.play { min-width: 66px; }
	.slider { flex: 1; min-width: 0; max-width: 260px; accent-color: var(--lime); }
	.slider.off { opacity: 0.45; }
	.current { font-size: 11px; color: var(--text); min-width: 90px; }
	.strip { display: grid; grid-auto-flow: column; grid-auto-columns: minmax(0, 1fr); gap: 2px; margin-top: 8px; padding-top: 16px; }
	.cell { position: relative; height: 46px; display: flex; flex-direction: column; justify-content: flex-end; align-items: center; gap: 3px; border-bottom: 2px solid var(--lime-dim); transition: background var(--fast); }
	.cell:hover { background: var(--panel-2); }
	.bar { width: 60%; max-width: 16px; background: color-mix(in srgb, var(--lime) 55%, transparent); border-radius: 1px 1px 0 0; }
	.mlabel { font-family: var(--mono); font-size: 8px; color: var(--dim); white-space: nowrap; }
	.cell.partial { border-bottom-color: var(--line-strong); }
	.cell.partial .bar { background: repeating-linear-gradient(135deg, var(--faint) 0 2px, transparent 2px 4px); outline: 1px solid var(--faint); }
	.cell.partial .mlabel { color: var(--faint); }
	.cell.selected { background: var(--panel-3); box-shadow: inset 0 0 0 1px var(--line-bright); }
	.cell.selected .bar { background: var(--lime); }
	.cell.selected .mlabel { color: var(--text); }
	.cell.partial.selected .bar { background: var(--amber); outline-color: var(--amber); }
	.ann { position: absolute; top: -15px; left: 50%; font-family: var(--mono); font-size: 8px; color: var(--lime); white-space: nowrap; padding-left: 6px; border-left: 1px solid var(--lime); }
	.strip-note { display: flex; flex-wrap: wrap; gap: 4px 14px; margin-top: 6px; font-family: var(--mono); font-size: 8.5px; color: var(--muted); }
	.key { display: inline-block; width: 10px; height: 0; border-top: 2px solid var(--lime-dim); margin-right: 5px; vertical-align: middle; }
	.key.partial { border-color: var(--line-strong); }
	.dimtext { color: var(--dim); }
	@media (max-width: 1280px) { .stats { display: none; } }
	@media (max-width: 860px) { .seg button { padding: 0 6px; font-size: 8px; } .sw, .mlabel { display: none; } }
	@media (max-width: 600px) { .toolbar { height: auto; min-height: 42px; flex-wrap: wrap; padding: 7px 10px; gap: 7px; } .right { margin-left: 0; } .current { min-width: 0; font-size: 9px; } .ann { display: none; } }
</style>
