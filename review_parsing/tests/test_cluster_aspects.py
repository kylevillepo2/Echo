import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq


SCRIPT = Path(__file__).resolve().parents[1] / 'nlp' / 'cluster_aspects.py'
SPEC = importlib.util.spec_from_file_location('cluster_aspects', SCRIPT)
cluster = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cluster)


class ClusterAspectsTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.source = self.root / 'input'
        self.source.mkdir()
        self.target = self.root / 'output'
        rng = np.random.default_rng(42)
        vectors = np.concatenate([
            rng.normal([1, 0, 0], 0.01, (15, 3)),
            rng.normal([0, 1, 0], 0.01, (15, 3)),
        ]).astype(np.float32)
        vectors /= np.linalg.norm(vectors, axis=1, keepdims=True)
        self.vectors = vectors
        self.rows = [
            {'aspect_id': f'0:{i}:0', 'review_key': f'0:{i}', 'cluster_id': i % 4,
             'description': f'Issue {i}', 'category': 'playback',
             'polarity': 'negative', 'random_inclusion_probability': 0.1}
            for i in range(30)
        ]
        self.write_input()

    def write_input(self):
        np.save(self.source / 'part-000000.npy', self.vectors)
        pq.write_table(pa.Table.from_pylist(self.rows), self.source / 'part-000000.parquet')
        (self.source / 'manifest.json').write_text(json.dumps({
            'status': 'complete', 'aspect_count': len(self.rows),
            'completed_shards': 1, 'embedding_dimension': 3,
            'config': {'source_sha256': 'source-hash'},
        }))

    def args(self, **changes):
        values = dict(input=self.source, output=self.target, min_cluster_size=5,
                      min_samples=3, umap_dims=2, neighbors=5, no_umap=True,
                      representatives=3, random_state=42, allow_existing=False)
        values.update(changes)
        return SimpleNamespace(**values)

    def test_aligned_outputs_and_metadata(self):
        with contextlib.redirect_stdout(io.StringIO()):
            config = cluster.run(self.args())
        assignment = pq.read_table(self.target / 'aspect_clusters.parquet')
        reps = pq.read_table(self.target / 'representative_aspects.parquet')
        noise = pq.read_table(self.target / 'noise_aspects.parquet')
        self.assertEqual(assignment.num_rows, 30)
        self.assertEqual(assignment.column('aspect_id').to_pylist(),
                         [row['aspect_id'] for row in self.rows])
        self.assertEqual(assignment.column('random_inclusion_probability').to_pylist(), [0.1] * 30)
        self.assertEqual(noise.num_rows, config['noise_aspects'])
        self.assertEqual(reps.num_rows, config['clusters'] * 6)
        self.assertEqual(set(reps.column('sample_role').to_pylist()), {'centroid', 'random'})
        self.assertTrue((self.target / 'cluster_summary.csv').exists())
        self.assertEqual(json.loads((self.target / 'run_config.json').read_text()), config)
        with self.assertRaises(FileExistsError):
            cluster.run(self.args())

    def test_rejects_mismatched_shard_and_duplicate_ids(self):
        self.vectors = self.vectors[:-1]
        self.write_input()
        with self.assertRaisesRegex(ValueError, 'shape mismatch'):
            cluster.load_shards(self.source)
        self.vectors = np.concatenate([self.vectors, self.vectors[-1:]])
        self.rows[1]['aspect_id'] = self.rows[0]['aspect_id']
        self.write_input()
        with self.assertRaisesRegex(ValueError, 'duplicated'):
            cluster.load_shards(self.source)


if __name__ == '__main__':
    unittest.main()
