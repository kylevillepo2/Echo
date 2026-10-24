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


SCRIPT = Path(__file__).resolve().parents[1] / 'nlp' / 'embed_aspects.py'
SPEC = importlib.util.spec_from_file_location('embed_aspects', SCRIPT)
embed = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(embed)


def args(source, output, **changes):
    values = dict(input=source, output=output, model='fake-model', device=None,
                  batch_size=2, shard_size=2, dtype='float32', max_aspects=None,
                  force=False)
    values.update(changes)
    return SimpleNamespace(**values)


class FakeEncoder:
    instances = []

    def __init__(self, model, device=None):
        self.inputs = []
        self.instances.append(self)

    def encode(self, descriptions, **kwargs):
        self.inputs.extend(descriptions)
        return np.array([[i + 1, len(text) + 1, 3] for i, text in enumerate(descriptions)],
                        dtype=np.float32)


class EmbedAspectsTests(unittest.TestCase):
    def setUp(self):
        FakeEncoder.instances.clear()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'review_aspects.parquet'
        self.output = self.root / 'embeddings'
        self.rows = [
            {'review_key': f'0:{i}', 'aspect_index': 0, 'description': f'Issue {i}',
             'app_name': 'Spotify', 'category': 'usability', 'polarity': 'negative',
             'random_inclusion_probability': 0.1}
            for i in range(5)
        ]
        self.write_input()

    def write_input(self):
        pq.write_table(pa.Table.from_pylist(self.rows), self.source)

    def run_embed(self, **changes):
        with contextlib.redirect_stdout(io.StringIO()):
            return embed.run(args(self.source, self.output, **changes), FakeEncoder)

    def test_aligned_shards_description_only_and_resume(self):
        self.run_embed()
        self.assertEqual(len(FakeEncoder.instances), 1)
        self.assertEqual(FakeEncoder.instances[0].inputs, [row['description'] for row in self.rows])
        all_ids = []
        for number, expected_count in enumerate((2, 2, 1)):
            vectors = np.load(self.output / f'part-{number:06d}.npy')
            table = pq.read_table(self.output / f'part-{number:06d}.parquet')
            self.assertEqual(vectors.shape, (expected_count, 3))
            self.assertEqual(table.num_rows, expected_count)
            self.assertEqual(table.column('random_inclusion_probability').to_pylist(),
                             [0.1] * expected_count)
            self.assertTrue(np.allclose(np.linalg.norm(vectors, axis=1), 1))
            all_ids.extend(table.column('aspect_id').to_pylist())
        self.assertEqual(all_ids, [f'0:{i}:0' for i in range(5)])
        self.run_embed(batch_size=5)
        self.assertEqual(len(FakeEncoder.instances), 1)
        manifest = json.loads((self.output / 'manifest.json').read_text())
        self.assertEqual(manifest['status'], 'complete')
        self.assertEqual(manifest['aspect_count'], 5)

    def test_partial_shard_is_rebuilt_without_touching_complete_shards(self):
        self.run_embed()
        (self.output / 'part-000001.parquet').unlink()
        (self.output / 'part-000001.tmp.npy').write_bytes(b'stale')
        self.run_embed()
        self.assertEqual(len(FakeEncoder.instances), 2)
        self.assertEqual(FakeEncoder.instances[1].inputs, ['Issue 2', 'Issue 3'])
        self.assertFalse((self.output / 'part-000001.tmp.npy').exists())

    def test_changed_source_requires_new_output_or_force(self):
        self.run_embed()
        self.rows.append({'review_key': '0:5', 'aspect_index': 0, 'description': 'New issue',
                          'app_name': 'Spotify', 'category': 'bug', 'polarity': 'negative',
                          'random_inclusion_probability': 0.1})
        self.write_input()
        with self.assertRaisesRegex(RuntimeError, 'Input or settings changed'):
            self.run_embed()
        self.run_embed(force=True)
        self.assertEqual(json.loads((self.output / 'manifest.json').read_text())['aspect_count'], 6)

    def test_bad_input_is_not_silently_dropped(self):
        self.rows[1]['description'] = ''
        self.write_input()
        with self.assertRaisesRegex(ValueError, 'Empty aspect description'):
            self.run_embed()
        self.rows[1]['description'] = 'Good issue'
        self.rows[1]['review_key'] = self.rows[0]['review_key']
        self.write_input()
        with self.assertRaisesRegex(ValueError, 'Duplicate aspect_id'):
            self.run_embed()


if __name__ == '__main__':
    unittest.main()
