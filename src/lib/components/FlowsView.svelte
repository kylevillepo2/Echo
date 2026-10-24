<script lang="ts">
	import { onDestroy } from 'svelte';
	import { studio } from '#lib/state/studio.svelte';
	import { flowsState, type FlowArrow } from '#lib/state/flows.svelte';
	import {
		allMonthIds,
		coverageMonths,
		flowAnnotations,
		flowMonth,
		flowMonths,
		flowNode,
		flowNodes,
		fmtMonth,
		legendReasons,
		monthlyActivity,
		OTHER_COLOUR,
		reasonColour,
		reasonLabel,
		topReason,
		volumeOf,
		type FlowNode
	} from '#lib/data/flows';
	import { fmtCount } from '#lib/utils/format';

	/* ----------------------------- layout ----------------------------- */
	// Static layout in a fixed viewBox: the three observed apps form a triangle in
	// the middle; outside apps sit on a ring around them.

	const VB = { x: -520, y: -300, w: 1040, h: 600 };
	const CORE: Record<string, { x: number; y: number }> = {
		spotify: { x: 0, y: -105 },
		soundcloud: { x: -150, y: 95 },
		audiomack: { x: 150, y: 95 }
	};

	const positions: Map<string, { x: number; y: number }> = (() => {
		const map = new Map<string, { x: number; y: number }>();
		for (const n of flowNodes) if (CORE[n.id]) map.set(n.id, CORE[n.id]);
		return placeRing(
			map,
			flowNodes.filter((n) => !CORE[n.id])
		);
	})();

	function placeRing(map: Map<string, { x: number; y: number }>, outside: FlowNode[]) {
		const rx = 430;
		const ry = 238;
		// Even slots around the ring, biggest apps first so they land on the sides.
		const order = [...outside].sort((a, b) => b.edgeCount - a.edgeCount);
		const slots = order.length;
		// Interleave so neighbours alternate between large and small apps.
		const placed: FlowNode[] = new Array(slots);
		let left = 0;
		let right = slots - 1;
		order.forEach((n, i) => {
			if (i % 2 === 0) placed[left++] = n;
			else placed[right--] = n;
		});
		placed.forEach((n, i) => {
			const angle = -Math.PI / 2 + Math.PI / slots + (i / slots) * Math.PI * 2;
			map.set(n.id, { x: Math.cos(angle) * rx, y: Math.sin(angle) * ry });
		});
		return map;
	}

	/* ----------------------------- derived ---------------------------- */

	const arrows = $derived(flowsState.arrows);
	const scaleMax = $derived(flowsState.scaleMax);
	const months = $derived(flowsState.periodMonths);
	const monthInfo = $derived(flowsState.period === 'all' ? undefined : flowMonth(flowsState.period));
	const annotation = $derived(flowAnnotations.find((a) => a.month === flowsState.period));

	const maxVolume = Math.max(...flowNodes.map((n) => (n.volume ? Math.max(...Object.values(n.volume)) : 0)), 1);
	const maxTotal = Math.max(...flowNodes.map((n) => n.totalVolume ?? 0), 1);
	const maxEdges = Math.max(...flowNodes.filter((n) => !n.observed).map((n) => n.edgeCount), 1);

	function radius(node: FlowNode): number {
		if (!node.observed) return 7 + Math.sqrt(node.edgeCount / maxEdges) * 10;
		const vol = flowsState.period === 'all' ? (node.totalVolume ?? 0) : volumeOf(node.id, months);
		const ref = flowsState.period === 'all' ? maxTotal : maxVolume;
		return 16 + Math.sqrt(vol / ref) * 26;
	}

	const radii = $derived(new Map(flowNodes.map((n) => [n.id, radius(n)])));

	const visibleArrows = $derived(
		arrows
			.filter((a) => a.value >= scaleMax * 0.004)
			.sort((a, b) => layerOrder(a) - layerOrder(b) || a.value - b.value)
	);

	function layerOrder(a: FlowArrow): number {
		return a.layer === 'preference' ? 0 : a.layer === 'intent' ? 1 : 2;
	}

	const selectedEdge = $derived(flowsState.selection?.type === 'edge' ? flowsState.selection : null);
	const selectedApp = $derived(flowsState.selection?.type === 'app' ? flowsState.selection.id : null);
	const focusApp = $derived(flowsState.hoveredNode ?? selectedApp);

	/* ---------------------------- geometry ---------------------------- */

	const CURVE: Record<string, number> = { switch: 0.13, intent: 0.22, preference: 0.31, net: 0.07 };

	interface ArrowGeom {
		path: string;
		hit: string;
		head: string;
		width: number;
		mid: { x: number; y: number };
	}

	function geometry(a: FlowArrow): ArrowGeom | null {
		const p0 = positions.get(a.s);
		const p2 = positions.get(a.t);
		if (!p0 || !p2) return null;
		const dx = p2.x - p0.x;
		const dy = p2.y - p0.y;
		const dist = Math.hypot(dx, dy) || 1;
		// control point to the right of the direction of travel, so A->B and B->A separate
		const k = CURVE[a.layer] ?? 0.15;
		const c = { x: (p0.x + p2.x) / 2 - (dy / dist) * dist * k, y: (p0.y + p2.y) / 2 + (dx / dist) * dist * k };
		const width = 1.1 + Math.sqrt(a.value / scaleMax) * 13;
		const rs = (radii.get(a.s) ?? 10) + 3;
		const rt = (radii.get(a.t) ?? 10) + 3;
		const start = along(p0, c, rs);
		const tip = along(p2, c, rt);
		const dir = unit(c, tip);
		const headLen = Math.max(7, width * 1.6);
		const headHalf = Math.max(4.5, width * 1.15);
		const base = { x: tip.x - dir.x * headLen, y: tip.y - dir.y * headLen };
		const nx = -dir.y;
		const ny = dir.x;
		const head = [
			`${tip.x.toFixed(1)},${tip.y.toFixed(1)}`,
			`${(base.x + nx * headHalf).toFixed(1)},${(base.y + ny * headHalf).toFixed(1)}`,
			`${(base.x - nx * headHalf).toFixed(1)},${(base.y - ny * headHalf).toFixed(1)}`
		].join(' ');
		const path = `M${start.x.toFixed(1)},${start.y.toFixed(1)} Q${c.x.toFixed(1)},${c.y.toFixed(1)} ${base.x.toFixed(1)},${base.y.toFixed(1)}`;
		const hit = `M${start.x.toFixed(1)},${start.y.toFixed(1)} Q${c.x.toFixed(1)},${c.y.toFixed(1)} ${tip.x.toFixed(1)},${tip.y.toFixed(1)}`;
		const mid = { x: 0.25 * start.x + 0.5 * c.x + 0.25 * tip.x, y: 0.25 * start.y + 0.5 * c.y + 0.25 * tip.y };
		return { path, hit, head, width, mid };
	}

	function along(from: { x: number; y: number }, to: { x: number; y: number }, d: number) {
		const u = unit(from, to);
		return { x: from.x + u.x * d, y: from.y + u.y * d };
	}

	function unit(from: { x: number; y: number }, to: { x: number; y: number }) {
		const dx = to.x - from.x;
		const dy = to.y - from.y;
		const len = Math.hypot(dx, dy) || 1;
		return { x: dx / len, y: dy / len };
	}

	/* ----------------------------- styling ---------------------------- */

	function arrowColour(a: FlowArrow): string {
		return reasonColour(topReason(a.reasons));
	}

	function isActive(a: FlowArrow): boolean {
		if (flowsState.hoveredArrow) return flowsState.hoveredArrow === a.key;
		if (selectedEdge) {
			return (
				(a.s === selectedEdge.s && a.t === selectedEdge.t) ||
				(flowsState.netMode && a.s === selectedEdge.t && a.t === selectedEdge.s)
			);
		}
		if (focusApp) return a.s === focusApp || a.t === focusApp;
		return true;
	}

	const anyFocus = $derived(Boolean(flowsState.hoveredArrow || selectedEdge || focusApp));

	function arrowOpacity(a: FlowArrow): number {
		const base = a.layer === 'preference' ? 0.32 : a.layer === 'intent' ? 0.75 : 0.88;
		if (!anyFocus) return base;
		return isActive(a) ? Math.max(base, 0.85) : 0.07;
	}

	function nodeDim(id: string): boolean {
		if (!anyFocus) return false;
		if (focusApp) {
			if (id === focusApp) return false;
			return !visibleArrows.some((a) => (a.s === focusApp && a.t === id) || (a.t === focusApp && a.s === id));
		}
		const active = visibleArrows.filter(isActive);
		return !active.some((a) => a.s === id || a.t === id);
	}

	function layerLabel(layer: FlowArrow['layer']): string {
		return layer === 'switch'
			? 'switches + returns'
			: layer === 'intent'
				? 'intents'
				: layer === 'preference'
					? 'preferences'
					: 'net flow';
	}

	/* ---------------------------- tooltips ---------------------------- */

	let stage: HTMLDivElement;
	let pointer = $state({ x: 0, y: 0 });
	let stageW = $state(0);
	let stageH = $state(0);

	function onMove(event: PointerEvent) {
		const rect = stage.getBoundingClientRect();
		pointer = { x: event.clientX - rect.left, y: event.clientY - rect.top };
	}

	const tipX = $derived(pointer.x > stageW - 270 ? Math.max(8, pointer.x - 262) : pointer.x + 16);
	const tipY = $derived(pointer.y > stageH - 150 ? Math.max(8, pointer.y - 132) : pointer.y + 16);

	const hoveredArrow = $derived(visibleArrows.find((a) => a.key === flowsState.hoveredArrow));
	const hoveredNode = $derived(flowsState.hoveredNode ? flowNode(flowsState.hoveredNode) : undefined);

	function name(id: string): string {
		return flowNode(id)?.name ?? id;
	}

	function select(a: FlowArrow) {
		flowsState.selectEdge(a.s, a.t);
		studio.inspectorOpen = true;
	}

	function selectNode(id: string) {
		flowsState.selectApp(id);
		studio.inspectorOpen = true;
	}

	function onBackground(event: MouseEvent) {
		const target = event.target as Element;
		if (target.closest('.arrow') || target.closest('.fnode')) return;
		flowsState.clearSelection();
	}

	/* ---------------------------- timeline ---------------------------- */

	const coverageIndex = $derived(coverageMonths.indexOf(flowsState.period));
	const maxActivity = Math.max(...allMonthIds.map((m) => monthlyActivity[m] ?? 0), 1);
	const partialCount = flowMonths.filter((m) => !m.full).length;

	function onSlider(event: Event) {
		flowsState.stop();
		const idx = Number((event.currentTarget as HTMLInputElement).value);
		flowsState.setPeriod(coverageMonths[idx]);
	}

	function pickMonth(id: string) {
		flowsState.stop();
		flowsState.setPeriod(flowsState.period === id ? 'all' : id);
	}

	onDestroy(() => flowsState.stop());

	const periodLabel = $derived(
		flowsState.period === 'all' ? `All months · ${fmtMonth(allMonthIds[0], true)}–${fmtMonth(allMonthIds.at(-1)!, true)}` : fmtMonth(flowsState.period)
	);
</script>

<section class="flows" aria-label="Switching flows between music apps">
	<header class="toolbar">
		<div class="left">
			<span class="label">Switching flows</span>
			<span class="stats num">
				{flowNodes.length} apps · {visibleArrows.length} arrows · {periodLabel}
			</span>
		</div>

		<div class="right">
			<div class="seg" role="group" aria-label="Edge types">
				<button
					class:active={flowsState.showSwitches}
					aria-pressed={flowsState.showSwitches}
					onclick={() => (flowsState.showSwitches = !flowsState.showSwitches)}
					title="Users who said they left one app for another, or came back"
				>
					<i class="sw solid"></i>Switches + returns
				</button>
				<button
					class:active={flowsState.showIntents}
					aria-pressed={flowsState.showIntents}
					onclick={() => (flowsState.showIntents = !flowsState.showIntents)}
					title="Users who said they are about to switch"
				>
					<i class="sw dashed"></i>Intents
				</button>
				<button
					class:active={flowsState.showPreferences}
					aria-pressed={flowsState.showPreferences}
					onclick={() => (flowsState.showPreferences = !flowsState.showPreferences)}
					title="Comparisons that favour one app, with no stated move"
				>
					<i class="sw faint"></i>Preferences
				</button>
			</div>
			<div class="seg" role="group" aria-label="Direction mode">
				<button
					class:active={flowsState.netMode}
					aria-pressed={flowsState.netMode}
					onclick={() => (flowsState.netMode = !flowsState.netMode)}
					title="One arrow per pair of apps, pointing in the net direction"
				>
					Net flow
				</button>
			</div>
		</div>
	</header>

	<!-- svelte-ignore a11y_click_events_have_key_events -->
	<!-- svelte-ignore a11y_no_static_element_interactions -->
	<div
		class="stage"
		bind:this={stage}
		bind:clientWidth={stageW}
		bind:clientHeight={stageH}
		onpointermove={onMove}
		onclick={onBackground}
	>
		<svg
			class="canvas"
			viewBox="{VB.x} {VB.y} {VB.w} {VB.h}"
			preserveAspectRatio="xMidYMid meet"
			role="img"
			aria-label="Directed flows between music apps for {periodLabel}"
		>
			<defs>
				<pattern id="flow-grid" width="34" height="34" patternUnits="userSpaceOnUse">
					<circle cx="1" cy="1" r="1" fill="#ffffff" opacity="0.05" />
				</pattern>
			</defs>
			<rect x={VB.x * 2} y={VB.y * 2} width={VB.w * 2} height={VB.h * 2} fill="url(#flow-grid)" style="pointer-events: none" />

			<!-- observed core -->
			<polygon
				class="core"
				points="{CORE.spotify.x},{CORE.spotify.y - 70} {CORE.soundcloud.x - 70},{CORE.soundcloud.y + 40} {CORE.audiomack.x + 70},{CORE.audiomack.y + 40}"
			/>

			<g class="arrows">
				{#each visibleArrows as a (a.key)}
					{@const g = geometry(a)}
					{@const colour = arrowColour(a)}
					{#if g}
						<g
							class="arrow"
							class:active={anyFocus && isActive(a)}
							style:opacity={arrowOpacity(a)}
							role="button"
							tabindex="0"
							aria-label="{name(a.s)} to {name(a.t)}, {layerLabel(a.layer)}, {a.value.toFixed(1)} per 10k reviews"
							onpointerenter={() => (flowsState.hoveredArrow = a.key)}
							onpointerleave={() => (flowsState.hoveredArrow = null)}
							onclick={(event) => {
								event.stopPropagation();
								select(a);
							}}
							onkeydown={(event) => {
								if (event.key === 'Enter' || event.key === ' ') {
									event.preventDefault();
									select(a);
								}
							}}
						>
							<path d={g.hit} class="hit" />
							<path
								d={g.path}
								fill="none"
								style:stroke={colour}
								style:stroke-width="{g.width}px"
								stroke-linecap="round"
								stroke-dasharray={a.layer === 'intent' ? `${Math.max(4, g.width * 1.4)} ${Math.max(4, g.width * 1.2)}` : undefined}
							/>
							<polygon points={g.head} style:fill={colour} />
						</g>
					{/if}
				{/each}
			</g>

			<g class="nodes">
				{#each flowNodes as node (node.id)}
					{@const p = positions.get(node.id)}
					{@const r = radii.get(node.id) ?? 10}
					{@const selected = selectedApp === node.id}
					{#if p}
						<g
							class="fnode"
							class:observed={node.observed}
							class:dim={nodeDim(node.id)}
							class:selected
							transform="translate({p.x},{p.y})"
							role="button"
							tabindex="0"
							aria-label="{node.name}{node.observed ? '' : ', only seen through other apps’ reviews'}"
							onpointerenter={() => (flowsState.hoveredNode = node.id)}
							onpointerleave={() => (flowsState.hoveredNode = null)}
							onclick={(event) => {
								event.stopPropagation();
								selectNode(node.id);
							}}
							onkeydown={(event) => {
								if (event.key === 'Enter' || event.key === ' ') {
									event.preventDefault();
									selectNode(node.id);
								}
							}}
						>
							{#if selected}
								<circle r={r + 7} class="ring" />
							{/if}
							<circle {r} class="disc" />
							<text class="name" y={node.observed ? 4 : r + 13} text-anchor="middle">{node.name}</text>
						</g>
					{/if}
				{/each}
			</g>
		</svg>

		{#if annotation}
			<div class="callout">
				<span class="label">{fmtMonth(annotation.month)} · {annotation.label}</span>
				<p>{annotation.detail}</p>
			</div>
		{/if}

		{#if flowsState.isPartial && monthInfo}
			<div class="partial-note">
				<span class="label">Partial month</span>
				<p>{monthInfo.note}. Flows seen in that app’s reviews are missing or noisy, so compare with care.</p>
			</div>
		{/if}

		{#if flowsState.layers.size === 0}
			<div class="empty">
				<p class="empty-title">No edge types selected</p>
				<p>Turn on switches, intents or preferences above.</p>
			</div>
		{:else if visibleArrows.length === 0}
			<div class="empty">
				<p class="empty-title">No flows in {periodLabel}</p>
				<p>Try another month or add intents and preferences.</p>
			</div>
		{/if}

		{#if hoveredArrow}
			<div class="tooltip" style:left="{tipX}px" style:top="{tipY}px">
				<div class="tt-head">
					<span class="tt-dot" style:background={arrowColour(hoveredArrow)}></span>
					<span class="tt-name">{name(hoveredArrow.s)} → {name(hoveredArrow.t)}</span>
				</div>
				<div class="tt-sub">{layerLabel(hoveredArrow.layer)} · {periodLabel}</div>
				<div class="tt-row">
					<span class="num">{hoveredArrow.value.toFixed(1)}</span>
					<span class="tt-muted">weight per 10k reviews · {fmtCount(hoveredArrow.count)} reviews</span>
				</div>
				{#if hoveredArrow.layer === 'net'}
					<div class="tt-row small">
						<span class="num">{hoveredArrow.forward?.toFixed(1)} → vs {hoveredArrow.backward?.toFixed(1)} ←</span>
					</div>
				{/if}
				{#if topReason(hoveredArrow.reasons)}
					<div class="tt-row small">top reason: {reasonLabel(topReason(hoveredArrow.reasons)!)}</div>
				{/if}
				<div class="tt-hint">click for reasons and quotes →</div>
			</div>
		{:else if hoveredNode}
			<div class="tooltip" style:left="{tipX}px" style:top="{tipY}px">
				<div class="tt-head">
					<span class="tt-dot" class:hollow={!hoveredNode.observed}></span>
					<span class="tt-name">{hoveredNode.name}</span>
				</div>
				{#if hoveredNode.observed}
					<div class="tt-sub">reviews in dataset</div>
					<div class="tt-row">
						<span class="num">{fmtCount(flowsState.period === 'all' ? (hoveredNode.totalVolume ?? 0) : volumeOf(hoveredNode.id, months))}</span>
						<span class="tt-muted">reviews · {periodLabel}</span>
					</div>
				{:else}
					<div class="tt-sub">only seen through other apps’ reviews</div>
					<div class="tt-row small">{fmtCount(hoveredNode.edgeCount)} labeled mentions, all months</div>
				{/if}
				<div class="tt-hint">click for who it wins and loses →</div>
			</div>
		{/if}

		<div class="legend">
			<div class="legend-row">
				<span class="shape solid"></span><span>reviewed app · size = reviews</span>
				<span class="shape hollow"></span><span>outside app</span>
			</div>
			<div class="legend-row">
				<span class="ln solid"></span><span>switch</span>
				<span class="ln dashed"></span><span>intent</span>
				<span class="ln faint"></span><span>preference</span>
				<span class="legend-dim">width = weight / 10k reviews</span>
			</div>
			<div class="legend-row wrap">
				<span class="legend-dim">colour = top reason</span>
				{#each legendReasons as reason (reason.id)}
					<span class="reason"><i style:background={reason.colour}></i>{reason.label}</span>
				{/each}
				<span class="reason"><i style:background={OTHER_COLOUR}></i>other</span>
			</div>
		</div>
	</div>

	<footer class="timeline">
		<div class="controls">
			<button
				class="btn is-sm play"
				onclick={() => flowsState.togglePlay()}
				aria-label={flowsState.playing ? 'Pause' : 'Play month by month'}
			>
				{#if flowsState.playing}
					<svg width="10" height="10" viewBox="0 0 10 10" aria-hidden="true"><path d="M2 1h2v8H2zM6 1h2v8H6z" fill="currentColor" /></svg>
				{:else}
					<svg width="10" height="10" viewBox="0 0 10 10" aria-hidden="true"><path d="M2 1l7 4-7 4z" fill="currentColor" /></svg>
				{/if}
				{flowsState.playing ? 'Pause' : 'Play'}
			</button>
			<button
				class="btn is-sm"
				class:is-active={flowsState.period === 'all'}
				onclick={() => {
					flowsState.stop();
					flowsState.setPeriod('all');
				}}
			>
				All months
			</button>
			<input
				class="slider"
				type="range"
				min="0"
				max={coverageMonths.length - 1}
				step="1"
				value={coverageIndex === -1 ? 0 : coverageIndex}
				class:off={coverageIndex === -1}
				oninput={onSlider}
				aria-label="Month within full-coverage period"
			/>
			<span class="current num">{flowsState.period === 'all' ? 'All months' : fmtMonth(flowsState.period)}</span>
		</div>

		<div class="strip" role="group" aria-label="Months">
			{#each flowMonths as m (m.month)}
				{@const ann = flowAnnotations.find((a) => a.month === m.month)}
				{@const activity = monthlyActivity[m.month] ?? 0}
				<button
					class="cell"
					class:partial={!m.full}
					class:selected={flowsState.period === m.month}
					class:in-period={flowsState.period === 'all'}
					onclick={() => pickMonth(m.month)}
					title="{fmtMonth(m.month)}{m.full ? '' : ` — partial: ${m.note}`} · {activity} switch/intent mentions"
				>
					{#if ann}
						<span class="ann">{ann.label}</span>
					{/if}
					<span class="bar" style:height="{4 + (activity / maxActivity) * 26}px"></span>
					<span class="mlabel">{m.month.endsWith('-01') || m.month === flowMonths[0].month ? fmtMonth(m.month, true) : fmtMonth(m.month).slice(0, 1)}</span>
				</button>
			{/each}
		</div>
		<div class="strip-note">
			<span><i class="key full"></i>full coverage {fmtMonth(coverageMonths[0], true)}–{fmtMonth(coverageMonths.at(-1)!, true)} (slider + play)</span>
			<span><i class="key partial"></i>{partialCount} partial months: Spotify reviews only run Aug ’24–Apr ’25; Audiomack starts Sep ’24</span>
			<span class="dimtext">bars = switch + intent mentions per month (raw count)</span>
		</div>
	</footer>
</section>

<style>
	.flows {
		flex: 1;
		min-width: 0;
		min-height: 0;
		display: flex;
		flex-direction: column;
	}

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
	.left {
		display: flex;
		align-items: baseline;
		gap: 10px;
		min-width: 0;
	}
	.stats {
		font-size: 9px;
		color: var(--dim);
		letter-spacing: 0.02em;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.right {
		margin-left: auto;
		display: flex;
		align-items: center;
		gap: 8px;
		flex: none;
	}
	.seg {
		display: flex;
		border: 1px solid var(--line);
		border-radius: 2px;
		overflow: hidden;
	}
	.seg button {
		display: flex;
		align-items: center;
		gap: 6px;
		height: 23px;
		padding: 0 9px;
		font-family: var(--mono);
		font-size: 8.5px;
		letter-spacing: 0.06em;
		text-transform: uppercase;
		color: var(--dim);
		border-right: 1px solid var(--line);
		transition:
			background var(--fast),
			color var(--fast);
	}
	.seg button:last-child {
		border-right: 0;
	}
	.seg button:hover {
		color: var(--text-2);
		background: var(--panel-2);
	}
	.seg button.active {
		background: var(--panel-3);
		color: var(--lime);
	}
	.sw {
		width: 12px;
		height: 0;
		border-top: 2px solid currentColor;
	}
	.sw.dashed {
		border-top-style: dashed;
	}
	.sw.faint {
		opacity: 0.4;
	}

	.stage {
		position: relative;
		flex: 1;
		min-height: 0;
		overflow: hidden;
		background:
			radial-gradient(900px 520px at 50% 45%, rgba(200, 255, 60, 0.028), transparent 65%),
			var(--bg);
	}
	.canvas {
		display: block;
		width: 100%;
		height: 100%;
		user-select: none;
	}

	.core {
		fill: color-mix(in srgb, var(--lime) 3%, transparent);
		stroke: color-mix(in srgb, var(--lime) 22%, transparent);
		stroke-width: 1;
		stroke-dasharray: 2 5;
		stroke-linejoin: round;
		pointer-events: none;
	}

	.arrow {
		cursor: pointer;
		outline: none;
		transition: opacity 220ms var(--ease);
	}
	.arrow path:not(.hit) {
		transition:
			stroke-width 600ms var(--ease),
			stroke 400ms var(--ease);
	}
	.arrow polygon {
		transition: fill 400ms var(--ease);
	}
	.arrow .hit {
		fill: none;
		stroke: transparent;
		stroke-width: 16px;
	}
	.arrow:focus-visible path:not(.hit) {
		stroke: var(--text) !important;
	}

	.fnode {
		cursor: pointer;
		outline: none;
		transition: opacity 200ms var(--ease);
	}
	.fnode .disc {
		fill: var(--bg);
		stroke: var(--muted);
		stroke-width: 1.3;
		stroke-dasharray: 3 2.5;
		transition: r 600ms var(--ease);
	}
	.fnode.observed .disc {
		fill: color-mix(in srgb, var(--lime) 22%, var(--panel-2));
		stroke: var(--lime);
		stroke-width: 1.6;
		stroke-dasharray: none;
	}
	.fnode:hover .disc,
	.fnode:focus-visible .disc {
		stroke: var(--text);
	}
	.fnode .ring {
		fill: none;
		stroke: var(--text);
		stroke-width: 1;
		stroke-dasharray: 3 3;
	}
	.fnode.dim {
		opacity: 0.25;
	}
	.name {
		font-family: var(--mono);
		font-size: 10px;
		fill: var(--text-2);
		pointer-events: none;
		paint-order: stroke;
		stroke: var(--bg);
		stroke-width: 3.5px;
		stroke-linejoin: round;
	}
	.fnode.observed .name {
		font-size: 11px;
		font-weight: 600;
		fill: var(--text);
		stroke: color-mix(in srgb, var(--lime) 22%, var(--panel-2));
	}

	.callout,
	.partial-note {
		position: absolute;
		left: 14px;
		top: 12px;
		max-width: 330px;
		padding: 9px 11px;
		background: color-mix(in srgb, var(--panel) 90%, transparent);
		border: 1px solid var(--line-strong);
		border-left: 2px solid var(--lime);
		border-radius: 2px;
		backdrop-filter: blur(6px);
		pointer-events: none;
	}
	.callout .label {
		color: var(--lime);
	}
	.partial-note {
		left: auto;
		right: 14px;
		border-left-color: var(--amber);
	}
	.partial-note .label {
		color: var(--amber);
	}
	.callout p,
	.partial-note p {
		margin: 4px 0 0;
		font-size: 11.5px;
		line-height: 1.45;
		color: var(--text-2);
	}

	.tooltip {
		position: absolute;
		width: 252px;
		padding: 10px 11px;
		background: color-mix(in srgb, var(--panel) 92%, black);
		border: 1px solid var(--line-bright);
		border-radius: 2px;
		box-shadow: 0 18px 50px rgba(0, 0, 0, 0.6);
		pointer-events: none;
		z-index: 10;
		backdrop-filter: blur(8px);
	}
	.tt-head {
		display: flex;
		align-items: center;
		gap: 6px;
	}
	.tt-dot {
		width: 7px;
		height: 7px;
		border-radius: 50%;
		background: var(--lime);
		flex: none;
	}
	.tt-dot.hollow {
		background: transparent;
		border: 1px dashed var(--muted);
	}
	.tt-name {
		font-size: 12px;
		font-weight: 600;
		flex: 1;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.tt-sub {
		margin-top: 2px;
		font-family: var(--mono);
		font-size: 9px;
		color: var(--dim);
	}
	.tt-row {
		display: flex;
		align-items: baseline;
		gap: 7px;
		margin-top: 7px;
		font-size: 12px;
		color: var(--text-2);
	}
	.tt-row.small {
		margin-top: 4px;
		font-family: var(--mono);
		font-size: 9px;
		color: var(--muted);
	}
	.tt-muted {
		font-family: var(--mono);
		font-size: 9px;
		color: var(--dim);
	}
	.tt-hint {
		margin-top: 8px;
		padding-top: 7px;
		border-top: 1px solid var(--line);
		font-family: var(--mono);
		font-size: 8.5px;
		letter-spacing: 0.06em;
		color: var(--lime);
		text-transform: uppercase;
	}

	.legend {
		position: absolute;
		left: 14px;
		bottom: 12px;
		max-width: min(560px, calc(100% - 28px));
		padding: 8px 10px;
		background: color-mix(in srgb, var(--bg) 78%, transparent);
		border: 1px solid var(--line);
		border-radius: 2px;
		backdrop-filter: blur(6px);
		font-family: var(--mono);
		font-size: 8.5px;
		color: var(--muted);
		display: flex;
		flex-direction: column;
		gap: 5px;
		pointer-events: none;
	}
	.legend-row {
		display: flex;
		align-items: center;
		gap: 5px;
	}
	.legend-row.wrap {
		flex-wrap: wrap;
		row-gap: 3px;
	}
	.legend-row > span:not(.shape):not(.ln) {
		margin-right: 6px;
	}
	.legend-dim {
		color: var(--dim);
	}
	.shape {
		width: 9px;
		height: 9px;
		border-radius: 50%;
		flex: none;
	}
	.shape.solid {
		background: color-mix(in srgb, var(--lime) 30%, transparent);
		border: 1px solid var(--lime);
	}
	.shape.hollow {
		border: 1px dashed var(--muted);
	}
	.ln {
		width: 14px;
		height: 0;
		border-top: 2px solid var(--text-2);
		flex: none;
	}
	.ln.dashed {
		border-top-style: dashed;
	}
	.ln.faint {
		opacity: 0.35;
	}
	.reason {
		display: inline-flex;
		align-items: center;
		gap: 4px;
	}
	.reason i {
		width: 8px;
		height: 3px;
		border-radius: 1px;
	}

	.empty {
		position: absolute;
		inset: 0;
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		gap: 4px;
		text-align: center;
		pointer-events: none;
	}
	.empty p {
		margin: 0;
		font-size: 12px;
		color: var(--dim);
	}
	.empty .empty-title {
		font-family: var(--mono);
		font-size: 11px;
		letter-spacing: 0.1em;
		text-transform: uppercase;
		color: var(--muted);
	}

	/* ---------- timeline ---------- */

	.timeline {
		flex: none;
		border-top: 1px solid var(--line);
		background: var(--panel);
		padding: 8px 14px 8px;
	}
	.controls {
		display: flex;
		align-items: center;
		gap: 8px;
	}
	.play {
		min-width: 66px;
	}
	.slider {
		flex: 1;
		max-width: 260px;
		accent-color: var(--lime);
	}
	.slider.off {
		opacity: 0.45;
	}
	.current {
		font-size: 11px;
		color: var(--text);
		min-width: 90px;
	}

	.strip {
		display: grid;
		grid-auto-flow: column;
		grid-auto-columns: minmax(0, 1fr);
		gap: 2px;
		margin-top: 8px;
		padding-top: 16px;
	}
	.cell {
		position: relative;
		height: 46px;
		display: flex;
		flex-direction: column;
		justify-content: flex-end;
		align-items: center;
		gap: 3px;
		border-bottom: 2px solid var(--lime-dim);
		transition: background var(--fast);
	}
	.cell:hover {
		background: var(--panel-2);
	}
	.cell .bar {
		width: 60%;
		max-width: 16px;
		background: color-mix(in srgb, var(--lime) 55%, transparent);
		border-radius: 1px 1px 0 0;
		transition: background var(--fast);
	}
	.cell .mlabel {
		font-family: var(--mono);
		font-size: 8px;
		color: var(--dim);
		white-space: nowrap;
	}
	.cell.partial {
		border-bottom-color: var(--line-strong);
	}
	.cell.partial .bar {
		background: repeating-linear-gradient(
			135deg,
			var(--faint) 0 2px,
			transparent 2px 4px
		);
		outline: 1px solid var(--faint);
	}
	.cell.partial .mlabel {
		color: var(--faint);
	}
	.cell.selected {
		background: var(--panel-3);
		box-shadow: inset 0 0 0 1px var(--line-bright);
	}
	.cell.selected .bar {
		background: var(--lime);
	}
	.cell.selected .mlabel {
		color: var(--text);
	}
	.cell.partial.selected .bar {
		background: var(--amber);
		outline-color: var(--amber);
	}
	.ann {
		position: absolute;
		top: -15px;
		left: 50%;
		font-family: var(--mono);
		font-size: 8px;
		letter-spacing: 0.04em;
		color: var(--lime);
		white-space: nowrap;
		padding-left: 6px;
		border-left: 1px solid var(--lime);
	}
	.strip-note {
		display: flex;
		flex-wrap: wrap;
		gap: 4px 14px;
		margin-top: 6px;
		font-family: var(--mono);
		font-size: 8.5px;
		color: var(--muted);
	}
	.key {
		display: inline-block;
		width: 10px;
		height: 0;
		border-top: 2px solid var(--lime-dim);
		margin-right: 5px;
		vertical-align: middle;
	}
	.key.partial {
		border-color: var(--line-strong);
	}
	.dimtext {
		color: var(--dim);
	}

	@media (max-width: 1180px) {
		.stats {
			display: none;
		}
	}
	@media (max-width: 860px) {
		.seg button {
			padding: 0 6px;
			font-size: 8px;
		}
		.sw {
			display: none;
		}
		.legend {
			display: none;
		}
		.mlabel {
			display: none;
		}
	}
</style>
