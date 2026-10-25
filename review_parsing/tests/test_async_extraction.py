import asyncio
import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace


SCRIPT = Path(__file__).resolve().parents[1] / 'nlp' / 'extract_review_aspects.py'
SPEC = importlib.util.spec_from_file_location('extract_async', SCRIPT)
extract = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(extract)


def review(number):
    return {'review_key': f'0:{number}', 'text': f'Review {number}', 'title': '',
            'cluster_id': 0, 'feedback_id': str(number), 'app_name': 'Spotify',
            'stars': '5', 'feedback_date': '2026-01-01', 'data_source': 'store',
            'app_versions': '[]', 'language_status': 'english',
            'sample_roles': 'random', 'random_inclusion_probability': 0.1}


def options(**overrides):
    values = dict(concurrency=5, rpm=0, tpm=0, max_requests=0, batch_size=8,
                  model='gpt-4o-mini', max_chars=2500, retries=1,
                  max_retry_seconds=10, repair_invalid=False)
    values.update(overrides)
    return SimpleNamespace(**values)


class FakeRaw:
    def __init__(self, body):
        self.body = body
        self.headers = {'x-ratelimit-limit-requests': '1000',
                        'x-ratelimit-limit-tokens': '1000000'}

    async def parse(self):
        return SimpleNamespace(status='completed', output_text=json.dumps(self.body),
                               usage=SimpleNamespace(input_tokens=100, output_tokens=40))


class FakeSyncRaw(FakeRaw):
    def parse(self):
        return SimpleNamespace(status='completed', output_text=json.dumps(self.body),
                               usage=SimpleNamespace(input_tokens=100, output_tokens=40))


class FakeClient:
    def __init__(self, delay=0.002, omit_once=None, fail_once=None):
        self.delay = delay
        self.omit_once = omit_once
        self.fail_once = fail_once
        self.calls = []
        self.active = 0
        self.max_active = 0
        self.responses = SimpleNamespace(with_raw_response=self)

    async def create(self, **request):
        payload = json.loads(request['input'])
        keys = [item['review_key'] for item in payload]
        self.calls.append(list(keys))
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            await asyncio.sleep(self.delay)
            if self.fail_once and self.fail_once in keys:
                self.fail_once = None
                error = RuntimeError('temporary server error')
                error.status_code = 503
                error.response = SimpleNamespace(headers={'Retry-After': '0'})
                raise error
            if self.omit_once in keys:
                keys.remove(self.omit_once)
                self.omit_once = None
            return FakeRaw({'reviews': [
                {'review_key': key, 'aspects': [], 'behavioral_signals': []}
                for key in keys]})
        finally:
            self.active -= 1


class AsyncExtractionTests(unittest.TestCase):
    def test_request_schema_only_allows_current_batch_ids(self):
        captured = []

        class SchemaClient(FakeClient):
            async def create(self, **request):
                captured.append(request['text']['format']['schema'])
                return await super().create(**request)

        rows = [review(i) for i in range(4)]
        _, _, _, saved, _ = self.run_mock(rows, SchemaClient(), options(batch_size=2))
        self.assertEqual(len(saved), 4)
        enums = [s['properties']['reviews']['items']['properties']['review_key']['enum']
                 for s in captured]
        self.assertEqual(enums, [['0:0', '0:1'], ['0:2', '0:3']])
        self.assertNotIn('enum', extract.SCHEMA['properties']['reviews']['items']['properties']['review_key'])
        repair = extract.schema_for_keys(['0:2'], repair=True)
        self.assertEqual(repair['properties']['repairs']['items']['properties']['review_key']['enum'], ['0:2'])
        self.assertNotIn('enum', extract.REPAIR_SCHEMA['properties']['repairs']['items']['properties']['review_key'])

    def test_invalid_ids_split_to_singletons_and_all_usage_is_checkpointed(self):
        class WrongBatchKey(FakeClient):
            async def create(self, **request):
                raw = await super().create(**request)
                if len(json.loads(request['input'])) > 1:
                    raw.body['reviews'][0]['review_key'] = '4:100000000'
                return raw

        client = WrongBatchKey()
        rows = [review(i) for i in range(4)]
        outcomes, metrics, budget, saved, calls = self.run_mock(
            rows, client, options(batch_size=4, retries=3))
        self.assertEqual(set(saved), {r['review_key'] for r in rows})
        self.assertNotIn('4:100000000', saved)
        self.assertEqual(outcomes[0][0], 'done')
        self.assertEqual(metrics.batch_splits, 3)
        self.assertEqual(metrics.validation_failures, 3)
        self.assertEqual(calls, budget.used)
        self.assertEqual(calls, 7)  # 4 -> 2+2 -> individual reviews; no repeated bad full batch.
        self.assertEqual(metrics.input_tokens, 700)

    def test_bad_singleton_stays_pending_without_stopping_other_reviews(self):
        class OneBadReview(FakeClient):
            async def create(self, **request):
                raw = await super().create(**request)
                if '0:0' in [r['review_key'] for r in json.loads(request['input'])]:
                    raw.body['reviews'][0]['review_key'] = 'invented'
                return raw

        rows = [review(i) for i in range(4)]
        client = OneBadReview()
        outcomes, metrics, budget, saved, calls = self.run_mock(
            rows, client, options(batch_size=2, concurrency=1, retries=0))
        self.assertEqual(set(saved), {'0:1', '0:2', '0:3'})
        errors = [o for o in outcomes if o[0] == 'error']
        self.assertEqual(errors[0][1], ['0:0'])
        self.assertEqual(calls, len(client.calls))
        self.assertEqual(calls, budget.used)

    def test_recovery_respects_request_budget_and_does_not_fake_empty_labels(self):
        class WrongKey(FakeClient):
            async def create(self, **request):
                raw = await super().create(**request)
                raw.body['reviews'][0]['review_key'] = 'wrong'
                return raw

        client = WrongKey()
        outcomes, metrics, budget, saved, calls = self.run_mock(
            [review(0), review(1)], client, options(batch_size=2, max_requests=1))
        self.assertEqual(saved, {})
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(calls, 1)
        self.assertEqual(outcomes[0][0], 'request_limit')
        self.assertEqual(set(outcomes[0][1]), {'0:0', '0:1'})

    def test_failed_response_tokens_are_present_in_reloaded_log(self):
        class InvalidUntilSingle(FakeClient):
            async def create(self, **request):
                raw = await super().create(**request)
                if len(raw.body['reviews']) > 1:
                    raw.body['reviews'] = []
                return raw

        with tempfile.TemporaryDirectory() as td:
            log = Path(td) / 'log.jsonl'
            saved = {}
            metrics = extract.ThroughputMetrics(2, 0)
            with contextlib.redirect_stdout(io.StringIO()):
                asyncio.run(extract.run_batches_async(InvalidUntilSingle(), [review(0), review(1)],
                            options(batch_size=2), log, saved, metrics))
            loaded, calls, tokens_in, tokens_out = extract.load_log(log)
            self.assertEqual(set(loaded), {'0:0', '0:1'})
            self.assertEqual((calls, tokens_in, tokens_out), (3, 300, 120))

    def test_malformed_json_recovers_by_splitting(self):
        class BadJSON(FakeRaw):
            async def parse(self):
                response = await super().parse()
                response.output_text = 'not json'
                return response

        class MalformedBatch(FakeClient):
            async def create(self, **request):
                raw = await super().create(**request)
                return BadJSON(raw.body) if len(raw.body['reviews']) > 1 else raw

        outcomes, _, _, saved, calls = self.run_mock([review(0), review(1)], MalformedBatch(), options(batch_size=2))
        self.assertEqual(len(saved), 2)
        self.assertEqual(calls, 3)
        self.assertEqual(outcomes[0][0], 'done')

    def test_singleton_validation_retries_are_bounded(self):
        class AlwaysWrong(FakeClient):
            async def create(self, **request):
                raw = await super().create(**request)
                raw.body['reviews'][0]['review_key'] = 'wrong'
                return raw

        client = AlwaysWrong()
        outcomes, metrics, _, saved, calls = self.run_mock([review(0)], client, options(retries=1))
        self.assertEqual(saved, {})
        self.assertEqual(len(client.calls), 2)
        self.assertEqual(calls, 2)
        self.assertEqual(metrics.batch_splits, 0)
        self.assertEqual(outcomes[0][0], 'error')

    def test_legacy_checkpoint_and_new_usage_records_can_be_resumed_together(self):
        with tempfile.TemporaryDirectory() as td:
            log = Path(td) / 'log.jsonl'
            old = {'extraction_schema_version': '2', 'records': [{
                'review_key': '0:0', 'aspects': [], 'behavioral_signals': [], 'validation_issues': []}],
                'request_count': 1, 'input_tokens': 11, 'output_tokens': 7}
            log.write_text(json.dumps(old) + '\n')
            saved, _, _, _ = extract.load_log(log)
            client = FakeClient()
            metrics = extract.ThroughputMetrics(2, 1)
            with contextlib.redirect_stdout(io.StringIO()):
                asyncio.run(extract.run_batches_async(client, [review(1)], options(), log, saved, metrics))
            saved, calls, tokens_in, tokens_out = extract.load_log(log)
            self.assertEqual(set(saved), {'0:0', '0:1'})
            self.assertEqual(client.calls, [['0:1']])
            self.assertEqual((calls, tokens_in, tokens_out), (2, 111, 47))

    def run_mock(self, rows, client, args):
        with tempfile.TemporaryDirectory() as td:
            log = Path(td) / 'extraction_log.jsonl'
            saved = {}
            metrics = extract.ThroughputMetrics(len(rows), 0)
            with contextlib.redirect_stdout(io.StringIO()):
                outcomes, metrics, budget = asyncio.run(
                    extract.run_batches_async(client, rows, args, log, saved, metrics))
            loaded, calls, tokens_in, tokens_out = extract.load_log(log)
            self.assertEqual(set(loaded), set(saved))
            return outcomes, metrics, budget, loaded, calls

    def test_concurrency_and_batch_sizes(self):
        for batch_size, expected_calls in [(5, 8), (10, 4), (20, 2)]:
            with self.subTest(batch_size=batch_size):
                client = FakeClient(delay=0.01)
                outcomes, metrics, budget, saved, calls = self.run_mock(
                    [review(i) for i in range(40)], client,
                    options(batch_size=batch_size, concurrency=3))
                self.assertEqual(len(saved), 40)
                self.assertEqual(calls, expected_calls)
                self.assertGreater(client.max_active, 1)
                self.assertLessEqual(client.max_active, 3)
                self.assertEqual(metrics.completed, 40)
                self.assertTrue(all(outcome[0] == 'done' for outcome in outcomes))

    def test_sdk_legacy_raw_response_parse_is_synchronous(self):
        class SyncRawClient(FakeClient):
            async def create(self, **request):
                raw = await super().create(**request)
                return FakeSyncRaw(raw.body)

        _, metrics, _, saved, calls = self.run_mock(
            [review(i) for i in range(3)], SyncRawClient(), options(batch_size=3))
        self.assertEqual(len(saved), 3)
        self.assertEqual(calls, 1)
        self.assertEqual(metrics.failed, 0)

    def test_omitted_review_retries_only_missing_key(self):
        client = FakeClient(omit_once='0:2')
        outcomes, metrics, _, saved, calls = self.run_mock(
            [review(i) for i in range(5)], client, options(batch_size=5))
        self.assertEqual(len(saved), 5)
        self.assertEqual(client.calls, [[f'0:{i}' for i in range(5)], ['0:2']])
        self.assertEqual(calls, 2)
        self.assertEqual(metrics.retried, 1)

    def test_duplicate_review_key_keeps_valid_work_and_checkpoints_once(self):
        class DuplicateClient(FakeClient):
            async def create(self, **request):
                raw = await super().create(**request)
                key = raw.body['reviews'][0]['review_key']
                raw.body['reviews'].append({
                    'review_key': key, 'aspects': [], 'behavioral_signals': []})
                return raw

        rows = [review(0), review(1)]
        outcomes, metrics, _, saved, calls = self.run_mock(
            rows, DuplicateClient(), options(batch_size=2))
        self.assertEqual(set(saved), {row['review_key'] for row in rows})
        self.assertEqual(calls, 1)
        self.assertEqual(metrics.failed, 0)
        self.assertEqual(outcomes[0][0], 'done')
        self.assertEqual(saved['0:0']['validation_issues'][0]['issue_type'],
                         'duplicate_review_entry')

        parsed = extract.normalize_partial_json({'reviews': [
            {'review_key': '0:0', 'aspects': [{'description': 'First'}],
             'behavioral_signals': []},
            {'review_key': '0:0', 'aspects': [{'description': 'Second'}],
             'behavioral_signals': [{'related_aspect_index': 0}]},
        ]}, {'0:0'})
        self.assertEqual(len(parsed['0:0']['aspects']), 2)
        self.assertEqual(parsed['0:0']['behavioral_signals'][0]['related_aspect_index'], 1)

    def test_transient_failure_retries_without_duplicate_checkpoint(self):
        client = FakeClient(fail_once='0:0')
        outcomes, metrics, budget, saved, calls = self.run_mock(
            [review(0), review(1)], client, options(batch_size=2))
        self.assertEqual(len(saved), 2)
        self.assertEqual(calls, 2)
        self.assertEqual(metrics.failed, 1)
        self.assertEqual(metrics.retried, 1)
        self.assertEqual(budget.used, 2)

    def test_quota_and_auth_errors_are_permanent(self):
        for status, code in [(401, 'invalid_api_key'), (429, 'insufficient_quota')]:
            with self.subTest(status=status):
                error = RuntimeError('permanent')
                error.status_code = status
                error.body = {'code': code}
                self.assertFalse(extract._retryable(error))

        class AuthFailure(FakeClient):
            async def create(self, **request):
                self.calls.append([item['review_key'] for item in json.loads(request['input'])])
                error = RuntimeError('invalid API key')
                error.status_code = 401
                error.body = {'code': 'invalid_api_key'}
                raise error

        client = AuthFailure()
        outcomes, metrics, budget, saved, calls = self.run_mock(
            [review(0)], client, options(batch_size=1, retries=3))
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(saved, {})
        self.assertEqual(outcomes[0][0], 'error')
        self.assertEqual(metrics.retried, 0)

    def test_rate_governor_adapts_and_retry_after(self):
        async def check():
            governor = extract.RateGovernor(5)
            await governor.rate_limited(0)
            await governor.rate_limited(0)
            self.assertEqual(governor.current, 4)
        asyncio.run(check())
        error = RuntimeError('rate limited')
        error.response = SimpleNamespace(headers={'Retry-After': '3'})
        self.assertEqual(extract._retry_after(error), 3.0)

    def test_resume_skips_saved_reviews(self):
        async def run_two_passes(log):
            rows = [review(i) for i in range(6)]
            args = options(batch_size=2, max_requests=2)
            first = FakeClient()
            saved = {}
            metrics = extract.ThroughputMetrics(6, 0)
            with contextlib.redirect_stdout(io.StringIO()):
                await extract.run_batches_async(first, rows, args, log, saved, metrics)
            saved, _, _, _ = extract.load_log(log)
            pending = [row for row in rows if row['review_key'] not in saved]
            second = FakeClient()
            metrics = extract.ThroughputMetrics(6, len(saved))
            with contextlib.redirect_stdout(io.StringIO()):
                await extract.run_batches_async(second, pending, options(batch_size=2),
                                                log, saved, metrics)
            return first, second, extract.load_log(log)[0]

        with tempfile.TemporaryDirectory() as td:
            first, second, saved = asyncio.run(run_two_passes(Path(td) / 'log.jsonl'))
            self.assertEqual(len(saved), 6)
            self.assertEqual(len(first.calls), 2)
            self.assertEqual(len(second.calls), 1)


if __name__ == '__main__':
    unittest.main()
