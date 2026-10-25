<script lang="ts">
	import { onMount, untrack } from 'svelte';
	import { cubicInOut } from 'svelte/easing';
	import { studio } from '#lib/state/studio.svelte';
	import { flowsState } from '#lib/state/flows.svelte';
	import { flows, overviewConnections } from '#lib/data/flows';
	import FlowOverlay from './FlowOverlay.svelte';
	import AppLogo from './AppLogo.svelte';
	import { Simulation, boundsOf, type SimLink, type SimNode } from '#lib/utils/force';
	import { platformColor, receptionColor } from '#lib/utils/palette';
	import { fmtCount } from '#lib/utils/format';
	import { layoutNodeLabels } from '#lib/utils/labels';

	let stage: HTMLDivElement;
	let width = $state(0);
	let height = $state(0);

	let nodes = $state.raw<SimNode[]>([]);
	let links = $state.raw<SimLink[]>([]);
	let tick = $state(0);

	let scale = $state(1);
	let camX = $state(0);
	let camY = $state(0);

	let hovered = $state<string | null>(null);
	let hoveredCluster = $state<string | null>(null);
	let pointer = $state({ x: 0, y: 0 });

	let dragging: { id: string; sx: number; sy: number; moved: boolean } | null = null;
	let panning: { sx: number; sy: number; camX: number; camY: number } | null = null;

	let simulation: Simulation | null = null;
	let frame = 0;
	let needsFit = true;
	let lastLayoutKey = '';
	let zoomFrame = 0;
	let zooming = $state(false);
	let hasClusterZoom = false;

	const appMap = $derived(new Map(studio.mapApps.map((a) => [a.id, a])));
	const allApps = $derived(new Map(studio.apps.map((a) => [a.id, a])));
	const categoryMap = $derived(new Map(studio.categories.map((c) => [c.id, c])));
	const mapCategories = $derived(studio.categories.filter((c) => studio.mapApps.some((app) => app.categoryId === c.id)));
	const hasFlowData = $derived(studio.categoryApps.some((app) => flows.meta.observed.includes(app.id)));
	const hasExportedInsights = $derived(studio.categoryApps.some((app) => Boolean(app.insightsId)));

	const appNodes = $derived.by(() => {
		tick;
		return nodes.filter((n) => n.kind === 'app').map((node) => ({ ...node }));
	});
	const viewLinks = $derived.by(() => {
		tick;
		return links.map((link) => ({ ...link, source: { ...link.source }, target: { ...link.target } }));
	});
	const isFocused = $derived(Boolean(studio.categoryFilter));
	const homeConnections = $derived(overviewConnections(new Set(studio.mapApps.map((app) => app.id))));
	const homeMax = $derived(Math.max(...homeConnections.map((pair) => pair.count), 1));
	const nodePositions = $derived(new Map(appNodes.map((node) => [node.id, node])));
	const connectedFlowIds = $derived(new Set(
		(isFocused && hasFlowData ? flowsState.drawnArrows : []).flatMap((arrow) => [arrow.s, arrow.t])
	));
	const activeClusterId = $derived(studio.zoomingCategory ?? studio.categoryFilter);

	const signature = $derived(
		`${studio.graph?.meta.generatedAt ?? ''}|${studio.metric}|${studio.mapApps.map((app) => `${app.id}:${studio.metricValue(app)}`).join(',')}`
	);

	const focusId = $derived(hovered ?? studio.selected?.id ?? null);
	const focusSet = $derived.by(() => {
		const set = new Set<string>();
		if (!focusId) return set;
		set.add(focusId);
		for (const link of isFocused ? flowsState.drawnArrows : homeConnections) {
			if (link.s === focusId) set.add(link.t);
			if (link.t === focusId) set.add(link.s);
		}
		return set;
	});

	const hoveredApp = $derived(hovered ? appMap.get(hovered) ?? allApps.get(hovered) : undefined);
	const hoveredCategory = $derived(
		hoveredCluster ? categoryMap.get(hoveredCluster) : undefined
	);

	const tipX = $derived(
		pointer.x > width - 264 ? Math.max(8, pointer.x - 250) : pointer.x + 16
	);
	const tipY = $derived(
		pointer.y > height - 150 ? Math.max(8, pointer.y - 136) : pointer.y + 16
	);

	const showLabels = $derived(isFocused || (!activeClusterId && scale > 1.02));
	const appLabels = $derived(isFocused
		? layoutNodeLabels(
			appNodes.filter((node) => nodeVisible(node)),
			(node) => shortName(appMap.get(node.id)?.name ?? allApps.get(node.id)?.name ?? node.id),
			10 / scale,
			6 / scale
		)
		: null);

	interface ClusterView {
		id: string;
		name: string;
		reception: number;
		x: number;
		y: number;
		radius: number;
		count: number;
	}

	/** Hulls wrap the settled node positions without changing the overview layout. */
	const clusters = $derived.by(() => {
		tick;
		const out: ClusterView[] = [];
		for (const category of mapCategories) {
			const members = nodes.filter((n) => n.clusterId === category.id);
			if (!members.length) continue;
			const x = members.reduce((sum, n) => sum + n.x, 0) / members.length;
			const y = members.reduce((sum, n) => sum + n.y, 0) / members.length;
			let radius = 0;
			for (const n of members) {
				radius = Math.max(radius, Math.hypot(n.x - x, n.y - y) + n.radius + 26);
			}
			out.push({
				id: category.id,
				name: category.name,
				reception: category.reception,
				x,
				y,
				radius: radius + 4,
				count: members.length
			});
		}
		return out;
	});

	/* ---------------------------- layout ---------------------------- */

	$effect(() => {
		signature;
		untrack(rebuild);
	});

	$effect(() => {
		if (needsFit && width > 0 && height > 0 && nodes.length > 0) {
			fitView();
			needsFit = false;
		}
	});

	onMount(() => () => {
		cancelAnimationFrame(frame);
		cancelAnimationFrame(zoomFrame);
	});

	$effect(() => {
		const id = studio.zoomingCategory;
		if (!id) return;
		untrack(() => zoomToCluster(id));
		return () => {
			cancelAnimationFrame(zoomFrame);
			zooming = false;
		};
	});

	$effect(() => {
		const focused = studio.categoryFilter || studio.zoomingCategory;
		if (!focused) untrack(() => {
			if (!hasClusterZoom) return;
			hasClusterZoom = false;
			const main = stage.closest('main');
			const toolbar = stage.closest('.network')?.querySelector<HTMLElement>(':scope > .toolbar');
			// Fit the final overview viewport, not the still-collapsing flow timeline.
			animateCamera(overviewTarget(
				main?.clientWidth ?? width,
				main ? main.clientHeight - (toolbar?.getBoundingClientRect().height ?? 42) : height
			));
		});
	});

	function zoomToCluster(id: string) {
		const cluster = clusters.find((c) => c.id === id);
		if (!cluster) {
			studio.finishClusterZoom(id);
			return;
		}
		hasClusterZoom = true;
		const hasData = studio.appsForCategory(id).some((app) => flows.meta.observed.includes(app.id));
		const availableHeight = Math.max(180, height - (hasData && !studio.categoryFilter ? 145 : 0));
		const targetScale = Math.min(width, availableHeight) / (cluster.radius * (hasData ? 3.6 : 2.3));
		animateCamera({ x: cluster.x, y: cluster.y, scale: targetScale }, () => studio.finishClusterZoom(id));
	}

	function animateCamera(target: { x: number; y: number; scale: number }, done?: () => void) {
		cancelAnimationFrame(zoomFrame);
		cancelAnimationFrame(frame);
		hovered = null;
		hoveredCluster = null;
		dragging = null;
		panning = null;
		zooming = true;
		const start = { x: camX, y: camY, scale };
		if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
			camX = target.x;
			camY = target.y;
			scale = target.scale;
			zooming = false;
			done?.();
			return;
		}
		const started = performance.now();
		const animate = (now: number) => {
			const progress = Math.min(1, (now - started) / 650);
			const eased = cubicInOut(progress);
			camX = start.x + (target.x - start.x) * eased;
			camY = start.y + (target.y - start.y) * eased;
			scale = start.scale * Math.pow(target.scale / start.scale, eased);
			if (progress < 1) zoomFrame = requestAnimationFrame(animate);
			else {
				camX = target.x;
				camY = target.y;
				scale = target.scale;
				zooming = false;
				done?.();
			}
		};
		zoomFrame = requestAnimationFrame(animate);
	}

	function desiredHullRadius(count: number, focused: boolean): number {
		return focused ? 100 + Math.sqrt(count) * 58 : 44 + Math.sqrt(count) * 22;
	}

	function buildAnchors(categories: typeof studio.categories, focused: boolean) {
		const anchors = new Map<string, { x: number; y: number }>();
		if (focused || categories.length <= 1) {
			for (const category of categories) anchors.set(category.id, { x: 0, y: 0 });
			return anchors;
		}

		// Start on a loose ring, then let the anchors repel each other until
		// every cluster has room for its hull and label. Deterministic, fast.
		const points = categories.map((category, index) => {
			const angle = (index / categories.length) * Math.PI * 2 - Math.PI / 2;
			const radius = 330;
			return {
				id: category.id,
				x: Math.cos(angle) * radius,
				y: Math.sin(angle) * radius,
				r: desiredHullRadius(category.appIds.length, false)
			};
		});

		const gap = 36;
		for (let iteration = 0; iteration < 600; iteration++) {
			for (let i = 0; i < points.length; i++) {
				for (let j = i + 1; j < points.length; j++) {
					const a = points[i];
					const b = points[j];
					let dx = b.x - a.x;
					let dy = b.y - a.y;
					const dist = Math.hypot(dx, dy) || 0.01;
					const need = a.r + b.r + gap;
					if (dist >= need) continue;
					const push = (need - dist) * 0.5;
					dx /= dist;
					dy /= dist;
					a.x -= dx * push;
					a.y -= dy * push;
					b.x += dx * push;
					b.y += dy * push;
				}
			}
			for (const point of points) {
				point.x *= 0.999;
				point.y *= 0.999;
			}
		}

		for (const point of points) {
			anchors.set(point.id, { x: point.x, y: point.y });
		}
		return anchors;
	}

	function compactClusters(anchors: Map<string, { x: number; y: number }>, focused: boolean) {
		const byCluster = new Map<string, SimNode[]>();
		for (const node of nodes) {
			if (!node.clusterId) continue;
			const list = byCluster.get(node.clusterId) ?? [];
			list.push(node);
			byCluster.set(node.clusterId, list);
		}

		for (const [id, members] of byCluster) {
			const anchor = anchors.get(id);
			if (!anchor) continue;

			// Keep the rendered centroid on the packed anchor so cross-cluster
			// springs cannot drag neighbouring hulls into each other.
			const cx = members.reduce((sum, node) => sum + node.x, 0) / members.length;
			const cy = members.reduce((sum, node) => sum + node.y, 0) / members.length;
			for (const node of members) {
				node.x += anchor.x - cx;
				node.y += anchor.y - cy;
			}

			const target = desiredHullRadius(members.length, focused) - 24;
			let maxRadius = 0;
			for (const node of members) {
				maxRadius = Math.max(
					maxRadius,
					Math.hypot(node.x - anchor.x, node.y - anchor.y) + node.radius
				);
			}
			if (maxRadius <= target) continue;
			const scaleDown = target / maxRadius;
			for (const node of members) {
				node.x = anchor.x + (node.x - anchor.x) * scaleDown;
				node.y = anchor.y + (node.y - anchor.y) * scaleDown;
				node.vx = 0;
				node.vy = 0;
			}
		}
	}

	function rebuild() {
		const apps = studio.mapApps;
		const categories = mapCategories;
		const ids = new Set(apps.map((app) => app.id));
		const edges = (studio.graph?.edges ?? []).filter((edge) => ids.has(edge.source) && ids.has(edge.target));

		const previous = new Map(nodes.map((n) => [n.id, { x: n.x, y: n.y }]));
		const maxMetric = Math.max(...apps.map((a) => studio.metricValue(a)), 1);
		const focused = categories.length === 1;
		const layoutKey = focused ? `focus:${studio.categoryFilter}` : 'overview';
		const reuse = lastLayoutKey === layoutKey;
		lastLayoutKey = layoutKey;
		const anchors = buildAnchors(categories, focused);

		const next: SimNode[] = [];

		for (const category of categories) {
			const anchor = anchors.get(category.id) ?? { x: 0, y: 0 };
			const members = apps.filter((a) => a.categoryId === category.id);
			const count = members.length;
			const spread = desiredHullRadius(count, focused) * (focused ? 1.05 : 0.78);

			members.forEach((app, index) => {
				const prior = previous.get(app.id);
				const angle = index * 2.399963 + category.id.length;
				const radius = spread * Math.sqrt((index + 0.4) / Math.max(1, count));
				next.push({
					id: app.id,
					kind: 'app',
					clusterId: category.id,
					x: (reuse ? prior?.x : undefined) ?? anchor.x + Math.cos(angle) * radius,
					y: (reuse ? prior?.y : undefined) ?? anchor.y + Math.sin(angle) * radius,
					vx: 0,
					vy: 0,
					radius: (7 + Math.sqrt(studio.metricValue(app) / maxMetric) * 16) * (focused ? 1 : 0.95),
					charge: 1
				});
			});
		}

		nodes = next;

		const byId = new Map(nodes.map((n) => [n.id, n]));
		const nextLinks: SimLink[] = [];

		for (const edge of edges) {
			const source = byId.get(edge.source);
			const target = byId.get(edge.target);
			if (!source || !target) continue;
			const sameCluster = source.clusterId === target.clusterId;
			nextLinks.push({
				source,
				target,
				distance: sameCluster
					? (focused ? 190 : 86) + (1 - edge.score) * (focused ? 120 : 80)
					: 250 + (1 - edge.score) * 120,
				strength: sameCluster
					? (focused ? 0.004 : 0.012) + edge.score * (focused ? 0.006 : 0.018)
					: 0.003 + edge.score * 0.004,
				kind: 'similar',
				score: edge.score
			});
		}

		links = nextLinks;
		simulation = new Simulation(nodes, links, {
			repulsion: focused ? 26000 : 12000,
			centerStrength: focused ? 0.00002 : 0.00018,
			damping: 0.85,
			clusterCenters: anchors,
			clusterStrength: focused ? 0.0002 : 0.004,
			collisionPadding: focused ? 52 : 18
		});
		simulation.settle(240);
		compactClusters(anchors, focused);
		tick += 1;
		startLoop();

		needsFit = true;
		if (width > 0) {
			fitView();
			needsFit = false;
		}
	}

	function startLoop() {
		cancelAnimationFrame(frame);
		const advance = () => {
			if (simulation?.step()) {
				tick += 1;
				frame = requestAnimationFrame(advance);
			}
		};
		frame = requestAnimationFrame(advance);
	}

	/* ---------------------------- camera ---------------------------- */

	function fitView() {
		if (!nodes.length || !width || !height) return;
		const focusedCluster = clusters.find((cluster) => cluster.id === studio.categoryFilter);
		if (focusedCluster) {
			animateCamera({ x: focusedCluster.x, y: focusedCluster.y, scale: Math.min(width, height) / (focusedCluster.radius * (hasFlowData ? 3.6 : 2.3)) });
			return;
		}
		const target = overviewTarget(width, height);
		scale = target.scale;
		camX = target.x;
		camY = target.y;
	}

	function overviewTarget(viewWidth: number, viewHeight: number) {
		const bounds = boundsOf(nodes);
		const spanX = Math.max(180, bounds.maxX - bounds.minX + 110);
		const spanY = Math.max(180, bounds.maxY - bounds.minY + 110);
		return {
			x: (bounds.minX + bounds.maxX) / 2,
			y: (bounds.minY + bounds.maxY) / 2,
			scale: Math.max(0.22, Math.min(viewWidth / spanX, viewHeight / spanY, 1.15))
		};
	}

	function zoomAt(factor: number, sx = width / 2, sy = height / 2) {
		const nextScale = Math.min(2.8, Math.max(0.2, scale * factor));
		const wx = camX + (sx - width / 2) / scale;
		const wy = camY + (sy - height / 2) / scale;
		camX = wx - (sx - width / 2) / nextScale;
		camY = wy - (sy - height / 2) / nextScale;
		scale = nextScale;
	}

	function onWheel(event: WheelEvent) {
		event.preventDefault();
		const rect = (event.currentTarget as SVGSVGElement).getBoundingClientRect();
		zoomAt(Math.exp(-event.deltaY * 0.0016), event.clientX - rect.left, event.clientY - rect.top);
	}

	function onBackgroundDown(event: PointerEvent) {
		if (event.button !== 0) return;
		const target = event.target as Element;
		if (target.closest('.node') || target.closest('.cluster') || target.closest('.flow-overlay')) return;
		if (isFocused) flowsState.clearSelection();
		panning = { sx: event.clientX, sy: event.clientY, camX, camY };
	}

	function startDrag(event: PointerEvent, node: SimNode) {
		if (event.button !== 0) return;
		event.stopPropagation();
		dragging = { id: node.id, sx: event.clientX, sy: event.clientY, moved: false };
	}

	function onPointerMove(event: PointerEvent) {
		if (!stage) return;
		const rect = stage.getBoundingClientRect();
		pointer = { x: event.clientX - rect.left, y: event.clientY - rect.top };

		if (panning) {
			camX = panning.camX - (event.clientX - panning.sx) / scale;
			camY = panning.camY - (event.clientY - panning.sy) / scale;
			return;
		}

		if (dragging) {
			const node = nodes.find((n) => n.id === dragging!.id);
			if (!node) return;
			const dx = event.clientX - dragging.sx;
			const dy = event.clientY - dragging.sy;
			if (!dragging.moved && dx * dx + dy * dy < 9) return;
			dragging.moved = true;
			node.fx = camX + (event.clientX - rect.left - width / 2) / scale;
			node.fy = camY + (event.clientY - rect.top - height / 2) / scale;
			node.x = node.fx;
			node.y = node.fy;
			tick += 1;
		}
	}

	function onPointerUp() {
		panning = null;
		if (!dragging) return;
		const finished = dragging;
		dragging = null;
		if (!finished.moved) {
			const node = nodes.find((n) => n.id === finished.id);
			if (node) selectApp(node.id);
		} else if (!isFocused) {
			simulation?.reheat(0.35);
			startLoop();
		}
	}

	function unpin(event: MouseEvent, node: SimNode) {
		event.stopPropagation();
		const original = nodes.find((candidate) => candidate.id === node.id);
		if (!original) return;
		original.fx = null;
		original.fy = null;
		if (!isFocused) {
			simulation?.reheat(0.6);
			startLoop();
		}
	}

	function focusCluster(event: MouseEvent, id: string) {
		event.stopPropagation();
		studio.setCategoryFilter(id);
	}

	function shortName(name: string): string {
		return name.length > 16 ? `${name.slice(0, 15).trimEnd()}…` : name;
	}

	function selectApp(id: string) {
		if (studio.categoryFilter) studio.select('app', id);
		else studio.openCompany(id);
	}

	/* ---------------------------- styling --------------------------- */

	function colorFor(node: SimNode): string {
		const app = appMap.get(node.id) ?? allApps.get(node.id);
		if (!app) return '#8b8b97';
		if (studio.colourMode === 'reception') return app.insightsId ? 'var(--muted)' : receptionColor(app.reception);
		if (studio.colourMode === 'platform') return platformColor(app.platform);
		return categoryMap.get(app.categoryId)?.accent ?? app.accent ?? '#8b8b97';
	}

	function nodeOpacity(node: SimNode): number {
		if (!nodeVisible(node)) return 0;
		if (isFocused) return 1;
		if (!focusId) return 1;
		if (!focusSet.has(node.id)) return 0.22;
		return 1;
	}

	function nodeVisible(node: SimNode): boolean {
		if (activeClusterId && node.clusterId !== activeClusterId) return false;
		if (!appHasContent(node.id)) return false;
		if (isFocused) {
			const selection = flowsState.selection;
			if (selection?.type === 'app') return node.id === selection.id || connectedFlowIds.has(node.id);
			if (selection?.type === 'edge') return node.id === selection.s || node.id === selection.t;
		}
		return true;
	}

	function appHasContent(id: string): boolean {
		return studio.appHasReviews(id) || connectedFlowIds.has(id);
	}

	function edgeOpacity(link: SimLink): number {
		if (!appHasContent(link.source.id) || !appHasContent(link.target.id)) return 0;
		if (activeClusterId && (link.source.clusterId !== activeClusterId || link.target.clusterId !== activeClusterId)) return 0;
		if (isFocused) return hasFlowData ? 0 : 0.18;
		const base = 0.13;
		if (!focusId) return base;
		const active = link.source.id === focusId || link.target.id === focusId;
		return active ? 0.9 : 0.05;
	}

	function edgeColor(link: SimLink): string {
		const app = appMap.get(link.source.id) ?? allApps.get(link.source.id);
		const category = app ? categoryMap.get(app.categoryId) : undefined;
		if (link.source.clusterId !== link.target.clusterId) {
			return 'color-mix(in srgb, var(--text) 28%, transparent)';
		}
		return category?.accent ?? 'var(--line-bright)';
	}

	function edgeWidth(link: SimLink): number {
		return 0.5 + (link.score ?? 0) * 1.6;
	}
</script>

<svelte:window onpointermove={onPointerMove} onpointerup={onPointerUp} />

<div class="stage" class:zooming class:focused={isFocused} bind:this={stage} bind:clientWidth={width} bind:clientHeight={height}>
	<svg
		class="canvas"
		role="img"
		aria-label="Category map of apps, clustered by what they do"
		onwheel={onWheel}
		onpointerdown={onBackgroundDown}
	>
		<defs>
			<pattern id="dot-grid" width="34" height="34" patternUnits="userSpaceOnUse">
				<circle cx="1" cy="1" r="1" fill="#ffffff" opacity="0.055" />
			</pattern>
		</defs>

		<rect width="100%" height="100%" fill="url(#dot-grid)" style="pointer-events: none" />

		<g transform="translate({width / 2},{height / 2}) scale({scale}) translate({-camX},{-camY})">
			<g class="hulls">
				{#each clusters as cluster (cluster.id)}
					{@const category = categoryMap.get(cluster.id)}
					{@const focused = studio.categoryFilter === cluster.id}
					{#if category}
						<g
							class="cluster"
							class:focused
							class:hovered={hoveredCluster === cluster.id || studio.zoomingCategory === cluster.id}
							class:receding={Boolean(activeClusterId && activeClusterId !== cluster.id)}
							style:--accent={category.accent}
							role="button"
							tabindex={activeClusterId && activeClusterId !== cluster.id ? -1 : 0}
							aria-hidden={Boolean(activeClusterId && activeClusterId !== cluster.id)}
							aria-label="Open flows for {category.name}, {cluster.count} apps"
							onpointerenter={() => (hoveredCluster = cluster.id)}
							onpointerleave={() => (hoveredCluster = null)}
							onclick={(event) => focusCluster(event, cluster.id)}
							onkeydown={(event) => {
								if (event.key === 'Enter' || event.key === ' ') {
									event.preventDefault();
									studio.setCategoryFilter(cluster.id);
								}
							}}
						>
							<circle
								cx={cluster.x}
								cy={cluster.y}
								r={cluster.radius}
								fill={category.accent}
								fill-opacity={focused ? 0.08 : 0.028}
								stroke={category.accent}
								stroke-opacity={focused ? 0.7 : 0.34}
								stroke-width="1"
								stroke-dasharray={focused ? undefined : '2 5'}
								vector-effect="non-scaling-stroke"
							/>
						</g>
					{/if}
				{/each}
			</g>

			{#if !isFocused}
				<g class="home-connections" aria-label="Connections from reported switches">
					{#each homeConnections as pair (pair.s + '|' + pair.t)}
						{@const source = nodePositions.get(pair.s)}
						{@const target = nodePositions.get(pair.t)}
						{#if source && target}
							<line x1={source.x} y1={source.y} x2={target.x} y2={target.y} stroke="var(--text-2)" stroke-width={0.7 + Math.sqrt(pair.count / homeMax) * 1.8} stroke-opacity={focusId ? pair.s === focusId || pair.t === focusId ? 0.85 : 0.06 : 0.25 + Math.sqrt(pair.count / homeMax) * 0.35} vector-effect="non-scaling-stroke"><title>{appMap.get(pair.s)?.name} ↔ {appMap.get(pair.t)?.name}: {pair.count} reported switches</title></line>
						{/if}
					{/each}
				</g>
			{:else}
			<g class="edges">
				{#each viewLinks as link, index (`${link.source.id}-${link.target.id}-${index}`)}
					<line
						class:outside-cluster={Boolean(activeClusterId && (link.source.clusterId !== activeClusterId || link.target.clusterId !== activeClusterId))}
						x1={link.source.x}
						y1={link.source.y}
						x2={link.target.x}
						y2={link.target.y}
						stroke={edgeColor(link)}
						stroke-width={edgeWidth(link)}
						stroke-opacity={edgeOpacity(link)}
						stroke-dasharray={link.source.clusterId === link.target.clusterId ? '2 4' : '1 6'}
						vector-effect="non-scaling-stroke"
					/>
				{/each}
			</g>
			{/if}

			{#if isFocused && hasFlowData}
				{@const cluster = clusters.find((cluster) => cluster.id === studio.categoryFilter)}
				{#if cluster}
					<FlowOverlay nodes={appNodes} {cluster} {scale} />
				{/if}
			{/if}

			<g class="app-layer">
				{#each appNodes as node, index (node.id)}
					{@const app = appMap.get(node.id) ?? allApps.get(node.id)}
					{@const color = colorFor(node)}
					{@const label = appLabels?.get(node.id)}
					{@const selected = isFocused && flowsState.selection?.type === 'app' ? flowsState.selection.id === node.id : studio.selected?.kind === 'app' && studio.selected.id === node.id}
					{@const logoRadius = Math.max(node.radius, (isFocused ? 12 : 10) / scale)}
					{#if app && appHasContent(node.id)}
						<g
							class="node app"
							class:selected
							class:hovered={hovered === node.id}
							class:dimmed={focusId !== null && !focusSet.has(node.id)}
							class:outside-cluster={!nodeVisible(node)}
							style:opacity={nodeOpacity(node)}
							transform="translate({node.x},{node.y})"
							role="button"
							tabindex={nodeVisible(node) ? 0 : -1}
							aria-hidden={!nodeVisible(node)}
							aria-label="{app.name}, {app.categoryName}, {fmtCount(app.reviewCount)} reviews"
							onpointerdown={(event) => startDrag(event, node)}
							onpointerenter={() => { hovered = node.id; if (hasFlowData) flowsState.hoveredNode = node.id; }}
							onpointerleave={() => { hovered = null; flowsState.hoveredNode = null; }}
							onclick={(event) => event.stopPropagation()}
							onkeydown={(event) => {
								if (event.key === 'Enter' || event.key === ' ') {
									event.preventDefault();
									selectApp(node.id);
								}
							}}
							ondblclick={(event) => unpin(event, node)}
						>
							<g class="logo-body">
								<rect class="node-outline" x={-logoRadius - 2 / scale} y={-logoRadius - 2 / scale} width={logoRadius * 2 + 4 / scale} height={logoRadius * 2 + 4 / scale} rx={logoRadius * 0.48} fill="var(--panel)" stroke={selected || hovered === node.id ? 'white' : color} stroke-width={selected || hovered === node.id ? 2 : 1} vector-effect="non-scaling-stroke" />
								<g transform="translate({-logoRadius},{-logoRadius})"><AppLogo appId={app.id} name={app.name} size={logoRadius * 2} /></g>
							</g>
							<text
								class="app-label"
								class:soft={(!showLabels && hovered !== node.id && !selected) || (label && !label.visible)}
								text-anchor={label?.anchor ?? 'middle'}
								x={label?.x ?? 0}
								y={label?.y ?? (index % 2 === 0 ? node.radius + 13 : -(node.radius + 7))}
								fill="var(--muted)"
								font-size={isFocused ? 10 / scale : 8.5}
								style:stroke-width="{isFocused ? 3 / scale : 3.5}px"
								font-family="var(--mono)"
							>
								{shortName(app.name)}
							</text>
						</g>
					{/if}
				{/each}
			</g>
		</g>
	</svg>

	{#if hoveredApp}
		<div class="tooltip" style:left="{tipX}px" style:top="{tipY}px">
			<div class="tt-head">
				<AppLogo appId={hoveredApp.id} name={hoveredApp.name} size={25} />
				<span class="tt-name">{hoveredApp.name}</span>
			</div>
			<div class="tt-sub">{hoveredApp.categoryName}</div>
			<div class="tt-row">
				<span class="tt-muted">{fmtCount(hoveredApp.reviewCount)} reviews</span>
			</div>
			<div class="tt-hint">click to explore company →</div>
		</div>
	{:else if hoveredCategory}
		<div class="tooltip" style:left="{tipX}px" style:top="{tipY}px">
			<div class="tt-head">
				<span class="tt-dot" style:background={hoveredCategory.accent}></span>
				<span class="tt-name">{hoveredCategory.name}</span>
			</div>
			<div class="tt-sub">{hoveredCategory.blurb}</div>
			<div class="tt-row">
				<span class="num">{hoveredCategory.appIds.length} apps</span>
				<span class="tt-muted">{fmtCount(hoveredCategory.reviewCount)} reviews</span>
			</div>
			<div class="tt-hint">click to open flows →</div>
		</div>
	{/if}

	{#if isFocused && !hasFlowData}
		<div class="no-flows">
			{#if hasExportedInsights}
				<span class="label">Topic analytics available</span><p>Select an app for imported topics and review excerpts. Switching flows aren’t included in these exports.</p>
			{:else}
				<span class="label">No switching data for this cluster yet</span><p>The network stays visible. No switching reports are available for the apps in this cluster.</p>
			{/if}
		</div>
	{/if}

	<div class="controls">
		<button onclick={() => zoomAt(1.3)} aria-label="Zoom in">+</button>
		<button onclick={() => zoomAt(0.77)} aria-label="Zoom out">−</button>
		<button onclick={fitView} aria-label="Fit graph" class="fit">FIT</button>
	</div>

	{#if nodes.length === 0}
		<div class="empty">
			<p class="empty-title">Nothing in view</p>
			<p>No apps match the current filters.</p>
			<button class="btn is-sm" onclick={() => studio.clearFilters()}>Reset filters</button>
		</div>
	{/if}
</div>

<style>
	.stage {
		position: relative;
		flex: 1;
		min-height: 0;
		overflow: hidden;
		background:
			radial-gradient(1100px 600px at 50% 42%, rgba(200, 255, 60, 0.028), transparent 65%),
			var(--bg);
		cursor: grab;
	}
	.stage:active {
		cursor: grabbing;
	}
	.stage.zooming {
		pointer-events: none;
	}
	.zooming .controls {
		opacity: 0;
		transition: opacity 180ms;
	}
	.zooming :global(.flow-overlay) { opacity: 0; pointer-events: none; }
	.cluster.receding {
		opacity: 0;
		visibility: hidden;
		pointer-events: none;
	}

	.canvas {
		display: block;
		width: 100%;
		height: 100%;
		touch-action: none;
		user-select: none;
	}

	.cluster {
		cursor: pointer;
		outline: none;
		transition: opacity 180ms var(--ease);
	}
	.cluster circle {
		transition:
			fill-opacity 180ms var(--ease),
			stroke-opacity 180ms var(--ease);
	}
	.cluster.hovered circle,
	.cluster.focused circle {
		fill-opacity: 0.1;
		stroke-opacity: 0.8;
	}
	.cluster:focus-visible circle {
		stroke: var(--text);
		stroke-width: 1.5;
	}
	.node {
		cursor: pointer;
		transition: opacity 180ms var(--ease);
		outline: none;
	}
	.outside-cluster {
		visibility: hidden;
		pointer-events: none;
	}
	.no-flows {
		position: absolute;
		top: 12px;
		left: 14px;
		max-width: calc(100% - 28px);
		padding: 10px 12px;
		background: var(--panel);
		border: 1px solid var(--line);
		pointer-events: none;
	}
	.no-flows p {
		margin: 5px 0 0;
		font-size: 11px;
		color: var(--muted);
	}
	.logo-body { transition: transform 180ms var(--ease); }
	.node.hovered .logo-body, .node.selected .logo-body { transform: scale(1.06); }
	.node.hovered .node-outline, .node.selected .node-outline, .node:focus-visible .node-outline { stroke: white; stroke-width: 2px; filter: drop-shadow(0 0 6px #ffffff55); }
	.app-label {
		pointer-events: none;
		paint-order: stroke;
		stroke: var(--bg);
		stroke-width: 3.5px;
		stroke-linejoin: round;
	}
	.app-label.soft {
		opacity: 0;
	}

	.tooltip {
		position: absolute;
		width: 238px;
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
		width: 6px;
		height: 6px;
		border-radius: 1px;
		flex: none;
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
		align-items: center;
		gap: 7px;
		margin-top: 7px;
		font-size: 10px;
		color: var(--text-2);
	}
	.tt-muted {
		margin-left: auto;
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


	.controls {
		position: absolute;
		right: 14px;
		bottom: 14px;
		display: flex;
		flex-direction: column;
		border: 1px solid var(--line-strong);
		border-radius: 2px;
		overflow: hidden;
		background: var(--panel);
	}
	.controls button {
		width: 30px;
		height: 28px;
		font-family: var(--mono);
		font-size: 13px;
		color: var(--muted);
		border-bottom: 1px solid var(--line);
	}
	.controls button:last-child {
		border-bottom: 0;
	}
	.controls button:hover {
		background: var(--panel-3);
		color: var(--text);
	}
	.controls .fit {
		font-size: 8px;
		letter-spacing: 0.1em;
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
		background: color-mix(in srgb, var(--bg) 70%, transparent);
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
	.empty .btn {
		margin-top: 8px;
	}

</style>
