#!/usr/bin/env python3
"""Build a manual review checklist for an aspect-extraction run.

The reported flags are heuristics for review, not accuracy measurements.
"""

import argparse
import csv
import json
import random
from collections import Counter, defaultdict
from pathlib import Path

import pyarrow.parquet as pq


def read_table(path):
    if not path.is_file():
        raise ValueError(f'Missing extraction file: {path}')
    return pq.read_table(path).to_pylist()


def star_band(value):
    try:
        stars = float(value)
    except (TypeError, ValueError):
        return 'unrated'
    if stars <= 2:
        return '1-2'
    if stars == 3:
        return '3'
    return '4-5'


def flag_review(review, aspects, signals):
    flags = []
    seen = set()
    text = review.get('text') or ''
    title = review.get('title') or ''
    generic = {'bad', 'good', 'great', 'great app', 'good app', 'bad app',
               'bad user experience', 'overall dissatisfaction with the app',
               'user is disappointed'}
    for aspect in aspects:
        description = (aspect.get('description') or '').strip()
        normalized = ' '.join(description.casefold().split()).strip(' .!?')
        if normalized in generic:
            flags.append('generic_description')
        if normalized in seen:
            flags.append('duplicate_description')
        seen.add(normalized)
        evidence = aspect.get('evidence') or ''
        if not evidence or (evidence not in text and evidence not in title):
            flags.append('unsupported_aspect_evidence')
        if aspect.get('category') == 'feature_request' and aspect.get('signal_type') == 'praise':
            flags.append('praise_as_feature_request')
    for signal in signals:
        evidence = signal.get('evidence') or ''
        if not evidence or (evidence not in text and evidence not in title):
            flags.append('unsupported_behavior_evidence')
    return sorted(set(flags))


def stratified_sample(reviews, limit, seed):
    rng = random.Random(seed)
    buckets = defaultdict(list)
    for review in reviews:
        roles = (review.get('sample_roles') or '').split(',')
        role = 'random' if 'random' in roles else ('boundary' if 'boundary' in roles else 'representative')
        buckets[(review['cluster_id'], star_band(review.get('stars')), role)].append(review)
    for bucket in buckets.values():
        rng.shuffle(bucket)
    keys = list(buckets)
    rng.shuffle(keys)
    chosen = []
    while keys and len(chosen) < limit:
        next_keys = []
        for key in keys:
            chosen.append(buckets[key].pop())
            if buckets[key]:
                next_keys.append(key)
            if len(chosen) == limit:
                break
        keys = next_keys
    return chosen


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True, help='New extraction result folder')
    parser.add_argument('--old', type=Path, help='Optional prior result folder for comparison')
    parser.add_argument('--output', type=Path, default=Path('evaluation/aspect_review_v2.csv'))
    parser.add_argument('--sample-size', type=int, default=50)
    parser.add_argument('--seed', type=int, default=42)
    args = parser.parse_args()
    if args.sample_size < 1:
        parser.error('--sample-size must be positive')
    reviews = read_table(args.input / 'review_extractions.parquet')
    aspects = read_table(args.input / 'review_aspects.parquet')
    signals_path = args.input / 'review_behavioral_signals.parquet'
    signals = read_table(signals_path) if signals_path.is_file() else []
    validation_path = args.input / 'review_validation_issues.parquet'
    validation_issues = read_table(validation_path) if validation_path.is_file() else []
    aspect_map = defaultdict(list)
    signal_map = defaultdict(list)
    for aspect in aspects:
        aspect_map[aspect['review_key']].append(aspect)
    for signal in signals:
        signal_map[signal['review_key']].append(signal)
    validation_map = defaultdict(list)
    for issue in validation_issues:
        validation_map[issue['review_key']].append(issue)
    old_map = defaultdict(list)
    if args.old:
        for aspect in read_table(args.old / 'review_aspects.parquet'):
            old_map[aspect['review_key']].append(aspect)

    review_flags = {review['review_key']: sorted(set(flag_review(
        review, aspect_map[review['review_key']], signal_map[review['review_key']]) +
        [(issue.get('status') or 'rejected') + '_' + issue['issue_type']
         for issue in validation_map[review['review_key']]]))
                    for review in reviews}
    chosen = stratified_sample(reviews, min(args.sample_size, len(reviews)), args.seed)
    columns = ['review_key', 'cluster_id', 'stars', 'sample_roles',
               'random_inclusion_probability', 'review_text', 'review_title',
               'new_aspects_json', 'behavioral_signals_json', 'old_aspects_json',
               'validation_issues_json',
               'heuristic_flags', 'missed_aspects', 'unsupported_aspects',
               'category_correct', 'polarity_correct', 'behavior_correct', 'notes']
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('w', newline='', encoding='utf-8') as fp:
        writer = csv.DictWriter(fp, fieldnames=columns)
        writer.writeheader()
        for review in chosen:
            key = review['review_key']
            writer.writerow({
                'review_key': key, 'cluster_id': review['cluster_id'],
                'stars': review.get('stars'), 'sample_roles': review.get('sample_roles'),
                'random_inclusion_probability': review.get('random_inclusion_probability'),
                'review_text': review.get('text'), 'review_title': review.get('title'),
                'new_aspects_json': json.dumps([{field: a.get(field) for field in
                    ('description', 'category', 'polarity', 'signal_type', 'feature', 'evidence')}
                    for a in aspect_map[key]], ensure_ascii=False),
                'behavioral_signals_json': json.dumps([{field: s.get(field) for field in
                    ('type', 'target', 'evidence', 'related_aspect_index')}
                    for s in signal_map[key]], ensure_ascii=False),
                'old_aspects_json': json.dumps([{field: a.get(field) for field in
                    ('description', 'category', 'polarity', 'evidence')}
                    for a in old_map[key]], ensure_ascii=False) if args.old else '',
                'validation_issues_json': json.dumps(validation_map[key], ensure_ascii=False),
                'heuristic_flags': ','.join(review_flags[key]),
                'missed_aspects': '', 'unsupported_aspects': '',
                'category_correct': '', 'polarity_correct': '',
                'behavior_correct': '', 'notes': '',
            })
    categories = Counter(aspect.get('category') for aspect in aspects)
    roles = Counter(role for review in reviews for role in (review.get('sample_roles') or '').split(','))
    flags = Counter(flag for value in review_flags.values() for flag in value)
    summary = {
        'reviews_processed': len(reviews), 'aspects': len(aspects),
        'behavioral_signals': len(signals),
        'rejected_or_flagged_items': len(validation_issues),
        'validation_status_counts': dict(Counter(
            issue.get('status') or 'rejected' for issue in validation_issues)),
        'zero_aspect_reviews': sum(not aspect_map[r['review_key']] for r in reviews),
        'zero_aspect_rate': (sum(not aspect_map[r['review_key']] for r in reviews) / len(reviews)
                             if reviews else None),
        'category_counts': dict(categories), 'sample_role_counts': dict(roles),
        'heuristic_flag_counts': dict(flags),
        'matched_old_reviews': sum(r['review_key'] in old_map for r in reviews) if args.old else None,
        'checklist_rows': len(chosen),
        'note': 'Heuristic flags and category counts are not ground-truth accuracy metrics.',
    }
    summary_path = args.output.with_suffix('.summary.json')
    summary_path.write_text(json.dumps(summary, indent=2), encoding='utf-8')
    print(f'Wrote {len(chosen)} checklist rows to {args.output}')
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
