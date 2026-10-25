/** Sum issue mentions across raw directed aggregates, not net/display-limited arrows.
 * Each aggregate is visited once, including routes between two cluster members.
 * A switching report can mention multiple issues; these are not unique-review counts.
 */
export function combinedFlowIssues(rows: Iterable<{ layer: string; reasons: Map<string, number> }>): [string, number][] {
	const totals = new Map<string, number>();
	for (const row of rows) {
		if (row.layer !== 'switch') continue;
		for (const [id, count] of row.reasons) totals.set(id, (totals.get(id) ?? 0) + count);
	}
	return [...totals].filter(([, count]) => count > 0)
		.sort(([a, countA], [b, countB]) => countB - countA || a.localeCompare(b));
}
