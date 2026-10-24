/* Colour helpers — every colour is paired with a number or label in the UI. */

export const CATEGORY_ACCENTS = [
	'#c8ff3c',
	'#45e6ff',
	'#9d7bff',
	'#ffb545',
	'#ff4d7d',
	'#3ddc97',
	'#ff8a4d',
	'#6c8cff',
	'#e0e0e6',
	'#b0ff8a',
	'#ff6ad5',
	'#7ad8c8'
];

export function accentFor(index: number): string {
	return CATEGORY_ACCENTS[index % CATEGORY_ACCENTS.length];
}

export function platformColor(platform: string): string {
	if (platform === 'ios') return 'var(--cyan)';
	if (platform === 'android') return 'var(--lime)';
	return 'var(--violet)';
}

export function platformLabel(platform: string): string {
	if (platform === 'ios') return 'iOS';
	if (platform === 'android') return 'Android';
	return 'iOS + Android';
}

/** 0..100 → red / amber / lime / green. Always shown next to a numeric score. */
export function receptionColor(score: number): string {
	const s = Math.max(0, Math.min(100, score));
	if (s < 35) return '#ff4d5e';
	if (s < 50) return '#ff6a4d';
	if (s < 62) return '#ffb545';
	if (s < 74) return '#d8e84a';
	if (s < 86) return '#c8ff3c';
	return '#3ddc97';
}

export function receptionLabel(score: number): string {
	if (score >= 82) return 'Excellent';
	if (score >= 70) return 'Healthy';
	if (score >= 55) return 'Mixed';
	if (score >= 40) return 'Strained';
	return 'Hostile';
}

export function sentimentColor(s: string): string {
	if (s === 'positive') return 'var(--pos)';
	if (s === 'negative') return 'var(--neg)';
	return 'var(--neu)';
}

export function sentimentFromStars(stars: number): 'positive' | 'neutral' | 'negative' {
	if (stars >= 4) return 'positive';
	if (stars <= 2) return 'negative';
	return 'neutral';
}
