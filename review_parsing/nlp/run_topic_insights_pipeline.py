#!/usr/bin/env python3
"""Run one app from source CSV through frontend topic insights JSON.

Order: app pipeline -> topic refinement -> similarity tagging -> aggregation.
The extraction and refinement stages make paid OpenAI API calls. Rerunning the
same command reuses or resumes their completed work when inputs are unchanged.
"""
import argparse
import hashlib
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

from aggregate_topics import slugify as insight_slugify
from generate_app_embeddings import slugify

SCRIPTS = Path(__file__).resolve().parent
PROJECT = SCRIPTS.parent
FRONTEND = PROJECT.parent
PLACEHOLDERS = {'your-api-key', 'your-key-here', 'YOUR_API_KEY'}


def file_sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def ensure_api_key():
    current = os.environ.get('OPENAI_API_KEY')
    if current and current not in PLACEHOLDERS:
        return
    for path in (PROJECT / '.env', Path.cwd() / '.env'):
        if not path.is_file():
            continue
        for line in path.read_text(encoding='utf-8').splitlines():
            key, separator, value = line.strip().partition('=')
            if separator and key.strip() == 'OPENAI_API_KEY':
                value = value.strip().strip('"\'')
                if value and value not in PLACEHOLDERS:
                    os.environ['OPENAI_API_KEY'] = value
                    return
    raise ValueError('Set OPENAI_API_KEY in the environment or a project/workspace .env file')


def command(script, *options):
    return [sys.executable, str(SCRIPTS / script), *map(str, options)]


def plan(args):
    source = args.input.expanduser().resolve()
    runs_base = Path.cwd() / 'pipeline-runs'
    if not runs_base.is_dir():
        runs_base = PROJECT / 'pipeline-runs'
    run_root = (args.run_root.expanduser().resolve() if args.run_root else
                (runs_base / slugify(args.app.casefold())).resolve())
    refinement = run_root / 'refined-topics'
    insights = args.insights_dir.expanduser().resolve()
    pipeline = command('run_app_pipeline.py', args.app, '--input', source,
                       '--output', run_root, '--clusters', args.clusters,
                       '--review-model', args.review_model,
                       '--aspect-model', args.aspect_model,
                       '--extraction-model', args.extraction_model,
                       '--batch-size', args.batch_size, '--concurrency', args.concurrency)
    refine = command('refine_aspect_clusters.py', '--strategy', 'global',
                     '--input', run_root / 'aspect-clusters', '--output', refinement,
                     '--model', args.refinement_model, '--concurrency', args.concurrency,
                     '--resume')
    if args.refinement_max_cost_usd is not None:
        refine += ['--max-cost-usd', str(args.refinement_max_cost_usd)]
    similarity = command('run_similarity_workflow.py', args.app, '--run-root', run_root)
    aggregate = command('aggregate_topics.py', '--app', args.app,
                        '--runs-root', run_root.parent, '--output-dir', insights,
                        '--refinement-root', refinement)
    return source, run_root, refinement, insights, [
        ('1/4 App pipeline (paid extraction)', pipeline),
        ('2/4 Topic refinement (paid API)', refine),
        ('3/4 Similarity tagging (local)', similarity),
        ('4/4 JSON aggregation (local)', aggregate)]


def refinement_is_complete(root, refinement, model):
    required = ['canonical_topics.json', 'refined_aspects.parquet', 'refinement_report.json']
    if not all((refinement / name).is_file() for name in required):
        return False
    config = refinement / 'run_config.json'
    clusters = root / 'aspect-clusters/aspect_clusters.parquet'
    if not config.is_file() or not clusters.is_file():
        return False
    saved = read_json(config)
    if saved.get('source_assignment_sha256') != file_sha256(clusters):
        raise ValueError('Completed refinement belongs to different aspect clusters; use a new run folder')
    if saved.get('model') != model or saved.get('strategy') != 'global':
        raise ValueError('Completed refinement uses a different model or strategy; use a new run folder')
    return True


def run(args, runner=subprocess.run):
    source, root, refinement, insights, stages = plan(args)
    if not source.is_file():
        raise ValueError(f'Input CSV not found: {source}')
    if args.dry_run:
        print(f'App: {args.app}\nRun folder: {root}\nInsights folder: {insights}')
        for label, cmd in stages:
            print(f'{label}:\n  {shlex.join(cmd)}')
        return
    ensure_api_key()
    for number, (label, cmd) in enumerate(stages, 1):
        if number == 2 and refinement_is_complete(root, refinement, args.refinement_model):
            print(f'\n== {label}: reusing {refinement} ==', flush=True)
        else:
            print(f'\n== {label} ==', flush=True)
            runner(cmd, cwd=PROJECT, check=True)
        if number == 1 and not (root / 'aspect-clusters/aspect_clusters.parquet').is_file():
            raise ValueError('App pipeline did not produce aspect clusters')
        if number == 2 and not all((refinement / name).is_file() for name in
                                   ('canonical_topics.json', 'refined_aspects.parquet')):
            raise ValueError('Topic refinement did not finish')
        if number == 3 and not (root / 'similarity-workflow-v1/description/tagging-global/tagged_reviews.parquet').is_file():
            raise ValueError('Similarity workflow did not produce tagged reviews')
    output = insights / f'{insight_slugify(args.app)}.json'
    if not output.is_file():
        raise ValueError(f'Aggregation did not produce {output}')
    exported = read_json(output)
    if (exported.get('app', {}).get('name', '').casefold() != args.app.casefold()
            or exported.get('app', {}).get('pipeline_run_slug') != root.name):
        raise ValueError(f'Aggregation output does not match this app run: {output}')
    print(f'\nComplete: {output}', flush=True)


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('app', help='Exact app name in the source CSV, case insensitive')
    p.add_argument('--input', type=Path, default=Path.home() / 'Downloads/app-store-reviews.csv')
    p.add_argument('--run-root', type=Path, help='Defaults to ./pipeline-runs/<app-slug> if present, else review_parsing/pipeline-runs/<app-slug>')
    p.add_argument('--insights-dir', type=Path, default=FRONTEND / 'static/data/insights')
    p.add_argument('--clusters', type=int, default=50)
    p.add_argument('--review-model', default='sentence-transformers/all-MiniLM-L6-v2')
    p.add_argument('--aspect-model', default='sentence-transformers/all-MiniLM-L6-v2')
    p.add_argument('--extraction-model', default='gpt-4o-mini')
    p.add_argument('--refinement-model', default='gpt-6.1-sol')
    p.add_argument('--refinement-max-cost-usd', type=float)
    p.add_argument('--batch-size', type=int, default=8)
    p.add_argument('--concurrency', type=int, default=5)
    p.add_argument('--dry-run', action='store_true', help='Print stages without writing or making API calls')
    return p


def main():
    p = parser()
    args = p.parse_args()
    if min(args.clusters, args.batch_size, args.concurrency) < 1:
        p.error('Cluster count, batch size, and concurrency must be positive')
    if args.refinement_max_cost_usd is not None and args.refinement_max_cost_usd <= 0:
        p.error('--refinement-max-cost-usd must be positive')
    try:
        run(args)
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as exc:
        p.exit(1, f'Error: {exc}\n')


if __name__ == '__main__':
    main()
