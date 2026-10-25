import assert from 'node:assert/strict';
import test from 'node:test';
import { countBarWidth } from '../src/lib/utils/count-bars.ts';

test('the largest review count fills the bar and all others use that count scale', () => {
	assert.equal(countBarWidth(12000, 12000), 100);
	assert.equal(countBarWidth(6000, 12000), 50);
	assert.equal(countBarWidth(3000, 12000), 25);
	assert.equal(countBarWidth(0, 12000), 0);
});

test('empty counts stay empty and invalid inputs cannot overflow a bar', () => {
	assert.equal(countBarWidth(0, 0), 0);
	assert.equal(countBarWidth(100, 0), 0);
	assert.equal(countBarWidth(-1, 100), 0);
	assert.equal(countBarWidth(200, 100), 100);
	assert.equal(countBarWidth(NaN, 100), 0);
	assert.equal(countBarWidth(100, Infinity), 0);
});
