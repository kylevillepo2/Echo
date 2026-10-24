/* ============================================================
   A small deterministic force layout.

   No d3 dependency: for the node counts this UI ships with
   (tens to a few hundred) an O(n²) repulsion pass is plenty
   and it keeps the bundle tiny.
   ============================================================ */

export interface SimNode {
	id: string;
	kind: 'app';
	x: number;
	y: number;
	vx: number;
	vy: number;
	radius: number;
	charge: number;
	/** category cluster this node belongs to */
	clusterId?: string;
	/** pinned position (dragging) */
	fx?: number | null;
	fy?: number | null;
}

export interface SimLink {
	source: SimNode;
	target: SimNode;
	distance: number;
	strength: number;
	kind?: 'similar';
	/** similarity 0..1 for semantic edges */
	score?: number;
}

export interface SimulationOptions {
	centerStrength?: number;
	repulsion?: number;
	damping?: number;
	minAlpha?: number;
	/** category anchor positions used to keep clusters together */
	clusterCenters?: Map<string, { x: number; y: number }>;
	clusterStrength?: number;
	/** extra space kept between node edges during collision resolution */
	collisionPadding?: number;
}

export class Simulation {
	nodes: SimNode[];
	links: SimLink[];
	alpha = 1;
	centerStrength: number;
	repulsion: number;
	damping: number;
	minAlpha: number;
	clusterCenters?: Map<string, { x: number; y: number }>;
	clusterStrength: number;
	collisionPadding: number;

	constructor(nodes: SimNode[], links: SimLink[], options: SimulationOptions = {}) {
		this.nodes = nodes;
		this.links = links;
		this.centerStrength = options.centerStrength ?? 0.0011;
		this.repulsion = options.repulsion ?? 16000;
		this.damping = options.damping ?? 0.85;
		this.minAlpha = options.minAlpha ?? 0.01;
		this.clusterCenters = options.clusterCenters;
		this.clusterStrength = options.clusterStrength ?? 0.018;
		this.collisionPadding = options.collisionPadding ?? 30;
	}

	reheat(alpha = 0.75) {
		this.alpha = Math.max(this.alpha, alpha);
	}

	step() {
		if (this.alpha < this.minAlpha) return false;

		const nodes = this.nodes;
		const alpha = this.alpha;

		// repulsion (Coulomb-ish) + mild collision for large nodes
		for (let i = 0; i < nodes.length; i++) {
			const a = nodes[i];
			for (let j = i + 1; j < nodes.length; j++) {
				const b = nodes[j];
				let dx = b.x - a.x;
				let dy = b.y - a.y;
				let distSq = dx * dx + dy * dy;
				if (distSq < 1) {
					dx = (Math.random() - 0.5) * 2;
					dy = (Math.random() - 0.5) * 2;
					distSq = dx * dx + dy * dy;
				}
				const dist = Math.sqrt(distSq);
				const force = (a.charge * b.charge * this.repulsion) / distSq / 1000;
				const minDist = a.radius + b.radius + this.collisionPadding;
				const push = dist < minDist ? (minDist - dist) * 0.55 : 0;
				const f = force + push;
				const fx = (dx / dist) * f * alpha;
				const fy = (dy / dist) * f * alpha;
				if (a.fx == null) {
					a.vx -= fx / Math.max(1, a.radius / 12);
					a.vy -= fy / Math.max(1, a.radius / 12);
				}
				if (b.fx == null) {
					b.vx += fx / Math.max(1, b.radius / 12);
					b.vy += fy / Math.max(1, b.radius / 12);
				}
			}
		}

		// springs
		for (const link of this.links) {
			const a = link.source;
			const b = link.target;
			const dx = b.x - a.x;
			const dy = b.y - a.y;
			const dist = Math.sqrt(dx * dx + dy * dy) || 1;
			const delta = (dist - link.distance) / dist;
			const f = delta * link.strength * alpha;
			const fx = dx * f;
			const fy = dy * f;
			if (a.fx == null) {
				a.vx += fx;
				a.vy += fy;
			}
			if (b.fx == null) {
				b.vx -= fx;
				b.vy -= fy;
			}
		}

		// centering + cluster anchors + integration
		for (const n of nodes) {
			if (n.fx != null && n.fy != null) {
				n.x = n.fx;
				n.y = n.fy;
				n.vx = 0;
				n.vy = 0;
				continue;
			}
			if (this.clusterCenters && n.clusterId) {
				const anchor = this.clusterCenters.get(n.clusterId);
				if (anchor) {
					n.vx += (anchor.x - n.x) * this.clusterStrength * alpha;
					n.vy += (anchor.y - n.y) * this.clusterStrength * alpha;
				}
			}
			n.vx -= n.x * this.centerStrength * alpha;
			n.vy -= n.y * this.centerStrength * alpha;
			n.vx *= this.damping;
			n.vy *= this.damping;
			n.x += n.vx;
			n.y += n.vy;
		}

		this.alpha *= 0.985;
		return this.alpha > this.minAlpha;
	}

	/** run to near-equilibrium before the first paint */
	settle(iterations = 320) {
		for (let i = 0; i < iterations; i++) {
			this.alpha = 1 - i / iterations;
			if (!this.step()) break;
		}
		this.alpha = 0.28;
	}
}

export function boundsOf(nodes: SimNode[]) {
	let minX = Infinity;
	let minY = Infinity;
	let maxX = -Infinity;
	let maxY = -Infinity;
	for (const n of nodes) {
		minX = Math.min(minX, n.x - n.radius);
		minY = Math.min(minY, n.y - n.radius);
		maxX = Math.max(maxX, n.x + n.radius);
		maxY = Math.max(maxY, n.y + n.radius);
	}
	if (!Number.isFinite(minX)) return { minX: -100, minY: -100, maxX: 100, maxY: 100 };
	return { minX, minY, maxX, maxY };
}
