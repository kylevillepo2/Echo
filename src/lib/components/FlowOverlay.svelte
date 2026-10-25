<script lang="ts">
	import { flowsState, type FlowArrow } from '#lib/state/flows.svelte';
	import { studio } from '#lib/state/studio.svelte';
	import { flowNode, reasonColour, reasonLabel, topReason } from '#lib/data/flows';
	import type { SimNode } from '#lib/utils/force';

	let { nodes, cluster, scale }: {
		nodes: SimNode[];
		cluster: { x: number; y: number; radius: number; id: string };
		scale: number;
	} = $props();

	const members = $derived(nodes.filter((node) => node.clusterId === cluster.id));
	const memberIds = $derived(new Set(members.map((node) => node.id)));
	// Every outside app linked to the cluster, strongest first. Positions are assigned to all of them
	// up front, so showing more apps or selecting one never moves an app that is already drawn.
	const ranked = $derived(flowsState.competitorRanking
		.filter((rank) => !memberIds.has(rank.id))
		.map((rank) => ({ rank, node: flowNode(rank.id) }))
		.filter((entry): entry is { rank: typeof entry.rank; node: NonNullable<typeof entry.node> } => Boolean(entry.node)));
	const GOLDEN_ANGLE = Math.PI * (3 - Math.sqrt(5));
	const positions = $derived.by(() => {
		const map = new Map(members.map((node) => [node.id, { x: node.x, y: node.y, radius: node.radius + 5 }]));
		const maxSwitches = Math.max(...ranked.map((entry) => entry.rank.switches), 1);
		ranked.forEach(({ rank }, index) => {
			// Golden-angle spiral by rank: the top 6 spread around the cluster; weaker apps fill the gaps
			// on wider rings.
			const angle = -Math.PI / 2 + index * GOLDEN_ANGLE;
			const ring = index < 6 ? 1.45 : index < 18 ? 1.72 : 1.98;
			map.set(rank.id, {
				x: cluster.x + Math.cos(angle) * cluster.radius * ring,
				y: cluster.y + Math.sin(angle) * cluster.radius * ring,
				radius: 5 + Math.sqrt(rank.switches / maxSwitches) * 5
			});
		});
		return map;
	});
	// Draw a route only when it touches the cluster and both ends are visible.
	const arrows = $derived(flowsState.drawnArrows
		.filter((arrow) => (memberIds.has(arrow.s) || memberIds.has(arrow.t)) && positions.has(arrow.s) && positions.has(arrow.t))
		.sort((a, b) => a.value - b.value));
	const connectedIds = $derived(new Set(arrows.flatMap((arrow) => [arrow.s, arrow.t])));
	// Only ranked competitors that the current view shows (top 6, all, or the selection's own).
	const visibleOutside = $derived(ranked.map((entry) => entry.node).filter((node) => flowsState.visibleOutsideIds.has(node.id)));
	const hasFocus = $derived(Boolean(flowsState.hoveredArrow || flowsState.hoveredNode || flowsState.selection));
	const scaleMax = $derived(flowsState.scaleMax);

	function geometry(arrow: FlowArrow) {
		const source = positions.get(arrow.s)!;
		const target = positions.get(arrow.t)!;
		const dx = target.x - source.x;
		const dy = target.y - source.y;
		// Separate opposite directions and parallel layers into gentle, distinct lanes.
		const curve = arrow.layer === 'preference' ? 0.24 : arrow.layer === 'intent' ? 0.18 : 0.12;
		const controlAt = (bend: number) => ({ x: (source.x + target.x) / 2 - dy * bend, y: (source.y + target.y) / 2 + dx * bend });
		// Prefer the shallowest lane that does not run through another app node.
		const obstacles = members.filter((node) => node.id !== arrow.s && node.id !== arrow.t);
		let control = controlAt(curve);
		let bestScore = Infinity;
		for (const offset of [0, 0.16, 0.32, 0.48]) {
			const candidate = controlAt(curve + offset);
			let score = offset;
			for (let step = 1; step < 20; step++) {
				const t = step / 20;
				const x = (1 - t) ** 2 * source.x + 2 * (1 - t) * t * candidate.x + t ** 2 * target.x;
				const y = (1 - t) ** 2 * source.y + 2 * (1 - t) * t * candidate.y + t ** 2 * target.y;
				for (const obstacle of obstacles) {
					const clearance = obstacle.radius + 9 / scale;
					score += Math.max(0, clearance - Math.hypot(x - obstacle.x, y - obstacle.y)) ** 2;
				}
			}
			if (score < bestScore) {
				bestScore = score;
				control = candidate;
			}
		}
		const startDistance = Math.hypot(control.x - source.x, control.y - source.y) || 1;
		const endDistance = Math.hypot(target.x - control.x, target.y - control.y) || 1;
		const ux = (target.x - control.x) / endDistance;
		const uy = (target.y - control.y) / endDistance;
		const width = (0.7 + Math.sqrt(arrow.value / scaleMax) * 2.1) / scale;
		const headLength = (4.5 + Math.sqrt(arrow.value / scaleMax) * 1.5) / scale;
		const headWidth = (1.8 + Math.sqrt(arrow.value / scaleMax) * 0.7) / scale;
		const start = { x: source.x + (control.x - source.x) / startDistance * source.radius, y: source.y + (control.y - source.y) / startDistance * source.radius };
		const tip = { x: target.x - ux * target.radius, y: target.y - uy * target.radius };
		const base = { x: tip.x - ux * headLength, y: tip.y - uy * headLength };
		return {
			path: `M${start.x},${start.y} Q${control.x},${control.y} ${base.x},${base.y}`,
			head: `${tip.x},${tip.y} ${base.x - uy * headWidth},${base.y + ux * headWidth} ${base.x + uy * headWidth},${base.y - ux * headWidth}`,
			mid: { x: 0.25 * start.x + 0.5 * control.x + 0.25 * base.x, y: 0.25 * start.y + 0.5 * control.y + 0.25 * base.y },
			width
		};
	}

	function active(arrow: FlowArrow) {
		if (flowsState.hoveredArrow) return flowsState.hoveredArrow === arrow.key;
		const selection = flowsState.selection;
		const appId = flowsState.hoveredNode ?? (selection?.type === 'app' ? selection.id : null);
		if (appId) return arrow.s === appId || arrow.t === appId;
		if (selection?.type === 'edge') return (arrow.s === selection.s && arrow.t === selection.t) ||
			(flowsState.netMode && arrow.s === selection.t && arrow.t === selection.s);
		return true;
	}

	function opacity(arrow: FlowArrow) {
		if (hasFocus) return active(arrow) ? 1 : 0.08;
		return arrow.layer === 'preference' ? 0.65 : 0.95;
	}

	function colour(arrow: FlowArrow) {
		return reasonColour(topReason(arrow.reasons));
	}

	function select(arrow: FlowArrow) {
		studio.clearSelection();
		flowsState.selectEdge(arrow.s, arrow.t);
		studio.inspectorOpen = true;
	}

	function selectApp(id: string) {
		studio.selectFlowApp(id);
	}
</script>

<g class="flow-overlay">
	<g class="arrows">
		{#each arrows as arrow (arrow.key)}
			{@const shape = geometry(arrow)}
			{@const stroke = colour(arrow)}
			<g
				class="flow-arrow"
				class:highlighted={hasFocus && active(arrow)}
				style:opacity={opacity(arrow)}
				role="button"
				tabindex="0"
				aria-label="{flowNode(arrow.s)?.name} to {flowNode(arrow.t)?.name}, {arrow.value.toFixed(1)} per 10k reviews"
				onpointerenter={() => (flowsState.hoveredArrow = arrow.key)}
				onpointerleave={() => (flowsState.hoveredArrow = null)}
				onfocus={() => (flowsState.hoveredArrow = arrow.key)}
				onblur={() => (flowsState.hoveredArrow = null)}
				onclick={(event) => { event.stopPropagation(); select(arrow); }}
				onkeydown={(event) => {
					if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); select(arrow); }
				}}
			>
				<title>{flowNode(arrow.s)?.name} → {flowNode(arrow.t)?.name} · {arrow.value.toFixed(1)} per 10k · {arrow.count} reviews · {reasonLabel(topReason(arrow.reasons) ?? 'other')}</title>
				<path class="hit" d={shape.path} fill="none" stroke="transparent" stroke-width={12 / scale} />
				<path class="route" d={shape.path} fill="none" stroke={stroke} stroke-width={shape.width} stroke-linecap="round" stroke-dasharray={arrow.layer === 'intent' ? `${4 / scale} ${5 / scale}` : undefined} />
				<polygon points={shape.head} fill={stroke} />
				{#if flowsState.hoveredArrow === arrow.key}
					<g class="route-caption" transform="translate({shape.mid.x},{shape.mid.y}) scale({1 / scale})">
						<rect x="-30" y="-9" width="60" height="18" rx="3" />
						<text text-anchor="middle" dy="3" font-size="8">{arrow.value.toFixed(1)} / 10k</text>
					</g>
				{/if}
			</g>
		{/each}
	</g>
	{#each visibleOutside as node (node.id)}
		{@const position = positions.get(node.id)!}
		<g
			class="outside-node"
			class:quiet={!connectedIds.has(node.id)}
			class:selected={flowsState.selection?.type === 'app' && flowsState.selection.id === node.id}
			transform="translate({position.x},{position.y})"
			role="button"
			tabindex="0"
			aria-label="{node.name}, {node.observed ? 'reviewed app in another cluster' : 'outside app, only seen in other apps’ reviews'}"
			onpointerenter={() => (flowsState.hoveredNode = node.id)}
			onpointerleave={() => (flowsState.hoveredNode = null)}
			onclick={(event) => { event.stopPropagation(); selectApp(node.id); }}
			onkeydown={(event) => {
				if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); selectApp(node.id); }
			}}
		>
			<circle r={position.radius} fill="var(--bg)" stroke="var(--muted)" stroke-width="1" stroke-dasharray={node.observed ? undefined : '3 2'} vector-effect="non-scaling-stroke" />
			<text class:quiet={!connectedIds.has(node.id)} y={position.radius + 11 / scale} text-anchor="middle" font-size={9 / scale}>{node.name}</text>
		</g>
	{/each}
</g>

<style>
	.flow-overlay { animation: reveal 450ms ease-out both; }
	.flow-arrow, .outside-node { cursor: pointer; outline: none; transition: opacity 180ms; }
	.flow-arrow:focus-visible .route { stroke: var(--text); }
	.route, polygon { pointer-events: none; }
	.route, polygon { transition: stroke 180ms, fill 180ms; }
	.outside-node.quiet { opacity: 0.35; }
	.outside-node.quiet:hover, .outside-node:focus-visible { opacity: 1; }
	text.quiet { opacity: 0; }
	.outside-node:hover text, .outside-node:focus-visible text { opacity: 1; }
	.route-caption { pointer-events: none; }
	.route-caption rect { fill: var(--panel); stroke: var(--line-strong); stroke-width: 1; }
	.outside-node:hover circle, .outside-node:focus-visible circle, .outside-node.selected circle { stroke: var(--lime); }
	text { fill: var(--text-2); font-family: var(--mono); paint-order: stroke; stroke: var(--bg); stroke-width: 3px; stroke-linejoin: round; pointer-events: none; }
	@keyframes reveal { from { opacity: 0; } to { opacity: 1; } }
	@media (prefers-reduced-motion: reduce) { .flow-overlay { animation: none; } }
</style>
