import argparse
import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'nlp'))
import build_topic_embeddings as build
import evaluate_similarity_tagging as evaluate
import tag_reviews_similarity as tag
from similarity_common import (choose, compatible, load_topics, normalize,
                               provisional_labels, score, split_for, threshold_values)


class SimilarityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.runroot = self.root / 'run'
        self.review_dir = self.runroot / 'review-embeddings/apps/cash'
        self.review_dir.mkdir(parents=True)
        self.aspect_dir = self.runroot / 'aspect-embeddings'
        self.aspect_dir.mkdir()
        self.refined = self.runroot / 'refined-topics'
        self.refined.mkdir()
        self.extraction = self.runroot / 'aspects/cash'
        self.extraction.mkdir(parents=True)
        self.meta = [{'feedback_id': str(i), 'data_source': 'gplay',
                      'full_text': f'text {i}', 'stars': '1', 'feedback_date': '2026-01-01'} for i in range(6)]
        np.save(self.review_dir / 'part-000000.npy', np.array([[1, 0], [0, 1], [1, 1], [-1, -1], [1, 0], [0, 1]], dtype=np.float32))
        pq.write_table(pa.Table.from_pylist(self.meta), self.review_dir / 'part-000000.parquet')
        self.write_json(self.review_dir / 'part-000000.done', {'model': 'fixture', 'dimensions': 2, 'row_count': 6})
        self.write_json(self.review_dir / 'manifest.json', {'model': 'fixture', 'row_count': 6,
                        'completed_rows': 6, 'shard_count': 1, 'slug': 'cash'})
        self.write_json(self.runroot / 'review-embeddings/app_index.json', {'Cash App': {'slug': 'cash', 'row_count': 6}})
        topics = [{'topic_id': 'a', 'canonical_name': 'A', 'definition': 'A feature', 'original_cluster_ids': [0], 'relevance_status': 'keep'},
                  {'topic_id': 'b', 'canonical_name': 'B', 'definition': 'B feature', 'original_cluster_ids': [1], 'relevance_status': 'keep'},
                  {'topic_id': 'c', 'canonical_name': 'C', 'definition': 'C', 'original_cluster_ids': [2], 'relevance_status': 'exclude'},
                  {'topic_id': 'd', 'canonical_name': 'D', 'definition': 'D', 'original_cluster_ids': [3], 'relevance_status': 'needs_review'}]
        self.write_json(self.refined / 'canonical_topics.json', {'topics': topics, 'clusters_needing_split': [{'cluster_id': 4}]})
        self.rows = [{'review_key': f'0:{i}', 'feedback_id': str(i), 'data_source': 'gplay',
                      'text': f'text {i}', 'app_name': 'Cash App', 'topic_id': 'a' if i % 2 == 0 else 'b',
                      'description': f'aspect {i}', 'aspect_id': f'0:{i}:0', 'relevance_status': 'keep',
                      'polarity': 'negative', 'stars': '1'} for i in range(6)]
        pq.write_table(pa.Table.from_pylist(self.rows), self.refined / 'refined_aspects.parquet')
        pq.write_table(pa.Table.from_pylist(self.rows + [{'review_key': '0:99', 'feedback_id': '99', 'data_source': 'gplay',
                       'text': 'empty', 'aspect_count': 0}]), self.extraction / 'review_extractions.parquet')
        pq.write_table(pa.Table.from_pylist(self.rows), self.aspect_dir / 'part-000000.parquet')
        np.save(self.aspect_dir / 'part-000000.npy', np.array([[1, 0] if i % 2 == 0 else [0, 1] for i in range(6)], dtype=np.float32))
        self.write_json(self.aspect_dir / 'manifest.json', {'status': 'complete', 'aspect_count': 6,
                        'completed_shards': 1, 'embedding_dimension': 2, 'config': {'model': 'fixture'}})

    def tearDown(self):
        self.tmp.cleanup()

    def write_json(self, path, obj):
        path.write_text(json.dumps(obj))

    def build_topics(self, method='description'):
        out = self.root / method
        class Encoder:
            def encode(self, *args, **kwargs): return np.eye(2, dtype=np.float32)
        build.run(argparse.Namespace(run_root=self.runroot, app='Cash App', method=method,
                                    output=out, seed=42, device='cpu'), Encoder())
        return out

    def tag_args(self, output, batch=2, threshold=0.6):
        return argparse.Namespace(run_root=self.runroot, app='Cash App', topic_embeddings=self.root/'description',
                                  output=output, threshold=threshold, threshold_config=None, max_tags=5, batch_size=batch)

    def test_cosine_normalization_and_invalid(self):
        np.testing.assert_allclose(normalize([[3, 4]]), [[.6, .8]])
        np.testing.assert_allclose(score(np.eye(2), np.eye(2)), np.eye(2))
        for x in [[[0, 0]], [[float('nan'), 1]]]:
            with self.assertRaises(ValueError): normalize(x)
        with self.assertRaises(ValueError): score(np.eye(2), np.eye(3))
        with self.assertRaises(ValueError): compatible('a', 2, 'b', 2)
        with self.assertRaises(ValueError): compatible('a', 2, 'a', 3)

    def test_multilabel_zero_cap_thresholds_and_order(self):
        x = np.array([[.8, .8, .3], [.1, .2, .3]])
        self.assertEqual(choose(x, .5, 5), [[0, 1], []])
        self.assertEqual(choose(x, [.9, .7, .2], 5), [[1, 2], [2]])
        self.assertEqual(choose(x, .2, 1), [[0], [2]])
        with self.assertRaises(ValueError): choose(x, float('nan'), 5)
        with self.assertRaises(ValueError): choose(x, .5, 0)
        self.assertEqual(threshold_values({'global_threshold': .6, 'per_topic': {'b': .8}, 'max_tags': 2}, ['a', 'b']), [.6, .8])
        with self.assertRaises(ValueError): threshold_values({'global_threshold': .5, 'per_topic': {'z': .2}, 'max_tags': 2}, ['a'])

    def test_approved_topic_alignment(self):
        out = self.build_topics()
        x, rows, config = load_topics(out)
        self.assertEqual([r['topic_id'] for r in rows], ['a', 'b'])
        self.assertEqual([r['embedding_row'] for r in rows], [0, 1])
        self.assertEqual(config['excluded_topic_count'], 2)
        np.testing.assert_allclose(x, np.eye(2))
        with (out/'topic_vectors.npy').open('ab') as f: f.write(b'bad')
        with self.assertRaises(ValueError): load_topics(out)

    def test_prototypes_exclude_validation_and_test_text_groups(self):
        out = self.build_topics('prototype')
        _, rows, _ = load_topics(out)
        for row in rows:
            for key in row['training_review_keys']:
                source = next(r for r in self.rows if r['review_key'] == key)
                self.assertEqual(split_for(source), 'train')
        self.assertEqual(split_for({'text': ' SAME text '}), split_for({'text': 'same   TEXT'}))

    def test_batch_resume_dedup_metadata_sentiment_and_config_guard(self):
        self.build_topics()
        a = self.tag_args(self.root/'out1', batch=1)
        report = tag.run(a)
        first = pq.read_table(a.output/'tagged_reviews.parquet')
        self.assertEqual(first.num_rows, 6)
        self.assertEqual(first.column('feedback_date').to_pylist(), ['2026-01-01']*6)
        lists = first.column('topics').to_pylist()
        self.assertEqual(len(lists[2]), 2)
        self.assertEqual(lists[3], [])
        self.assertEqual(lists[0][0]['sentiment'], 'negative')
        self.assertEqual(lists[2][1]['sentiment'], 'unknown')
        self.assertTrue(all(len({t['topic_id'] for t in ts}) == len(ts) for ts in lists))
        self.assertEqual(tag.run(a)['resumed_shards'], 1)
        self.assertEqual(first.to_pylist(), pq.read_table(a.output/'tagged_reviews.parquet').to_pylist())
        b = self.tag_args(self.root/'out2', batch=4)
        tag.run(b)
        self.assertEqual(first.to_pylist(), pq.read_table(b.output/'tagged_reviews.parquet').to_pylist())
        a.threshold = .7
        with self.assertRaises(ValueError): tag.run(a)
        a.threshold = .6
        (a.output/'part-000000.parquet').write_bytes(b'corrupt')
        with self.assertRaises(ValueError): tag.run(a)

    def test_zero_aspect_reference_and_uncertain_exclusion(self):
        labels = provisional_labels(self.refined/'refined_aspects.parquet', self.extraction/'review_extractions.parquet', ['a'])
        self.assertEqual(labels['gplay:99']['topics'], set())
        self.assertTrue(labels['gplay:1']['unresolved'])

    def test_metrics_and_tuning(self):
        y = np.array([[1, 0], [1, 1], [0, 0]], dtype=bool)
        m = evaluate.metrics(y, y, ['a', 'b'])
        self.assertEqual(m['micro_f1'], 1)
        self.assertEqual(m['macro_f1'], 1)
        self.assertAlmostEqual(m['zero_topics_percent'], 100/3)
        scores = np.array([[.9, .1], [.8, .9], [.2, .2]])
        threshold, per, sweep = evaluate.tune(scores, y, ['a', 'b'], [.1, .5, .7], 5, 1)
        self.assertEqual(threshold, .7)
        self.assertEqual(set(per), {'a', 'b'})

    def test_inspection_retains_assigned_scores_outside_top_five(self):
        ids = [str(i) for i in range(7)]
        scores = np.array([[.9, .8, .7, .6, .5, .4, .3]])
        truth = np.zeros((1, 7), dtype=bool)
        prediction = truth.copy()
        prediction[0, 6] = True
        rows, _ = evaluate.inspect_rows([{'review_key': 'r', 'text': 'example', 'stars': '1'}],
                                        truth, scores, prediction, ids, 42, 120)
        saved = json.loads(rows[0]['similarity_scores'])
        self.assertEqual(saved['6'], .3)

    def test_evaluation_cli_flow_has_separate_partitions_and_inspection(self):
        topics = self.build_topics()
        meta = [{**self.meta[i % 6], 'feedback_id': str(i), 'full_text': f'text {i}'} for i in range(250)]
        pq.write_table(pa.Table.from_pylist(meta), self.review_dir/'part-000000.parquet')
        np.save(self.review_dir/'part-000000.npy', np.tile(np.eye(2), (125, 1)).astype(np.float32))
        self.write_json(self.review_dir/'part-000000.done', {'model': 'fixture', 'dimensions': 2, 'row_count': 250})
        self.write_json(self.review_dir/'manifest.json', {'model': 'fixture', 'row_count': 250,
                        'completed_rows': 250, 'shard_count': 1, 'slug': 'cash'})
        reviews = [{**r, 'review_key': f'0:{i}', 'text': r['full_text']} for i, r in enumerate(meta)]
        pq.write_table(pa.Table.from_pylist(reviews), self.extraction/'review_extractions.parquet')
        out = self.root/'evaluation'
        result = evaluate.run(argparse.Namespace(run_root=self.runroot, app='Cash App',
                     topic_embeddings=topics, output=out, threshold_grid='0.3,0.5,0.7',
                     max_tags=5, min_support=5, inspection_count=100))
        self.assertGreaterEqual(result['partition_counts']['test_evaluable'], 20)
        self.assertTrue((out/'global_inspection.csv').exists())
        parts = pq.read_table(out/'evaluation_partitions.parquet').to_pylist()
        self.assertEqual({r['partition'] for r in parts}, {'train', 'validation', 'test'})

    def test_interrupted_part_rebuilt_and_duplicate_source_rejected(self):
        self.build_topics()
        args = self.tag_args(self.root/'interrupted')
        tag.run(args)
        (args.output/'part-000000.done.json').unlink()
        self.assertEqual(tag.run(args)['resumed_shards'], 0)
        duplicate = self.meta + [self.meta[0]]
        pq.write_table(pa.Table.from_pylist(duplicate), self.review_dir/'part-000000.parquet')
        with self.assertRaises(ValueError): tag.run(self.tag_args(self.root/'bad'))


if __name__ == '__main__':
    unittest.main()
