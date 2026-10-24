"""Report eligibility and authoritative balance regression fixtures."""
import csv
import json
import unittest
import tempfile
from collections import Counter
from copy import deepcopy
from pathlib import Path

from export_network import export, assert_health_matches_stats, REPO
from fix_switching import build_stats, health_bucket, BALANCE_DEFINITION
import report_rules as rules


def row(review_id='1', source='Alpha', target='Beta', **fields):
    return dict(feedback_id=review_id, source=source, target=target, kind='switch', weight='0.8',
                reasons='price_fees;ads', month='2025-01', evidence=f'I moved from {source} to {target} because of price and ads. Report {review_id}.',
                reviewed_app=source, category='music', reviewer_role='n/a', forced_move='False') | fields


class ExportTests(unittest.TestCase):
    def fixture(self, directory, modern=True):
        path = Path(directory)
        (path / 'app_month_counts.csv').write_text('app_name,category,month,reviews\nAlpha,music,2024-01,100\nAlpha,music,2025-01,200\nBeta,music,2025-01,50\n')
        rows = [row(str(index), month='2024-01' if index % 2 else '2025-01') for index in range(25)]
        rows += [dict(rows[0]), row('return', source='Beta', target='Alpha', kind='return')]
        # Outside-app reports remain visible but must never affect balance.
        rows += [row(f'outside-{index}', target='Gamma') for index in range(40)]
        if modern:
            rows += [row('driver', reviewer_role='driver/courier'), row('unknown', reviewer_role='unclear'),
                     row('forced', forced_move='True')]
        else:
            rows = [{k: v for k, v in item.items() if k not in {'reviewer_role', 'forced_move'}} for item in rows]
        with (path / 'edges.csv').open('w') as handle:
            writer = csv.DictWriter(handle, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)
        star_data = {'Alpha': {'2024-01': Counter({5: 100}), '2025-01': Counter({4: 200})},
                     'Beta': {'2025-01': Counter({5: 50})}}
        stats = build_stats(rows, star_data, {'Alpha': 'music', 'Beta': 'music'})
        (path / 'app_stats.json').write_text(json.dumps(stats))
        return path, stats

    def test_old_and_new_schemas_and_both_endpoint_scope(self):
        for modern in (False, True):
            with self.subTest(modern=modern), tempfile.TemporaryDirectory() as directory:
                path, stats = self.fixture(directory, modern)
                data = export(path)
                self.assertEqual(sum(edge['count'] for edge in data['edges']), 66)
                by_name = {node['name']: node for node in data['nodes']}
                alpha, beta, gamma = (by_name[name] for name in ('Alpha', 'Beta', 'Gamma'))
                self.assertEqual(alpha['reviewCount'], 300)
                self.assertTrue(alpha['observed'])
                self.assertFalse(gamma['observed'])
                self.assertEqual(alpha['health']['bucket'], 'Strongly negative')
                self.assertEqual(beta['health']['bucket'], 'Positive switching balance')
                self.assertEqual(alpha['health']['reports_in'], 1)
                self.assertEqual(alpha['health']['reports_out'], 25)
                self.assertEqual(alpha['health']['total'], 26)
                self.assertEqual(gamma['health']['total'], 0)
                self.assertIsNone(gamma['health']['score'])
                self.assertEqual(stats['meta']['eligible_switch_reports'], 26)
                self.assertEqual(stats['meta']['outside_scope_switch_reports'], 40)
                self.assertEqual(alpha['health']['definition'], BALANCE_DEFINITION)
                self.assertTrue(all(len(pair['quotes']) <= 3 for pair in data['pairs']))
                assert_health_matches_stats(data, stats)

    def test_export_copies_stats_instead_of_calculating(self):
        with tempfile.TemporaryDirectory() as directory:
            path, stats = self.fixture(directory)
            # Distinct sentinel values prove that the exporter cannot overwrite
            # authoritative values using its visible (outside-inclusive) edges.
            stats['apps'][0]['health'].update(score=.123456, bucket='Mixed', reports_in=77, reports_out=55, total=132)
            stats['apps'][0]['health_by_period']['2025'].update(score=-.125, reports_in=7, reports_out=9, total=16)
            (path / 'app_stats.json').write_text(json.dumps(stats))
            data = export(path)
            self.assertEqual(data['nodes'][0]['health'], stats['apps'][0]['health'])
            self.assertEqual(data['nodes'][0]['healthByPeriod'], stats['apps'][0]['health_by_period'])
            for field in ('score', 'bucket', 'reports_in', 'reports_out', 'total', 'definition'):
                corrupted = deepcopy(data)
                corrupted['nodes'][0]['health'][field] = 'wrong'
                with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'Health disagrees'):
                    assert_health_matches_stats(corrupted, stats)
            data['nodes'][0]['healthByPeriod']['2025']['reports_in'] += 1
            with self.assertRaisesRegex(ValueError, 'Health disagrees'):
                assert_health_matches_stats(data, stats)

    def test_missing_stats_fails_without_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            path, _ = self.fixture(directory)
            (path / 'app_stats.json').unlink()
            with self.assertRaisesRegex(ValueError, 'app_stats.json is required'):
                export(path)

    def test_bucket_boundaries(self):
        self.assertEqual(health_bucket(1, 19), 'Too few reports')
        self.assertEqual(health_bucket(.21, 20), 'Positive switching balance')
        self.assertEqual(health_bucket(.2, 20), 'Mixed')
        self.assertEqual(health_bucket(-.2, 20), 'Mixed')
        self.assertEqual(health_bucket(-.21, 20), 'Negative switching balance')
        self.assertEqual(health_bucket(-.5, 20), 'Negative switching balance')
        self.assertEqual(health_bucket(-.51, 20), 'Strongly negative')

    def test_skype_cutoff_overrides_old_blanket_flag(self):
        for month, forced in [('2024-10', False), ('2025-01', False), ('2025-02', True), ('2026-01', True), ('', False)]:
            with self.subTest(month=month):
                self.assertEqual(rules.is_forced(row(source='Skype', month=month, forced_move='True')), forced)
        edges = [row('pre', 'Skype', 'Zoom', month='2025-01', forced_move='True'),
                 row('cutoff', 'Skype', 'Zoom', month='2025-02', forced_move='True'),
                 row('reverse', 'Zoom', 'Skype', month='2025-03')]
        result = build_stats(edges, {}, {'Skype': 'calls', 'Zoom': 'calls'}, {'Skype': {}})
        skype = next(app for app in result['apps'] if app['app'] == 'Skype')
        self.assertEqual(skype['health']['reports_in'], 1)
        self.assertEqual(skype['health']['reports_out'], 1)
        self.assertEqual(skype['health_by_period']['2025'], skype['health'])

    def test_uber_markets_and_own_review_attribution(self):
        cases = [('Uber', 'Lyft', 'Uber', 'Uber (Rides)', 'Lyft', 'Uber (Rides)'),
                 ('Lyft', 'Uber', 'Uber', 'Lyft', 'Uber (Rides)', 'Uber (Rides)'),
                 ('Uber', 'DoorDash', 'Uber', 'Uber Eats', 'DoorDash', 'Uber Eats'),
                 ('Grubhub', 'Uber', 'Grubhub', 'Grubhub', 'Uber Eats', 'Grubhub'),
                 ('Uber Eats', 'Instacart', 'Uber Eats', 'Uber Eats', 'Instacart', 'Uber Eats')]
        for source, target, reviewed, expected_source, expected_target, expected_reviewed in cases:
            with self.subTest(source=source, target=target):
                normalized = rules.normalize_edge(row(source=source, target=target, reviewed_app=reviewed))
                self.assertEqual((normalized['source'], normalized['target'], normalized['reviewed_app']),
                                 (expected_source, expected_target, expected_reviewed))
                self.assertEqual(rules.normalize_edge(normalized), normalized)
        mentions = [{'feedback_id': key, 'reviewed_app': 'Uber', 'mentioned_app': app}
                    for key, app in [('a', 'Lyft'), ('b', 'DoorDash'), ('c', 'Lyft'), ('c', 'DoorDash'), ('d', 'Other')]]
        self.assertEqual(rules.uber_review_markets(mentions), {'a': 'Uber (Rides)', 'b': 'Uber Eats'})
        with self.assertRaisesRegex(ValueError, 'Cannot assign Uber market'):
            rules.normalize_edge(row(source='Uber', target='Unknown app'))
        edges = [row(str(i), 'DoorDash', 'Uber', category='rides_delivery', reviewer_role='customer') for i in range(25)]
        edges += [row('ride', 'Uber', 'Lyft', category='rides_delivery', reviewer_role='customer')]
        result = build_stats(edges, {}, {'Uber': 'rides_delivery', 'DoorDash': 'rides_delivery'})
        apps = {app['app']: app for app in result['apps']}
        self.assertNotIn('Uber', apps)
        self.assertEqual(apps['Uber Eats']['health']['reports_in'], 25)
        self.assertEqual(apps['Uber (Rides)']['health']['total'], 0)

    def test_live_export_agrees_with_authoritative_stats(self):
        stats_path = REPO.parent / 'out/all/app_stats.json'
        export_path = REPO / 'src/lib/data/network.json'
        if not stats_path.exists() or not export_path.exists():
            self.skipTest('Live artifacts are not present')
        stats = json.loads(stats_path.read_text())
        data = json.loads(export_path.read_text())
        assert_health_matches_stats(data, stats)
        records = stats['apps'] + stats.get('outside_apps', [])
        self.assertEqual(sum(app['health']['reports_in'] for app in records), stats['meta']['eligible_switch_reports'])
        self.assertEqual(sum(app['health']['reports_out'] for app in records), stats['meta']['eligible_switch_reports'])
        for app in records:
            for health in [app['health'], *app['health_by_period'].values()]:
                self.assertEqual(health['total'], health['reports_in'] + health['reports_out'])
                self.assertEqual(health['definition'], BALANCE_DEFINITION)
        self.assertLess(export_path.stat().st_size, 2_000_000)
        self.assertNotIn('loses_users_to', stats_path.read_text())
        self.assertNotIn('wins_users_from', stats_path.read_text())


if __name__ == '__main__':
    unittest.main()
