/* Small, dependency-free correlation helpers used by the demo signals.
 *
 * The numbers are directional, not causal: weekly review signals are
 * correlated against the modelled download series. A positive `lag` means the
 * review signal moves first and downloads follow that many weeks later.
 */

import type { CorrelationSignal, SignalConfidence, ThemeImpact } from '#lib/api/types';

export function mean(values: number[]): number {
	if (!values.length) return 0;
	return values.reduce((sum, value) => sum + value, 0) / values.length;
}

export function pearson(x: number[], y: number[]): number {
	const n = Math.min(x.length, y.length);
	if (n < 3) return 0;
	const mx = mean(x.slice(0, n));
	const my = mean(y.slice(0, n));
	let num = 0;
	let dx = 0;
	let dy = 0;
	for (let i = 0; i < n; i++) {
		const a = x[i] - mx;
		const b = y[i] - my;
		num += a * b;
		dx += a * a;
		dy += b * b;
	}
	if (dx === 0 || dy === 0) return 0;
	return num / Math.sqrt(dx * dy);
}

/** Centered moving average with clamped edges. */
export function smooth(values: number[], window = 3): number[] {
	if (window <= 1 || values.length < window) return [...values];
	const half = Math.floor(window / 2);
	return values.map((_, i) => {
		let sum = 0;
		let count = 0;
		for (let k = -half; k <= half; k++) {
			const j = i + k;
			if (j < 0 || j >= values.length) continue;
			sum += values[j];
			count++;
		}
		return count ? sum / count : 0;
	});
}

export interface LaggedCorrelation {
	r: number;
	lag: number;
	n: number;
}

/** Correlate driver[t] with target[t + lag]. Positive lag = driver leads. */
export function correlateAtLag(
	driver: number[],
	target: number[],
	lag: number
): LaggedCorrelation {
	const n = Math.min(driver.length, target.length);
	const start = Math.max(0, -lag);
	const end = Math.min(n - 1, n - 1 - lag);
	const xs: number[] = [];
	const ys: number[] = [];
	for (let t = start; t <= end; t++) {
		xs.push(driver[t]);
		ys.push(target[t + lag]);
	}
	return { r: pearson(xs, ys), lag, n: xs.length };
}

/** Pick the lag with the strongest absolute correlation. */
export function bestCorrelation(
	driver: number[],
	target: number[],
	maxLag = 2
): LaggedCorrelation | null {
	let best: LaggedCorrelation | null = null;
	for (let lag = -maxLag; lag <= maxLag; lag++) {
		const result = correlateAtLag(driver, target, lag);
		if (result.n < 8) continue;
		if (!best || Math.abs(result.r) > Math.abs(best.r)) best = result;
	}
	return best;
}

export function confidenceFor(r: number, n: number, mentions: number): SignalConfidence {
	const strength = Math.abs(r);
	if (mentions >= 30 && n >= 18 && strength >= 0.45) return 'strong';
	if (mentions >= 12 && n >= 12 && strength >= 0.28) return 'moderate';
	return 'low';
}

export function signal(
	id: string,
	label: string,
	kind: CorrelationSignal['kind'],
	driver: number[],
	downloads: number[],
	mentions: number,
	maxLag = 2
): CorrelationSignal | null {
	const result = bestCorrelation(smooth(driver), smooth(downloads), maxLag);
	if (!result) return null;
	return {
		id,
		label,
		kind,
		r: Number(result.r.toFixed(2)),
		lag: result.lag,
		n: result.n,
		mentions,
		confidence: confidenceFor(result.r, result.n, mentions)
	};
}

/** Merge two theme impacts, weighted by mention count. */
export function mergeImpact(a?: ThemeImpact, b?: ThemeImpact): ThemeImpact | undefined {
	if (!a) return b;
	if (!b) return a;
	const mentions = a.mentions + b.mentions;
	if (!mentions) return a;
	return {
		r: Number(((a.r * a.mentions + b.r * b.mentions) / mentions).toFixed(2)),
		lag: Math.round((a.lag * a.mentions + b.lag * b.mentions) / mentions),
		n: Math.min(a.n, b.n),
		mentions,
		confidence: confidenceFor((a.r + b.r) / 2, Math.min(a.n, b.n), mentions)
	};
}
