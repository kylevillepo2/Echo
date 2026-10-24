#!/usr/bin/env python3
"""Build, evaluate, tag, and export readable review/topic inspections without APIs.

Example: .venv/bin/python nlp/run_similarity_workflow.py "Venmo"
Requires a completed app run through topic refinement and a cached local encoder.
"""
import argparse
import os
import subprocess
import sys
from pathlib import Path

from run_similarity_inspection import find_run, merge_file
from similarity_common import atomic_json, digest, fingerprint, read_json, review_inputs

SCRIPTS = Path(__file__).resolve().parent


def execute_stage(label, script, options, artifacts, state, state_path, runner):
    saved = state['completed'].get(label)
    if saved is not None:
        if any(not p.is_file() or saved.get(p.name) != digest(p) for p in artifacts):
            raise ValueError(f'Completed {label} artifacts changed; use a new --output folder')
        print(f'{label}: reusing verified output', flush=True)
        return
    # Build/evaluation stages require empty output folders; tagger itself resumes shards.
    print(f'\n{label}', flush=True)
    env = {**os.environ, 'HF_HUB_OFFLINE': '1', 'TRANSFORMERS_OFFLINE': '1',
           'PYTHONDONTWRITEBYTECODE': '1'}
    runner([sys.executable, str(SCRIPTS / script), *map(str, options)], check=True, env=env)
    if any(not p.is_file() for p in artifacts):
        raise ValueError(f'{label} did not produce its expected artifacts')
    state['completed'][label] = {p.name: digest(p) for p in artifacts}
    atomic_json(state_path, state)


def run(args, runner=subprocess.run):
    root = find_run(args.app, args.run_root)
    app, manifest, dimension, files = review_inputs(root / 'review-embeddings', args.app)
    required = [root / 'refined-topics/canonical_topics.json',
                root / 'refined-topics/refined_aspects.parquet']
    extractions = sorted((root / 'aspects').glob('*/review_extractions.parquet'))
    if len(extractions) != 1 or any(not p.is_file() for p in required):
        raise ValueError('Finish aspect extraction and canonical topic refinement for this app first')
    methods = ['description', 'prototype'] if args.method == 'both' else [args.method]
    if 'prototype' in methods:
        required.append(root / 'aspect-embeddings/manifest.json')
        required += sorted((root / 'aspect-embeddings').glob('part-*.npy'))
        required += sorted((root / 'aspect-embeddings').glob('part-*.parquet'))
    config = {'version': 1, 'app': app, 'run_root': str(root), 'methods': methods,
              'strategy': args.strategy, 'seed': args.seed, 'max_tags': args.max_tags,
              'min_support': args.min_support, 'threshold_grid': args.threshold_grid,
              'inspection_count': args.inspection_count, 'batch_size': args.batch_size,
              'device': args.device, 'review_model': manifest['model'], 'dimension': dimension,
              'input_shards': files,
              'sources': {str(p): digest(p) for p in required + extractions},
              'implementation': {name: digest(SCRIPTS / name) for name in [
                  'run_similarity_workflow.py', 'build_topic_embeddings.py',
                  'evaluate_similarity_tagging.py', 'tag_reviews_similarity.py',
                  'similarity_common.py', 'enrich_similarity_inspection.py',
                  'run_similarity_inspection.py']}}
    out = args.output.expanduser().resolve() if args.output else root / 'similarity-workflow-v1'
    if out == root or out in root.parents:
        raise ValueError('Workflow output must be a separate subfolder, not a source ancestor')
    if args.dry_run:
        print(f'App: {app}; reviews: {manifest["row_count"]:,}; methods: {", ".join(methods)}')
        print(f'Output: {out}\nSteps: topic embeddings -> validation/test evaluation -> full tagging -> readable inspection')
        return []
    state_path = out / 'workflow_checkpoint.json'
    if state_path.exists():
        state = read_json(state_path)
        if state['identity'] != fingerprint(config):
            raise ValueError('Workflow settings, source data, or code changed. Use a new --output folder.')
    else:
        if out.exists() and any(out.iterdir()):
            raise ValueError('Output is nonempty without a workflow checkpoint; use a new --output folder')
        state = {'identity': fingerprint(config), 'config': config, 'completed': {}}
        atomic_json(state_path, state)
    results = []
    for method in methods:
        topic = out / method / 'topic-embeddings'
        evaluation = out / method / 'evaluation'
        tagging = out / method / f'tagging-{args.strategy}'
        execute_stage(f'{method}: 1/4 topic embeddings', 'build_topic_embeddings.py',
                      ['--run-root', root, '--app', app, '--method', method, '--output', topic,
                       '--seed', args.seed, '--device', args.device],
                      [topic / p for p in ['config.json', 'topic_vectors.npy', 'topic_metadata.parquet']],
                      state, state_path, runner)
        execute_stage(f'{method}: 2/4 evaluation', 'evaluate_similarity_tagging.py',
                      ['--run-root', root, '--app', app, '--topic-embeddings', topic, '--output', evaluation,
                       '--max-tags', args.max_tags, '--min-support', args.min_support,
                       '--threshold-grid', args.threshold_grid, '--inspection-count', args.inspection_count],
                      [evaluation / p for p in ['evaluation_report.json', 'global_thresholds.json',
                                               'per_topic_thresholds.json', 'evaluation_partitions.parquet']],
                      state, state_path, runner)
        execute_stage(f'{method}: 3/4 full review tagging', 'tag_reviews_similarity.py',
                      ['--run-root', root, '--app', app, '--topic-embeddings', topic,
                       '--threshold-config', evaluation / f'{args.strategy}_thresholds.json',
                       '--output', tagging, '--batch-size', args.batch_size],
                      [tagging / p for p in ['tagged_reviews.parquet', 'tagging_report.json']],
                      state, state_path, runner)
        print(f'\n{method}: 4/4 readable inspection', flush=True)
        # Taxonomy JSON is authoritative and contains the names and definitions.
        # This does not require an additional topic_catalog.csv to be generated.
        taxonomy = read_json(root / 'refined-topics/canonical_topics.json')
        catalog = {t['topic_id']: t for t in taxonomy['topics']}
        source = evaluation / f'{args.strategy}_inspection.csv'
        if not source.is_file():
            raise ValueError(f'Inspection input missing: {source}. Use a new output folder to regenerate evaluation.')
        readable = evaluation / f'{args.strategy}_inspection_readable.csv'
        merge_file(source, readable, catalog)
        results.append(str(readable))
    atomic_json(out / 'workflow_report.json', {'app': app, 'review_count': manifest['row_count'],
                'readable_inspection_files': results, 'checkpoint_identity': state['identity'],
                'note': 'Provisional machine-reference evaluation; semantic assignments are not verified complaints.'})
    print('\nFinished. Open the readable inspection file(s) listed above.', flush=True)
    return results


def parser():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('app', help='App name, e.g. "Venmo" or "Cash App"')
    p.add_argument('--run-root', type=Path, help='Completed app run; auto-detect when unique')
    p.add_argument('--output', type=Path, help='Defaults to <run-root>/similarity-workflow-v1')
    p.add_argument('--method', choices=['description', 'prototype', 'both'], default='description')
    p.add_argument('--strategy', choices=['global', 'per_topic'], default='global')
    p.add_argument('--seed', type=int, default=42)
    p.add_argument('--max-tags', type=int, default=5)
    p.add_argument('--min-support', type=int, default=5)
    p.add_argument('--threshold-grid', default='0.2,0.25,0.3,0.35,0.4,0.45,0.5,0.55,0.6,0.65,0.7,0.75,0.8')
    p.add_argument('--inspection-count', type=int, default=120)
    p.add_argument('--batch-size', type=int, default=1024)
    p.add_argument('--device', default='cpu')
    p.add_argument('--dry-run', action='store_true')
    return p


def main():
    p = parser()
    args = p.parse_args()
    if min(args.max_tags, args.min_support, args.inspection_count, args.batch_size) < 1:
        p.error('Tag cap, support, inspection count, and batch size must be positive')
    try:
        run(args)
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as exc:
        p.exit(1, f'Error: {exc}\n')


if __name__ == '__main__':
    main()
