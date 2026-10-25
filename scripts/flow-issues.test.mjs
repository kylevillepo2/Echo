import assert from 'node:assert/strict';
import test from 'node:test';
import { combinedFlowIssues } from '../src/lib/utils/flow-issues.ts';
import { aggregate, allMonthIds } from '../src/lib/data/flows.ts';

test('combined issues include both directions and internal routes exactly once', () => {
	const rows = [
		{ s: 'a', t: 'b', layer: 'switch', reasons: new Map([['bugs', 4], ['price', 2]]) },
		{ s: 'b', t: 'a', layer: 'switch', reasons: new Map([['bugs', 3]]) },
		{ s: 'a', t: 'outside', layer: 'switch', reasons: new Map([['price', 6]]) },
		{ s: 'outside', t: 'b', layer: 'intent', reasons: new Map([['bugs', 100]]) }
	];
	assert.deepEqual(combinedFlowIssues(rows), [['price', 8], ['bugs', 7]]);
});

test('issues are not limited to the five displayed routes or netted away', () => {
	const rows = Array.from({ length: 12 }, () => ({ layer: 'switch', reasons: new Map([['bugs', 2]]) }));
	assert.deepEqual(combinedFlowIssues(rows), [['bugs', 24]]);
	assert.deepEqual(combinedFlowIssues([]), []);
});

test('real cluster issue counts reconcile to all scoped routes for the selected range', () => {
	const scope = new Set(['spotify', 'soundcloud', 'audiomack']);
	for (const months of [allMonthIds, allMonthIds.slice(4, 9), [allMonthIds[0]]]) {
		const rows = aggregate(months, new Set(['switch']), scope);
		const expected = new Map();
		for (const row of rows.values()) {
			assert(scope.has(row.s) || scope.has(row.t));
			for (const [id, count] of row.reasons) expected.set(id, (expected.get(id) ?? 0) + count);
		}
		assert.deepEqual(new Map(combinedFlowIssues(rows.values())), expected);
	}
});
