import assert from 'node:assert/strict';
import test from 'node:test';
import { hotSingleton } from '../src/lib/utils/hot-state.ts';

test('timestamped module imports share the same selected app and insights', () => {
	const data = {};
	const context = () => ({ data, accept() {} });
	let created = 0;
	const create = () => { created++; return { selected: null, insights: {} }; };
	const inspector = hotSingleton(context(), 'studio', create, () => {});
	inspector.selected = 'chime';
	inspector.insights.chime = { totalReviews: 43813 };
	const overview = hotSingleton(context(), 'studio', create, () => {});
	assert.equal(overview, inspector);
	assert.equal(overview.selected, 'chime');
	assert.equal(overview.insights.chime.totalReviews, 43813);
	assert.equal(created, 1);
});

test('a store update invokes the reload callback', () => {
	let update;
	let reloads = 0;
	hotSingleton({ data: {}, accept(callback) { update = callback; } }, 'studio', () => ({}), () => reloads++);
	update();
	assert.equal(reloads, 1);
});

test('server and production creation do not share a hot registry', () => {
	const first = hotSingleton(undefined, 'studio', () => ({}), () => {});
	const second = hotSingleton(undefined, 'studio', () => ({}), () => {});
	assert.notEqual(first, second);
});

test('independent stores keep independent instances', () => {
	const hot = { data: {}, accept() {} };
	const studio = hotSingleton(hot, 'studio', () => ({}), () => {});
	const flows = hotSingleton(hot, 'flowsState', () => ({}), () => {});
	assert.notEqual(studio, flows);
});
