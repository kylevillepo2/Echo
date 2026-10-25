import assert from 'node:assert/strict';
import test from 'node:test';
import { timelineIndex, timelineWindow, shiftTimelineWindow, timelineMonths } from '../src/lib/utils/timeline.ts';

test('scrubbing selects nearest month and reaches both ends', () => {
	assert.equal(timelineIndex(100, 100, 460, 24), 0);
	assert.equal(timelineIndex(560, 100, 460, 24), 23);
	assert.equal(timelineIndex(340, 100, 460, 24), 12);
	assert.equal(timelineIndex(331, 100, 460, 24), 12);
	assert.equal(timelineIndex(329, 100, 460, 24), 11);
});

test('captured drags outside chart clamp safely', () => {
	assert.equal(timelineIndex(-400, 100, 460, 24), 0);
	assert.equal(timelineIndex(2000, 100, 460, 24), 23);
	assert.equal(timelineIndex(10, 0, 0, 24), 0);
	assert.equal(timelineIndex(10, 0, 100, 1), 0);
	assert.equal(timelineIndex(10, 0, 100, 0), 0);
});

test('range selections normalize reverse drags and clamp both boundaries', () => {
	assert.deepEqual(timelineWindow(16, 4, 24), [4, 16]);
	assert.deepEqual(timelineWindow(-10, 40, 24), [0, 23]);
	assert.deepEqual(timelineWindow(5, 5, 24), [5, 5]);
});

test('moving a selection keeps its width even against chart boundaries', () => {
	assert.deepEqual(shiftTimelineWindow(4, 8, 3, 24), [7, 11]);
	assert.deepEqual(shiftTimelineWindow(4, 8, -20, 24), [0, 4]);
	assert.deepEqual(shiftTimelineWindow(4, 8, 40, 24), [19, 23]);
});

test('selected windows include every month and never leak outside the range', () => {
	const months = ['2025-01', '2025-02', '2025-03', '2025-04'];
	assert.deepEqual(timelineMonths(months, '2025-02', '2025-03'), months.slice(1, 3));
	assert.deepEqual(timelineMonths(months, '2025-03', '2025-02'), months.slice(1, 3));
	assert.deepEqual(timelineMonths(months, '2025-02', null), ['2025-02']);
	assert.deepEqual(timelineMonths(months, 'all', null), months);
	assert.deepEqual(timelineMonths(months, 'invalid', null), []);
});
