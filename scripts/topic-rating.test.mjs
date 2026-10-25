import assert from 'node:assert/strict';
import test from 'node:test';
import { topicAverageLabel, topicRatingGroup } from '../src/lib/utils/topic-rating.ts';

const topic = (average, count = 10) => ({ average_stars: average, rated_review_count: count });

test('average rating groups have explicit boundaries', () => {
	for (const average of [1, 2, 2.9999]) assert.equal(topicRatingGroup(topic(average)), 'negative');
	for (const average of [3, 3.5, 3.9999]) assert.equal(topicRatingGroup(topic(average)), 'mixed');
	for (const average of [4, 4.5, 5]) assert.equal(topicRatingGroup(topic(average)), 'positive');
});

test('missing ratings are not treated as negative or zero stars', () => {
	for (const value of [topic(null), topic(4, 0), topic(4, -1), topic(4, NaN), topic(NaN), topic(0), topic(6)]) {
		assert.equal(topicRatingGroup(value), 'unrated');
		assert.equal(topicAverageLabel(value), 'No ratings');
	}
});

test('display rounding cannot contradict the rating group', () => {
	assert.equal(topicAverageLabel(topic(3.9999)), '3.9999★ avg');
	assert.equal(topicAverageLabel(topic(2.9999)), '2.9999★ avg');
	assert.equal(topicAverageLabel(topic(4)), '4.00★ avg');
	assert.equal(topicAverageLabel(topic(3.4267)), '3.43★ avg');
});

test('topic names do not influence rating-based grouping', () => {
	assert.equal(topicRatingGroup({ ...topic(1.5), name: 'Excellent service' }), 'negative');
	assert.equal(topicRatingGroup({ ...topic(4.8), name: 'Account problems' }), 'positive');
});
