import {
	aggregate,
	allMonthIds,
	coverageMonths,
	flowMonth,
	type FlowAgg,
	type FlowLayer
} from '#lib/data/flows';

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

class FlowsState {
	/** selected month id, or 'all' for every month with data */
	period = $state<string>('all');
	showSwitches = $state(true);
	showIntents = $state(false);
	showPreferences = $state(false);
	netMode = $state(false);
	showAllRoutes = $state(false);
	playing = $state(false);

	selection = $state<FlowSelection>(null);
	hoveredArrow = $state<string | null>(null);
	hoveredNode = $state<string | null>(null);

	private timer: ReturnType<typeof setInterval> | undefined;

	get layers(): Set<FlowLayer> {
		const set = new Set<FlowLayer>();
		if (this.showSwitches) set.add('switch');
		if (this.showIntents) set.add('intent');
		if (this.showPreferences) set.add('preference');
		return set;
	}

	get periodMonths(): string[] {
		return this.period === 'all' ? allMonthIds : [this.period];
	}

	get isPartial(): boolean {
		return this.period !== 'all' && !flowMonth(this.period)?.full;
	}

	get aggregates(): Map<string, FlowAgg> {
		return aggregate(this.periodMonths, this.layers);
	}

	get arrows(): FlowArrow[] {
		return buildArrows(this.aggregates, this.netMode);
	}

	get availableArrows(): FlowArrow[] {
		const max = this.scaleMax;
		return this.arrows.filter((arrow) => arrow.value >= max * 0.004)
			.sort((a, b) => b.value - a.value || a.key.localeCompare(b.key));
	}

	/** Keep the overview legible; inspection reveals routes hidden by the summary. */
	get visibleArrows(): FlowArrow[] {
		const selection = this.selection;
		const appId = this.hoveredNode ?? (selection?.type === 'app' ? selection.id : null);
		if (appId) {
			const connected = this.arrows.filter((arrow) => arrow.s === appId || arrow.t === appId)
				.sort((a, b) => b.value - a.value || a.key.localeCompare(b.key));
			return this.showAllRoutes ? connected : connected.slice(0, 8);
		}
		if (selection?.type === 'edge') {
			return this.arrows.filter((arrow) =>
				(arrow.s === selection.s && arrow.t === selection.t) ||
				(arrow.s === selection.t && arrow.t === selection.s)
			);
		}
		return this.showAllRoutes ? this.availableArrows : this.availableArrows.slice(0, 8);
	}

	/** Max arrow value across coverage months (and the current period), so widths stay
	 *  comparable while the timeline plays. */
	get scaleMax(): number {
		const layers = this.layers;
		let max = 0;
		const periods = this.period === 'all' ? [allMonthIds] : [...coverageMonths.map((m) => [m]), [this.period]];
		for (const months of periods) {
			for (const arrow of buildArrows(aggregate(months, layers), this.netMode)) {
				if (arrow.value > max) max = arrow.value;
			}
		}
		return max || 1;
	}

	setPeriod(period: string) {
		this.period = period;
	}

	selectEdge(s: string, t: string) {
		this.selection = { type: 'edge', s, t };
	}

	selectApp(id: string) {
		this.selection = { type: 'app', id };
	}

	clearSelection() {
		this.selection = null;
	}

	step(delta: number) {
		const idx = coverageMonths.indexOf(this.period);
		const next = idx === -1 ? (delta > 0 ? 0 : coverageMonths.length - 1) : idx + delta;
		if (next >= 0 && next < coverageMonths.length) this.period = coverageMonths[next];
	}

	togglePlay() {
		if (this.playing) this.stop();
		else this.play();
	}

	play() {
		if (!coverageMonths.length) return;
		const idx = coverageMonths.indexOf(this.period);
		if (idx === -1 || idx === coverageMonths.length - 1) this.period = coverageMonths[0];
		this.playing = true;
		clearInterval(this.timer);
		this.timer = setInterval(() => {
			const i = coverageMonths.indexOf(this.period);
			if (i === -1 || i >= coverageMonths.length - 1) {
				this.stop();
				return;
			}
			this.period = coverageMonths[i + 1];
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

export const flowsState = new FlowsState();
