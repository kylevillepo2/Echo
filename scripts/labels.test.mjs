import assert from 'node:assert/strict';
import test from 'node:test';
import { layoutNodeLabels } from '../src/lib/utils/labels.ts';

function visibleBoxes(nodes, labels, fontSize, gap) {
	return nodes.flatMap((node) => {
		const label = labels.get(node.id);
		if (!label?.visible) return [];
		const width = node.id.length * fontSize * 0.65;
		const start = label.anchor === 'start' ? 0 : label.anchor === 'end' ? -width : -width / 2;
		return [{
			left: node.x + label.x + start - gap / 3,
			right: node.x + label.x + start + width + gap / 3,
			top: node.y + label.y - fontSize - gap / 3,
			bottom: node.y + label.y + fontSize * 0.3 + gap / 3
		}];
	});
}

function assertSeparated(boxes) {
	for (let i = 0; i < boxes.length; i++) {
		for (let j = i + 1; j < boxes.length; j++) {
			const a = boxes[i];
			const b = boxes[j];
			assert(!(a.left < b.right && a.right > b.left && a.top < b.bottom && a.bottom > b.top));
		}
	}
}

test('labels avoid each other and app nodes without moving the network', () => {
	const nodes = Array.from({ length: 10 }, (_, index) => ({
		id: `App name ${index}`,
		x: (index % 3) * 45,
		y: Math.floor(index / 3) * 45,
		radius: 10
	}));
	const original = structuredClone(nodes);
	const labels = layoutNodeLabels(nodes, (node) => node.id, 10, 6);
	const boxes = visibleBoxes(nodes, labels, 10, 6);
	assert(boxes.length > 0);
	assertSeparated(boxes);
	for (const box of boxes) {
		for (const node of nodes) {
			const x = Math.max(box.left, Math.min(node.x, box.right));
			const y = Math.max(box.top, Math.min(node.y, box.bottom));
			assert(Math.hypot(x - node.x, y - node.y) >= node.radius + 5.5);
		}
	}
	assert.deepEqual(nodes, original);
});

test('crowded labels are suppressed instead of overlapping', () => {
	const nodes = Array.from({ length: 20 }, (_, index) => ({
		id: `Very crowded app ${index}`, x: 0, y: 0, radius: 12
	}));
	const labels = layoutNodeLabels(nodes, (node) => node.id, 10, 6);
	assert([...labels.values()].some((label) => !label.visible));
	assertSeparated(visibleBoxes(nodes, labels, 10, 6));
});

test('label placement is deterministic regardless of input order', () => {
	const nodes = [
		{ id: 'Duolingo', x: 0, y: 0, radius: 12 },
		{ id: 'Hoopla', x: 35, y: 15, radius: 12 }
	];
	assert.deepEqual(
		layoutNodeLabels(nodes, (node) => node.id, 10, 6),
		layoutNodeLabels([...nodes].reverse(), (node) => node.id, 10, 6)
	);
});
