import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'nlp'))
from run_similarity_inspection import find_run, merge_file, parser, run


class InspectionWorkflowTests(unittest.TestCase):
    def test_app_discovery_ambiguity_and_missing(self):
        with tempfile.TemporaryDirectory() as temp:
            runs = Path(temp)
            for name in ['cash-one', 'cash-two']:
                root = runs / name / 'review-embeddings'
                root.mkdir(parents=True)
                (root / 'app_index.json').write_text(json.dumps({'Cash App': {'slug': 'cash'}}))
            with self.assertRaises(ValueError): find_run('Cash App', runs_root=runs)
            self.assertEqual(find_run('cash app', runs/'cash-one'), (runs/'cash-one').resolve())
            with self.assertRaises(ValueError): find_run('Venmo', runs_root=runs)

    def test_merge_preserves_annotations_and_raw_fields(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source, output = root/'global_inspection.csv', root/'global_inspection_readable.csv'
            row = {'review_key': '0:1', 'review_text': 'My account froze', 'true_topic_ids': '["a"]',
                   'predicted_topic_ids': '["a"]', 'similarity_scores': '{"a": 0.8}',
                   'false_positive_topics': '[]', 'false_negative_topics': '[]'}
            def write(path, rows):
                with path.open('w', newline='') as f:
                    w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
            write(source, [row])
            catalog = {'a': {'canonical_name': 'Account freezes', 'definition': 'Accounts become frozen.'}}
            merge_file(source, output, catalog)
            with output.open(encoding='utf-8-sig', newline='') as f: rows=list(csv.DictReader(f))
            self.assertEqual(rows[0]['assigned_tags'], 'Account freezes')
            rows[0]['human_notes'] = 'Verified manually'
            write(output, rows)
            merge_file(source, output, catalog)
            with output.open(encoding='utf-8-sig', newline='') as f: merged=list(csv.DictReader(f))[0]
            self.assertEqual(merged['human_notes'], 'Verified manually')
            self.assertTrue(all(merged[k] == v for k, v in row.items()))

    def test_missing_evaluation_gives_actionable_error(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            (root/'review-embeddings').mkdir()
            (root/'review-embeddings/app_index.json').write_text('{"Venmo": {}}')
            (root/'refined-topics').mkdir()
            (root/'refined-topics/topic_catalog.csv').write_text('topic_id,canonical_name,definition\na,A,Definition\n')
            args=parser().parse_args(['Venmo','--run-root',str(root)])
            with self.assertRaisesRegex(ValueError, 'evaluate_similarity_tagging.py'):
                run(args)


if __name__ == '__main__':
    unittest.main()
