<script lang="ts">
	import { tick } from 'svelte';
	import { studio } from '#lib/state/studio.svelte';
	import { flowsState } from '#lib/state/flows.svelte';
	import AppFlows from './AppFlows.svelte';
	import AppLogo from './AppLogo.svelte';
	import {
		allMonthIds,
		examplesFor,
		flowNode,
		flows,
		fmtMonth,
		pairSeries,
		pairReviewVolume,
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
	import { combinedFlowIssues } from '#lib/utils/flow-issues';

	const selection = $derived(flowsState.selection);
	const months = $derived(flowsState.periodMonths);
	const layers = $derived(flowsState.layers);
	const aggs = $derived(flowsState.aggregates);
	const periodLabel = $derived(flowsState.periodLabel);

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
	const reviewCount = $derived(edge ? pairReviewVolume(edge.s, edge.t, months) : 0);
	const coverageMonths = $derived(flowsState.coverageMonths);
	const reasonRows = $derived(forward ? sortedReasons(forward.reasons) : []);
	const series = $derived(edge ? pairSeries(edge.s, edge.t, layers) : []);
	const reverseSeries = $derived(edge ? pairSeries(edge.t, edge.s, layers) : []);
	let selectedReason = $state<string | null>(null);
	let includeAllMonths = $state(false);
	let showAllIssues = $state(false);
	let reviewSection = $state<HTMLElement>();
	let evidenceContext = '';

	$effect(() => {
		const next = `${edge?.s}|${edge?.t}|${months.join(',')}|${[...layers].join(',')}`;
		if (next !== evidenceContext) {
			evidenceContext = next;
			selectedReason = null;
			includeAllMonths = false;
			showAllIssues = false;
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
	const examples = $derived(filterFlowEvidence(allExamples, selectedReason, months, includeAllMonths));
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
		[...flowsState.arrows].sort((a, b) => b.count - a.count || a.key.localeCompare(b.key))
	);
	const clusterIssues = $derived(combinedFlowIssues(aggs.values()));
	let showAllRoutes = $state(false);
	let showAllClusterIssues = $state(false);
	let clusterContext = '';
	$effect(() => {
		const next = `${studio.categoryFilter}|${months.join(',')}`;
		if (next !== clusterContext) {
			clusterContext = next;
			showAllRoutes = false;
			showAllClusterIssues = false;
		}
	});
	const partialMonths = $derived(allMonthIds.map((month) => flowsState.monthInfo(month)).filter((month) => !month.full));

	/* --------------------------- mini chart ------------------------- */

	const CW = 340;
	const CH = 96;
	const PAD = { l: 4, r: 4, t: 10, b: 14 };

	const chart = $derived.by(() => {
		// Both directions use the same count scale so the dashed comparison is honest.
		const max = Math.max(...series.map((p) => p.count), ...reverseSeries.map((p) => p.count), 1);
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
			reverse: line(reverseSeries),
			band: { x: x(covStart) - 4, w: x(covEnd) - x(covStart) + 8 },
			selected: flowsState.period === 'all' ? -1 : allMonthIds.indexOf(flowsState.period),
			selectedEnd: flowsState.rangeEnd ? allMonthIds.indexOf(flowsState.rangeEnd) : -1
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
			<span class="label-dim">What customers are saying{selectedReason ? ` · ${reasonLabel(selectedReason)}` : ''}</span>
			{#if selectedReason}
				<button class="clear-filter" onclick={() => { selectedReason = null; includeAllMonths = false; }}>All issues</button>
			{/if}
		</div>
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
			<p class="muted">No saved comments{selectedReason ? ` about ${reasonLabel(selectedReason)}` : ''} for this period.</p>
		{/if}
		{#if flowsState.period !== 'all' && !includeAllMonths && archivedExamples.length > examples.length}
			<button class="clear-filter archived" onclick={() => (includeAllMonths = true)}>Show matching excerpts from all months</button>
		{/if}
		<details class="source-note"><summary>About these comments</summary><p>{examples.length} representative excerpts · {includeAllMonths || flowsState.period === 'all' ? 'all months' : periodLabel}. This snapshot contains sampled quotes, not the complete review archive.</p></details>
	</section>
{/snippet}

{#snippet switchingChart()}
	{#if edge && forward}
		<section class="block route-chart">
			<div class="block-head"><span class="label-dim">Switching over time</span></div>
			<svg class="mini" viewBox="0 0 {CW} {CH}" preserveAspectRatio="none" role="img" aria-label="Monthly reported switches: solid {name(edge.s)} to {name(edge.t)}; dashed {name(edge.t)} to {name(edge.s)}. Both directions share the same count scale.">
				{#each allMonthIds as month, index (month)}
					{#if !flowsState.monthInfo(month).full}<rect x={chart.x(index) - 3} y={CH - PAD.b} width="6" height="2" class="partial-tick" />{/if}
				{/each}
				{#if chart.selectedEnd >= 0}<rect x={chart.x(chart.selected)} y="0" width={chart.x(chart.selectedEnd) - chart.x(chart.selected)} height={CH - PAD.b} fill="var(--lime)" fill-opacity="0.12" />{:else if chart.selected >= 0}<line x1={chart.x(chart.selected)} x2={chart.x(chart.selected)} y1="0" y2={CH - PAD.b} class="sel-line" />{/if}
				<path d={chart.reverse} class="reverse"><title>{name(edge.t)} → {name(edge.s)}</title></path>
				<path d={chart.fwd} class="fwd" style:stroke="var(--lime)"><title>{name(edge.s)} → {name(edge.t)}</title></path>
			</svg>
			<div class="axis"><span>{fmtMonth(allMonthIds[0], true)}</span><span>{fmtMonth(allMonthIds.at(-1)!, true)}</span></div>
			<div class="direction-key" aria-hidden="true"><span><i></i>{name(edge.s)} → {name(edge.t)}</span><span class="reverse-key"><i></i>{name(edge.t)} → {name(edge.s)}</span></div>
		</section>
	{/if}
{/snippet}

<aside class="inspector" aria-label="Switching details">
	{#if edge && forward}
		<header class="head" style:--accent={reasonColour(topReason(forward.reasons))}>
			<div class="eyebrow">
				<button class="crumb" onclick={returnToApp}>{studio.selectedApp?.name ?? 'Flows'}</button>
				<span class="slash">/</span>
				<span>{[...layers].map((l) => layerNames[l]).join(' · ') || 'no layers'}</span>
			</div>
			<div class="title-row">
				<h2>
					<button class="app-link" onclick={() => studio.selectFlowApp(edge.s)} aria-label={name(edge.s)}><AppLogo appId={edge.s} name={name(edge.s)} size={25} />{name(edge.s)}</button>
					<span class="arrow-glyph">→</span>
					<button class="app-link" onclick={() => studio.selectFlowApp(edge.t)} aria-label={name(edge.t)}><AppLogo appId={edge.t} name={name(edge.t)} size={25} />{name(edge.t)}</button>
				</h2>
				<button class="close" onclick={close} aria-label="Close">×</button>
			</div>
			{#if layers.has('switch')}
				<div class="switch-summary">
					<div aria-label="{switchCount} reported switches"><strong class="switch-total num">{fmtCount(switchCount)}</strong><span class="switch-label">Reported switches</span></div>
					<div aria-label="{reviewCount} reviews analyzed" title="Review volume in the switching dataset for the apps whose reviews contain this route"><strong class="review-count num">{fmtCount(reviewCount)}</strong><span class="switch-label">Reviews analyzed</span></div>
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
		</header>

		<div class="body scroll">
			{@render switchingChart()}
			<section class="block">
				<div class="block-head">
					<span class="label-dim">Issues customers mention</span>
				</div>
				{#if reasonRows.length}
					<div class="reasons">
						{#each showAllIssues ? reasonRows : reasonRows.slice(0, 5) as [id, n] (id)}
							<button class="reason-row" class:active={selectedReason === id} aria-pressed={selectedReason === id} aria-controls="flow-review-evidence" aria-label="Show reviews about {reasonLabel(id)}" onclick={() => chooseReason(id)}>
								<span class="reason-name">{reasonLabel(id)}</span>
								<span class="meter" style:color={reasonColour(id)}><i style:width="{(n / reasonRows[0][1]) * 100}%"></i></span>
								<span class="reason-n num">{n}</span>
							</button>
						{/each}
					</div>
					{#if reasonRows.length > 5}<button class="clear-filter archived" onclick={() => (showAllIssues = !showAllIssues)}>{showAllIssues ? 'View less' : 'View more'}</button>{/if}
				{:else}
					<p class="muted">No stated reasons for this direction in {periodLabel}{forward.count ? '' : ' (no flows this period)'}.</p>
				{/if}
			</section>

			{@render reviewEvidence()}

		</div>
	{:else if app}
		<header class="head" style:--accent={app.observed ? 'var(--lime)' : 'var(--muted)'}>
			<div class="eyebrow">
				<button class="crumb" onclick={returnToApp}>Flows</button>
				<span class="slash">/</span>
				<span>{app.observed ? 'reviewed app' : 'outside app'}</span>
			</div>
			<div class="title-row">
				<AppLogo appId={app.id} name={app.name} size={32} />
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
				<h2>{studio.selectedCategory?.name ?? 'App'} switching</h2>
				<button class="close" onclick={close} aria-label="Close">×</button>
			</div>
			<div class="meta-row">
				<span class="chip">Customer review snapshot</span>
				<span class="chip">Google Play &amp; App Store</span>
			</div>
		</header>

		<div class="body scroll">
			<section class="block cluster-routes" aria-label="Cluster switching routes">
				<div class="block-head">
					<span class="label-dim">Reported switches · {periodLabel}</span>
				</div>
				{#if topFlows.length}
					<div class="partners" id="cluster-route-list">
						{#each showAllRoutes ? topFlows : topFlows.slice(0, 5) as a (a.key)}
							<button class="partner" onclick={() => flowsState.selectEdge(a.s, a.t)}>
								<span class="p-name">{name(a.s)} → {name(a.t)}</span>
								<span class="p-val num" class:reported-switch-route={a.layer === 'switch' || a.layer === 'net'}>{fmtCount(a.count)} {a.layer === 'switch' || a.layer === 'net' ? 'switches' : 'mentions'}</span>
								<span class="meter" style:color={reasonColour(topReason(a.reasons))}><i style:width="{(a.count / (topFlows[0].count || 1)) * 100}%"></i></span>
								<span class="p-meta">
									{a.layer === 'net' ? 'dominant direction' : layerNames[a.layer]}
									{#if topReason(a.reasons)}· {reasonLabel(topReason(a.reasons)!)}{/if}
								</span>
							</button>
						{/each}
					</div>
					{#if topFlows.length > 5}<button class="clear-filter archived" aria-label={showAllRoutes ? 'See fewer routes' : 'See more routes'} aria-expanded={showAllRoutes} aria-controls="cluster-route-list" onclick={() => (showAllRoutes = !showAllRoutes)}>{showAllRoutes ? 'See less' : 'See more'}</button>{/if}
				{:else}
					<p class="muted">No reported switches in this period.</p>
				{/if}
			</section>

			<section class="block cluster-issues" aria-label="Combined cluster issues">
				<div class="block-head"><span class="label-dim">Issues across all apps</span></div>
				{#if clusterIssues.length}
					<div class="reasons" id="cluster-issue-list">
						{#each showAllClusterIssues ? clusterIssues : clusterIssues.slice(0, 5) as [id, count] (id)}
							<div class="reason-row cluster-reason" data-issue={id} title="{count.toLocaleString()} issue mentions in switching reports">
								<span class="reason-name">{reasonLabel(id)}</span>
								<span class="meter" style:color={reasonColour(id)}><i style:width="{count / clusterIssues[0][1] * 100}%"></i></span>
								<span class="reason-n num">{count.toLocaleString()}</span>
								</div>
						{/each}
					</div>
					{#if clusterIssues.length > 5}<button class="clear-filter archived" aria-label={showAllClusterIssues ? 'See fewer issues' : 'See more issues'} aria-expanded={showAllClusterIssues} aria-controls="cluster-issue-list" onclick={() => (showAllClusterIssues = !showAllClusterIssues)}>{showAllClusterIssues ? 'See less' : 'See more'}</button>{/if}
					<p class="issue-note">Combined switching reports for this period. Reports can mention multiple issues.</p>
				{:else}<p class="muted">No stated switching issues in this period.</p>{/if}
			</section>

			<section class="block">
				<div class="block-head"><span class="label-dim">How to read it</span></div>
				<ul class="howto">
					<li><b>Arrow</b> source → target: the main switching direction reported in reviews.</li>
					<li><b>Width</b> the strength of the review signal, adjusted so apps with more reviews don’t automatically dominate.</li>
					<li><b>Colour</b> green enters this industry, red leaves it; internal routes show the most common stated reason.</li>
					<li>Click an arrow for reasons, a monthly line and quotes. Click an app for who it loses to and wins from.</li>
				</ul>
			</section>

			<section class="block">
				<div class="block-head"><span class="label-dim">Coverage</span></div>
				{#if coverageMonths.length}<p class="text">
					Full coverage {fmtMonth(coverageMonths[0])} – {fmtMonth(coverageMonths.at(-1)!)}: the selected
					apps have normal review volume. {partialMonths.length} other months are partial
					because reviews are missing or unusually sparse.
				</p>{:else}<p class="text">Review coverage is limited for this industry.</p>{/if}
				<p class="text dimmed">
					Counts are reports in reviews, not unique people or measured migrations.
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
		display: inline-flex;
		align-items: center;
		gap: 6px;
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
		display: grid;
		grid-template-columns: 1fr 1fr;
		align-items: end;
		gap: 16px;
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
		font-weight: 700;
		text-transform: uppercase;
		color: var(--text);
	}
	.review-count { font-size: 26px; color: white; line-height: 1; }
	.source-note { margin-top: 12px; font-size: 9px; color: var(--muted); }
	.source-note summary { cursor: pointer; }
	.source-note p { line-height: 1.5; }
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
	.cluster-reason { grid-template-columns: minmax(110px, 1fr) 1fr minmax(30px, auto); }
	.cluster-reason:hover { background: none; border-color: transparent; }
	.issue-note { margin: 10px 0 0; font-size: 9px; color: var(--muted); line-height: 1.5; }

	.mini {
		width: 100%;
		height: 96px;
		display: block;
		overflow: visible;
	}
	.mini .partial-tick {
		fill: var(--faint);
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
	.mini .reverse { fill: none; stroke: var(--text-2); stroke-width: 1.3; stroke-dasharray: 4 4; stroke-opacity: 0.5; vector-effect: non-scaling-stroke; }
	.direction-key { display: flex; flex-wrap: wrap; gap: 5px 12px; margin-top: 8px; font-size: 9px; color: var(--muted); }
	.direction-key span { display: inline-flex; align-items: center; gap: 5px; }
	.direction-key i { width: 16px; border-top: 2px solid var(--lime); }
	.direction-key .reverse-key { opacity: 0.7; }
	.direction-key .reverse-key i { border-top: 1px dashed var(--text-2); }
	.axis {
		display: flex;
		justify-content: space-between;
		margin-top: 3px;
		font-family: var(--mono);
		font-size: 8px;
		color: var(--faint);
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
			top: 0;
			bottom: var(--status-h);
			right: 0;
			z-index: 26;
			width: min(396px, 94vw);
			box-shadow: -24px 0 60px rgba(0, 0, 0, 0.55);
		}
	}
</style>
