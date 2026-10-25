import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import test from 'node:test';
import { findInsightEntry, insightDateLabel, insightReviewSamples, insightTopicKey, parseAppInsights, parseInsightCatalog } from '../src/lib/data/insights.ts';
import { buildInsightCatalog } from './insights-catalog.ts';

const read = (name) => JSON.parse(readFileSync(new URL(`../static/data/insights/${name}`, import.meta.url), 'utf8'));
const report = read('aggregation_validation_report.json');
const generated = buildInsightCatalog();
const catalog = parseInsightCatalog(generated);

test('catalog discovers all app files even when the latest report covers only one run', () => {
	const files = readdirSync(new URL('../static/data/insights/', import.meta.url)).filter((name) => /^[a-z0-9]+(?:-[a-z0-9]+)*\.json$/.test(name) && name !== 'catalog.json');
	assert.equal(catalog.length, files.length);
	assert.deepEqual(new Set(catalog.map((entry) => entry.filename)), new Set(files));
	assert(catalog.every((entry) => !entry.filename.includes('/') && !entry.filename.includes('\\')));
	assert.equal(catalog.reduce((sum, app) => sum + app.reviewCount, 0), generated.total_reviews);
});

test('a partial report does not falsely mark other exports as failed or verified', () => {
	const reported = parseInsightCatalog(report);
	for (const entry of catalog) {
		const match = reported.find((item) => item.id === entry.id);
		const data = read(entry.filename);
		const current = match && report.generated_at === data.generated_at && match.reviewCount === entry.reviewCount && match.topicCount === entry.topicCount;
		assert.equal(entry.checksPassed, current ? match.checksPassed : null);
	}
});

for (const entry of catalog) {
	test(`${entry.name}: final export parses and reconciles`, () => {
		const data = parseAppInsights(read(entry.filename), entry);
		assert.equal(data.app.id, entry.id);
		assert.equal(data.summary.total_reviews, entry.reviewCount);
		assert.equal(data.topics.length, entry.topicCount);
		assert.equal(data.monthly_reviews.reduce((sum, month) => sum + month.review_count, 0) + data.summary.missing_date_count, entry.reviewCount);
		const samples = insightReviewSamples(data);
		assert.equal(new Set(samples.map((sample) => sample.review_key)).size, samples.length);
		assert(samples.every((sample) => !('stars' in sample) && !('date' in sample)));
	});
}

test('legacy map IDs resolve to the canonical export identity', () => {
	for (const [id, expected] of [['bofa', 'bank-of-america-mobile-banking'], ['capital-one', 'capital-one-mobile'], ['credit-karma', 'intuit-credit-karma'], ['cash-app', 'cash-app']]) {
		assert.equal(findInsightEntry({ id, name: '' }, catalog)?.id, expected);
	}
	assert.equal(findInsightEntry({ id: 'different-backend-id', name: 'Capital One Mobile' }, catalog)?.id, 'capital-one-mobile');
	assert.equal(findInsightEntry({ id: 'no-export-for-this-test-app', name: 'No export for this test app' }, catalog), undefined);
});

test('app-scoped topic IDs cannot collide across apps', () => {
	assert.notEqual(insightTopicKey('chime', 'topic-0001'), insightTopicKey('paypal', 'topic-0001'));
});

test('calendar dates do not move back one day in western timezones', () => {
	assert.equal(insightDateLabel('2024-07-13'), 'Jul 13, 2024');
	assert.equal(insightDateLabel('2026-05-18'), 'May 18, 2026');
	assert.equal(insightDateLabel(null), 'Unknown date');
});

test('null topic ratings and zero-match topics are preserved', () => {
	const entry = catalog.find((entry) => entry.id === 'chime');
	const fixture = read(entry.filename);
	const topic = fixture.topics[0];
	Object.assign(topic, { review_count: 0, rated_review_count: 0, missing_rating_count: 0, missing_date_count: 0, percentage_of_all_reviews: 0, average_stars: null, mean_accepted_cosine_similarity: null, representative_reviews: [] });
	topic.star_distribution = topic.star_distribution.map((bucket) => ({ ...bucket, count: 0 }));
	topic.monthly = topic.monthly.map((month) => ({ ...month, review_count: 0, rated_review_count: 0, percentage_of_monthly_reviews: 0, average_stars: null, change_percentage_points: null }));
	topic.trend = { label: 'insufficient_data', change_percentage_points: null, latest_complete_month: null, previous_complete_month: null };
	const data = parseAppInsights(fixture, entry);
	const empty = data.topics[0];
	assert.equal(empty.average_stars, null);
	assert.equal(empty.representative_reviews.length, 0);
});

test('duplicate topic IDs are rejected within an app, not across different apps', () => {
	const entry = catalog.find((entry) => entry.id === 'chime');
	const data = read(entry.filename);
	data.topics[1].topic_id = data.topics[0].topic_id;
	assert.throws(() => parseAppInsights(data, entry), /Duplicate topic ID/);
});

test('wrong-app files and unsupported schemas cannot silently fall back to demo data', () => {
	const chime = catalog.find((entry) => entry.id === 'chime');
	assert.throws(() => parseAppInsights(read('paypal.json'), chime), /requested app/);
	const data = read('chime.json');
	data.schema_version = 'unknown';
	assert.throws(() => parseAppInsights(data, chime), /Unsupported/);
});

test('inconsistent totals and unsafe filenames are rejected', () => {
	const data = read('chime.json');
	data.monthly_reviews[0].review_count++;
	assert.throws(() => parseAppInsights(data, catalog.find((entry) => entry.id === 'chime')), /reconcile/);
	const badReport = structuredClone(report);
	badReport.apps[0].output = '/some/path/not-a-file.json?redirect=elsewhere';
	assert.throws(() => parseInsightCatalog(badReport), /Unsafe/);
});

test('a representative review appears once with all of its app-scoped topic tags', () => {
	const entry = catalog.find((entry) => entry.id === 'chime');
	const data = parseAppInsights(read(entry.filename), entry);
	const sample = data.topics[0].representative_reviews[0];
	data.topics[1].representative_reviews.push({ ...sample });
	const deduped = insightReviewSamples(data).filter((review) => review.review_key === sample.review_key);
	assert.equal(deduped.length, 1);
	assert(deduped[0].topics.some((topic) => topic.id === insightTopicKey(data.app.id, data.topics[0].topic_id)));
	assert(deduped[0].topics.some((topic) => topic.id === insightTopicKey(data.app.id, data.topics[1].topic_id)));
});
