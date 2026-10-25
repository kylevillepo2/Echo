/** Filter the saved evidence excerpts without substituting unrelated reviews. */
export function filterFlowEvidence<T extends { r: string[]; m: string }>(
	examples: T[],
	reason: string | null,
	period: string | string[],
	includeAllMonths = false
): T[] {
	return examples.filter((example) =>
		(!reason || example.r.includes(reason)) &&
		(includeAllMonths || period === 'all' || (Array.isArray(period) ? period.includes(example.m) : example.m === period))
	);
}
