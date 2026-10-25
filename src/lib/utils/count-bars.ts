/** Relative count bars share one maximum; zero counts must stay empty. */
export function countBarWidth(count: number, maximum: number): number {
	if (!Number.isFinite(count) || !Number.isFinite(maximum) || maximum <= 0) return 0;
	return Math.max(0, Math.min(100, count / maximum * 100));
}
