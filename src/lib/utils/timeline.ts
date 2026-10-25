/** Clamp pointer positions to the nearest month, including both ends of the chart. */
export function timelineIndex(clientX: number, left: number, width: number, count: number): number {
	if (count <= 1 || width <= 0) return 0;
	return Math.max(0, Math.min(count - 1, Math.round((clientX - left) / width * (count - 1))));
}

export function timelineWindow(start: number, end: number, count: number): [number, number] {
	const clamp = (index: number) => Math.max(0, Math.min(Math.max(count - 1, 0), index));
	return [clamp(Math.min(start, end)), clamp(Math.max(start, end))];
}

export function shiftTimelineWindow(start: number, end: number, delta: number, count: number): [number, number] {
	const offset = Math.max(-start, Math.min(Math.max(count - 1, 0) - end, delta));
	return [start + offset, end + offset];
}

export function timelineMonths(months: string[], start: string, end: string | null): string[] {
	if (start === 'all') return months;
	const first = months.indexOf(start);
	const last = end === null ? first : months.indexOf(end);
	if (first < 0 || last < 0) return [];
	return months.slice(Math.min(first, last), Math.max(first, last) + 1);
}
