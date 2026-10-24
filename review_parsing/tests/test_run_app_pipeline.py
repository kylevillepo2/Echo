import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'nlp'))
import run_app_pipeline as pipeline


class PipelineTest(unittest.TestCase):
    def test_one_app_runs_all_stages_and_resumes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'reviews.csv'
            source.write_text('app_names,full_text,language_status\n', encoding='utf-8')
            output = (root / 'run').resolve()
            args = SimpleNamespace(app='Spotify', input=source, output=output, clusters=50,
                                   review_model='review-model', aspect_model='aspect-model',
                                   extraction_model='extract-model', batch_size=8, concurrency=5)
            slug = 'spotify-test'
            calls = []
            extraction_complete = [True]

            def write(path, value):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(value), encoding='utf-8')

            def runner(command, *, cwd, check):
                self.assertEqual(cwd, pipeline.PROJECT)
                self.assertTrue(check)
                script = Path(command[1]).name
                calls.append(script)
                if script == 'generate_app_embeddings.py':
                    write(output / 'review-embeddings/app_index.json',
                          {'Spotify': {'slug': slug, 'row_count': 100}})
                    write(output / 'review-embeddings/apps' / slug / 'manifest.json',
                          {'slug': slug, 'row_count': 100, 'completed_rows': 100})
                elif script == 'cluster_app_reviews.py':
                    write(output / 'review-clusters' / slug / 'run_config.json', {
                        'app': 'Spotify', 'embedding_root': str(output / 'review-embeddings'),
                        'source_manifest': {'slug': slug, 'row_count': 100, 'completed_rows': 100},
                        'clusters': 50, 'completed_rows': 100})
                    (output / 'review-clusters' / slug / 'cluster_samples.parquet').touch()
                elif script == 'extract_review_aspects.py':
                    self.assertEqual(command[command.index('--app') + 1], 'Spotify')
                    write(output / 'aspects' / slug / 'summary.json',
                          {'processed_unique_reviews': 10 if extraction_complete[0] else 9,
                           'sampled_unique_reviews': 10,
                           'aspect_rows': 8})
                    (output / 'aspects' / slug / 'review_aspects.parquet').touch()
                elif script == 'embed_aspects.py':
                    self.assertEqual(Path(command[command.index('--input') + 1]),
                                     output / 'aspects' / slug / 'review_aspects.parquet')
                    write(output / 'aspect-embeddings/manifest.json',
                          {'status': 'complete', 'config': {'source_sha256': 'source'},
                           'aspect_count': 8})
                elif script == 'cluster_aspects.py':
                    write(output / 'aspect-clusters/run_config.json', {
                        'input': str(output / 'aspect-embeddings'),
                        'input_source_sha256': 'source', 'aspects': 8})
                    (output / 'aspect-clusters/aspect_clusters.parquet').touch()
                else:
                    self.fail(f'Unexpected stage: {script}')

            with patch.object(pipeline, 'require_api_key'):
                pipeline.run(args, runner)
                self.assertEqual(calls, [
                    'generate_app_embeddings.py', 'cluster_app_reviews.py',
                    'extract_review_aspects.py', 'embed_aspects.py', 'cluster_aspects.py'])
                calls.clear()
                pipeline.run(args, runner)
                self.assertEqual(calls, [
                    'generate_app_embeddings.py', 'extract_review_aspects.py',
                    'embed_aspects.py'])
                extraction_complete[0] = False
                with self.assertRaisesRegex(ValueError, 'incomplete'):
                    pipeline.run(args, runner)
                self.assertEqual(calls[-1], 'extract_review_aspects.py')


if __name__ == '__main__':
    unittest.main()
