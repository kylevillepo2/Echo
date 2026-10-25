import {
	aggregate,
	allMonthIds,
	annotationsFor,
	coverageFor,
	monthInfoFor,
	monthlyActivityFor,
	rankCompetitors,
	flowNode,
	pairReviewObservers,
	reviewObserversFor,
	fmtMonth,
	type CompetitorRank,
	type FlowAgg,
	type FlowAnnotation,
	type FlowLayer,
	type FlowMonth
} from '#lib/data/flows';
import { hotSingleton } from '#lib/utils/hot-state';
import { timelineMonths } from '#lib/utils/timeline';

export type FlowSelection =
	| { type: 'edge'; s: string; t: string }
	| { type: 'app'; id: string }
	| null;

/** One drawn arrow. In net mode, layer is 'net' and value is the net difference. */
export interface FlowArrow {
	key: string;
	s: string;
	t: string;
	layer: FlowLayer | 'net';
	value: number;
	count: number;
	reasons: Map<string, number>;
	/** net mode: gross value in each direction */
	forward?: number;
	backward?: number;
}

const PLAY_MS = 1300;
/** Outside competitors shown around a focused cluster before "Show all". */
export const TOP_COMPETITORS = 4;

class FlowsState {
	/** selected month id, or 'all' for every month with data */
	period = $state<string>('all');
	rangeEnd = $state<string | null>(null);
	showSwitches = $state(true);
	showIntents = $state(false);
	showPreferences = $state(false);
	netMode = $state(true);
	playing = $state(false);

	selection = $state<FlowSelection>(null);
	hoveredArrow = $state<string | null>(null);
	hoveredNode = $state<string | null>(null);

	/** Apps of the focused map cluster. Flows touching one of them are shown; null = every app. */
	scope = $state.raw<Set<string> | null>(null);
	showAllCompetitors = $state(false);

	private timer: ReturnType<typeof setInterval> | undefined;

	layers = $derived.by(() => {
		const set = new Set<FlowLayer>();
		if (this.showSwitches) set.add('switch');
		if (this.showIntents) set.add('intent');
		if (this.showPreferences) set.add('preference');
		return set;
	});

	/** The timeline follows the selected company/route, otherwise the selected industry. */
	timelineScope = $derived(this.selection?.type === 'app'
		? flowNode(this.selection.id)?.observed ? new Set([this.selection.id]) : reviewObserversFor(new Set([this.selection.id]))
		: this.selection?.type === 'edge' ? pairReviewObservers(this.selection.s, this.selection.t) : this.scope);
	coverageMonths = $derived(coverageFor(this.timelineScope));
	annotations = $derived<FlowAnnotation[]>(annotationsFor(this.timelineScope));
	activity = $derived<Record<string, number>>(monthlyActivityFor(
		this.selection?.type === 'app' ? new Set([this.selection.id]) : this.scope,
		this.selection?.type === 'edge' ? this.selection : undefined
	));

	periodMonths = $derived(timelineMonths(allMonthIds, this.period, this.rangeEnd));
	periodLabel = $derived(this.period === 'all' ? 'all months' : this.rangeEnd
		? `${fmtMonth(this.period, true)} – ${fmtMonth(this.rangeEnd, true)}` : fmtMonth(this.period));

	aggregates = $derived<Map<string, FlowAgg>>(aggregate(this.periodMonths, this.layers, this.scope));

	arrows = $derived<FlowArrow[]>(buildArrows(this.aggregates, this.netMode));

	/** Max arrow value across coverage months (and the current period), so widths stay
	 *  comparable while the timeline plays. Computed for the current scope. */
	scaleMax = $derived.by(() => {
		let max = 0;
		const periods = this.period === 'all'
			? [allMonthIds]
			: [...this.coverageMonths.map((m) => [m]), this.periodMonths];
		for (const months of periods) {
			for (const arrow of buildArrows(aggregate(months, this.layers, this.scope), this.selection?.type === 'edge' ? false : this.netMode)) {
				if (arrow.value > max) max = arrow.value;
			}
		}
		return max || 1;
	});

	availableArrows = $derived<FlowArrow[]>(
		this.arrows.filter((arrow) => arrow.value >= this.scaleMax * 0.004)
			.sort((a, b) => b.value - a.value || a.key.localeCompare(b.key))
	);

	/** Outside apps linked to the cluster, strongest first (raw switch/return counts, all months). */
	competitorRanking = $derived<CompetitorRank[]>(rankCompetitors(this.scope));

	/** Outside apps drawn on the ring. Members of the cluster are always drawn by the map. */
	visibleOutsideIds = $derived.by(() => {
		const scope = this.scope;
		const selection = this.selection;
		const isOutside = (id: string) => !scope?.has(id);
		// A selected flow shows only its own endpoints.
		if (selection?.type === 'edge') return new Set([selection.s, selection.t].filter(isOutside));
		// A selected app shows its own direct outside competitors (an outside app shows just itself).
		if (selection?.type === 'app') {
			if (isOutside(selection.id)) return new Set([selection.id]);
			const ids = new Set<string>();
			for (const arrow of [...this.arrows].sort((a, b) => b.count - a.count)) {
				if (arrow.s === selection.id && isOutside(arrow.t)) ids.add(arrow.t);
				if (arrow.t === selection.id && isOutside(arrow.s)) ids.add(arrow.s);
				if (!this.showAllCompetitors && ids.size >= 5) break;
			}
			return ids;
		}
		const ranked = this.competitorRanking.map((rank) => rank.id);
		return new Set(this.showAllCompetitors ? ranked : ranked.slice(0, TOP_COMPETITORS));
	});

	/** Routes actually drawn: at least one end in the cluster, both ends visible. Totals in the
	 *  timeline and inspector still use the full cluster data (aggregates / arrows). */
	drawnArrows = $derived.by<FlowArrow[]>(() => {
		const scope = this.scope;
		if (!scope) return this.visibleArrows;
		const visible = (id: string) => scope.has(id) || this.visibleOutsideIds.has(id);
		return this.visibleArrows.filter((arrow) =>
			(scope.has(arrow.s) || scope.has(arrow.t)) && visible(arrow.s) && visible(arrow.t));
	});

	monthInfo(month: string): FlowMonth {
		return monthInfoFor(this.timelineScope, month);
	}

	get isPartial(): boolean {
		return this.period !== 'all' && this.periodMonths.some((month) => !this.monthInfo(month).full);
	}

	setScope(ids: string[] | null) {
		const next = ids ? new Set(ids) : null;
		const same = next && this.scope
			? next.size === this.scope.size && [...next].every((id) => this.scope!.has(id))
			: next === this.scope;
		if (same) return;
		this.scope = next;
		// A new cluster starts clean: all months, top competitors, nothing selected or hovered.
		this.stop();
		this.period = 'all';
		this.rangeEnd = null;
		this.netMode = true;
		this.showSwitches = true;
		this.showIntents = false;
		this.showPreferences = false;
		this.showAllCompetitors = false;
		this.selection = null;
		this.hoveredArrow = null;
		this.hoveredNode = null;
	}

	/** Show all routes, scoped to the app or pair being inspected when focused. */
	get visibleArrows(): FlowArrow[] {
		const selection = this.selection;
		const appId = selection?.type === 'app' ? selection.id : this.hoveredNode;
		if (appId) {
			return this.arrows.filter((arrow) => arrow.s === appId || arrow.t === appId)
				.sort((a, b) => b.value - a.value || a.key.localeCompare(b.key));
		}
		if (selection?.type === 'edge') {
			// A route drill-down must match its ordered reports and issue evidence, even when
			// the opposite route is the stronger company-level signal.
			return buildArrows(this.aggregates, false).filter((arrow) => arrow.s === selection.s && arrow.t === selection.t);
		}
		return this.availableArrows;
	}

	setPeriod(period: string) {
		if (period !== 'all' && !allMonthIds.includes(period)) return;
		this.period = period;
		this.rangeEnd = null;
	}

	setRange(start: string, end: string) {
		const months = timelineMonths(allMonthIds, start, end);
		if (!months.length || start === 'all') return;
		this.stop();
		this.period = months[0];
		this.rangeEnd = months.length > 1 ? months.at(-1)! : null;
	}

	selectEdge(s: string, t: string) {
		this.selection = { type: 'edge', s, t };
	}

	selectApp(id: string) {
		this.netMode = true;
		this.selection = { type: 'app', id };
	}

	clearSelection() {
		this.selection = null;
	}

	step(delta: number) {
		const coverageMonths = this.coverageMonths;
		const idx = coverageMonths.indexOf(this.period);
		const next = idx === -1 ? (delta > 0 ? 0 : coverageMonths.length - 1) : idx + delta;
		if (next >= 0 && next < coverageMonths.length) this.setPeriod(coverageMonths[next]);
	}

	togglePlay() {
		if (this.playing) this.stop();
		else this.play();
	}

	play() {
		const coverageMonths = this.coverageMonths;
		if (!coverageMonths.length) return;
		const idx = coverageMonths.indexOf(this.period);
		this.rangeEnd = null;
		if (idx === -1 || idx === coverageMonths.length - 1) this.setPeriod(coverageMonths[0]);
		this.playing = true;
		clearInterval(this.timer);
		this.timer = setInterval(() => {
			const i = coverageMonths.indexOf(this.period);
			if (i === -1 || i >= coverageMonths.length - 1) {
				this.stop();
				return;
			}
			this.setPeriod(coverageMonths[i + 1]);
		}, PLAY_MS);
	}

	stop() {
		this.playing = false;
		clearInterval(this.timer);
		this.timer = undefined;
	}
}

function buildArrows(aggs: Map<string, FlowAgg>, net: boolean): FlowArrow[] {
	if (!net) {
		return [...aggs.entries()].map(([key, a]) => ({
			key,
			s: a.s,
			t: a.t,
			layer: a.layer,
			value: a.value,
			count: a.count,
			reasons: a.reasons
		}));
	}

	// Net: one arrow per unordered pair, all visible layers combined.
	const pairs = new Map<
		string,
		{ a: string; b: string; ab: number; ba: number; nab: number; nba: number; rab: Map<string, number>; rba: Map<string, number> }
	>();
	for (const agg of aggs.values()) {
		const [a, b] = agg.s < agg.t ? [agg.s, agg.t] : [agg.t, agg.s];
		const key = `${a}|${b}`;
		let p = pairs.get(key);
		if (!p) {
			p = { a, b, ab: 0, ba: 0, nab: 0, nba: 0, rab: new Map(), rba: new Map() };
			pairs.set(key, p);
		}
		const forward = agg.s === a;
		if (forward) {
			p.ab += agg.value;
			p.nab += agg.count;
		} else {
			p.ba += agg.value;
			p.nba += agg.count;
		}
		const into = forward ? p.rab : p.rba;
		for (const [id, n] of agg.reasons) into.set(id, (into.get(id) ?? 0) + n);
	}
	const out: FlowArrow[] = [];
	for (const p of pairs.values()) {
		const diff = p.ab - p.ba;
		if (Math.abs(diff) < 1e-9) continue;
		const forward = diff > 0;
		out.push({
			key: `${p.a}|${p.b}|net`,
			s: forward ? p.a : p.b,
			t: forward ? p.b : p.a,
			layer: 'net',
			value: Math.abs(diff),
			count: forward ? p.nab : p.nba,
			reasons: forward ? p.rab : p.rba,
			forward: forward ? p.ab : p.ba,
			backward: forward ? p.ba : p.ab
		});
	}
	return out;
}

export const flowsState = hotSingleton(
	typeof window !== 'undefined' ? import.meta.hot : undefined,
	'flowsState',
	() => new FlowsState(),
	() => {
		flowsState.stop();
		window.location.reload();
	}
);
