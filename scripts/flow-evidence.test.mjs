import assert from 'node:assert/strict';
import test from 'node:test';
import { filterFlowEvidence } from '../src/lib/utils/flow-evidence.ts';

const examples = [
	{ q: 'Ads and pricing', r: ['ads', 'price'], m: '2025-01' },
	{ q: 'Missing songs', r: ['catalog'], m: '2025-01' },
	{ q: 'Too many ads', r: ['ads'], m: '2025-02' }
];

test('issue selection shows only matching evidence', () => {
	assert.deepEqual(filterFlowEvidence(examples, 'ads', 'all'), [examples[0], examples[2]]);
	assert.deepEqual(filterFlowEvidence(examples, 'catalog', 'all'), [examples[1]]);
});

test('issue and period filters apply together', () => {
	assert.deepEqual(filterFlowEvidence(examples, 'ads', '2025-01'), [examples[0]]);
	assert.deepEqual(filterFlowEvidence(examples, null, '2025-01'), [examples[0], examples[1]]);
});

test('all-month fallback keeps the selected issue filter', () => {
	assert.deepEqual(filterFlowEvidence(examples, 'ads', '2025-03', true), [examples[0], examples[2]]);
});

test('missing evidence never falls back to unrelated reviews', () => {
	assert.deepEqual(filterFlowEvidence(examples, 'bugs_performance', 'all'), []);
	assert.deepEqual(filterFlowEvidence(examples, 'ads', '2025-03'), []);
	assert.equal(examples.length, 3);
});
