import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'nlp'))
from run_similarity_workflow import execute_stage, parser


class SimilarityWorkflowTests(unittest.TestCase):
    def test_defaults_and_both_method_option(self):
        args = parser().parse_args(['Venmo'])
        self.assertEqual(args.method, 'description')
        self.assertEqual(args.strategy, 'global')
        self.assertEqual(parser().parse_args(['Cash App', '--method', 'both']).method, 'both')

    def test_stage_completion_reuse_and_changed_artifact(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            output = folder/'result.json'
            state = {'completed': {}}
            calls=[]
            def runner(command, check, env):
                calls.append(command)
                self.assertTrue(check)
                self.assertEqual(env['HF_HUB_OFFLINE'], '1')
                self.assertEqual(env['TRANSFORMERS_OFFLINE'], '1')
                output.write_text('{}')
            params = ('test', 'build_topic_embeddings.py', ['--app', 'Venmo'], [output],
                      state, folder/'checkpoint.json', runner)
            execute_stage(*params)
            execute_stage(*params)
            self.assertEqual(len(calls), 1)
            output.write_text('changed')
            with self.assertRaises(ValueError): execute_stage(*params)

    def test_failed_stage_is_not_marked_complete(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            state = {'completed': {}}
            with self.assertRaises(ValueError):
                execute_stage('failed', 'build_topic_embeddings.py', [], [folder/'missing'],
                              state, folder/'checkpoint.json', lambda *a, **kw: None)
            self.assertEqual(state['completed'], {})


if __name__ == '__main__':
    unittest.main()
