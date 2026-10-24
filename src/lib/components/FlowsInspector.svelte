<script lang="ts">
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

	const selection = $derived(flowsState.selection);
	const months = $derived(flowsState.periodMonths);
	const layers = $derived(flowsState.layers);
	const aggs = $derived(flowsState.aggregates);
	const periodLabel = $derived(flowsState.period === 'all' ? 'all months' : fmtMonth(flowsState.period));

	const layerNames: Record<FlowLayer, string> = {
		switch: 'switches + returns',
		intent: 'intents',
		preference: 'preferences'
	};
	const kindNames: Record<FlowKind, [string, string]> = {
		switch: ['switch', 'switches'],
		return: ['return', 'returns'],
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
	const backward = $derived(edge ? pair(edge.t, edge.s) : null);
	const reasonRows = $derived(forward ? sortedReasons(forward.reasons) : []);
	const reasonTotal = $derived(reasonRows.reduce((sum, [, n]) => sum + n, 0));
	const series = $derived(edge ? pairSeries(edge.s, edge.t, layers) : []);
	const reverseSeries = $derived(edge ? pairSeries(edge.t, edge.s, layers) : []);
	const exampleKinds = $derived(
		(['switch', 'return', 'intent', 'preference'] as FlowKind[]).filter((k) =>
			layers.has(k === 'return' ? 'switch' : (k as FlowLayer))
		)
	);
	const examples = $derived(
		edge
			? exampleKinds.flatMap((kind) => examplesFor(edge.s, edge.t, kind).map((ex) => ({ ...ex, kind })))
			: []
	);

	/* ----------------------------- app ------------------------------ */

	const appId = $derived(selection?.type === 'app' ? selection.id : null);
	const app = $derived(appId ? flowNode(appId) : undefined);
	const appVolume = $derived(app?.observed ? volumeOf(app.id, months) : 0);

	/* --------------------------- overview --------------------------- */

	const topFlows = $derived(
		[...flowsState.arrows].sort((a, b) => b.value - a.value).slice(0, 10)
	);
	const partialMonths = flows.months.filter((m) => !m.full);

	/* --------------------------- mini chart ------------------------- */

	const CW = 340;
	const CH = 96;
	const PAD = { l: 4, r: 4, t: 10, b: 14 };

	const chart = $derived.by(() => {
		const max = Math.max(...series.map((p) => p.value), ...reverseSeries.map((p) => p.value), 0.001);
		const n = allMonthIds.length;
		const x = (i: number) => PAD.l + (i / Math.max(1, n - 1)) * (CW - PAD.l - PAD.r);
		const y = (v: number) => PAD.t + (1 - v / max) * (CH - PAD.t - PAD.b);
		const line = (pts: { value: number }[]) =>
			pts.map((p, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(p.value).toFixed(1)}`).join(' ');
		const covStart = allMonthIds.indexOf(coverageMonths[0]);
		const covEnd = allMonthIds.indexOf(coverageMonths[coverageMonths.length - 1]);
		return {
			max,
			x,
			y,
			fwd: line(series),
			bwd: line(reverseSeries),
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

<aside class="inspector" aria-label="Flows inspector">
	{#if edge && forward && backward}
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
			<div class="meta-row">
				{#each Object.entries(forward.kinds) as [kind, n] (kind)}
					<span class="chip">{n} {kindNames[kind as FlowKind][n === 1 ? 0 : 1]}</span>
				{/each}
				<button class="swap" onclick={() => flowsState.selectEdge(edge.t, edge.s)}>reverse ⇄</button>
			</div>
		</header>

		<div class="body scroll">
			<section class="block stats">
				<div class="stat">
					<span class="label-dim">this way</span>
					<span class="big num">{forward.value.toFixed(1)}</span>
					<span class="unit">per 10k · {fmtCount(forward.count)} reviews</span>
				</div>
				<div class="stat">
					<span class="label-dim">reverse</span>
					<span class="big num dim">{backward.value.toFixed(1)}</span>
					<span class="unit">per 10k · {fmtCount(backward.count)} reviews</span>
				</div>
				<div class="stat">
					<span class="label-dim">net</span>
					<span class="big num" class:pos={forward.value >= backward.value} class:neg={forward.value < backward.value}>
						{forward.value >= backward.value ? '→' : '←'}
						{Math.abs(forward.value - backward.value).toFixed(1)}
					</span>
					<span class="unit">{periodLabel}</span>
				</div>
			</section>

			<section class="block">
				<div class="block-head">
					<span class="label-dim">Why · {periodLabel}</span>
					<span class="soft num">{reasonTotal} stated reasons</span>
				</div>
				{#if reasonRows.length}
					<div class="reasons">
						{#each reasonRows.slice(0, 8) as [id, n] (id)}
							<div class="reason-row">
								<span class="reason-name">{reasonLabel(id)}</span>
								<span class="meter" style:color={reasonColour(id)}><i style:width="{(n / reasonRows[0][1]) * 100}%"></i></span>
								<span class="reason-n num">{n}</span>
							</div>
						{/each}
					</div>
				{:else}
					<p class="muted">No stated reasons for this direction in {periodLabel}{forward.count ? '' : ' (no flows this period)'}.</p>
				{/if}
			</section>

			<section class="block">
				<div class="block-head">
					<span class="label-dim">Monthly · per 10k reviews</span>
					<span class="soft num">
						<i class="key fwd"></i>this way <i class="key bwd"></i>reverse
					</span>
				</div>
				<svg class="mini" viewBox="0 0 {CW} {CH}" preserveAspectRatio="none" role="img" aria-label="Monthly flow for this pair">
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
					<path d={chart.bwd} class="bwd" />
					<path d={chart.fwd} class="fwd" style:stroke={reasonColour(topReason(forward.reasons))} />
				</svg>
				<div class="axis">
					<span>{fmtMonth(allMonthIds[0], true)}</span>
					<span class="cov">full coverage {fmtMonth(coverageMonths[0], true)}–{fmtMonth(coverageMonths.at(-1)!, true)}</span>
					<span>{fmtMonth(allMonthIds.at(-1)!, true)}</span>
				</div>
				<p class="hint">Peak {chart.max.toFixed(1)}. Outside the band some apps have no reviews, so spikes there can be noise.</p>
			</section>

			<section class="block">
				<div class="block-head">
					<span class="label-dim">What reviewers said</span>
					<span class="soft num">{examples.length} quotes · all months</span>
				</div>
				{#if examples.length}
					<div class="quotes">
						{#each examples as ex, i (i)}
							<article class="quote">
								<p>“{ex.q}”</p>
								<div class="quote-meta">
									<span class="stars">{stars(ex.stars)}</span>
									<span>{fmtMonth(ex.m, true)}</span>
									<span>{ex.kind}</span>
									<span>in {name(ex.o)} reviews</span>
								</div>
								{#if ex.d}<div class="quote-detail">{ex.d}</div>{/if}
								{#if ex.r.length}
									<div class="quote-reasons">
										{#each ex.r as r (r)}
											<span class="chip mini-chip"><i style:background={reasonColour(r)}></i>{reasonLabel(r)}</span>
										{/each}
									</div>
								{/if}
							</article>
						{/each}
					</div>
				{:else}
					<p class="muted">No example quotes for the visible edge types.</p>
				{/if}
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
				<span class="chip">{fmtCount(flows.meta.edgeRows)} labeled edges</span>
				<span class="chip">{flows.meta.model}</span>
			</div>
		</header>

		<div class="body scroll">
			<section class="block">
				<div class="block-head">
					<span class="label-dim">Top flows · {periodLabel}</span>
					<span class="soft num">per 10k reviews</span>
				</div>
				{#if topFlows.length}
					<div class="partners">
						{#each topFlows as a (a.key)}
							<button class="partner" onclick={() => flowsState.selectEdge(a.s, a.t)}>
								<span class="p-name">{name(a.s)} → {name(a.t)}</span>
								<span class="p-val num">{a.value.toFixed(1)}</span>
								<span class="meter" style:color={reasonColour(topReason(a.reasons))}><i style:width="{(a.value / (topFlows[0].value || 1)) * 100}%"></i></span>
								<span class="p-meta">
									{fmtCount(a.count)} reviews · {a.layer === 'net' ? 'net' : layerNames[a.layer]}
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
					<li><b>Width</b> edge weight per 10k reviews of the app the review was posted on, so busy apps don’t dominate.</li>
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
					(mostly no Spotify reviews after Apr 2025), shown greyed on the timeline.
				</p>
				<p class="text dimmed">
					Labels by {flows.meta.model}. {flows.meta.normalization}
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
		margin-left: auto;
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
	.stats {
		display: grid;
		grid-template-columns: repeat(3, 1fr);
		gap: 10px;
	}
	.stat {
		display: flex;
		flex-direction: column;
		gap: 2px;
		min-width: 0;
	}
	.big {
		font-size: 20px;
		font-weight: 600;
		color: var(--text);
		line-height: 1.15;
	}
	.big.dim {
		color: var(--muted);
	}
	.big.pos {
		color: var(--pos);
	}
	.big.neg {
		color: var(--neg);
	}
	.unit {
		font-family: var(--mono);
		font-size: 8.5px;
		color: var(--dim);
	}

	.reasons {
		display: flex;
		flex-direction: column;
		gap: 6px;
	}
	.reason-row {
		display: grid;
		grid-template-columns: 128px 1fr 30px;
		align-items: center;
		gap: 8px;
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
	.mini .bwd {
		fill: none;
		stroke: var(--muted);
		stroke-width: 1.2;
		stroke-dasharray: 3 3;
		vector-effect: non-scaling-stroke;
	}
	.key {
		display: inline-block;
		width: 10px;
		height: 0;
		border-top: 2px solid var(--text-2);
		margin: 0 3px 0 8px;
		vertical-align: middle;
	}
	.key.bwd {
		border-top: 1px dashed var(--muted);
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
