/* Formatting helpers. Kept tiny and dependency-free. */

export function fmtCount(n: number): string {
	if (!Number.isFinite(n)) return '—';
	if (n < 1000) return String(Math.round(n));
	if (n < 1_000_000) {
		const k = n / 1000;
		return `${k >= 100 ? Math.round(k) : k.toFixed(k >= 10 ? 0 : 1)}k`;
	}
	if (n < 1_000_000_000) {
		const m = n / 1_000_000;
		return `${m >= 10 ? Math.round(m) : m.toFixed(1)}M`;
	}
	const b = n / 1_000_000_000;
	return `${b >= 10 ? Math.round(b) : b.toFixed(1)}B`;
}

/** e.g. "318k/day" */
export function fmtRate(n: number): string {
	return `${fmtCount(n)}/day`;
}

/** e.g. "+5.2%" from a fraction */
export function fmtDeltaPct(x: number, digits = 1): string {
	if (!Number.isFinite(x)) return '—';
	return `${x > 0 ? '+' : ''}${(x * 100).toFixed(digits)}%`;
}

/** e.g. "+0.42" */
export function fmtR(r: number): string {
	if (!Number.isFinite(r)) return '—';
	return `${r > 0 ? '+' : ''}${r.toFixed(2)}`;
}

/** "leads 1w" / "lags 2w" / "same week" */
export function fmtLag(lag: number): string {
	if (!lag) return 'same week';
	return lag > 0 ? `leads ${lag}w` : `lags ${-lag}w`;
}

export function fmtFull(n: number): string {
	return new Intl.NumberFormat('en-US').format(Math.round(n));
}

export function fmtPct(x: number, digits = 0): string {
	return `${(x * 100).toFixed(digits)}%`;
}

export function fmtScore(score: number): string {
	return Math.round(score).toString();
}

export function fmtDelta(n: number, digits = 1): string {
	const v = n.toFixed(digits);
	return n > 0 ? `+${v}` : v;
}

export function fmtDate(iso: string, style: 'short' | 'long' = 'short'): string {
	const d = new Date(iso);
	if (Number.isNaN(d.getTime())) return iso;
	if (style === 'long') {
		return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
	}
	return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
}

export function relTime(iso: string): string {
	const d = new Date(iso).getTime();
	if (Number.isNaN(d)) return '';
	const diff = Date.now() - d;
	const day = 86_400_000;
	if (diff < day) {
		const h = Math.max(1, Math.round(diff / 3_600_000));
		return `${h}h ago`;
	}
	if (diff < 30 * day) return `${Math.round(diff / day)}d ago`;
	if (diff < 365 * day) return `${Math.round(diff / (30 * day))}mo ago`;
	return `${Math.round(diff / (365 * day))}y ago`;
}

export function truncate(text: string, max = 140): string {
	if (text.length <= max) return text;
	return `${text.slice(0, max - 1).trimEnd()}…`;
}

export function initials(name: string): string {
	const parts = name.replace(/[^a-zA-Z0-9 ]/g, ' ').trim().split(/\s+/);
	if (parts.length === 0) return '?';
	if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
	return (parts[0][0] + parts[1][0]).toUpperCase();
}

export function slug(name: string): string {
	return name
		.toLowerCase()
		.replace(/[^a-z0-9]+/g, '-')
		.replace(/^-|-$/g, '');
}
