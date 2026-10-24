import contextlib
import csv
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'nlp'))
import global_aspect_refinement as global_refine
import refine_aspect_clusters as core


def settings(source, output, **changes):
    values = dict(strategy='global', input=source, output=output, embedding_root=None,
                  model='fake-model', concurrency=2, dry_run=False, max_clusters=None,
                  max_cost_usd=100, analysis_objective=core.DEFAULT_OBJECTIVE,
                  max_input_tokens=180000, max_output_tokens=64000,
                  max_repair_attempts=2,
                  skip_verification=False, duplicate_threshold=0.83,
                  review_threshold=0.86, noise_threshold=0.7,
                  pair_batch_size=5, noise_batch_size=8, retries=1,
                  similarity_threshold=0.72, neighbors=7,
                  input_cost_per_million=2, output_cost_per_million=10,
                  resume=False)
    values.update(changes)
    return SimpleNamespace(**values)


class FakeGlobalClient:
    def __init__(self, invalid_first=False):
        self.responses = self
        self.calls = []
        self.invalid_first = invalid_first

    async def parse(self, **request):
        schema = request['text_format']
        data = json.loads(request['input'])
        self.calls.append(schema.__name__)
        if schema is global_refine.GlobalResponse:
            if self.invalid_first:
                self.invalid_first = False
                ids = [0, 1, 2, 3, 4, 5, 6]
            else:
                ids = [0, 1, 2, 3, 4, 5, 6, 7]
            topics = [
                ('Excessive ad frequency', [0, 1], 'Advertising', 'keep'),
                ('Misleading ad-free promise', [2], 'Advertising', 'keep'),
                ('Cannot add songs to queue', [3], 'Queue', 'keep'),
                ('Cannot remove songs from queue', [4], 'Queue', 'keep'),
                ('Generic sentiment', [5], 'General', 'exclude'),
                ('Excellent sound quality', [6], 'Audio', 'keep'),
            ]
            response = {'canonical_topics': [
                {'canonical_name': name, 'definition': name + ' specifically',
                 'parent_category': parent, 'source_cluster_ids': members,
                 'relevance_status': status, 'decision_reason': 'Supported by examples',
                 'exclusion_reason': 'generic_sentiment' if status == 'exclude' else 'none'}
                for name, members, parent, status in topics],
                'clusters_needing_split': [
                    {'cluster_id': 7, 'reason': 'Connectivity and filters are distinct',
                     'suggested_subtopics': ['Connection failures', 'Filter resets'],
                     'distinguishing_descriptions': ['Connection fails', 'Filters reset']}
                ] if 7 in ids else [],
                'clusters_needing_review': []}
            parsed = global_refine.GlobalResponse.model_validate(response)
        elif schema is global_refine.VerifyResponse:
            topic = data['proposed_topic']
            parsed = global_refine.VerifyResponse.model_validate({'parts': [
                {'source_cluster_ids': topic['source_cluster_ids'], 'status': 'approved',
                 'canonical_name': topic['canonical_name'], 'definition': topic['definition'],
                 'reason': 'Descriptions describe one issue'}]})
        elif schema is global_refine.DuplicateBatch:
            parsed = global_refine.DuplicateBatch.model_validate({'decisions': [
                {'topic_a': pair['topic_a'], 'topic_b': pair['topic_b'],
                 'relationship': 'distinct', 'reason': 'Different product failures',
                 'proposed_name': '', 'proposed_definition': ''}
                for pair in data]})
        elif schema is core.NoiseBatch:
            parsed = core.NoiseBatch.model_validate({'decisions': [
                {'aspect_id': item['aspect_id'], 'topic_id': '',
                 'relationship': 'ambiguous', 'confidence': 'low', 'reason': 'Rare issue'}
                for item in data['aspects']]})
        else:
            raise AssertionError(schema)
        return SimpleNamespace(status='completed', output_parsed=parsed,
                               usage=SimpleNamespace(input_tokens=200, output_tokens=80))


class GlobalRefinementTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.source = self.root / 'clusters'
        self.embeddings = self.root / 'embeddings'
        self.output = self.root / 'global'
        self.source.mkdir()
        self.embeddings.mkdir()
        descriptions = [
            ('Excessive ads after songs', 'ads', 'negative', [1, 0, 0]),
            ('Too many ads between tracks', 'ads', 'negative', [.99, .01, 0]),
            ('Promised ad-free period still has ads', 'ads', 'negative', [.8, .2, 0]),
            ('Cannot add song to queue', 'usability', 'negative', [0, 1, 0]),
            ('Cannot remove song from queue', 'usability', 'negative', [0, .99, .01]),
            ('App is amazing', 'praise', 'positive', [0, 0, 1]),
            ('Excellent sound quality', 'content_quality', 'positive', [.1, 0, .99]),
            ('Connection fails and filters reset', 'bug', 'negative', [.2, .3, .8]),
            ('Rare download issue', 'bug', 'negative', [.3, .2, .9]),
        ]
        self.rows = []
        vectors = []
        for cid, (description, category, polarity, vector) in enumerate(descriptions):
            self.rows.append({'aspect_id': f'0:{cid}:0', 'review_key': f'0:{cid}',
                              'cluster_id': cid % 3, 'aspect_cluster_id': cid if cid < 8 else -1,
                              'description': description, 'category': category,
                              'polarity': polarity, 'feature': None, 'app_name': 'Spotify',
                              'feedback_date': '2026-07-01', 'sample_roles': 'random',
                              'random_inclusion_probability': 0.1,
                              'cluster_membership_strength': 1.0, 'is_noise': cid == 8})
            vectors.append(vector)
        vectors = np.asarray(vectors, dtype=np.float32)
        vectors /= np.linalg.norm(vectors, axis=1, keepdims=True)
        np.save(self.embeddings / 'part-000000.npy', vectors)
        pq.write_table(pa.Table.from_pylist(self.rows).drop(
            ['cluster_id', 'aspect_cluster_id', 'cluster_membership_strength', 'is_noise']),
            self.embeddings / 'part-000000.parquet')
        (self.embeddings / 'manifest.json').write_text(json.dumps({
            'status': 'complete', 'aspect_count': len(self.rows), 'completed_shards': 1,
            'embedding_dimension': 3, 'config': {'source_sha256': 'fixture'}}))
        pq.write_table(pa.Table.from_pylist(self.rows), self.source / 'aspect_clusters.parquet')
        pq.write_table(pa.Table.from_pylist([{**row, 'sample_role': 'centroid'} for row in self.rows[:-1]]),
                       self.source / 'representative_aspects.parquet')
        (self.source / 'run_config.json').write_text(json.dumps({
            'input': str(self.embeddings), 'aspects': len(self.rows)}))

    def run_global(self, client=None, **changes):
        with contextlib.redirect_stdout(io.StringIO()):
            return global_refine.run_global(settings(self.source, self.output, **changes), client)

    def test_global_outputs_distinguish_issues_and_preserve_source(self):
        report = self.run_global(FakeGlobalClient())
        self.assertEqual(report['source_aspects'], len(self.rows))
        self.assertEqual(report['clusters_needing_split'], 1)
        taxonomy = json.loads((self.output / 'canonical_topics.json').read_text())
        by_cluster = {cid: t for t in taxonomy['topics'] for cid in t['original_cluster_ids']}
        self.assertEqual(by_cluster[0]['topic_id'], by_cluster[1]['topic_id'])
        self.assertNotEqual(by_cluster[0]['topic_id'], by_cluster[2]['topic_id'])
        self.assertNotEqual(by_cluster[3]['topic_id'], by_cluster[4]['topic_id'])
        self.assertEqual(by_cluster[5]['relevance_status'], 'exclude')
        self.assertEqual(by_cluster[6]['relevance_status'], 'keep')
        rows = pq.read_table(self.output / 'refined_aspects.parquet').to_pylist()
        self.assertEqual([row['aspect_id'] for row in rows], [row['aspect_id'] for row in self.rows])
        self.assertEqual([row['review_key'] for row in rows], [row['review_key'] for row in self.rows])
        self.assertEqual([row['feedback_date'] for row in rows], ['2026-07-01'] * len(rows))
        self.assertEqual([row['random_inclusion_probability'] for row in rows], [0.1] * len(rows))
        self.assertEqual(rows[7]['assignment_method'], 'needs_split')
        self.assertIsNone(rows[7]['topic_id'])
        self.assertIsNone(rows[8]['topic_id'])
        self.assertEqual(pq.read_table(self.output / 'cluster_mapping.parquet').num_rows, 8)
        self.assertEqual(pq.read_schema(self.output / 'refined_aspects.parquet').names[:len(self.rows[0])],
                         pq.read_schema(self.source / 'aspect_clusters.parquet').names)
        with (self.output / 'topic_catalog.csv').open(newline='', encoding='utf-8') as fp:
            catalog = list(csv.DictReader(fp))
        self.assertEqual(len(catalog), len(taxonomy['topics']))
        self.assertEqual({row['topic_id'] for row in catalog},
                         {topic['topic_id'] for topic in taxonomy['topics']})
        for entry in catalog:
            expected = len({row['review_key'] for row in rows
                            if row['topic_id'] == entry['topic_id']})
            self.assertEqual(int(entry['unique_sampled_reviews']), expected)
        self.assertIn('Source clusters needing split',
                      (self.output / 'topic_catalog.md').read_text())

    def test_invalid_global_response_gets_targeted_repair(self):
        client = FakeGlobalClient(invalid_first=True)
        self.run_global(client)
        self.assertGreaterEqual(client.calls.count('GlobalResponse'), 2)
        saved, _ = core.load_checkpoint(self.output / 'checkpoint.jsonl')
        self.assertIn(('global', 'all'), saved)
        self.assertIn(('global_repair', 'attempt-1'), saved)

    def test_resume_skips_saved_paid_calls_and_stable_ids(self):
        first = FakeGlobalClient()
        self.run_global(first)
        ids_first = [row['topic_id'] for row in json.loads(
            (self.output / 'canonical_topics.json').read_text())['topics']]
        second = FakeGlobalClient()
        self.run_global(second, resume=True)
        self.assertEqual(second.calls, [])
        ids_second = [row['topic_id'] for row in json.loads(
            (self.output / 'canonical_topics.json').read_text())['topics']]
        self.assertEqual(ids_first, ids_second)

    def test_validator_rejects_missing_and_duplicate_clusters(self):
        proposal = {'canonical_topics': [{'canonical_name': 'Ads', 'definition': 'Too many ads',
                    'parent_category': 'Advertising', 'source_cluster_ids': [0, 0],
                    'relevance_status': 'keep', 'decision_reason': 'Same issue',
                    'exclusion_reason': 'none'}],
                    'clusters_needing_split': [], 'clusters_needing_review': []}
        errors = global_refine.validate_global(proposal, [0, 1])
        self.assertTrue(any('Missing' in item for item in errors))
        self.assertTrue(any('Duplicate' in item for item in errors))

    def test_validator_rejects_reflexive_mass_splitting(self):
        profiles = {cid: {'aspect_count': 10} for cid in range(8)}
        proposal = {'canonical_topics': [{
            'canonical_name': 'Specific ad frequency issue', 'definition': 'Excessive ads',
            'parent_category': 'Advertising', 'source_cluster_ids': [0],
            'relevance_status': 'keep', 'decision_reason': 'Repeated ad evidence',
            'exclusion_reason': 'none'}],
            'clusters_needing_split': [
                {'cluster_id': cid, 'reason': 'Mixed',
                 'suggested_subtopics': ['One', 'Two'], 'distinguishing_descriptions': []}
                for cid in range(1, 8)],
            'clusters_needing_review': []}
        errors = global_refine.validate_global(proposal, list(range(8)), profiles)
        self.assertTrue(any('Too many clusters marked needs_split' in error for error in errors))
        self.assertTrue(any('map to topics' in error for error in errors))

    def test_targeted_verification_separates_queue_actions(self):
        profiles = {3: {'examples': ['Cannot add songs to queue'], 'top_polarity': 'negative'},
                    4: {'examples': ['Cannot remove songs from queue'], 'top_polarity': 'negative'}}
        proposal = {'canonical_topics': [{
            'canonical_name': 'Queue add and remove failures',
            'definition': 'Queue actions fail', 'parent_category': 'Queue',
            'source_cluster_ids': [3, 4], 'relevance_status': 'keep',
            'decision_reason': 'Related queue controls', 'exclusion_reason': 'none'}],
            'clusters_needing_split': [], 'clusters_needing_review': []}
        verification = {'0': {'parts': [
            {'source_cluster_ids': [3], 'status': 'approved',
             'canonical_name': 'Cannot add songs to queue',
             'definition': 'Queue insertion fails', 'reason': 'Addition only'},
            {'source_cluster_ids': [4], 'status': 'approved',
             'canonical_name': 'Cannot remove songs from queue',
             'definition': 'Queue removal fails', 'reason': 'Removal only'}]}}
        taxonomy = global_refine.assemble_taxonomy(proposal, profiles, {'0': ['broad_name']},
                                                   verification, [])
        self.assertEqual([topic['original_cluster_ids'] for topic in taxonomy['topics']], [[3], [4]])

    def test_opposite_polarity_merge_is_flagged(self):
        topic = {'source_cluster_ids': [0, 1], 'canonical_name': 'Sound quality',
                 'parent_category': 'Audio'}
        profiles = {0: {'top_category': 'audio', 'top_polarity': 'positive',
                        'potentially_heterogeneous': False},
                    1: {'top_category': 'audio', 'top_polarity': 'negative',
                        'potentially_heterogeneous': False}}
        centroids = {0: np.array([1., 0.]), 1: np.array([1., 0.])}
        self.assertIn('opposite_dominant_polarities',
                      global_refine.semantic_flags(topic, profiles, centroids))

    def test_category_fallback_covers_each_cluster_once(self):
        _, rows, X, reps, *_ = core.prepare_inputs(self.source)
        profiles, _ = core.build_profiles(rows, X, reps)
        jobs = global_refine.grouped_payloads(profiles, budget=900, output_budget=540)
        self.assertEqual(sorted(cid for _, ids in jobs for cid in ids), sorted(profiles))
        self.assertGreater(len(jobs), 1)

    def test_global_prompt_uses_multiple_concise_examples(self):
        _, rows, X, reps, *_ = core.prepare_inputs(self.source)
        profiles, _ = core.build_profiles(rows, X, reps)
        profile = dict(profiles[0])
        profile['examples'] = [f'example {i}' for i in range(12)]
        profile['random_examples'] = [f'random {i}' for i in range(6)]
        compact = global_refine.compact_profile(profile)
        self.assertEqual(len(compact['examples']), 7)
        self.assertEqual(len(compact['random_examples']), 3)
        self.assertEqual(len(profile['examples']), 12)

    def test_dry_run_writes_report_without_api_calls(self):
        result = self.run_global(dry_run=True)
        self.assertTrue(result['single_global_request_feasible'])
        self.assertTrue((self.output / 'dry_run_report.json').exists())
        self.assertFalse((self.output / 'run_config.json').exists())


if __name__ == '__main__':
    unittest.main()
