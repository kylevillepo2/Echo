import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'nlp'))
from aggregate_topics import (aggregate_rows, atomic_json, discover_runs,
                             find_refinement, select_trend, tagging_paths,
                             TAGGED, TOPIC_META, TAG_REPORT,
                             LEGACY_TAGGED, LEGACY_TOPIC_META, LEGACY_TAG_REPORT)


TOPICS = [
    {'topic_id': 'topic-0001', 'canonical_name': 'Transfers', 'definition': 'Transfer experience',
     'parent_category_id': 'payments', 'parent_category_name': 'Payments'},
    {'topic_id': 'topic-0002', 'canonical_name': 'Login', 'definition': 'Login experience',
     'parent_category_id': 'access', 'parent_category_name': 'Access'},
]


def review(key, date, stars, topics):
    return {'review_key': key, 'feedback_id': key, 'data_source': 'gplay',
            'feedback_date': date, 'stars': stars, 'full_text': f'Review {key}', 'topics': topics}


def tag(topic, similarity):
    return {'topic_id': topic, 'similarity': similarity}


def aggregate(rows, **kwargs):
    return aggregate_rows(rows, TOPICS, app_name='Example App', app_id='example-1',
                          run_slug='example-run', taxonomy_version='abc',
                          method='semantic_similarity', representation='description',
                          embedding_model='fixture', threshold=.4,
                          generated_at='2026-05-15T12:00:00Z', **kwargs)


class AggregateTopicsTests(unittest.TestCase):
    def test_discovers_legacy_cash_app_tagging(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            root = base / 'cash-app'
            for path in (LEGACY_TAGGED, LEGACY_TOPIC_META, LEGACY_TAG_REPORT):
                target = root / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b'fixture')
            index = root / 'review-embeddings/app_index.json'
            index.parent.mkdir()
            index.write_text('{"Cash App": {}}')
            self.assertEqual(discover_runs(base), [('Cash App', root)])
            self.assertEqual(tagging_paths(root), tuple(root / p for p in
                             (LEGACY_TAGGED, LEGACY_TOPIC_META, LEGACY_TAG_REPORT)))

    def test_prefers_workflow_and_does_not_mix_incomplete_layouts(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.assertIsNone(tagging_paths(root))
            for path in (TAGGED, TOPIC_META, TAG_REPORT,
                         LEGACY_TAGGED, LEGACY_TOPIC_META, LEGACY_TAG_REPORT):
                target = root / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b'fixture')
            self.assertEqual(tagging_paths(root), tuple(root / p for p in (TAGGED, TOPIC_META, TAG_REPORT)))
            (root / TOPIC_META).unlink()
            with self.assertRaisesRegex(ValueError, 'Incomplete tagging output'):
                tagging_paths(root)

    def test_multilabel_dedup_denominators_missing_data_and_zero_month(self):
        rows = [
            review('r1', '2026-01-01 10:00:00', '5', [tag('topic-0001', .7), tag('topic-0001', .6), tag('topic-0002', .4)]),
            review('r2', '2026-01-31 10:00:00', '1', []),
            review('r3', '2026-03-01 10:00:00', None, [tag('topic-0001', .5)]),
            review('r4', '2026-04-30 10:00:00', '3', [tag('topic-0001', .8), tag('topic-0002', .9)]),
            review('r5', None, '2', [tag('topic-0002', .6)]),
        ]
        data, validation = aggregate(rows, min_monthly_reviews=1, min_topic_count=1)
        self.assertEqual(data['summary']['total_reviews'], 5)
        self.assertEqual(data['summary']['reviews_with_topics'], 4)
        self.assertEqual(data['summary']['tagging_coverage_percent'], 80)
        self.assertEqual(data['summary']['average_stars'], 2.75)
        self.assertEqual(data['summary']['missing_rating_count'], 1)
        self.assertEqual(data['summary']['missing_date_count'], 1)
        self.assertEqual([(m['month'], m['review_count']) for m in data['monthly_reviews']],
                         [('2026-01', 2), ('2026-02', 0), ('2026-03', 1), ('2026-04', 1)])
        by_id = {topic['topic_id']: topic for topic in data['topics']}
        self.assertEqual(set(by_id), {'topic-0001', 'topic-0002'})
        self.assertEqual(by_id['topic-0001']['review_count'], 3)
        self.assertEqual(by_id['topic-0001']['percentage_of_all_reviews'], 60)
        self.assertEqual(by_id['topic-0001']['average_stars'], 4)
        self.assertEqual(by_id['topic-0001']['mean_accepted_cosine_similarity'], round((.7+.5+.8)/3, 4))
        self.assertEqual(by_id['topic-0002']['missing_date_count'], 1)
        self.assertEqual(by_id['topic-0002']['review_count'], 3)
        self.assertEqual(by_id['topic-0001']['monthly'][0]['percentage_of_monthly_reviews'], 50)
        self.assertIsNone(by_id['topic-0001']['monthly'][1]['percentage_of_monthly_reviews'])
        self.assertIsNone(by_id['topic-0001']['monthly'][2]['change_percentage_points'])
        self.assertEqual(by_id['topic-0001']['monthly'][3]['change_percentage_points'], 0)
        self.assertTrue(validation['checks']['topic_review_reconciliation'])
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / 'example.json'
            atomic_json(output, data)
            self.assertEqual(json.loads(output.read_text())['topics'][0]['topic_id'], 'topic-0001')

    def test_partial_months_and_trend_thresholds(self):
        data, _ = aggregate([
            review('a', '2026-01-15', '5', []),
            review('b', '2026-02-10', '2', [tag('topic-0001', .8)]),
        ], min_monthly_reviews=1, min_topic_count=1)
        self.assertEqual([m['month'] for m in data['monthly_reviews'] if m['partial_month']],
                         ['2026-01', '2026-02'])
        self.assertEqual(data['topics'][0]['trend']['label'], 'insufficient_data')
        monthly = [
            {'month': '2026-03', 'partial_month': False, 'total_app_reviews': 100,
             'review_count': 1, 'percentage_of_monthly_reviews': 1},
            {'month': '2026-04', 'partial_month': False, 'total_app_reviews': 100,
             'review_count': 6, 'percentage_of_monthly_reviews': 6},
        ]
        self.assertEqual(select_trend(monthly, 30, 5, 2)['label'], 'increasing')
        self.assertEqual(select_trend(monthly, 30, 5, 2)['change_percentage_points'], 5)
        self.assertEqual(select_trend(list(reversed(monthly)), 30, 5, 2)['label'], 'decreasing')
        self.assertEqual(select_trend(monthly, 30, 10, 2)['label'], 'insufficient_data')

    def test_rejects_duplicate_reviews_and_unknown_topics(self):
        a = review('a', '2026-01-01', '5', [])
        with self.assertRaisesRegex(ValueError, 'duplicate review_key'):
            aggregate([a, a])
        with self.assertRaisesRegex(ValueError, 'Unknown or unapproved'):
            aggregate([review('b', '2026-01-01', '5', [tag('topic-9999', .8)])])

    def test_all_missing_dates_remain_in_overall_and_topic_totals(self):
        data, validation = aggregate([review('a', None, '4', [tag('topic-0001', .7)])])
        self.assertIsNone(data['summary']['earliest_review_date'])
        self.assertEqual(data['monthly_reviews'], [])
        self.assertEqual(data['topics'][0]['review_count'], 1)
        self.assertEqual(data['topics'][0]['missing_date_count'], 1)
        self.assertEqual(data['topics'][0]['monthly'], [])
        self.assertTrue(validation['checks']['topic_review_reconciliation'])

    def test_discovers_external_refinement_by_cluster_hash(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            run = base / 'pipeline-runs/paypal'
            clusters = run / 'aspect-clusters'
            clusters.mkdir(parents=True)
            source = clusters / 'aspect_clusters.parquet'
            source.write_bytes(b'cluster assignments')
            target = base / 'refined-topics/paypal-global'
            target.mkdir(parents=True)
            (target / 'canonical_topics.json').write_text('{}')
            (target / 'refined_aspects.parquet').write_bytes(b'labels')
            import hashlib
            (target / 'run_config.json').write_text(json.dumps({
                'source_assignment_sha256': hashlib.sha256(source.read_bytes()).hexdigest()}))
            self.assertEqual(find_refinement(run), target.resolve())


if __name__ == '__main__':
    unittest.main()
