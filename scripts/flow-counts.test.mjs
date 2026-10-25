import assert from 'node:assert/strict';
import test from 'node:test';
import { reportedSwitchCount } from '../src/lib/utils/flow-counts.ts';

test('reported switches include moves back without a separate count', () => {
	assert.equal(reportedSwitchCount({ switch: 171, return: 8 }), 179);
	assert.equal(reportedSwitchCount({ return: 8 }), 8);
});

test('intentions and preferences never inflate the switch count', () => {
	assert.equal(reportedSwitchCount({ switch: 10, return: 2, intent: 30, preference: 40 }), 12);
	assert.equal(reportedSwitchCount({ intent: 30, preference: 40 }), 0);
	assert.equal(reportedSwitchCount({}), 0);
});
