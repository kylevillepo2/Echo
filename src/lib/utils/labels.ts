interface LabelNode {
	id: string;
	x: number;
	y: number;
	radius: number;
}

interface Box {
	left: number;
	top: number;
	right: number;
	bottom: number;
}

export interface NodeLabel {
	x: number;
	y: number;
	anchor: 'start' | 'middle' | 'end';
	visible: boolean;
}

/** Place text around existing nodes, without moving the network layout. */
export function layoutNodeLabels(
	nodes: LabelNode[],
	textFor: (node: LabelNode) => string,
	fontSize: number,
	gap: number
): Map<string, NodeLabel> {
	const labels = new Map<string, NodeLabel>();
	const occupied: Box[] = [];
	const ordered = [...nodes].sort((a, b) => b.radius - a.radius || a.id.localeCompare(b.id));

	for (const node of ordered) {
		const width = textFor(node).length * fontSize * 0.65;
		const offset = node.radius + 3.5 + gap;
		const candidates: Omit<NodeLabel, 'visible'>[] = [
			{ x: 0, y: offset + fontSize, anchor: 'middle' },
			{ x: 0, y: -offset, anchor: 'middle' },
			{ x: offset, y: fontSize * 0.35, anchor: 'start' },
			{ x: -offset, y: fontSize * 0.35, anchor: 'end' },
			{ x: offset * 0.75, y: offset * 0.75 + fontSize, anchor: 'start' },
			{ x: -offset * 0.75, y: -offset * 0.75, anchor: 'end' },
			{ x: offset * 0.75, y: -offset * 0.75, anchor: 'start' },
			{ x: -offset * 0.75, y: offset * 0.75 + fontSize, anchor: 'end' }
		];

		let placed = false;
		for (const candidate of candidates) {
			const start = candidate.anchor === 'start' ? 0 : candidate.anchor === 'end' ? -width : -width / 2;
			const box = {
				left: node.x + candidate.x + start - gap / 3,
				right: node.x + candidate.x + start + width + gap / 3,
				top: node.y + candidate.y - fontSize - gap / 3,
				bottom: node.y + candidate.y + fontSize * 0.3 + gap / 3
			};
			const overlapsLabel = occupied.some((other) =>
				box.left < other.right && box.right > other.left && box.top < other.bottom && box.bottom > other.top
			);
			const overlapsNode = nodes.some((other) => {
				const x = Math.max(box.left, Math.min(other.x, box.right));
				const y = Math.max(box.top, Math.min(other.y, box.bottom));
				return Math.hypot(x - other.x, y - other.y) < other.radius + 3.5 + gap / 3;
			});
			if (overlapsLabel || overlapsNode) continue;
			labels.set(node.id, { ...candidate, visible: true });
			occupied.push(box);
			placed = true;
			break;
		}
		// Keep crowded names available in tooltips rather than drawing overlapping text.
		if (!placed) labels.set(node.id, { ...candidates[0], visible: false });
	}

	return labels;
}
