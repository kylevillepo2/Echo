import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import pyarrow.parquet as pq


SCRIPT = Path(__file__).resolve().parents[1] / 'nlp' / 'extract_review_aspects.py'
SPEC = importlib.util.spec_from_file_location('extract_review_aspects', SCRIPT)
extract = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(extract)


def aspect(description, category, polarity, signal_type, feature, evidence):
    return {'description': description, 'category': category, 'polarity': polarity,
            'signal_type': signal_type, 'feature': feature, 'evidence': evidence}


def behavior(kind, evidence, target='', related=None):
    return {'type': kind, 'target': target, 'evidence': evidence,
            'related_aspect_index': related}


class ExtractionTests(unittest.TestCase):
    def test_distinct_complaints_and_duplicate_removed(self):
        text = 'Shuffle repeats the same songs. Premium costs too much.'
        first = aspect('Shuffle repeats songs', 'usability', 'negative', 'complaint',
                       'shuffle', 'Shuffle repeats the same songs')
        second = aspect('Premium subscription is expensive', 'pricing', 'negative',
                        'complaint', 'Premium', 'Premium costs too much')
        result = extract.postprocess_review({'aspects': [first, first, second],
                                             'behavioral_signals': []}, text)
        self.assertEqual(len(result['aspects']), 2)
        self.assertIn('duplicate_aspect', [x['issue_type'] for x in result['validation_issues']])

    def test_praise_request_and_mixed_review(self):
        text = 'Recommendations are amazing, but shuffle is broken. Please fix shuffle.'
        rows = [
            aspect('Personalized recommendations are accurate', 'recommendations',
                   'positive', 'praise', 'music recommendations', 'Recommendations are amazing'),
            aspect('Shuffle fails to play songs correctly', 'bug', 'negative',
                   'complaint', 'shuffle', 'shuffle is broken'),
            aspect('Fix broken shuffle', 'bug', 'negative', 'request', 'shuffle',
                   'Please fix shuffle'),
        ]
        result = extract.postprocess_review({'aspects': rows, 'behavioral_signals': []}, text)
        self.assertEqual([x['polarity'] for x in result['aspects']],
                         ['positive', 'negative', 'negative'])
        self.assertEqual(result['aspects'][0]['category'], 'recommendations')
        self.assertEqual(result['aspects'][0]['signal_type'], 'praise')

    def test_generic_sentiment_unsupported_evidence_and_title(self):
        result = extract.postprocess_review({
            'aspects': [aspect('Bad', 'other', 'negative', 'complaint', 'app', 'Bad'),
                        aspect('Music stops playing', 'bug', 'negative', 'complaint',
                               'music playback', 'never said'),
                        aspect('Offline music fails', 'bug', 'negative', 'complaint',
                               'offline music', 'Offline music fails')],
            'behavioral_signals': []}, 'Bad', 'Offline music fails')
        self.assertEqual(len(result['aspects']), 1)
        self.assertEqual({x['issue_type'] for x in result['validation_issues']},
                         {'generic_aspect', 'unsupported_aspect_evidence'})

    def test_evidence_recovery_uses_exact_original_span(self):
        result = extract.postprocess_review({
            'aspects': [aspect('Music stops unexpectedly', 'bug', 'negative',
                               'complaint', 'playback', ' Music stops')],
            'behavioral_signals': []}, 'Music stops')
        self.assertEqual(result['aspects'][0]['evidence'], 'Music stops')
        self.assertEqual(result['validation_issues'][0]['issue_type'],
                         'unsupported_aspect_evidence')
        self.assertEqual(result['validation_issues'][0]['status'], 'recovered_local')

    def test_behavior_tense_and_troubleshooting_regressions(self):
        cases = [
            ('actual_uninstall', 'about to just trash this app and never use it again',
             'uninstall_intent'),
            ('cancellation_intent', 'I cancelled my subscription months ago',
             'actual_cancellation'),
            ('switching_intent', 'I use other apps now for music', 'actual_switch'),
            ('actual_uninstall', 'I just deleted the app and reinstalled it', None),
            ('switching_intent', "I really don't want to switch apps", None),
        ]
        for original, evidence, expected in cases:
            with self.subTest(evidence=evidence):
                result = extract.postprocess_review({
                    'aspects': [], 'behavioral_signals': [behavior(original, evidence)]},
                    evidence)
                self.assertEqual([s['type'] for s in result['behavioral_signals']],
                                 [expected] if expected else [])
        context = 'I deleted the app, then reinstalled it to fix playback.'
        result = extract.postprocess_review({
            'aspects': [],
            'behavioral_signals': [behavior('actual_uninstall', 'I deleted the app')]
        }, context)
        self.assertEqual(result['behavioral_signals'], [])

    def test_specific_shuffle_replaces_generic_and_keeps_distinct_issue(self):
        text = ('Shuffle is frustrating. Shuffle repeats the same 10 songs. '
                'Shuffle also adds songs outside my playlist.')
        rows = [
            aspect('Shuffle is frustrating', 'performance', 'negative',
                   'complaint', 'shuffle', 'Shuffle is frustrating'),
            aspect('Shuffle repeats the same 10 songs', 'performance', 'negative',
                   'complaint', 'shuffle', 'Shuffle repeats the same 10 songs'),
            aspect('Shuffle adds songs outside a playlist', 'usability', 'negative',
                   'complaint', 'shuffle', 'Shuffle also adds songs outside my playlist'),
        ]
        result = extract.postprocess_review({'aspects': rows, 'behavioral_signals': []}, text)
        self.assertEqual(len(result['aspects']), 2)
        self.assertEqual(result['aspects'][0]['description'],
                         'Shuffle repeats the same 10 songs')
        self.assertTrue(all(a['category'] == 'usability' for a in result['aspects']))

    def test_playlist_restriction_is_usability_but_slow_loading_is_performance(self):
        text = 'Playlists cannot be played in order. Playlists load slowly.'
        rows = [
            aspect('Playlists cannot be played in order', 'performance', 'negative',
                   'complaint', 'playlists', 'Playlists cannot be played in order'),
            aspect('Playlists load slowly', 'performance', 'negative',
                   'complaint', 'playlists', 'Playlists load slowly'),
        ]
        result = extract.postprocess_review({'aspects': rows, 'behavioral_signals': []}, text)
        self.assertEqual([a['category'] for a in result['aspects']],
                         ['usability', 'performance'])

    def test_positive_feature_praise_and_missing_feature_recovery(self):
        text = 'Sound quality is excellent. Recommendations are accurate. Navigation is easy.'
        rows = [
            aspect('Sound quality is excellent', 'content_quality', 'positive',
                   'praise', '', 'Sound quality is excellent'),
            aspect('Music recommendations are accurate', 'feature_request', 'positive',
                   'praise', '', 'Recommendations are accurate'),
            aspect('Navigation is easy', 'usability', 'positive', 'praise', '',
                   'Navigation is easy'),
        ]
        result = extract.postprocess_review({'aspects': rows, 'behavioral_signals': []}, text)
        self.assertEqual(len(result['aspects']), 3)
        self.assertEqual([a['category'] for a in result['aspects']],
                         ['content_quality', 'recommendations', 'usability'])
        self.assertEqual([a['feature'] for a in result['aspects']],
                         ['sound quality', 'music recommendations', 'navigation'])

    def test_targeted_repair_preserves_valid_aspects_and_rejects_fabrication(self):
        row = {'review_key': '0:test', 'text': 'Ads are frequent. Shuffle repeats the same songs.',
               'title': ''}
        valid = aspect('Frequent ads interrupt listening', 'ads', 'negative',
                       'complaint', 'advertising', 'Ads are frequent')
        invalid = aspect('', 'usability', 'negative', 'complaint', '',
                         'Shuffle repeats the same songs')
        extracted = {'aspects': [valid, invalid], 'behavioral_signals': []}
        original = extract.postprocess_review(extracted, row['text'])
        self.assertEqual(len(original['aspects']), 1)
        candidates = extract.repair_candidates(row, extracted, original)
        self.assertEqual(len(candidates), 1)
        repaired_aspect = aspect('Shuffle repeats the same songs', 'usability',
                                 'negative', 'complaint', 'shuffle',
                                 'Shuffle repeats the same songs')

        class Responses:
            def create(self, **kwargs):
                self_outer.assertTrue(kwargs['text']['format']['strict'])
                return SimpleNamespace(status='completed', output_text=json.dumps({
                    'repairs': [{'review_key': '0:test', 'original_index': 1,
                                 'aspect': repaired_aspect}]}),
                    usage=SimpleNamespace(input_tokens=20, output_tokens=10))
        self_outer = self
        repairs, _ = extract.request_aspect_repairs(
            SimpleNamespace(responses=Responses()), 'gpt-4o-mini', [row], candidates, 2500)
        final = extract.apply_aspect_repairs(row, extracted, original, candidates, repairs, 2500)
        self.assertEqual(len(final['aspects']), 2)
        self.assertIn('recovered_api', [i['status'] for i in final['validation_issues']])
        bad = {('0:test', 1): aspect('Shuffle issue', 'usability', 'negative',
                                    'complaint', 'shuffle', 'fabricated quote')}
        still_valid = extract.apply_aspect_repairs(row, extracted, original, candidates, bad, 2500)
        self.assertEqual(len(still_valid['aspects']), 1)
        self.assertIn('repair_failed_validation',
                      [i['issue_type'] for i in still_valid['validation_issues']])

    def test_intent_vs_completed_action_and_unlinked_criticism(self):
        text = ('Premium is money hungry. I am canceling my subscription and switching '
                'to Apple Music. I already uninstalled the app.')
        result = extract.postprocess_review({
            'aspects': [aspect('Premium monetization feels excessive', 'pricing',
                               'negative', 'complaint', 'Premium', 'Premium is money hungry')],
            'behavioral_signals': [
                behavior('cancellation_intent', 'I am canceling my subscription', related=0),
                behavior('switching_intent', 'switching to Apple Music', 'Apple Music'),
                behavior('actual_uninstall', 'I already uninstalled the app'),
            ]}, text)
        self.assertEqual([x['type'] for x in result['behavioral_signals']],
                         ['cancellation_intent', 'switching_intent', 'actual_uninstall'])
        self.assertEqual(result['behavioral_signals'][0]['related_aspect_index'], 0)
        self.assertIsNone(result['behavioral_signals'][1]['related_aspect_index'])

    def test_completed_cancellation_and_switch_are_not_intentions(self):
        text = 'I canceled Premium yesterday and switched to Apple Music.'
        result = extract.postprocess_review({
            'aspects': [], 'behavioral_signals': [
                behavior('actual_cancellation', 'I canceled Premium yesterday'),
                behavior('actual_switch', 'switched to Apple Music', 'Apple Music'),
                behavior('uninstall_intent', 'not present'),
            ]}, text)
        self.assertEqual([x['type'] for x in result['behavioral_signals']],
                         ['actual_cancellation', 'actual_switch'])
        self.assertIn('unsupported_behavior_evidence',
                      [x['issue_type'] for x in result['validation_issues']])

    def test_negative_review_with_five_stars_and_zero_aspects(self):
        result = extract.postprocess_review({'aspects': [], 'behavioral_signals': []}, 'Great!')
        self.assertEqual(result['aspects'], [])
        complaint = aspect('Music stops after one song', 'bug', 'negative',
                           'complaint', 'music playback', 'stops after one song')
        result = extract.postprocess_review({'aspects': [complaint], 'behavioral_signals': []},
                                            'Music stops after one song')
        self.assertEqual(result['aspects'][0]['polarity'], 'negative')

    def test_mock_api_and_versioned_resume(self):
        class Responses:
            def create(self, **kwargs):
                self_outer.assertTrue(kwargs['text']['format']['strict'])
                payload = json.loads(kwargs['input'])
                self_outer.assertIn('review_title', payload[0])
                return SimpleNamespace(status='completed', output_text=json.dumps({
                    'reviews': [{'review_key': payload[0]['review_key'], 'aspects': [],
                                 'behavioral_signals': []}]}),
                    usage=SimpleNamespace(input_tokens=10, output_tokens=5))
        self_outer = self
        result, _ = extract.request_aspects(SimpleNamespace(responses=Responses()),
                                            'gpt-4o-mini',
                                            [{'review_key': '0:test', 'title': '', 'text': 'Great'}], 2500)
        self.assertEqual(result['0:test']['aspects'], [])
        with tempfile.TemporaryDirectory() as td:
            old = Path(td) / 'old.jsonl'
            old.write_text(json.dumps({'records': [{'review_key': '0:test', 'aspects': []}]}) + '\n')
            with self.assertRaisesRegex(ValueError, 'version mismatch'):
                extract.load_log(old)
            new = Path(td) / 'new.jsonl'
            new.write_text(json.dumps({'extraction_schema_version': '2',
                                       'records': [{'review_key': '0:test', 'aspects': [],
                                                    'behavioral_signals': [],
                                                    'validation_issues': []}],
                                       'input_tokens': 10, 'output_tokens': 5}) + '\n' +
                           '{"partial":')
            saved, calls, tokens_in, tokens_out = extract.load_log(new)
            self.assertEqual((len(saved), calls, tokens_in, tokens_out), (1, 1, 10, 5))
            self.assertEqual(len(new.read_text().splitlines()), 1)

    def test_export_retains_metadata_and_behavior(self):
        row = {'review_key': '0:test', 'cluster_id': 0, 'feedback_id': 'test',
               'app_name': 'Spotify', 'text': 'Music stops. I canceled.', 'title': '',
               'stars': '5', 'feedback_date': '2026-01-01', 'data_source': 'store',
               'app_versions': '[]', 'language_status': 'english',
               'sample_roles': 'random', 'random_inclusion_probability': 0.1}
        saved = {'0:test': {'aspects': [aspect('Music stops unexpectedly', 'bug',
                                             'negative', 'complaint', 'music playback',
                                             'Music stops')],
                            'behavioral_signals': [behavior('actual_cancellation',
                                                            'I canceled', related=0)],
                            'validation_issues': [extract._issue(
                                'unsupported_aspect_evidence', 'bad quote',
                                'recovered_local', 0)]}}
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td)
            extract.export_results(dest, [row], saved, 'Spotify', 'gpt-4o-mini', 1, 10, 5)
            review = pq.read_table(dest / 'review_extractions.parquet').to_pylist()[0]
            signal = pq.read_table(dest / 'review_behavioral_signals.parquet').to_pylist()[0]
            self.assertEqual(review['random_inclusion_probability'], 0.1)
            self.assertEqual(review['behavioral_signals'][0]['type'], 'actual_cancellation')
            self.assertEqual(signal['related_aspect_index'], 0)
            self.assertEqual(pq.read_table(dest / 'review_aspects.parquet').num_rows, 1)
            issue = pq.read_table(dest / 'review_validation_issues.parquet').to_pylist()[0]
            self.assertEqual((issue['status'], issue['original_index']),
                             ('recovered_local', 0))

    def test_export_zero_aspect_review(self):
        row = {'review_key': '0:empty', 'cluster_id': 0, 'feedback_id': 'empty',
               'app_name': 'Spotify', 'text': 'Great!', 'title': '', 'stars': '5',
               'feedback_date': '2026-01-01', 'data_source': 'store',
               'app_versions': '[]', 'language_status': 'english',
               'sample_roles': 'random', 'random_inclusion_probability': 0.1}
        saved = {'0:empty': {'aspects': [], 'behavioral_signals': [],
                             'validation_issues': []}}
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td)
            extract.export_results(dest, [row], saved, 'Spotify', 'gpt-4o-mini', 1, 10, 5)
            self.assertEqual(pq.read_table(dest / 'review_extractions.parquet').num_rows, 1)
            self.assertEqual(pq.read_table(dest / 'review_aspects.parquet').num_rows, 0)
            self.assertEqual(pq.read_table(dest / 'review_behavioral_signals.parquet').num_rows, 0)


if __name__ == '__main__':
    unittest.main()
