import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq


NLP = Path(__file__).resolve().parents[1] / 'nlp'
sys.path.insert(0, str(NLP))
SPEC = importlib.util.spec_from_file_location('refine_aspects', NLP / 'refine_aspect_clusters.py')
refine = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(refine)


def decision(a, b, relation, confidence='high'):
    return {'cluster_a': a, 'cluster_b': b, 'relationship': relation,
            'confidence': confidence, 'reason': 'Compared the specific issue',
            'proposed_label': 'Ads'}


def options(source, target, **overrides):
    values = dict(input=source, output=target, embedding_root=None, model='fake-model',
                  concurrency=3, dry_run=False, max_clusters=None, similarity_threshold=0.5,
                  noise_threshold=0.5, neighbors=7, resume=False, max_cost_usd=100,
                  analysis_objective=refine.DEFAULT_OBJECTIVE, pair_batch_size=5,
                  topic_batch_size=10, noise_batch_size=8, retries=1,
                  input_cost_per_million=2.0, output_cost_per_million=10.0)
    values.update(overrides)
    return SimpleNamespace(**values)


class FakeClient:
    def __init__(self, fail_once=False):
        self.responses = self
        self.calls = []
        self.fail_once = fail_once

    async def parse(self, **request):
        format_class = request['text_format']
        payload = json.loads(request['input'])
        self.calls.append(format_class.__name__)
        if self.fail_once and format_class is refine.PairBatch:
            self.fail_once = False
            error = RuntimeError('temporary')
            error.status_code = 503
            error.response = SimpleNamespace(headers={'Retry-After': '0'})
            raise error
        if format_class is refine.PairBatch:
            rows = []
            for pair in payload:
                a, b = pair['cluster_a'], pair['cluster_b']
                relation = 'equivalent' if {a, b} == {0, 1} else 'distinct'
                rows.append(decision(a, b, relation))
            parsed = refine.PairBatch.model_validate({'decisions': rows})
        elif format_class is refine.GroupValidation:
            parsed = refine.GroupValidation.model_validate({'groups': [
                {'cluster_ids': payload['cluster_ids'], 'reason': 'Coherent issue'}]})
        elif format_class is refine.ParentPlan:
            parsed = refine.ParentPlan.model_validate({'categories': [
                {'parent_category_id': 'experience', 'parent_category_name': 'Product experience',
                 'definition': 'Feedback about app functionality'}]})
        elif format_class is refine.TopicBatch:
            rows = []
            for topic in payload['topics']:
                generic = 4 in topic['cluster_ids']
                rows.append({'topic_id': topic['topic_id'],
                             'canonical_name': 'Generic praise' if generic else 'Specific product issue',
                             'definition': 'Feedback evidenced by aspect descriptions',
                             'parent_category_id': 'experience',
                             'relevance_status': 'exclude' if generic else 'keep',
                             'exclusion_reason': 'generic_sentiment' if generic else 'none'})
            parsed = refine.TopicBatch.model_validate({'topics': rows})
        elif format_class is refine.NoiseBatch:
            parsed = refine.NoiseBatch.model_validate({'decisions': [
                {'aspect_id': row['aspect_id'], 'topic_id': '', 'relationship': 'ambiguous',
                 'confidence': 'low', 'reason': 'No clear equivalent'}
                for row in payload['aspects']]})
        else:
            raise AssertionError(format_class)
        return SimpleNamespace(status='completed', output_parsed=parsed,
                               usage=SimpleNamespace(input_tokens=100, output_tokens=30))


class RefinementTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / 'clusters'
        self.embeddings = self.root / 'embeddings'
        self.output = self.root / 'refined'
        self.source.mkdir()
        self.embeddings.mkdir()
        self.rows = []
        topics = [
            ('Excessive ads between songs', 'ads', 'negative', [1, 0, 0]),
            ('Too many advertisements after tracks', 'ads', 'negative', [.99, .01, 0]),
            ('Cannot add songs to queue', 'usability', 'negative', [0, 1, 0]),
            ('Cannot remove songs from queue', 'usability', 'negative', [0, .98, .02]),
            ('App is good', 'praise', 'positive', [0, 0, 1]),
            ('Rare battery drain', 'performance', 'negative', [.3, .3, .9]),
        ]
        vectors = []
        for cid, (description, category, polarity, vector) in enumerate(topics):
            for duplicate in range(2 if cid == 0 else 1):
                row = {'aspect_id': f'0:{cid}:{duplicate}', 'review_key': f'0:{cid}',
                       'cluster_id': cid % 2, 'aspect_cluster_id': cid if cid < 5 else -1,
                       'description': description, 'category': category, 'polarity': polarity,
                       'feature': 'ads' if cid < 2 else 'queue' if cid in (2, 3) else None,
                       'app_name': 'Spotify', 'feedback_date': '2026-01-01', 'stars': 3,
                       'sample_roles': 'random', 'random_inclusion_probability': 0.1,
                       'cluster_membership_strength': 1.0, 'is_noise': cid == 5}
                self.rows.append(row)
                vectors.append(vector)
        vectors = np.asarray(vectors, dtype=np.float32)
        vectors /= np.linalg.norm(vectors, axis=1, keepdims=True)
        np.save(self.embeddings / 'part-000000.npy', vectors)
        pq.write_table(pa.Table.from_pylist(self.rows).drop(['cluster_id', 'aspect_cluster_id',
                                                             'cluster_membership_strength', 'is_noise']),
                       self.embeddings / 'part-000000.parquet')
        (self.embeddings / 'manifest.json').write_text(json.dumps({
            'status': 'complete', 'aspect_count': len(self.rows), 'completed_shards': 1,
            'embedding_dimension': 3, 'config': {'source_sha256': 'source-fingerprint'}}))
        pq.write_table(pa.Table.from_pylist(self.rows), self.source / 'aspect_clusters.parquet')
        reps = [{**row, 'sample_role': 'centroid'} for row in self.rows if row['aspect_cluster_id'] >= 0]
        pq.write_table(pa.Table.from_pylist(reps), self.source / 'representative_aspects.parquet')
        (self.source / 'run_config.json').write_text(json.dumps({
            'input': str(self.embeddings), 'aspects': len(self.rows)}))

    def test_end_to_end_preserves_every_aspect_and_sampling(self):
        client = FakeClient()
        report = refine.run(options(self.source, self.output), client=client)
        self.assertEqual(report['source_aspects'], len(self.rows))
        self.assertEqual(report['total_original_aspect_clusters'], 5)
        self.assertEqual(report['accepted_merges'], 1)
        refined = pq.read_table(self.output / 'refined_aspects.parquet').to_pylist()
        mapping = pq.read_table(self.output / 'cluster_mapping.parquet').to_pylist()
        self.assertEqual(len(refined), len(self.rows))
        self.assertEqual(len(mapping), 5)
        self.assertEqual([item['aspect_id'] for item in refined], [item['aspect_id'] for item in self.rows])
        self.assertEqual([item['review_key'] for item in refined], [item['review_key'] for item in self.rows])
        self.assertEqual([item['random_inclusion_probability'] for item in refined], [0.1] * len(self.rows))
        self.assertEqual(refined[0]['topic_id'], refined[2]['topic_id'])
        self.assertNotEqual(refined[3]['topic_id'], refined[4]['topic_id'])
        self.assertNotEqual(refined[4]['topic_id'], refined[5]['topic_id'])
        self.assertEqual(refined[5]['relevance_status'], 'exclude')
        self.assertIsNone(refined[-1]['topic_id'])
        self.assertEqual(refined[-1]['assignment_method'], 'noise_unassigned')
        self.assertEqual(len({row['review_key'] for row in refined if row['topic_id'] == refined[0]['topic_id']}), 2)
        second = FakeClient()
        refine.run(options(self.source, self.output, resume=True), client=second)
        self.assertEqual(second.calls, [])

    def test_retry_saves_only_validated_result(self):
        client = FakeClient(fail_once=True)
        report = refine.run(options(self.source, self.output), client=client)
        self.assertGreater(report['api_requests'], 1)
        saved, usage = refine.load_checkpoint(self.output / 'checkpoint.jsonl')
        self.assertEqual(len(saved), len({(item['stage'], item['job_key']) for item in
                                       (json.loads(line) for line in
                                        (self.output / 'checkpoint.jsonl').read_text().splitlines())}))
        self.assertEqual(usage['requests'], report['api_requests'])

    def test_ambiguous_and_transitive_merges_are_conservative(self):
        decisions = [decision(0, 1, 'equivalent'), decision(1, 2, 'equivalent'),
                     decision(0, 2, 'distinct')]
        validation = {'0,1,2': {'groups': [
            {'cluster_ids': [0, 1], 'reason': 'Same issue'},
            {'cluster_ids': [2], 'reason': 'Different issue'}]}}
        groups = refine.resolve_groups([0, 1, 2], decisions, validation)
        self.assertEqual([item['cluster_ids'] for item in groups], [[0, 1], [2]])
        with self.assertRaisesRegex(ValueError, 'conflicts'):
            refine.resolve_groups([0, 1, 2], decisions, {'0,1,2': {'groups': [
                {'cluster_ids': [0, 1, 2], 'reason': 'Incorrect'}]}})
        self.assertEqual(refine.tentative_groups([0, 1], [decision(0, 1, 'ambiguous')]), [[0], [1]])

    def test_positive_negative_pairs_require_review(self):
        profiles = {0: {'top_polarity': 'positive'}, 1: {'top_polarity': 'negative'}}
        guarded = refine.guard_opposite_polarity([decision(0, 1, 'equivalent')], profiles)
        self.assertEqual(guarded[0]['relationship'], 'ambiguous')
        self.assertEqual(refine.tentative_groups([0, 1], guarded), [[0], [1]])

    def test_needs_review_can_include_a_reason(self):
        batch = refine.TopicBatch.model_validate({'topics': [{
            'topic_id': 'topic-0001', 'canonical_name': 'Mixed feedback',
            'definition': 'Several issues may be present', 'parent_category_id': 'experience',
            'relevance_status': 'needs_review', 'exclusion_reason': 'insufficient_information'}]})
        accepted = refine.validate_topic_batch(['topic-0001'], {'experience'}, batch)
        self.assertEqual(accepted[0]['relevance_status'], 'needs_review')

    def test_conflicting_relevance_fields_are_flagged_for_review(self):
        batch = refine.TopicBatch.model_validate({'topics': [
            {'topic_id': 'topic-0001', 'canonical_name': 'Unclear praise',
             'definition': 'Product feedback', 'parent_category_id': 'experience',
             'relevance_status': 'keep', 'exclusion_reason': 'insufficient_information'},
            {'topic_id': 'topic-0002', 'canonical_name': 'Unclear exclusion',
             'definition': 'Product feedback', 'parent_category_id': 'experience',
             'relevance_status': 'exclude', 'exclusion_reason': 'none'},
        ]})
        accepted = refine.validate_topic_batch(['topic-0001', 'topic-0002'], {'experience'}, batch)
        self.assertEqual([item['relevance_status'] for item in accepted], ['needs_review', 'needs_review'])
        self.assertEqual(accepted[1]['exclusion_reason'], 'insufficient_information')

    def test_queue_and_shuffle_failure_modes_stay_distinct(self):
        decisions = [decision(0, 1, 'distinct'), decision(2, 3, 'related')]
        self.assertEqual(refine.tentative_groups([0, 1, 2, 3], decisions),
                         [[0], [1], [2], [3]])

    def test_dry_run_creates_no_output(self):
        estimate = refine.run(options(self.source, self.output, dry_run=True))
        self.assertEqual(estimate['source_aspects'], len(self.rows))
        self.assertFalse(self.output.exists())

    def test_partial_evaluation_retains_all_source_rows(self):
        report = refine.run(options(self.source, self.output, max_clusters=2), client=FakeClient())
        self.assertTrue(report['partial_evaluation'])
        rows = pq.read_table(self.output / 'refined_aspects.parquet')
        self.assertEqual(rows.num_rows, len(self.rows))
        self.assertEqual(pq.read_table(self.output / 'cluster_mapping.parquet').num_rows, 5)

    def test_empty_pair_decisions_keep_typed_schema(self):
        refine.run(options(self.source, self.output, max_clusters=1), client=FakeClient())
        decisions = pq.read_table(self.output / 'pair_decisions.parquet')
        self.assertEqual(decisions.num_rows, 0)
        self.assertEqual(decisions.schema, refine.DECISION_SCHEMA)
        self.assertEqual(pq.read_table(self.output / 'refined_aspects.parquet').num_rows, len(self.rows))


if __name__ == '__main__':
    unittest.main()
