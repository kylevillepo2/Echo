#!/usr/bin/env python3
"""Export compact, app-scoped topic statistics from full similarity tagging results."""
import argparse
import calendar
import hashlib
import json
import math
import os
import re
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

import pyarrow.parquet as pq

from similarity_common import read_json

PROJECT = Path(__file__).resolve().parents[1]
FRONTEND = PROJECT.parent
SCHEMA_VERSION = 'topic-insights-v1'
TAGGED = Path('similarity-workflow-v1/description/tagging-global/tagged_reviews.parquet')
TOPIC_META = Path('similarity-workflow-v1/description/topic-embeddings/topic_metadata.parquet')
TAG_REPORT = Path('similarity-workflow-v1/description/tagging-global/tagging_report.json')


def slugify(name):
    return re.sub(r'-+', '-', re.sub(r'[^a-z0-9]+', '-', name.casefold())).strip('-')


def sha256(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def find_refinement(root, override=None):
    """Locate the taxonomy that was built from this app's exact cluster assignments."""
    root = root.resolve()
    source = root / 'aspect-clusters/aspect_clusters.parquet'
    if not source.is_file():
        raise ValueError(f'Missing aspect clusters for {root}')
    source_hash = sha256(source)
    if override:
        candidates = [override.expanduser().resolve()]
    else:
        candidates = [root / 'refined-topics']
        for parent in (root.parent.parent, Path.cwd(), FRONTEND.parent):
            folder = parent / 'refined-topics'
            if folder.is_dir():
                candidates.extend(sorted(p for p in folder.iterdir() if p.is_dir()))
    matches = []
    for candidate in dict.fromkeys(candidates):
        if not all((candidate / name).is_file() for name in
                   ('canonical_topics.json', 'refined_aspects.parquet')):
            continue
        config = candidate / 'run_config.json'
        if config.is_file():
            if read_json(config).get('source_assignment_sha256') == source_hash:
                matches.append(candidate)
        elif candidate == root / 'refined-topics' or override:
            matches.append(candidate)
    if len(matches) != 1:
        raise ValueError(f'Expected one matching refinement for {root}; found {len(matches)}. '
                         'Use --refinement-root for a single app.')
    return matches[0]


def month_range(start, end):
    year, month = start.year, start.month
    while (year, month) <= (end.year, end.month):
        yield f'{year:04d}-{month:02d}'
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)


def parse_date(value):
    if value is None or not str(value).strip():
        return None
    try:
        return datetime.fromisoformat(str(value).strip().replace('Z', '+00:00')).date()
    except ValueError:
        return None


def parse_stars(value):
    if value is None or str(value).strip() not in {'1', '2', '3', '4', '5'}:
        return None
    return int(str(value).strip())


def distribution(counts):
    return [{'stars': stars, 'count': counts[stars]} for stars in range(1, 6)]


def average(total, count):
    return round(total / count, 4) if count else None


def percentage(numerator, denominator):
    return round(100 * numerator / denominator, 4) if denominator else None


def partial_reasons(month, first, last, today):
    year, number = map(int, month.split('-'))
    reasons = []
    if (year, number) == (first.year, first.month) and first.day > 1:
        reasons.append('first_observed_review_after_month_start')
    last_day = calendar.monthrange(year, number)[1]
    if (year, number) == (last.year, last.month) and last.day < last_day:
        reasons.append('last_observed_review_before_month_end')
    if (year, number) >= (today.year, today.month):
        reasons.append('current_or_future_month')
    return reasons


def select_trend(monthly, min_monthly_reviews, min_topic_count, min_change_pp):
    complete = [m for m in monthly if not m['partial_month']]
    if len(complete) < 2:
        return {'label': 'insufficient_data', 'change_percentage_points': None,
                'latest_complete_month': complete[-1]['month'] if complete else None,
                'previous_complete_month': None}
    old, new = complete[-2:]
    old_share, new_share = old['percentage_of_monthly_reviews'], new['percentage_of_monthly_reviews']
    change = round(new_share - old_share, 4) if old_share is not None and new_share is not None else None
    enough = (min(old['total_app_reviews'], new['total_app_reviews']) >= min_monthly_reviews
              and old['review_count'] + new['review_count'] >= min_topic_count and change is not None)
    label = ('insufficient_data' if not enough else 'increasing' if change >= min_change_pp
             else 'decreasing' if change <= -min_change_pp else 'stable')
    return {'label': label, 'change_percentage_points': change,
            'latest_complete_month': new['month'], 'previous_complete_month': old['month']}


def aggregate_rows(rows, topics, *, app_name, app_id, run_slug, taxonomy_version,
                   method, representation, embedding_model, threshold, generated_at,
                   min_monthly_reviews=30, min_topic_count=5, min_change_pp=2.0,
                   representative_count=3):
    """Aggregate full review rows. Each review_key must identify exactly one source review."""
    topics_by_id = {t['topic_id']: t for t in topics}
    if len(topics_by_id) != len(topics):
        raise ValueError('Duplicate approved topic IDs')
    now = datetime.fromisoformat(generated_at.replace('Z', '+00:00')).date()
    seen_reviews = set()
    total = tagged = missing_date = missing_stars = 0
    stars_all = Counter()
    dates = []
    month_total = Counter()
    topic_count = Counter()
    topic_stars = defaultdict(Counter)
    topic_rating_sum = Counter()
    topic_rating_count = Counter()
    topic_score_sum = defaultdict(float)
    topic_score_count = Counter()
    topic_month = defaultdict(Counter)
    topic_month_stars = defaultdict(lambda: defaultdict(Counter))
    topic_missing_date = Counter()
    examples = defaultdict(list)
    for row in rows:
        key = row.get('review_key')
        if not key or key in seen_reviews:
            raise ValueError(f'Missing or duplicate review_key: {key!r}')
        seen_reviews.add(key)
        total += 1
        when = parse_date(row.get('feedback_date'))
        stars = parse_stars(row.get('stars'))
        if when:
            dates.append(when)
            month_total[when.strftime('%Y-%m')] += 1
        else:
            missing_date += 1
        if stars:
            stars_all[stars] += 1
        else:
            missing_stars += 1
        best = {}
        for assignment in row.get('topics') or []:
            tid = assignment.get('topic_id')
            if tid not in topics_by_id:
                raise ValueError(f'Unknown or unapproved topic ID {tid!r} in {key}')
            value = assignment.get('similarity')
            if value is None or not math.isfinite(float(value)) or not -1 <= float(value) <= 1:
                raise ValueError(f'Invalid cosine similarity for {tid} in {key}')
            if tid not in best or float(value) > best[tid]:
                best[tid] = float(value)
        if best:
            tagged += 1
        for tid, score in best.items():
            topic_count[tid] += 1
            topic_score_sum[tid] += score
            topic_score_count[tid] += 1
            if stars:
                topic_stars[tid][stars] += 1
                topic_rating_sum[tid] += stars
                topic_rating_count[tid] += 1
            if when:
                month = when.strftime('%Y-%m')
                topic_month[tid][month] += 1
                if stars:
                    topic_month_stars[tid][month]['sum'] += stars
                    topic_month_stars[tid][month]['count'] += 1
            else:
                topic_missing_date[tid] += 1
            snippet = ' '.join(str(row.get('full_text') or '').split())[:220]
            if snippet:
                examples[tid].append((score, str(key), {
                    'review_key': str(key), 'feedback_id': row.get('feedback_id'),
                    'data_source': row.get('data_source'), 'snippet': snippet,
                    'cosine_similarity': round(score, 4)}))
    if not total:
        raise ValueError('Need at least one review')
    first, last = (min(dates), max(dates)) if dates else (None, None)
    months = list(month_range(first, last)) if dates else []
    monthly_total = []
    month_meta = {}
    for month in months:
        reasons = partial_reasons(month, first, last, now)
        item = {'month': month, 'review_count': month_total[month],
                'partial_month': bool(reasons), 'partial_reasons': reasons,
                'insufficient_review_volume': month_total[month] < min_monthly_reviews}
        monthly_total.append(item)
        month_meta[month] = item
    sorted_topics = sorted(topics, key=lambda t: (-topic_count[t['topic_id']], t['topic_id']))
    summaries = []
    reconciliation = {}
    for rank, topic in enumerate(sorted_topics, 1):
        tid = topic['topic_id']
        series = []
        previous_share = None
        for month in months:
            count = topic_month[tid][month]
            denominator = month_total[month]
            share = percentage(count, denominator)
            ratings = topic_month_stars[tid][month]
            series.append({'month': month, 'review_count': count,
                           'total_app_reviews': denominator,
                           'percentage_of_monthly_reviews': share,
                           'average_stars': average(ratings['sum'], ratings['count']),
                           'rated_review_count': ratings['count'],
                           'change_percentage_points': round(share - previous_share, 4)
                           if previous_share is not None and share is not None else None,
                           'partial_month': month_meta[month]['partial_month'],
                           'insufficient_review_volume': month_meta[month]['insufficient_review_volume']})
            previous_share = share
        count = topic_count[tid]
        reconciled = sum(m['review_count'] for m in series) + topic_missing_date[tid] == count
        reconciliation[tid] = reconciled
        representatives = [item for _, _, item in sorted(examples[tid], key=lambda x: (-x[0], x[1]))[:representative_count]]
        summaries.append({'topic_id': tid, 'name': topic['canonical_name'],
                          'definition': topic['definition'], 'parent_category_id': topic.get('parent_category_id'),
                          'parent_category_name': topic.get('parent_category_name'),
                          'rank_by_review_count': rank, 'review_count': count,
                          'percentage_of_all_reviews': percentage(count, total),
                          'average_stars': average(topic_rating_sum[tid], topic_rating_count[tid]),
                          'rated_review_count': topic_rating_count[tid],
                          'missing_rating_count': count - topic_rating_count[tid],
                          'star_distribution': distribution(topic_stars[tid]),
                          'mean_accepted_cosine_similarity': average(topic_score_sum[tid], topic_score_count[tid]),
                          'missing_date_count': topic_missing_date[tid],
                          'monthly': series,
                          'trend': select_trend(series, min_monthly_reviews, min_topic_count, min_change_pp),
                          'representative_reviews': representatives})
    export = {'schema_version': SCHEMA_VERSION, 'generated_at': generated_at,
              'app': {'id': slugify(app_name), 'name': app_name, 'source_app_id': app_id,
                      'pipeline_run_slug': run_slug},
              'tagging': {'method': method, 'topic_representation': representation,
                          'embedding_model': embedding_model, 'taxonomy_version': taxonomy_version,
                          'global_cosine_threshold': threshold,
                          'topic_ids_are_app_scoped': True},
              'summary': {'total_reviews': total, 'reviews_with_topics': tagged,
                          'tagging_coverage_percent': percentage(tagged, total),
                          'average_stars': average(sum(s * n for s, n in stars_all.items()),
                                                   total - missing_stars),
                          'rated_review_count': total - missing_stars,
                          'missing_rating_count': missing_stars,
                          'star_distribution': distribution(stars_all),
                          'earliest_review_date': first.isoformat() if first else None,
                          'latest_review_date': last.isoformat() if last else None,
                          'missing_date_count': missing_date},
              'monthly_reviews': monthly_total, 'topics': summaries,
              'metadata': {'denominator': 'all reviews in this app tagging file, including untagged reviews',
                           'review_unit': 'distinct review_key; not unique users',
                           'similarity_interpretation': 'cosine similarity, not probability or sentiment',
                           'validation_limitation': 'Topic matches and earlier reference labels are machine-generated, not human verified.',
                           'trend_rule': {'minimum_monthly_reviews': min_monthly_reviews,
                                          'minimum_topic_mentions_across_two_months': min_topic_count,
                                          'minimum_change_percentage_points': min_change_pp},
                           'coverage_limitation': 'The source corpus may be sampled or uneven across history; monthly shares describe only this export.',
                           'taxonomy_scope': 'App-specific canonical topics; no shared finance taxonomy.'}}
    checks = {'app_review_reconciliation': sum(month_total.values()) + missing_date == total,
              'topic_review_reconciliation': all(reconciliation.values()),
              'topic_reconciliation_failures': [tid for tid, ok in reconciliation.items() if not ok],
              'tagged_count_reconciliation': tagged <= total,
              'rating_reconciliation': sum(stars_all.values()) + missing_stars == total}
    validation = {'app': app_name, 'run_slug': run_slug, 'total_reviews': total,
                  'reviews_with_topics': tagged, 'approved_topic_count': len(topics),
                  'missing_date_records': missing_date, 'missing_rating_records': missing_stars,
                  'monthly_coverage': {'first_month': months[0] if months else None,
                                       'last_month': months[-1] if months else None,
                                       'month_count': len(months),
                                       'partial_months': [m['month'] for m in monthly_total if m['partial_month']],
                                       'low_volume_months': [m['month'] for m in monthly_total if m['insufficient_review_volume']]},
                  'checks': checks,
                  'warnings': ['Historical review coverage may be sampled or uneven.']}
    if not all(v for k, v in checks.items() if isinstance(v, bool)):
        raise ValueError(f'Aggregation reconciliation failed for {app_name}: {checks}')
    return export, validation


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
    os.replace(temporary, path)


def discover_runs(runs_root):
    runs = []
    for root in sorted(runs_root.iterdir()):
        index = root / 'review-embeddings/app_index.json'
        if index.is_file() and (root / TAGGED).is_file():
            names = list(read_json(index))
            if len(names) != 1:
                raise ValueError(f'Expected one app per run: {root}')
            runs.append((names[0], root))
    return runs


def aggregate_app(name, root, args, generated_at):
    refinement = find_refinement(root, args.refinement_root)
    taxonomy_path = refinement / 'canonical_topics.json'
    taxonomy = read_json(taxonomy_path)
    blocked = {x['cluster_id'] for group in ('clusters_needing_split', 'clusters_needing_review')
               for x in taxonomy.get(group, [])}
    topics = [t for t in taxonomy['topics'] if t['relevance_status'] == 'keep'
              and not blocked.intersection(t['original_cluster_ids'])]
    metadata = pq.read_table(root / TOPIC_META).to_pylist()
    if {t['topic_id'] for t in topics} != {t['topic_id'] for t in metadata}:
        raise ValueError(f'Approved topic IDs disagree with tagging model for {name}')
    tag_report = read_json(root / TAG_REPORT)
    threshold = tag_report['threshold_configuration']['global_threshold']
    tag_path = root / TAGGED
    pf = pq.ParquetFile(tag_path)
    taxonomy_hash = sha256(taxonomy_path)
    required = {'review_key', 'feedback_id', 'data_source', 'feedback_date', 'stars',
                'full_text', 'app_id', 'topics', 'method', 'taxonomy_version', 'topic_representation'}
    if not required.issubset(pf.schema_arrow.names):
        raise ValueError(f'Tagged review columns missing: {required - set(pf.schema_arrow.names)}')
    values = []
    source_ids = set()
    for batch in pf.iter_batches(batch_size=4096, columns=sorted(required)):
        for row in batch.to_pylist():
            if row['taxonomy_version'] != taxonomy_hash:
                raise ValueError(f'Taxonomy version mismatch in {name}')
            if row['method'] != 'semantic_similarity' or row['topic_representation'] != 'description':
                raise ValueError(f'Unexpected tagging method for {name}')
            source_ids.add(row['app_id'])
            values.append(row)
    if (len(source_ids) != 1 or tag_report['total_reviews_processed'] != len(values)
            or tag_report['taxonomy_version'] != taxonomy_hash
            or tag_report['output_sha256'] != sha256(tag_path)):
        raise ValueError(f'App identity or review count mismatch for {name}')
    manifest = read_json(next((root / 'review-embeddings/apps').glob('*/manifest.json')))
    if manifest['row_count'] != len(values):
        raise ValueError(f'Original embedding metadata count differs from tagging output for {name}')
    export, validation = aggregate_rows(
        values, topics, app_name=name, app_id=next(iter(source_ids)), run_slug=root.name,
        taxonomy_version=taxonomy_hash, method='semantic_similarity',
        representation='description', embedding_model=tag_report['embedding_model'],
        threshold=threshold, generated_at=generated_at,
        min_monthly_reviews=args.min_monthly_reviews, min_topic_count=args.min_topic_count,
        min_change_pp=args.min_change_pp, representative_count=args.representative_count)
    if export['summary']['reviews_with_topics'] != tag_report['reviews_with_topics']:
        raise ValueError(f'Tagged review count differs from source tagging report for {name}')
    return export, validation


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument('--app', help='Exact app name, case insensitive')
    choice.add_argument('--all', action='store_true', help='Aggregate every completed app run')
    parser.add_argument('--runs-root', type=Path, help='Defaults to ./pipeline-runs when present')
    parser.add_argument('--refinement-root', type=Path, help='Override one app refinement folder')
    parser.add_argument('--output-dir', type=Path, default=FRONTEND / 'static/data/insights')
    parser.add_argument('--min-monthly-reviews', type=int, default=30)
    parser.add_argument('--min-topic-count', type=int, default=5)
    parser.add_argument('--min-change-pp', type=float, default=2.0)
    parser.add_argument('--representative-count', type=int, default=3)
    args = parser.parse_args()
    if min(args.min_monthly_reviews, args.min_topic_count, args.representative_count) < 1 or args.min_change_pp < 0:
        parser.error('Sample counts must be positive and the change threshold nonnegative')
    candidates = [Path.cwd() / 'pipeline-runs', PROJECT / 'pipeline-runs', FRONTEND.parent / 'pipeline-runs']
    runs_root = args.runs_root or next((p for p in candidates if p.is_dir()), candidates[0])
    runs = discover_runs(runs_root.resolve())
    if args.app:
        runs = [(name, root) for name, root in runs if name.casefold() == args.app.casefold()]
        if len(runs) != 1:
            raise ValueError(f'Expected one completed run for {args.app!r}; found {len(runs)}')
    if not runs:
        raise ValueError(f'No completed similarity runs under {runs_root}')
    generated_at = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
    report = {'schema_version': SCHEMA_VERSION, 'generated_at': generated_at,
              'app_count': len(runs), 'apps': [], 'errors': []}
    for name, root in runs:
        try:
            export, validation = aggregate_app(name, root, args, generated_at)
            target = args.output_dir / f'{slugify(name)}.json'
            atomic_json(target, export)
            validation['output'] = str(target.resolve())
            validation['json_bytes'] = target.stat().st_size
            report['apps'].append(validation)
            print(f'{name}: {export["summary"]["total_reviews"]:,} reviews, '
                  f'{len(export["topics"])} topics -> {target}')
        except (OSError, ValueError, KeyError, TypeError) as exc:
            report['errors'].append({'app': name, 'error': str(exc)})
            print(f'{name}: ERROR {exc}')
    report['total_reviews'] = sum(x['total_reviews'] for x in report['apps'])
    report['all_checks_passed'] = not report['errors'] and all(
        all(v for v in app['checks'].values() if isinstance(v, bool)) for app in report['apps'])
    atomic_json(args.output_dir / 'aggregation_validation_report.json', report)
    if report['errors']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
