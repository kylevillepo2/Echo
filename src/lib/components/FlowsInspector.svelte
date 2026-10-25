<script lang="ts">
	import { tick } from 'svelte';
	import { studio } from '#lib/state/studio.svelte';
	import { flowsState } from '#lib/state/flows.svelte';
	import AppFlows from './AppFlows.svelte';
	import {
		allMonthIds,
		coverageMonths,
		examplesFor,
		flowAnnotations,
		flowMonth,
		flowNode,
		flows,
		fmtMonth,
		pairSeries,
		reasonColour,
		reasonLabel,
		sortedReasons,
		topReason,
		volumeOf,
		type FlowAgg,
		type FlowKind,
		type FlowLayer
	} from '#lib/data/flows';
	import { fmtCount } from '#lib/utils/format';
	import { filterFlowEvidence } from '#lib/utils/flow-evidence';
	import { reportedSwitchCount } from '#lib/utils/flow-counts';

	const selection = $derived(flowsState.selection);
	const months = $derived(flowsState.periodMonths);
	const layers = $derived(flowsState.layers);
	const aggs = $derived(flowsState.aggregates);
	const periodLabel = $derived(flowsState.period === 'all' ? 'all months' : fmtMonth(flowsState.period));

	const layerNames: Record<FlowLayer, string> = {
		switch: 'switches',
		intent: 'intents',
		preference: 'preferences'
	};
	const kindNames: Record<FlowKind, [string, string]> = {
		switch: ['switch', 'switches'],
		return: ['switch', 'switches'],
		intent: ['intent', 'intents'],
		preference: ['preference', 'preferences']
	};

	function name(id: string): string {
		return flowNode(id)?.name ?? id;
	}

	/** Combine the visible layers for one directed pair. */
	interface PairSummary {
		s: string;
		t: string;
		value: number;
		count: number;
		kinds: Partial<Record<FlowKind, number>>;
		reasons: Map<string, number>;
	}

	function combine(list: FlowAgg[], s: string, t: string): PairSummary {
		const out: PairSummary = { s, t, value: 0, count: 0, kinds: {}, reasons: new Map() };
		for (const a of list) {
			out.value += a.value;
			out.count += a.count;
			for (const [k, n] of Object.entries(a.kinds) as [FlowKind, number][]) {
				out.kinds[k] = (out.kinds[k] ?? 0) + n;
			}
			for (const [id, n] of a.reasons) out.reasons.set(id, (out.reasons.get(id) ?? 0) + n);
		}
		return out;
	}

	function pair(s: string, t: string): PairSummary {
		return combine(
			[...aggs.values()].filter((a) => a.s === s && a.t === t),
			s,
			t
		);
	}

	/* ----------------------------- edge ----------------------------- */

	const edge = $derived(selection?.type === 'edge' ? selection : null);
	const forward = $derived(edge ? pair(edge.s, edge.t) : null);
	const switchCount = $derived(reportedSwitchCount(forward?.kinds ?? {}));
	const reasonRows = $derived(forward ? sortedReasons(forward.reasons) : []);
	const series = $derived(edge ? pairSeries(edge.s, edge.t, layers) : []);
	let selectedReason = $state<string | null>(null);
	let includeAllMonths = $state(false);
	let reviewSection = $state<HTMLElement>();
	let evidenceContext = '';

	$effect(() => {
		const next = `${edge?.s}|${edge?.t}|${flowsState.period}|${[...layers].join(',')}`;
		if (next !== evidenceContext) {
			evidenceContext = next;
			selectedReason = null;
			includeAllMonths = false;
		}
	});
	const exampleKinds = $derived(
		(['switch', 'return', 'intent', 'preference'] as FlowKind[]).filter((k) =>
			layers.has(k === 'return' ? 'switch' : (k as FlowLayer))
		)
	);
	const allExamples = $derived(
		edge
			? exampleKinds.flatMap((kind) => examplesFor(edge.s, edge.t, kind).map((ex) => ({ ...ex, kind })))
			: []
	);
	const examples = $derived(filterFlowEvidence(allExamples, selectedReason, flowsState.period, includeAllMonths));
	const archivedExamples = $derived(filterFlowEvidence(allExamples, selectedReason, 'all'));

	async function chooseReason(id: string) {
		selectedReason = selectedReason === id ? null : id;
		includeAllMonths = false;
		await tick();
		reviewSection?.scrollIntoView({
			behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth',
			block: 'start'
		});
	}

	/* ----------------------------- app ------------------------------ */

	const appId = $derived(selection?.type === 'app' ? selection.id : null);
	const app = $derived(appId ? flowNode(appId) : undefined);
	const appVolume = $derived(app?.observed ? volumeOf(app.id, months) : 0);

	/* --------------------------- overview --------------------------- */

	const topFlows = $derived(
		[...flowsState.arrows].sort((a, b) => b.count - a.count).slice(0, 10)
	);
	const partialMonths = flows.months.filter((m) => !m.full);

	/* --------------------------- mini chart ------------------------- */

	const CW = 340;
	const CH = 96;
	const PAD = { l: 4, r: 4, t: 10, b: 14 };

	const chart = $derived.by(() => {
		const max = Math.max(...series.map((p) => p.count), 1);
		const n = allMonthIds.length;
		const x = (i: number) => PAD.l + (i / Math.max(1, n - 1)) * (CW - PAD.l - PAD.r);
		const y = (v: number) => PAD.t + (1 - v / max) * (CH - PAD.t - PAD.b);
		const line = (pts: { count: number }[]) =>
			pts.map((p, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(p.count).toFixed(1)}`).join(' ');
		const covStart = allMonthIds.indexOf(coverageMonths[0]);
		const covEnd = allMonthIds.indexOf(coverageMonths[coverageMonths.length - 1]);
		return {
			max,
			x,
			y,
			fwd: line(series),
			band: { x: x(covStart) - 4, w: x(covEnd) - x(covStart) + 8 },
			selected: flowsState.period === 'all' ? -1 : allMonthIds.indexOf(flowsState.period)
		};
	});

	function stars(n: number | null): string {
		if (!n) return '';
		return '★'.repeat(n) + '☆'.repeat(5 - n);
	}

	function close() {
		if (flowsState.selection) returnToApp();
		else studio.inspectorOpen = false;
	}

	function returnToApp() {
		if (studio.selectedApp) flowsState.selectApp(studio.selectedApp.id);
		else flowsState.clearSelection();
	}
</script>

{#snippet reviewEvidence()}
	<section class="block" id="flow-review-evidence" bind:this={reviewSection}>
		<div class="block-head">
			<span class="label-dim">{selectedReason ? `Reviews mentioning ${reasonLabel(selectedReason)}` : 'Review excerpts'}</span>
			{#if selectedReason}
				<button class="clear-filter" onclick={() => { selectedReason = null; includeAllMonths = false; }}>All issues</button>
			{/if}
		</div>
		<p class="evidence-note" role="status">{examples.length} saved excerpts · {includeAllMonths || flowsState.period === 'all' ? 'all months' : periodLabel}. These are sampled review quotes, not the complete review archive.</p>
		{#if examples.length}
			<div class="quotes">
				{#each examples as ex, i (i)}
					<article class="quote">
						<p>“{ex.q}”</p>
						<div class="quote-meta">
							<span class="stars">{stars(ex.stars)}</span>
							<span>{fmtMonth(ex.m, true)}</span>
							<span>{kindNames[ex.kind][0]}</span>
							<span>in {name(ex.o)} reviews</span>
						</div>
						{#if ex.d}<div class="quote-detail">{ex.d}</div>{/if}
						{#if ex.r.length}
							<div class="quote-reasons">
								{#each ex.r as reason (reason)}
									<span class="chip mini-chip"><i style:background={reasonColour(reason)}></i>{reasonLabel(reason)}</span>
								{/each}
							</div>
						{/if}
					</article>
				{/each}
			</div>
		{:else}
			<p class="muted">No saved excerpts{selectedReason ? ` for ${reasonLabel(selectedReason)}` : ''} in {includeAllMonths ? 'all months' : periodLabel}. Issue counts come from the full extracted data; only a sample of quotes is bundled.</p>
		{/if}
		{#if flowsState.period !== 'all' && !includeAllMonths && archivedExamples.length > examples.length}
			<button class="clear-filter archived" onclick={() => (includeAllMonths = true)}>Show matching excerpts from all months</button>
		{/if}
	</section>
{/snippet}

<aside class="inspector" aria-label="Flows inspector">
	{#if edge && forward}
		<header class="head" style:--accent={reasonColour(topReason(forward.reasons))}>
			<div class="eyebrow">
				<button class="crumb" onclick={returnToApp}>{studio.selectedApp?.name ?? 'Flows'}</button>
				<span class="slash">/</span>
				<span>{[...layers].map((l) => layerNames[l]).join(' · ') || 'no layers'}</span>
			</div>
			<div class="title-row">
				<h2>
					<button class="app-link" onclick={() => studio.selectFlowApp(edge.s)}>{name(edge.s)}</button>
					<span class="arrow-glyph">→</span>
					<button class="app-link" onclick={() => studio.selectFlowApp(edge.t)}>{name(edge.t)}</button>
				</h2>
				<button class="close" onclick={close} aria-label="Close">×</button>
			</div>
			{#if layers.has('switch')}
				<div class="switch-summary" aria-label="{switchCount} reported switches">
					<strong class="switch-total num">{fmtCount(switchCount)}</strong>
					<div>
						<span class="switch-label">Reported switches</span>
						<span class="switch-period">{periodLabel} · reported in reviews</span>
					</div>
				</div>
			{/if}
			<div class="meta-row">
				{#each ['intent', 'preference'] as kind (kind)}
					{@const count = forward.kinds[kind as FlowKind] ?? 0}
					{#if count}
						<span class="chip">{fmtCount(count)} {kindNames[kind as FlowKind][count === 1 ? 0 : 1]}</span>
					{/if}
				{/each}
				<button class="swap" onclick={() => flowsState.selectEdge(edge.t, edge.s)}>View {name(edge.t)} → {name(edge.s)}</button>
			</div>
			<p class="direction-note">Counts are reports in reviews, not independently tracked users.</p>
		</header>

		<div class="body scroll">
			<section class="block">
				<div class="block-head">
					<span class="label-dim">Issues mentioned · {periodLabel}</span>
					<span class="soft">click to read reviews</span>
				</div>
				{#if reasonRows.length}
					<div class="reasons">
						{#each reasonRows.slice(0, 8) as [id, n] (id)}
							<button class="reason-row" class:active={selectedReason === id} aria-pressed={selectedReason === id} aria-controls="flow-review-evidence" aria-label="Show reviews about {reasonLabel(id)}" onclick={() => chooseReason(id)}>
								<span class="reason-name">{reasonLabel(id)}</span>
								<span class="meter" style:color={reasonColour(id)}><i style:width="{(n / reasonRows[0][1]) * 100}%"></i></span>
								<span class="reason-n num">{n}</span>
							</button>
						{/each}
					</div>
				{:else}
					<p class="muted">No stated reasons for this direction in {periodLabel}{forward.count ? '' : ' (no flows this period)'}.</p>
				{/if}
			</section>

			{@render reviewEvidence()}

			<section class="block">
				<div class="block-head">
					<span class="label-dim">Monthly review mentions</span>
				</div>
				<svg class="mini" viewBox="0 0 {CW} {CH}" preserveAspectRatio="none" role="img" aria-label="Monthly review mentions from {name(edge.s)} toward {name(edge.t)}">
					<rect x={chart.band.x} y={PAD.t - 6} width={chart.band.w} height={CH - PAD.t - PAD.b + 6} class="band" />
					{#each allMonthIds as m, i (m)}
						{#if !flowMonth(m)?.full}
							<rect x={chart.x(i) - 3} y={CH - PAD.b} width="6" height="2" class="partial-tick" />
						{/if}
						{#if flowAnnotations.some((a) => a.month === m)}
							<line x1={chart.x(i)} x2={chart.x(i)} y1={PAD.t - 6} y2={CH - PAD.b} class="ann-line" />
						{/if}
					{/each}
					{#if chart.selected >= 0}
						<line x1={chart.x(chart.selected)} x2={chart.x(chart.selected)} y1="0" y2={CH - PAD.b} class="sel-line" />
					{/if}
					<path d={chart.fwd} class="fwd" style:stroke={reasonColour(topReason(forward.reasons))} />
				</svg>
				<div class="axis">
					<span>{fmtMonth(allMonthIds[0], true)}</span>
					<span class="cov">full coverage {fmtMonth(coverageMonths[0], true)}–{fmtMonth(coverageMonths.at(-1)!, true)}</span>
					<span>{fmtMonth(allMonthIds.at(-1)!, true)}</span>
				</div>
				<p class="hint">Number of review mentions for {name(edge.s)} → {name(edge.t)} each month. Outside the shaded coverage band, missing reviews can distort the trend.</p>
			</section>
		</div>
	{:else if app}
		<header class="head" style:--accent={app.observed ? 'var(--lime)' : 'var(--muted)'}>
			<div class="eyebrow">
				<button class="crumb" onclick={returnToApp}>Flows</button>
				<span class="slash">/</span>
				<span>{app.observed ? 'reviewed app' : 'outside app'}</span>
			</div>
			<div class="title-row">
				<h2>{app.name}</h2>
				<button class="close" onclick={close} aria-label="Close">×</button>
			</div>
			<div class="meta-row">
				{#if app.observed}
					<span class="chip is-lime">{fmtCount(appVolume)} reviews · {periodLabel}</span>
				{:else}
					<span class="chip">only seen through other apps’ reviews</span>
				{/if}
				<span class="chip">{[...layers].map((l) => layerNames[l]).join(' · ') || 'no layers'}</span>
			</div>
		</header>

		<div class="body scroll">
			<AppFlows appId={app.id} appName={app.name} />
		</div>
	{:else}
		<header class="head" style:--accent="var(--lime)">
			<div class="eyebrow"><span>Flows</span><span class="slash">/</span><span>overview</span></div>
			<div class="title-row">
				<h2>Music app switching</h2>
				<button class="close" onclick={close} aria-label="Close">×</button>
			</div>
			<div class="meta-row">
				<span class="chip">Music review snapshot</span>
				<span class="chip">Google Play &amp; App Store</span>
			</div>
		</header>

		<div class="body scroll">
			<section class="block">
				<div class="block-head">
					<span class="label-dim">Frequently mentioned routes · {periodLabel}</span>
				</div>
				{#if topFlows.length}
					<div class="partners">
						{#each topFlows as a (a.key)}
							<button class="partner" onclick={() => flowsState.selectEdge(a.s, a.t)}>
								<span class="p-name">{name(a.s)} → {name(a.t)}</span>
								<span class="p-val num" class:reported-switch-route={a.layer === 'switch'}>{fmtCount(a.count)} {a.layer === 'switch' ? 'switches' : 'mentions'}</span>
								<span class="meter" style:color={reasonColour(topReason(a.reasons))}><i style:width="{(a.count / (topFlows[0].count || 1)) * 100}%"></i></span>
								<span class="p-meta">
									{a.layer === 'net' ? 'dominant direction' : layerNames[a.layer]}
									{#if topReason(a.reasons)}· {reasonLabel(topReason(a.reasons)!)}{/if}
								</span>
							</button>
						{/each}
					</div>
				{:else}
					<p class="muted">Nothing visible. Turn on an edge type.</p>
				{/if}
			</section>

			<section class="block">
				<div class="block-head"><span class="label-dim">How to read it</span></div>
				<ul class="howto">
					<li><b>Arrow</b> source → target: users moving (or leaning) from one app to the other.</li>
					<li><b>Width</b> the strength of the review signal, adjusted so apps with more reviews don’t automatically dominate.</li>
					<li><b>Colour</b> the most common stated reason.</li>
					<li><b>Hollow apps</b> are only seen through other apps’ reviews.</li>
					<li>Click an arrow for reasons, a monthly line and quotes. Click an app for who it loses to and wins from.</li>
				</ul>
			</section>

			<section class="block">
				<div class="block-head"><span class="label-dim">Coverage</span></div>
				<p class="text">
					Full coverage {fmtMonth(coverageMonths[0])} – {fmtMonth(coverageMonths.at(-1)!)}: all three
					reviewed apps have normal review volume. {partialMonths.length} other months are partial
					because reviews are missing or unusually sparse, shown greyed on the timeline.
				</p>
				<p class="text dimmed">
					Counts are mentions in reviews, not unique people or measured migrations. See “Where flow data comes from” below the map for methodology.
				</p>
			</section>
		</div>
	{/if}
</aside>

<style>
	.inspector {
		width: var(--inspector-w);
		flex: none;
		display: flex;
		flex-direction: column;
		min-height: 0;
		background: var(--panel);
		border-left: 1px solid var(--line);
	}
	.head {
		flex: none;
		padding: 12px 14px 11px;
		border-bottom: 1px solid var(--line);
		position: relative;
	}
	.head::before {
		content: '';
		position: absolute;
		left: 0;
		top: 0;
		bottom: 0;
		width: 2px;
		background: var(--accent);
		opacity: 0.9;
	}
	.eyebrow {
		display: flex;
		align-items: center;
		gap: 5px;
		font-family: var(--mono);
		font-size: 8.5px;
		letter-spacing: 0.12em;
		text-transform: uppercase;
		color: var(--dim);
		margin-bottom: 5px;
	}
	.crumb {
		color: var(--muted);
		font-family: var(--mono);
		font-size: 8.5px;
		letter-spacing: 0.12em;
		text-transform: uppercase;
		text-decoration: underline;
		text-underline-offset: 2px;
		text-decoration-color: var(--line-strong);
	}
	.crumb:hover {
		color: var(--lime);
	}
	.slash {
		color: var(--faint);
	}
	.title-row {
		display: flex;
		align-items: flex-start;
		gap: 8px;
	}
	h2 {
		margin: 0;
		font-size: 19px;
		font-weight: 600;
		letter-spacing: -0.015em;
		line-height: 1.2;
		flex: 1;
	}
	.app-link {
		font-weight: 600;
		text-decoration: underline;
		text-decoration-color: var(--line-strong);
		text-underline-offset: 3px;
	}
	.app-link:hover {
		color: var(--lime);
	}
	.arrow-glyph {
		color: var(--dim);
		margin: 0 4px;
	}
	.close {
		width: 22px;
		height: 22px;
		display: grid;
		place-items: center;
		font-size: 17px;
		line-height: 1;
		color: var(--dim);
		border: 1px solid transparent;
		border-radius: 2px;
		flex: none;
	}
	.close:hover {
		color: var(--text);
		border-color: var(--line-strong);
	}
	.meta-row {
		display: flex;
		align-items: center;
		gap: 5px;
		flex-wrap: wrap;
		margin-top: 8px;
	}
	.meta-row .chip {
		height: 19px;
		font-size: 8.5px;
	}
	.swap {
		text-align: left;
		font-family: var(--mono);
		font-size: 8px;
		letter-spacing: 0.06em;
		text-transform: uppercase;
		color: var(--lime);
		text-decoration: underline;
		text-underline-offset: 2px;
	}
	.swap:hover {
		color: var(--text);
	}
	.switch-summary {
		display: flex;
		align-items: center;
		gap: 12px;
		padding: 14px 0 4px;
	}
	.switch-total {
		font-size: 38px;
		font-weight: 600;
		line-height: 1;
		color: var(--lime);
	}
	.switch-summary > div {
		display: flex;
		flex-direction: column;
		gap: 3px;
	}
	.switch-label {
		font-family: var(--mono);
		font-size: 11px;
		font-weight: 500;
		text-transform: uppercase;
		color: var(--text);
	}
	.switch-period {
		font-size: 10px;
		color: var(--muted);
	}
	.direction-note,
	.evidence-note {
		margin: 8px 0 0;
		font-size: 10.5px;
		line-height: 1.5;
		color: var(--muted);
	}
	.evidence-note {
		margin: 0 0 10px;
	}
	.clear-filter {
		font-family: var(--mono);
		font-size: 9px;
		color: var(--lime);
		text-decoration: underline;
		text-underline-offset: 3px;
		white-space: nowrap;
	}
	.clear-filter:hover {
		color: var(--text);
	}
	.archived {
		margin-top: 10px;
		white-space: normal;
		text-align: left;
	}

	.body {
		flex: 1;
		min-height: 0;
		overflow-y: auto;
	}
	.block {
		padding: 12px 14px;
		border-bottom: 1px solid var(--line);
	}
	.block-head {
		display: flex;
		align-items: center;
		justify-content: space-between;
		margin-bottom: 8px;
		gap: 8px;
	}
	.soft {
		font-size: 8.5px;
		color: var(--dim);
	}
	.muted {
		margin: 0;
		font-size: 11.5px;
		color: var(--dim);
	}
	.text {
		margin: 0 0 6px;
		font-size: 11.5px;
		line-height: 1.5;
		color: var(--text-2);
	}
	.text.dimmed {
		font-family: var(--mono);
		font-size: 9px;
		color: var(--dim);
	}
	.reasons {
		display: flex;
		flex-direction: column;
		gap: 6px;
	}
	.reason-row {
		display: grid;
		grid-template-columns: minmax(110px, 1fr) 1fr 30px;
		align-items: center;
		gap: 8px;
		min-height: 32px;
		padding: 6px;
		border: 1px solid transparent;
		border-radius: 3px;
		text-align: left;
		transition: background var(--fast), border-color var(--fast);
	}
	.reason-row:hover,
	.reason-row:focus-visible,
	.reason-row.active {
		background: var(--panel-2);
		border-color: var(--line-strong);
	}
	.reason-row.active .reason-name {
		color: var(--lime);
	}
	.reason-name {
		font-size: 11.5px;
		color: var(--text-2);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.reason-n {
		font-size: 10px;
		color: var(--muted);
		text-align: right;
	}

	.mini {
		width: 100%;
		height: 96px;
		display: block;
		overflow: visible;
	}
	.mini .band {
		fill: color-mix(in srgb, var(--lime) 5%, transparent);
	}
	.mini .partial-tick {
		fill: var(--faint);
	}
	.mini .ann-line {
		stroke: var(--lime);
		stroke-opacity: 0.4;
		stroke-dasharray: 2 3;
		vector-effect: non-scaling-stroke;
	}
	.mini .sel-line {
		stroke: var(--text);
		stroke-opacity: 0.6;
		vector-effect: non-scaling-stroke;
	}
	.mini .fwd {
		fill: none;
		stroke-width: 1.8;
		vector-effect: non-scaling-stroke;
	}
	.axis {
		display: flex;
		justify-content: space-between;
		margin-top: 3px;
		font-family: var(--mono);
		font-size: 8px;
		color: var(--faint);
	}
	.axis .cov {
		color: var(--lime-dim);
	}
	.hint {
		margin: 6px 0 0;
		font-family: var(--mono);
		font-size: 8.5px;
		color: var(--dim);
		line-height: 1.5;
	}

	.quotes {
		display: flex;
		flex-direction: column;
		gap: 8px;
	}
	.quote {
		padding: 9px 10px;
		background: var(--panel-2);
		border: 1px solid var(--line);
		border-radius: 2px;
	}
	.quote p {
		margin: 0;
		font-size: 12.5px;
		line-height: 1.45;
		color: var(--text);
	}
	.quote-meta {
		display: flex;
		flex-wrap: wrap;
		gap: 4px 9px;
		margin-top: 6px;
		font-family: var(--mono);
		font-size: 8.5px;
		color: var(--dim);
	}
	.stars {
		color: var(--amber);
		letter-spacing: 1px;
	}
	.quote-detail {
		margin-top: 4px;
		font-size: 11px;
		color: var(--muted);
	}
	.quote-reasons {
		display: flex;
		flex-wrap: wrap;
		gap: 4px;
		margin-top: 6px;
	}
	.mini-chip {
		height: 18px;
		font-size: 8.5px;
	}
	.mini-chip i {
		width: 6px;
		height: 6px;
		border-radius: 50%;
		display: inline-block;
	}

	.partners {
		display: flex;
		flex-direction: column;
	}
	.partner {
		display: grid;
		grid-template-columns: 1fr auto;
		grid-template-areas:
			'name val'
			'meter meter'
			'meta meta';
		gap: 3px 8px;
		padding: 7px 6px;
		margin: 0 -6px;
		text-align: left;
		border-radius: 2px;
		transition: background var(--fast);
	}
	.partner:hover {
		background: var(--panel-2);
	}
	.p-name {
		grid-area: name;
		font-size: 12.5px;
		color: var(--text);
	}
	.p-val {
		grid-area: val;
		font-size: 11px;
		color: var(--text-2);
	}
	.p-val.reported-switch-route {
		font-size: 14px;
		font-weight: 600;
		color: var(--lime);
	}
	.partner .meter {
		grid-area: meter;
	}
	.p-meta {
		grid-area: meta;
		display: flex;
		flex-wrap: wrap;
		gap: 3px 9px;
		font-family: var(--mono);
		font-size: 8.5px;
		color: var(--dim);
	}
	.howto {
		margin: 0;
		padding-left: 16px;
		display: flex;
		flex-direction: column;
		gap: 5px;
		font-size: 11.5px;
		line-height: 1.45;
		color: var(--text-2);
	}
	.howto b {
		color: var(--text);
		font-weight: 600;
	}

	@media (max-width: 1180px) {
		.inspector {
			position: absolute;
			top: var(--header-h);
			bottom: var(--status-h);
			right: 0;
			z-index: 26;
			width: min(396px, 94vw);
			box-shadow: -24px 0 60px rgba(0, 0, 0, 0.55);
		}
	}
</style>
