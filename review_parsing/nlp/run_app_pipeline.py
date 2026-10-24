#!/usr/bin/env python3
"""Run review embeddings through aspect clustering for one dataset app.

Example: python nlp/run_app_pipeline.py Spotify
The aspect extraction stage makes paid OpenAI API calls. Topic refinement is
separate and is not run here.
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from generate_app_embeddings import atomic_json, slugify


SCRIPTS = Path(__file__).resolve().parent
PROJECT = SCRIPTS.parent


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def require_api_key():
    from extract_review_aspects import KEY_PLACEHOLDERS, load_api_key_from_env_file

    load_api_key_from_env_file()
    key = os.getenv('OPENAI_API_KEY')
    if not key or key in KEY_PLACEHOLDERS:
        raise ValueError('OPENAI_API_KEY is missing. Set it in the environment or project .env file.')


def run_stage(label, script, options, runner):
    command = [sys.executable, str(SCRIPTS / script), *map(str, options)]
    print(f'\n== {label} ==', flush=True)
    runner(command, cwd=PROJECT, check=True)


def validate_review_clusters(path, app, embedding_root, embedding_manifest, clusters):
    config_path = path / 'run_config.json'
    if not config_path.is_file() or not (path / 'cluster_samples.parquet').is_file():
        raise ValueError(f'Incomplete review clustering output: {path}')
    config = read_json(config_path)
    expected = {
        'app': app, 'embedding_root': str(embedding_root),
        'source_manifest': embedding_manifest,
        'clusters': min(clusters, embedding_manifest['row_count']),
        'completed_rows': embedding_manifest['row_count'],
    }
    if any(config.get(key) != value for key, value in expected.items()):
        raise ValueError(f'Review clustering output does not match this run: {path}')


def validate_extraction(path):
    summary_path = path / 'summary.json'
    aspects_path = path / 'review_aspects.parquet'
    if not summary_path.is_file() or not aspects_path.is_file():
        raise ValueError(f'Incomplete aspect extraction output: {path}')
    summary = read_json(summary_path)
    if summary['processed_unique_reviews'] != summary['sampled_unique_reviews']:
        raise ValueError(f'Aspect extraction is incomplete: {summary["processed_unique_reviews"]}/'
                         f'{summary["sampled_unique_reviews"]} reviews. Rerun to resume.')
    if summary['aspect_rows'] < 4:
        raise ValueError('Fewer than four aspects were extracted; aspect clustering cannot run.')


def validate_aspect_clusters(path, embeddings):
    config_path = path / 'run_config.json'
    assignments = path / 'aspect_clusters.parquet'
    if not config_path.is_file() or not assignments.is_file():
        raise ValueError(f'Incomplete aspect clustering output: {path}')
    config = read_json(config_path)
    manifest = read_json(embeddings / 'manifest.json')
    if (config.get('input') != str(embeddings) or
            config.get('input_source_sha256') != manifest['config']['source_sha256'] or
            config.get('aspects') != manifest['aspect_count']):
        raise ValueError(f'Aspect clustering output does not match current embeddings: {path}')


def run(args, runner=subprocess.run):
    source = args.input.expanduser().resolve()
    if not source.is_file():
        raise ValueError(f'Input CSV not found: {source}. Pass --input /path/to/app-store-reviews.csv.')
    require_api_key()
    output = args.output.expanduser().resolve() if args.output else \
        (PROJECT / 'pipeline-runs' / slugify(args.app.casefold())).resolve()
    output.mkdir(parents=True, exist_ok=True)
    settings = {
        'app_requested': args.app.casefold(), 'input': str(source),
        'input_size': source.stat().st_size, 'input_mtime_ns': source.stat().st_mtime_ns,
        'clusters': args.clusters, 'review_model': args.review_model,
        'aspect_model': args.aspect_model, 'extraction_model': args.extraction_model,
    }
    config_path = output / 'pipeline_config.json'
    if config_path.exists():
        if read_json(config_path) != settings:
            raise ValueError(f'Pipeline settings or input changed. Use a new --output folder: {output}')
    else:
        if any(output.iterdir()):
            raise ValueError(f'Output folder has no pipeline config and is not empty: {output}')
        atomic_json(config_path, settings)

    review_embeddings = output / 'review-embeddings'
    review_clusters = output / 'review-clusters'
    extractions = output / 'aspects'
    aspect_embeddings = output / 'aspect-embeddings'
    aspect_clusters = output / 'aspect-clusters'

    run_stage('1/5 Review embeddings', 'generate_app_embeddings.py',
              ['--input', source, '--output', review_embeddings, '--app', args.app,
               '--model', args.review_model], runner)
    index = read_json(review_embeddings / 'app_index.json')
    matches = [(name, info) for name, info in index.items()
               if name.casefold() == args.app.casefold()]
    if len(matches) != 1:
        raise ValueError(f'App {args.app!r} not found uniquely among eligible English reviews')
    app, info = matches[0]
    slug = info['slug']
    embedding_manifest = read_json(review_embeddings / 'apps' / slug / 'manifest.json')
    cluster_path = review_clusters / slug
    if cluster_path.exists():
        validate_review_clusters(cluster_path, app, review_embeddings, embedding_manifest,
                                 args.clusters)
        print(f'\n== 2/5 Review clustering: reusing {cluster_path} ==', flush=True)
    else:
        run_stage('2/5 Review clustering', 'cluster_app_reviews.py',
                  ['--embedding-root', review_embeddings, '--output', review_clusters,
                   '--app', app, '--clusters', args.clusters], runner)
        validate_review_clusters(cluster_path, app, review_embeddings, embedding_manifest,
                                 args.clusters)

    run_stage('3/5 Aspect extraction (paid API)', 'extract_review_aspects.py',
              ['--cluster-root', review_clusters, '--output', extractions, '--app', app,
               '--model', args.extraction_model, '--batch-size', args.batch_size,
               '--concurrency', args.concurrency], runner)
    extraction_path = extractions / slug
    validate_extraction(extraction_path)

    run_stage('4/5 Aspect embeddings', 'embed_aspects.py',
              ['--input', extraction_path / 'review_aspects.parquet',
               '--output', aspect_embeddings, '--model', args.aspect_model], runner)
    if read_json(aspect_embeddings / 'manifest.json').get('status') != 'complete':
        raise ValueError(f'Aspect embeddings incomplete: {aspect_embeddings}')
    if aspect_clusters.exists():
        validate_aspect_clusters(aspect_clusters, aspect_embeddings)
        print(f'\n== 5/5 Aspect clustering: reusing {aspect_clusters} ==', flush=True)
    else:
        run_stage('5/5 Aspect clustering', 'cluster_aspects.py',
                  ['--input', aspect_embeddings, '--output', aspect_clusters], runner)
        validate_aspect_clusters(aspect_clusters, aspect_embeddings)
    print(f'\nComplete for {app}. Aspect clusters: {aspect_clusters / "cluster_summary.csv"}',
          flush=True)
    return aspect_clusters


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('app', help='App name in the dataset (case insensitive exact match)')
    parser.add_argument('--input', type=Path, default=Path.home() / 'Downloads' / 'app-store-reviews.csv')
    parser.add_argument('--output', type=Path, help='Run folder; defaults to pipeline-runs/<app-slug>')
    parser.add_argument('--clusters', type=int, default=50, help='Review clusters (default: 50)')
    parser.add_argument('--review-model', default='sentence-transformers/all-MiniLM-L6-v2')
    parser.add_argument('--aspect-model', default='sentence-transformers/all-MiniLM-L6-v2')
    parser.add_argument('--extraction-model', default='gpt-4o-mini')
    parser.add_argument('--batch-size', type=int, default=8, help='Reviews per API request')
    parser.add_argument('--concurrency', type=int, default=5, help='Concurrent API requests')
    args = parser.parse_args()
    if args.clusters < 1 or args.batch_size < 1 or args.concurrency < 1:
        parser.error('--clusters, --batch-size and --concurrency must be positive')
    try:
        run(args)
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f'Error: {exc}', file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
