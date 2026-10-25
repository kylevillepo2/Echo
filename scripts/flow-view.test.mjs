import assert from 'node:assert/strict';
import test from 'node:test';
import {
	aggregate, allMonthIds, annotationsFor, flowEdges, flowNodes, monthlyActivityFor,
	monthInfoFor, overviewConnections, pairReviewObservers, pairReviewVolume, volumeOf
} from '../src/lib/data/flows.ts';

const switches = flowEdges.filter((row) => row.k === 'switch' || row.k === 'return');
const finance = new Set(['chime', 'cash-app', 'paypal']);

test('industry timeline counts contain only that industry’s reported switches', () => {
	const expected = {};
	for (const row of switches) if (finance.has(row.s) || finance.has(row.t)) expected[row.m] = (expected[row.m] ?? 0) + row.n;
	assert.deepEqual(monthlyActivityFor(finance), expected);
});

test('all-month totals equal the full set of scoped monthly switch reports', () => {
	const monthly = Object.values(monthlyActivityFor(finance)).reduce((sum, count) => sum + count, 0);
	const total = [...aggregate(allMonthIds, new Set(['switch']), finance).values()].reduce((sum, row) => sum + row.count, 0);
	assert.equal(total, monthly);
});

test('a route timeline counts the selected direction, not unrelated routes', () => {
	const pair = { s: 'chime', t: 'cash-app' };
	const expected = switches.filter((row) => row.s === pair.s && row.t === pair.t).reduce((sum, row) => sum + row.n, 0);
	assert.equal(Object.values(monthlyActivityFor(finance, pair)).reduce((sum, count) => sum + count, 0), expected);
});

test('timeline coverage and event captions do not leak in from music apps', () => {
	for (const month of allMonthIds) {
		const info = monthInfoFor(finance, month);
		assert([...info.low, ...info.missing].every((id) => finance.has(id)));
	}
	assert(annotationsFor(finance).every((event) => event.apps?.some((id) => finance.has(id))));
});

test('homepage links reconcile to real switch reports between visible apps', () => {
	const ids = new Set(flowNodes.filter((node) => node.observed).map((node) => node.id));
	const connections = overviewConnections(ids);
	assert(connections.length > 0);
	for (const pair of connections) {
		assert(ids.has(pair.s) && ids.has(pair.t) && pair.s !== pair.t);
		const expected = switches.filter((row) => (row.s === pair.s && row.t === pair.t) || (row.s === pair.t && row.t === pair.s)).reduce((sum, row) => sum + row.n, 0);
		assert.equal(pair.count, expected);
	}
});

test('review totals sum distinct observing apps only once', () => {
	const observers = pairReviewObservers('chime', 'cash-app');
	assert(observers.size > 0);
	const expected = [...observers].reduce((sum, id) => sum + volumeOf(id, allMonthIds), 0);
	assert.equal(pairReviewVolume('chime', 'cash-app', allMonthIds), expected);
});
