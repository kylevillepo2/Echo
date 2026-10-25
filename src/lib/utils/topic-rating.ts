export type TopicRatingGroup = 'positive' | 'negative' | 'mixed' | 'unrated';

interface RatedTopic {
	average_stars: number | null;
	rated_review_count: number;
}

export const topicRatingGroups = [
	{ id: 'positive', label: 'Positive review topics', range: '4.0★ and above', color: 'var(--pos)' },
	{ id: 'negative', label: 'Negative review topics', range: 'Below 3.0★', color: 'var(--neg)' },
	{ id: 'mixed', label: 'Mixed review topics', range: '3.0★ to under 4.0★', color: 'var(--amber)' },
	{ id: 'unrated', label: 'Unrated topics', range: 'No rated reviews', color: 'var(--muted)' }
] satisfies { id: TopicRatingGroup; label: string; range: string; color: string }[];

/** Rating-based organization, not sentiment inferred from topic names or cosine scores. */
export function topicRatingGroup(topic: RatedTopic): TopicRatingGroup {
	const average = topic.average_stars;
	if (!Number.isSafeInteger(topic.rated_review_count) || topic.rated_review_count <= 0 || average === null || !Number.isFinite(average) || average < 1 || average > 5) return 'unrated';
	if (average >= 4) return 'positive';
	if (average < 3) return 'negative';
	return 'mixed';
}

export function topicAverageLabel(topic: RatedTopic): string {
	if (topicRatingGroup(topic) === 'unrated') return 'No ratings';
	const average = topic.average_stars!;
	const rounded = Number(average.toFixed(2));
	// Do not display 4.00★ for a mixed topic whose actual mean is 3.9999★.
	const crossesBoundary = [3, 4].some((boundary) => average < boundary && rounded >= boundary);
	return `${crossesBoundary ? String(average) : average.toFixed(2)}★ avg`;
}
