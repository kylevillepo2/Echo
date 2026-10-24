#!/usr/bin/env python3
"""Create readable review/tag inspection CSVs for one completed app run.

Run from review_parsing/: .venv/bin/python nlp/run_similarity_inspection.py "Cash App"
Only joins existing inspection results to the app's topic catalog. No model calls.
"""
import argparse
import csv
import os
import sys
from pathlib import Path

from enrich_similarity_inspection import enrich_rows
from similarity_common import read_json

PROJECT = Path(__file__).resolve().parent.parent


def find_run(app, run_root=None, runs_root=None):
    roots = [run_root.expanduser().resolve()] if run_root else sorted(
        (runs_root or PROJECT / 'pipeline-runs').expanduser().resolve().glob('*'))
    matches = []
    for root in roots:
        index = root / 'review-embeddings/app_index.json'
        if index.is_file() and any(name.casefold() == app.casefold() for name in read_json(index)):
            matches.append(root)
    if not matches:
        raise ValueError(f'No completed run found for {app!r}. Pass --run-root /path/to/the/app-run.')
    if len(matches) != 1:
        raise ValueError('Multiple matching runs; choose one with --run-root:\n' +
                         '\n'.join(str(p) for p in matches))
    return matches[0]


def read_csv(path):
    with path.open(newline='', encoding='utf-8-sig') as f:
        return list(csv.DictReader(f))


def merge_file(source, target, catalog):
    source_rows = read_csv(source)
    merged = enrich_rows(source_rows, catalog)
    if not merged:
        raise ValueError(f'No inspection rows: {source}')
    keys = [r['review_key'] for r in merged]
    if len(set(keys)) != len(keys):
        raise ValueError(f'Duplicate review keys: {source}')
    # Retain work entered in a previous readable export across repeated commands.
    if target.exists() and target != source:
        previous = read_csv(target)
        if len({r['review_key'] for r in previous}) != len(previous):
            raise ValueError(f'Duplicate review keys in previous export: {target}')
        previous_by_key = {r['review_key']: r for r in previous}
        for row in merged:
            old = previous_by_key.get(row['review_key'])
            if old:
                if old['review_text'] != row['review_text']:
                    raise ValueError(f'Review text changed for {row["review_key"]}; use a new output folder')
                for name in ['human_verdict', 'human_notes']:
                    if old.get(name): row[name] = old[name]
        disappeared = [r['review_key'] for r in previous if r['review_key'] not in keys
                       and (r.get('human_verdict') or r.get('human_notes'))]
        if disappeared:
            raise ValueError('Previous export contains annotated reviews absent from current input. '
                             'Use a new --output-dir to preserve those annotations.')
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(target.name + '.tmp')
    with temp.open('w', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=list(merged[0]))
        writer.writeheader()
        writer.writerows(merged)
    checked = read_csv(temp)
    if len(checked) != len(source_rows):
        raise ValueError('Merged row count does not match source')
    for original, row in zip(source_rows, checked):
        for key, value in original.items():
            if key not in {'human_verdict', 'human_notes'} and row[key] != value:
                raise ValueError(f'Original field changed: {key}')
    os.replace(temp, target)
    print(f'{len(merged)} reviews: {target}', flush=True)
    return target


def run(args):
    root = find_run(args.app, args.run_root, args.runs_root)
    catalog_path = root / 'refined-topics/topic_catalog.csv'
    if not catalog_path.is_file():
        raise ValueError(f'Topic catalog missing: {catalog_path}. Complete topic refinement first.')
    topics = read_csv(catalog_path)
    catalog = {t['topic_id']: t for t in topics}
    if not topics or len(catalog) != len(topics):
        raise ValueError('Topic catalog is empty or contains duplicate IDs')
    evaluation = args.evaluation_dir.expanduser().resolve() if args.evaluation_dir else root / 'similarity-evaluation'
    candidates = sorted(evaluation.glob('*/*_inspection.csv'))
    candidates += sorted(evaluation.glob('*_inspection.csv'))
    sources = [p for p in candidates if
               (args.strategy == 'all' or p.name == f'{args.strategy}_inspection.csv') and
               (args.method == 'all' or p.parent.name.startswith(args.method))]
    if not sources:
        raise ValueError(f'No {args.method}/{args.strategy} similarity inspection files found in {evaluation}. '
                         'This command merges existing results; run evaluate_similarity_tagging.py for this app first. '
                         'For a different evaluation folder, pass --evaluation-dir /path/to/evaluation.')
    outputs = []
    for source in sources:
        folder = args.output_dir.expanduser().resolve() / source.parent.name if args.output_dir else source.parent
        target = folder / (source.stem + '_readable.csv')
        if args.dry_run:
            print(f'Would merge {source}\n  with {catalog_path}\n  into {target}')
        else:
            outputs.append(merge_file(source, target, catalog))
    return outputs


def parser():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('app', help='Exact app name, case insensitive; quote names containing spaces')
    p.add_argument('--run-root', type=Path, help='Completed app pipeline folder; auto-detected when unique')
    p.add_argument('--runs-root', type=Path, help='Folder containing app runs; defaults to review_parsing/pipeline-runs')
    p.add_argument('--evaluation-dir', type=Path, help='Override similarity-evaluation folder')
    p.add_argument('--method', choices=['description', 'prototype', 'all'], default='description')
    p.add_argument('--strategy', choices=['global', 'per_topic', 'all'], default='global')
    p.add_argument('--output-dir', type=Path, help='Optional parent for readable outputs; defaults beside each inspection CSV')
    p.add_argument('--dry-run', action='store_true', help='List file operations without writing')
    return p


def main():
    p = parser()
    args = p.parse_args()
    try:
        run(args)
    except (OSError, ValueError, KeyError) as exc:
        p.exit(1, f'Error: {exc}\n')


if __name__ == '__main__':
    main()
