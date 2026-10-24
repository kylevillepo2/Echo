#!/usr/bin/env python3
"""Refine HDBSCAN aspect clusters into review-traceable product topics.

Dry runs are local. Paid calls are checkpointed by stage in output/checkpoint.jsonl;
rerunning with --resume reuses completed calls. No source aspect is discarded.
"""

import argparse
import asyncio
import csv
import hashlib
import json
import os
import random
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Literal

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
from pydantic import BaseModel, ConfigDict, Field

from cluster_aspects import load_shards


PROMPT_VERSION = 'aspect_refinement_v1'
DEFAULT_OBJECTIVE = 'Identify specific product experiences and actionable product issues, including specific praise and feature requests.'
PAIR_RULES = ("Compare the underlying product issue, not shared words. Distinguish different failure modes, "
              "shuffle defects, queue actions, pricing from feature behavior, positive from negative experience, "
              "and customer intent from product problems. Do not infer unsupported defects. Use ambiguous when "
              "evidence is insufficient. Give a short evidence-based reason.")
RELEVANCE_RULES = ("Keep specific product feedback, positive features, feature requests and rare issues. "
                   "Flag generic sentiment or unclear/non-product content; never fabricate a defect. "
                   "Names and definitions must describe the observed aspects, not inferred causes.")


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid')


class PairDecision(StrictModel):
    cluster_a: int
    cluster_b: int
    relationship: Literal['equivalent', 'related', 'distinct', 'ambiguous']
    confidence: Literal['high', 'medium', 'low']
    reason: str
    proposed_label: str


class PairBatch(StrictModel):
    decisions: list[PairDecision]


class ValidatedGroup(StrictModel):
    cluster_ids: list[int]
    reason: str


class GroupValidation(StrictModel):
    groups: list[ValidatedGroup]


class ParentCategory(StrictModel):
    parent_category_id: str
    parent_category_name: str
    definition: str


class ParentPlan(StrictModel):
    categories: list[ParentCategory]


class TopicDecision(StrictModel):
    topic_id: str
    canonical_name: str
    definition: str
    parent_category_id: str
    relevance_status: Literal['keep', 'exclude', 'needs_review']
    exclusion_reason: Literal['none', 'generic_sentiment', 'unintelligible',
                              'non_product_content', 'duplicate_artifact',
                              'insufficient_information']


class TopicBatch(StrictModel):
    topics: list[TopicDecision]


class NoiseDecision(StrictModel):
    aspect_id: str
    topic_id: str  # Empty string means unassigned.
    relationship: Literal['equivalent', 'related', 'distinct', 'ambiguous']
    confidence: Literal['high', 'medium', 'low']
    reason: str


class NoiseBatch(StrictModel):
    decisions: list[NoiseDecision]


def atomic_json(path, value):
    temp = path.with_name(path.name + '.tmp')
    try:
        with temp.open('w', encoding='utf-8') as fp:
            json.dump(value, fp, ensure_ascii=False, indent=2)
            fp.flush()
            os.fsync(fp.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def file_sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as fp:
        for chunk in iter(lambda: fp.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def normalized_description(text):
    return ' '.join(re.findall(r'[a-z0-9]+', (text or '').casefold()))


def distributions(rows, key):
    counts = Counter(str(row.get(key) or 'unknown') for row in rows)
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def prepare_inputs(source, embedding_root=None):
    assignment_path = source / 'aspect_clusters.parquet'
    reps_path = source / 'representative_aspects.parquet'
    run_path = source / 'run_config.json'
    if not all(path.is_file() for path in (assignment_path, reps_path, run_path)):
        raise ValueError('Missing Step 7 assignments, representatives, or run_config.json')
    assignments = pq.read_table(assignment_path)
    needed = {'aspect_id', 'review_key', 'aspect_cluster_id', 'description',
              'sample_roles', 'random_inclusion_probability'}
    if missing := needed - set(assignments.column_names):
        raise ValueError(f'Missing assignment fields: {sorted(missing)}')
    records = assignments.to_pylist()
    ids = [row['aspect_id'] for row in records]
    if len(set(ids)) != len(ids) or any(not key for key in ids):
        raise ValueError('Duplicate or empty aspect IDs in assignments')
    run = json.loads(run_path.read_text(encoding='utf-8'))
    embedding_path = Path(embedding_root or run['input']).expanduser().resolve()
    X, embedded_meta, manifest = load_shards(embedding_path)
    if ids != embedded_meta.column('aspect_id').to_pylist():
        raise ValueError('Step 7 assignments do not align with source aspect embeddings')
    if run.get('aspects') != len(records):
        raise ValueError('Step 7 aspect count differs from assignments')
    reps = pq.read_table(reps_path).to_pylist()
    return assignments, records, X, reps, run, manifest, embedding_path


def build_profiles(records, X, representatives, seed=42):
    groups = defaultdict(list)
    for position, row in enumerate(records):
        if int(row['aspect_cluster_id']) >= 0:
            groups[int(row['aspect_cluster_id'])].append(position)
    rep_by_cluster = defaultdict(lambda: defaultdict(list))
    for row in representatives:
        if row.get('sample_role') in {'centroid', 'random'}:
            rep_by_cluster[int(row['aspect_cluster_id'])][row['sample_role']].append(row['description'])
    profiles, centroids = {}, {}
    rng = random.Random(seed)
    for cid, positions in sorted(groups.items()):
        members = [records[i] for i in positions]
        centroid = X[positions].mean(axis=0)
        norm = np.linalg.norm(centroid)
        if norm <= 0 or not np.isfinite(norm):
            raise ValueError(f'Invalid centroid for cluster {cid}')
        centroid = (centroid / norm).astype(np.float32)
        centroids[cid] = centroid
        similarities = X[positions] @ centroid
        local_order = np.argsort(-similarities, kind='stable')[:10]
        examples = list(dict.fromkeys(rep_by_cluster[cid]['centroid'] +
                                      [members[i]['description'] for i in local_order]))[:10]
        random_examples = list(dict.fromkeys(rep_by_cluster[cid]['random']))[:5]
        if len(random_examples) < 3:
            random_examples = [members[i]['description'] for i in rng.sample(range(len(members)),
                               min(5, len(members)))]
        categories = distributions(members, 'category')
        polarities = distributions(members, 'polarity')
        features = distributions([row for row in members if row.get('feature')], 'feature')
        apps = distributions(members, 'app_name')
        dominant_category = max(categories.values()) / len(members)
        dominant_polarity = max(polarities.values()) / len(members)
        profiles[cid] = {
            'cluster_id': cid, 'aspect_count': len(members),
            'unique_reviews': len({row['review_key'] for row in members}),
            'category_distribution': categories, 'polarity_distribution': polarities,
            'top_category': next(iter(categories)), 'top_polarity': next(iter(polarities)),
            'top_features': list(features.items())[:5], 'app_distribution': apps,
            'examples': examples, 'random_examples': random_examples,
            'embedding_centroid': centroid.tolist(),
            'potentially_heterogeneous': dominant_category < 0.55 or dominant_polarity < 0.55,
        }
    return profiles, centroids


def candidate_pairs(profiles, centroids, threshold=0.72, neighbors=7):
    ids = sorted(profiles)
    matrix = np.stack([centroids[cid] for cid in ids])
    similarity = matrix @ matrix.T
    reasons = defaultdict(set)
    for i, cid in enumerate(ids):
        order = np.argsort(-similarity[i])
        for j in [item for item in order if item != i][:neighbors]:
            if similarity[i, j] >= threshold:
                reasons[tuple(sorted((cid, ids[j])))].add('nearest_centroid')
    descriptions = defaultdict(set)
    features = defaultdict(set)
    for cid in ids:
        for description in profiles[cid]['examples'] + profiles[cid]['random_examples']:
            normalized = normalized_description(description)
            if len(normalized) >= 12:
                descriptions[normalized].add(cid)
        for feature, count in profiles[cid]['top_features'][:2]:
            normalized = normalized_description(feature)
            if len(normalized) >= 5 and count >= 2:
                features[normalized].add(cid)
    for index in (descriptions, features):
        for matches in index.values():
            for a in matches:
                for b in matches:
                    if a < b:
                        reasons[a, b].add('matching_description' if index is descriptions else 'shared_feature')
    # All-pairs scan catches pairs outside another cluster's nearest neighbors.
    for i, a in enumerate(ids):
        for j in range(i + 1, len(ids)):
            if similarity[i, j] >= min(0.98, threshold + 0.12):
                reasons[a, ids[j]].add('all_pairs_high_similarity')
    positions = {cid: i for i, cid in enumerate(ids)}
    return [{'cluster_a': a, 'cluster_b': b,
             'cosine_similarity': float(similarity[positions[a], positions[b]]),
             'candidate_reason': ','.join(sorted(why))}
            for (a, b), why in sorted(reasons.items())]


def choose_clusters(profiles, pairs, limit):
    if limit is None or limit >= len(profiles):
        return sorted(profiles)
    chosen = set()
    for pair in sorted(pairs, key=lambda item: -item['cosine_similarity']):
        if len(chosen | {pair['cluster_a'], pair['cluster_b']}) <= limit:
            chosen.update((pair['cluster_a'], pair['cluster_b']))
        if len(chosen) == limit:
            break
    for cid in sorted(profiles, key=lambda item: (-profiles[item]['aspect_count'], item)):
        if len(chosen) >= limit:
            break
        chosen.add(cid)
    return sorted(chosen)


def pair_payload(pair, profiles):
    def compact(cid):
        p = profiles[cid]
        return {key: p[key] for key in ('cluster_id', 'aspect_count', 'unique_reviews',
                'category_distribution', 'polarity_distribution', 'top_features',
                'examples', 'random_examples', 'potentially_heterogeneous')}
    return {'cluster_a': pair['cluster_a'], 'cluster_b': pair['cluster_b'],
            'cosine_similarity': round(pair['cosine_similarity'], 4),
            'profile_a': compact(pair['cluster_a']), 'profile_b': compact(pair['cluster_b'])}


def topic_id(group):
    return f'topic-{min(group):04d}'


def tentative_groups(cluster_ids, decisions):
    parent = {cid: cid for cid in cluster_ids}

    def root(cid):
        while cid != parent[cid]:
            parent[cid] = parent[parent[cid]]
            cid = parent[cid]
        return cid

    for decision in decisions:
        if decision['relationship'] == 'equivalent' and decision['confidence'] == 'high':
            a, b = decision['cluster_a'], decision['cluster_b']
            parent[root(b)] = root(a)
    groups = defaultdict(list)
    for cid in cluster_ids:
        groups[root(cid)].append(cid)
    return sorted((sorted(group) for group in groups.values()), key=lambda group: group[0])


def resolve_groups(cluster_ids, decisions, validations):
    groups = tentative_groups(cluster_ids, decisions)
    decision_map = {(min(d['cluster_a'], d['cluster_b']), max(d['cluster_a'], d['cluster_b'])): d
                    for d in decisions}
    result = []
    for group in groups:
        if len(group) <= 2:
            pair = decision_map.get((group[0], group[1])) if len(group) == 2 else None
            result.append({'cluster_ids': group, 'status': 'pair_validated' if len(group) == 2 else 'singleton',
                           'reason': pair['reason'] if pair else 'No accepted merge',
                           'pair_evidence': [pair] if pair else []})
            continue
        key = ','.join(map(str, group))
        validation = validations[key]
        parts = [sorted(item['cluster_ids']) for item in validation['groups']]
        if sorted(cid for part in parts for cid in part) != group or any(not part for part in parts):
            raise ValueError(f'Group validation did not partition cluster {key}')
        for part, item in zip(parts, validation['groups']):
            for i, a in enumerate(part):
                for b in part[i + 1:]:
                    decision = decision_map.get((a, b))
                    if decision and decision['relationship'] in {'distinct', 'ambiguous', 'related'}:
                        raise ValueError(f'Group validation conflicts with pair decision {a}, {b}')
            evidence = [decision for decision in decisions
                        if decision['cluster_a'] in part and decision['cluster_b'] in part]
            result.append({'cluster_ids': part, 'status': 'group_validated',
                           'reason': item['reason'], 'pair_evidence': evidence})
    if sorted(cid for group in result for cid in group['cluster_ids']) != sorted(cluster_ids):
        raise ValueError('Validated groups lost or duplicated a source cluster')
    return sorted(result, key=lambda group: group['cluster_ids'][0])


def load_checkpoint(path):
    saved, usage = {}, {'requests': 0, 'input_tokens': 0, 'output_tokens': 0}
    if not path.exists():
        return saved, usage
    with path.open('rb+') as fp:
        while line := fp.readline():
            if not line.endswith(b'\n'):
                fp.truncate(fp.tell() - len(line))
                break
            item = json.loads(line)
            key = (item['stage'], item['job_key'])
            if key in saved:
                raise ValueError(f'Duplicate checkpoint entry: {key}')
            saved[key] = item['result']
            usage['requests'] += item['requests']
            usage['input_tokens'] += item['input_tokens']
            usage['output_tokens'] += item['output_tokens']
    return saved, usage


def retryable(exc):
    body = getattr(exc, 'body', None)
    error = body.get('error', body) if isinstance(body, dict) else None
    code = error.get('code') if isinstance(error, dict) else None
    if code in {'insufficient_quota', 'invalid_api_key', 'billing_hard_limit_reached'}:
        return False
    status = getattr(exc, 'status_code', None)
    return isinstance(exc, ValueError) or status in {408, 409, 429, 500, 502, 503, 504} or type(exc).__name__ in {
        'APIConnectionError', 'APITimeoutError', 'TimeoutException'}


def retry_after(exc):
    headers = getattr(getattr(exc, 'response', None), 'headers', {}) or {}
    value = headers.get('retry-after') or headers.get('Retry-After')
    try:
        return max(0.0, float(value or 0))
    except (TypeError, ValueError):
        try:
            return max(0.0, (parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds())
        except (TypeError, ValueError):
            return 0.0


class PaidRunner:
    def __init__(self, client, args, checkpoint, saved, usage):
        self.client, self.args, self.checkpoint = client, args, checkpoint
        self.saved, self.usage = saved, usage
        self.lock = asyncio.Lock()
        self.sem = asyncio.Semaphore(args.concurrency)
        self.in_flight_estimate = 0.0

    def estimated_cost(self):
        return (self.usage['input_tokens'] * self.args.input_cost_per_million +
                self.usage['output_tokens'] * self.args.output_cost_per_million) / 1_000_000

    async def call(self, stage, key, payload, prompt, schema, validate):
        if (stage, key) in self.saved:
            return self.saved[stage, key]
        request_text = json.dumps(payload, ensure_ascii=False, separators=(',', ':'))
        estimate = ((len(request_text) + len(prompt)) / 4 * self.args.input_cost_per_million +
                    900 * self.args.output_cost_per_million) / 1_000_000
        async with self.sem:
            async with self.lock:
                if (stage, key) in self.saved:
                    return self.saved[stage, key]
                if (self.args.max_cost_usd is not None and
                        self.estimated_cost() + self.in_flight_estimate + estimate > self.args.max_cost_usd):
                    raise RuntimeError('Cost ceiling reached before request. Completed work is checkpointed.')
                self.in_flight_estimate += estimate
            try:
                for attempt in range(self.args.retries + 1):
                    try:
                        response = await self.client.responses.parse(
                            model=self.args.model, instructions=prompt, input=request_text,
                            text_format=schema)
                        if response.status != 'completed' or response.output_parsed is None:
                            raise ValueError('Incomplete structured response')
                        parsed = response.output_parsed
                        result = validate(parsed)
                        usage = getattr(response, 'usage', None)
                        item = {'stage': stage, 'job_key': key, 'result': result, 'requests': attempt + 1,
                                'input_tokens': getattr(usage, 'input_tokens', 0) or 0,
                                'output_tokens': getattr(usage, 'output_tokens', 0) or 0}
                        async with self.lock:
                            with self.checkpoint.open('a', encoding='utf-8') as fp:
                                fp.write(json.dumps(item, ensure_ascii=False) + '\n')
                                fp.flush()
                                os.fsync(fp.fileno())
                            self.saved[stage, key] = result
                            for field in ('requests', 'input_tokens', 'output_tokens'):
                                self.usage[field] += item[field]
                            print(f'{stage}: checkpointed {key} | {self.usage["requests"]} requests | '
                                  f'cost about ${self.estimated_cost():.4f}', flush=True)
                        return result
                    except Exception as exc:
                        if attempt >= self.args.retries or not retryable(exc):
                            raise
                        await asyncio.sleep(max(retry_after(exc), min(2 ** attempt, 30) + random.random()))
            finally:
                async with self.lock:
                    self.in_flight_estimate -= estimate

    async def batches(self, stage, jobs, prompt, schema, validate):
        tasks = [asyncio.create_task(self.call(stage, key, payload, prompt, schema,
                                               lambda parsed, key=key: validate(key, parsed)))
                 for key, payload in jobs]
        try:
            return await asyncio.gather(*tasks)
        except Exception:
            await asyncio.gather(*tasks, return_exceptions=True)
            raise


def chunks(items, size):
    for start in range(0, len(items), size):
        yield items[start:start + size]


def validate_pair_batch(expected, parsed):
    found = [item.model_dump() for item in parsed.decisions]
    required = {(item['cluster_a'], item['cluster_b']) for item in expected}
    actual = {(item['cluster_a'], item['cluster_b']) for item in found}
    if actual != required or len(found) != len(required):
        raise ValueError('Pair response omitted, duplicated, or changed a candidate pair')
    if any(not item['reason'].strip() for item in found):
        raise ValueError('Pair decision missing evidence-based reason')
    return found


def guard_opposite_polarity(decisions, profiles):
    guarded = []
    for item in decisions:
        value = dict(item)
        a = profiles[value['cluster_a']]['top_polarity'].casefold()
        b = profiles[value['cluster_b']]['top_polarity'].casefold()
        if value['relationship'] == 'equivalent' and {a, b} == {'positive', 'negative'}:
            value['relationship'] = 'ambiguous'
            value['confidence'] = 'low'
            value['reason'] += ' Opposite dominant polarities require review before merging.'
        guarded.append(value)
    return guarded


def validate_topic_batch(expected, parents, parsed):
    found = [item.model_dump() for item in parsed.topics]
    if {item['topic_id'] for item in found} != set(expected) or len(found) != len(expected):
        raise ValueError('Topic response omitted, duplicated, or changed a topic ID')
    for item in found:
        if item['parent_category_id'] not in parents:
            raise ValueError('Topic used unknown parent category')
        if not item['canonical_name'].strip() or not item['definition'].strip():
            raise ValueError('Topic lacks name or definition')
        # Preserve a contradictory model decision for review instead of paying
        # to repeat the whole batch or silently treating it as a firm verdict.
        if item['relevance_status'] == 'keep' and item['exclusion_reason'] != 'none':
            item['relevance_status'] = 'needs_review'
        elif item['relevance_status'] == 'exclude' and item['exclusion_reason'] == 'none':
            item['relevance_status'] = 'needs_review'
            item['exclusion_reason'] = 'insufficient_information'
    return found


def validate_noise_batch(expected, candidates, parsed):
    found = [item.model_dump() for item in parsed.decisions]
    if {item['aspect_id'] for item in found} != set(expected) or len(found) != len(expected):
        raise ValueError('Noise response omitted, duplicated, or changed an aspect ID')
    for item in found:
        if item['topic_id'] and item['topic_id'] not in candidates[item['aspect_id']]:
            raise ValueError('Noise assignment used a topic not presented as a candidate')
    return found


def make_noise_candidates(records, X, groups, max_candidates=3, threshold=0.7):
    positions = defaultdict(list)
    for i, row in enumerate(records):
        if row['aspect_cluster_id'] >= 0:
            positions[row['aspect_cluster_id']].append(i)
    topic_centroids = {}
    for group in groups:
        member_positions = [i for cid in group['cluster_ids'] for i in positions[cid]]
        vector = X[member_positions].mean(axis=0)
        topic_centroids[topic_id(group['cluster_ids'])] = vector / np.linalg.norm(vector)
    ids = sorted(topic_centroids)
    matrix = np.stack([topic_centroids[key] for key in ids]) if ids else np.empty((0, X.shape[1]))
    candidates = {}
    for i, row in enumerate(records):
        if row['aspect_cluster_id'] != -1:
            continue
        scores = matrix @ X[i] if ids else np.array([])
        order = np.argsort(-scores)[:max_candidates]
        candidates[row['aspect_id']] = [(ids[j], float(scores[j])) for j in order if scores[j] >= threshold]
    return candidates


def build_final(records, groups, topics, parents, noise_decisions, pair_decisions):
    group_by_cid = {cid: group for group in groups for cid in group['cluster_ids']}
    topic_by_id = {item['topic_id']: item for item in topics}
    parent_by_id = {item['parent_category_id']: item for item in parents}
    mappings = []
    for cid in sorted(group_by_cid):
        group = group_by_cid[cid]
        tid = topic_id(group['cluster_ids'])
        topic = topic_by_id[tid]
        mappings.append({'aspect_cluster_id': cid, 'topic_id': tid,
                         'parent_category_id': topic['parent_category_id'],
                         'refinement_decision': group['status'],
                         'relevance_status': topic['relevance_status'],
                         'confidence_review_status': 'validated' if len(group['cluster_ids']) > 1 else 'singleton',
                         'merge_reason': group['reason']})
    mapped = {item['aspect_cluster_id']: item for item in mappings}
    noise_by_id = {item['aspect_id']: item for item in noise_decisions}
    final = []
    for row in records:
        item = dict(row)
        cid = item['aspect_cluster_id']
        if cid >= 0:
            mapping = mapped[cid]
            tid = mapping['topic_id']
            item.update({'topic_id': tid, 'canonical_topic_name': topic_by_id[tid]['canonical_name'],
                         'parent_category_id': mapping['parent_category_id'],
                         'parent_category_name': parent_by_id[mapping['parent_category_id']]['parent_category_name'],
                         'relevance_status': mapping['relevance_status'],
                         'assignment_method': 'cluster_mapping', 'assignment_uncertainty': 'none'})
        else:
            decision = noise_by_id.get(item['aspect_id'])
            tid = decision['topic_id'] if decision and decision['relationship'] == 'equivalent' and decision['confidence'] == 'high' else ''
            topic = topic_by_id.get(tid)
            parent = parent_by_id.get(topic['parent_category_id']) if topic else None
            item.update({'topic_id': tid or None,
                         'canonical_topic_name': topic['canonical_name'] if topic else None,
                         'parent_category_id': topic['parent_category_id'] if topic else None,
                         'parent_category_name': parent['parent_category_name'] if parent else None,
                         'relevance_status': topic['relevance_status'] if topic else 'needs_review',
                         'assignment_method': 'noise_llm_equivalent' if topic else 'noise_unassigned',
                         'assignment_uncertainty': decision['reason'] if decision else 'No sufficiently similar candidate'})
        final.append(item)
    if len(final) != len(records) or [row['aspect_id'] for row in final] != [row['aspect_id'] for row in records]:
        raise ValueError('Refinement did not preserve all original aspects in order')
    return mappings, final


PAIR_SCHEMA = pa.schema([('cluster_a', pa.int32()), ('cluster_b', pa.int32()),
                         ('cosine_similarity', pa.float32()), ('candidate_reason', pa.string())])
DECISION_SCHEMA = pa.schema([('cluster_a', pa.int32()), ('cluster_b', pa.int32()),
                             ('relationship', pa.string()), ('confidence', pa.string()),
                             ('reason', pa.string()), ('proposed_label', pa.string())])
MAPPING_SCHEMA = pa.schema([('aspect_cluster_id', pa.int32()), ('topic_id', pa.string()),
                            ('parent_category_id', pa.string()), ('refinement_decision', pa.string()),
                            ('relevance_status', pa.string()), ('confidence_review_status', pa.string()),
                            ('merge_reason', pa.string())])
REFINED_FIELDS = [
    ('topic_id', pa.string()), ('canonical_topic_name', pa.string()),
    ('parent_category_id', pa.string()), ('parent_category_name', pa.string()),
    ('relevance_status', pa.string()), ('assignment_method', pa.string()),
    ('assignment_uncertainty', pa.string()),
]


def write_parquet(path, rows, schema):
    pq.write_table(pa.Table.from_pylist(rows, schema=schema), path)


def write_refined_aspects(path, originals, refined):
    table = originals
    for name, dtype in REFINED_FIELDS:
        table = table.append_column(name, pa.array([row[name] for row in refined], type=dtype))
    pq.write_table(table, path)


async def paid_refinement(args, records, X, profiles, pairs, selected, runner):
    selected_set = set(selected)
    chosen_pairs = [pair for pair in pairs if pair['cluster_a'] in selected_set and pair['cluster_b'] in selected_set]
    pair_jobs = []
    for batch in chunks(chosen_pairs, args.pair_batch_size):
        key = ','.join(f'{p["cluster_a"]}:{p["cluster_b"]}' for p in batch)
        pair_jobs.append((key, [pair_payload(pair, profiles) for pair in batch]))
    expected_pairs = {f'{p["cluster_a"]}:{p["cluster_b"]}': p for p in chosen_pairs}
    def validate_pairs(key, parsed):
        validated = validate_pair_batch([expected_pairs[item] for item in key.split(',')], parsed)
        return guard_opposite_polarity(validated, profiles)
    batches = await runner.batches('pairs', pair_jobs, PAIR_RULES, PairBatch, validate_pairs)
    pair_decisions = [item for batch in batches for item in batch]
    tentative = tentative_groups(selected, pair_decisions)
    group_jobs = []
    for group in tentative:
        if len(group) > 2:
            group_jobs.append((','.join(map(str, group)), {
                'cluster_ids': group,
                'profiles': [pair_payload({'cluster_a': group[0], 'cluster_b': cid,
                            'cosine_similarity': 0}, profiles)['profile_b'] for cid in group[1:]],
                'first_profile': pair_payload({'cluster_a': group[0], 'cluster_b': group[1],
                                 'cosine_similarity': 0}, profiles)['profile_a'],
                'pair_decisions': [d for d in pair_decisions if d['cluster_a'] in group and d['cluster_b'] in group],
            }))
    def validate_group(key, parsed):
        value = parsed.model_dump()
        expected = [int(item) for item in key.split(',')]
        if sorted(cid for group in value['groups'] for cid in group['cluster_ids']) != expected:
            raise ValueError('Group validation omitted or duplicated cluster IDs')
        prohibited = {(d['cluster_a'], d['cluster_b']) for d in pair_decisions
                      if d['relationship'] in {'distinct', 'related', 'ambiguous'}}
        for group in value['groups']:
            for i, a in enumerate(group['cluster_ids']):
                for b in group['cluster_ids'][i + 1:]:
                    if (min(a, b), max(a, b)) in prohibited:
                        raise ValueError('Group validation conflicts with a non-equivalent pair')
        return value
    group_results = await runner.batches('groups', group_jobs,
        PAIR_RULES + ' Partition every cluster ID into coherent equivalence groups; singleton when uncertain.',
        GroupValidation, validate_group)
    validations = dict(zip((key for key, _ in group_jobs), group_results))
    selected_groups = resolve_groups(selected, pair_decisions, validations)
    unselected = sorted(set(profiles) - selected_set)
    groups = sorted(selected_groups + [{'cluster_ids': [cid], 'status': 'not_evaluated',
                                      'reason': 'Outside --max-clusters evaluation'} for cid in unselected],
                    key=lambda item: item['cluster_ids'][0])

    brief = [{'topic_id': topic_id(group['cluster_ids']), 'cluster_ids': group['cluster_ids'],
              'categories': [profiles[cid]['top_category'] for cid in group['cluster_ids']],
              'examples': [text for cid in group['cluster_ids'] for text in profiles[cid]['examples'][:3]][:9]}
             for group in selected_groups]
    def validate_parents(parsed):
        value = parsed.model_dump()
        categories = value['categories']
        identifiers = [item['parent_category_id'] for item in categories]
        if (not categories or len(set(identifiers)) != len(identifiers) or
                any(not item['parent_category_name'].strip() or not item['definition'].strip()
                    for item in categories)):
            raise ValueError('Invalid or duplicate parent categories')
        if 'review_pending' in identifiers:
            raise ValueError('Parent category ID review_pending is reserved')
        return value
    parent_result = await runner.call('parents', 'all',
        {'analysis_objective': args.analysis_objective, 'topics': brief},
        'Create broad, coherent parent categories (maximum three taxonomy levels). ' + RELEVANCE_RULES,
        ParentPlan, validate_parents)
    parents = parent_result['categories']
    if unselected:
        parents.append({'parent_category_id': 'review_pending', 'parent_category_name': 'Review pending',
                        'definition': 'Topics outside the limited evaluation'})
    topic_jobs = []
    for batch in chunks(selected_groups, args.topic_batch_size):
        ids = [topic_id(group['cluster_ids']) for group in batch]
        payload = {'analysis_objective': args.analysis_objective, 'parent_categories': parents,
                   'topics': [{'topic_id': tid, 'cluster_ids': group['cluster_ids'],
                               'profiles': [pair_payload({'cluster_a': cid, 'cluster_b': cid,
                                            'cosine_similarity': 1}, profiles)['profile_a']
                                            for cid in group['cluster_ids']]}
                              for tid, group in zip(ids, batch)]}
        topic_jobs.append((','.join(ids), payload))
    def validate_topics(key, parsed):
        return validate_topic_batch(key.split(','), {p['parent_category_id'] for p in parents}, parsed)
    topic_batches = await runner.batches('topics', topic_jobs, RELEVANCE_RULES, TopicBatch, validate_topics)
    topics = [item for batch in topic_batches for item in batch]
    for cid in unselected:
        topics.append({'topic_id': topic_id([cid]), 'canonical_name': profiles[cid]['examples'][0],
                       'definition': 'Limited evaluation: definition needs model review.',
                       'parent_category_id': 'review_pending', 'relevance_status': 'needs_review',
                       'exclusion_reason': 'none'})

    noise_candidates = make_noise_candidates(records, X, groups, threshold=args.noise_threshold)
    topic_by_id = {item['topic_id']: item for item in topics}
    noise_rows = {row['aspect_id']: row for row in records if row['aspect_cluster_id'] == -1}
    # A partial evaluation deliberately leaves noise for the complete run.
    eligible = [] if unselected else [key for key, choices in noise_candidates.items() if choices]
    noise_jobs = []
    for batch in chunks(eligible, args.noise_batch_size):
        payload = {'analysis_objective': args.analysis_objective, 'aspects': [
            {'aspect_id': key, 'description': noise_rows[key]['description'],
             'polarity': noise_rows[key].get('polarity'), 'category': noise_rows[key].get('category'),
             'candidate_topics': [{'topic_id': tid, 'similarity': round(score, 4),
                                   'name': topic_by_id[tid]['canonical_name'],
                                   'examples': [text for cid in next(g for g in groups if topic_id(g['cluster_ids']) == tid)['cluster_ids']
                                                for text in profiles[cid]['examples'][:2]][:4]}
                                  for tid, score in noise_candidates[key]]}
            for key in batch]}
        noise_jobs.append((','.join(batch), payload))
    def validate_noise(key, parsed):
        options = {aspect_id: {tid for tid, _ in noise_candidates[aspect_id]} for aspect_id in key.split(',')}
        return validate_noise_batch(key.split(','), options, parsed)
    noise_batches = await runner.batches('noise', noise_jobs,
        'Assign only clearly equivalent aspects to a candidate topic. Otherwise use empty topic_id and ambiguous. '
        + PAIR_RULES, NoiseBatch, validate_noise)
    noise_decisions = [item for batch in noise_batches for item in batch]
    return chosen_pairs, pair_decisions, groups, validations, parents, topics, noise_decisions


def run_pairwise(args, client=None):
    if args.concurrency < 1 or args.pair_batch_size < 1 or args.topic_batch_size < 1 or args.noise_batch_size < 1:
        raise ValueError('Concurrency and batch sizes must be positive')
    if args.neighbors < 1 or args.retries < 0:
        raise ValueError('--neighbors must be positive and --retries cannot be negative')
    if args.input_cost_per_million < 0 or args.output_cost_per_million < 0:
        raise ValueError('Token prices cannot be negative')
    if not 0 <= args.similarity_threshold <= 1 or not 0 <= args.noise_threshold <= 1:
        raise ValueError('Similarity thresholds must be between 0 and 1')
    if args.max_clusters is not None and args.max_clusters < 1:
        raise ValueError('--max-clusters must be positive')
    if args.max_cost_usd is not None and args.max_cost_usd <= 0:
        raise ValueError('--max-cost-usd must be positive')
    source, output = args.input.expanduser().resolve(), args.output.expanduser().resolve()
    assignments, records, X, reps, step7, source_manifest, embedding_path = prepare_inputs(source, args.embedding_root)
    profiles, centroids = build_profiles(records, X, reps)
    pairs = candidate_pairs(profiles, centroids, args.similarity_threshold, args.neighbors)
    selected = choose_clusters(profiles, pairs, args.max_clusters)
    planned = [pair for pair in pairs if pair['cluster_a'] in selected and pair['cluster_b'] in selected]
    estimate = {'source_aspects': len(records), 'source_clusters': len(profiles),
                'selected_clusters': len(selected), 'candidate_comparisons': len(planned),
                'pair_requests': (len(planned) + args.pair_batch_size - 1) // args.pair_batch_size,
                'topic_requests_at_least': (len(selected) + args.topic_batch_size - 1) // args.topic_batch_size,
                'noise_aspects': sum(row['aspect_cluster_id'] == -1 for row in records)}
    estimate['possible_group_validation_requests'] = len(selected) // 3
    estimate['possible_noise_requests'] = ((estimate['noise_aspects'] + args.noise_batch_size - 1)
                                           // args.noise_batch_size) if len(selected) == len(profiles) else 0
    estimate['parent_category_requests'] = 1
    if args.dry_run:
        preview = sorted(planned, key=lambda item: -item['cosine_similarity'])[:20]
        print(json.dumps({**estimate, 'selected_cluster_ids': selected,
                          'candidate_pair_preview': preview}, indent=2))
        print('No API calls or output files created.')
        return estimate
    config = {'prompt_version': PROMPT_VERSION, 'model': args.model, 'source': str(source),
              'source_assignment_sha256': file_sha256(source / 'aspect_clusters.parquet'),
              'source_embedding_sha256': source_manifest.get('config', {}).get('source_sha256'),
              'embedding_root': str(embedding_path), 'analysis_objective': args.analysis_objective,
              'max_clusters': args.max_clusters, 'similarity_threshold': args.similarity_threshold,
              'noise_threshold': args.noise_threshold, 'neighbors': args.neighbors,
              'pair_batch_size': args.pair_batch_size, 'topic_batch_size': args.topic_batch_size,
              'noise_batch_size': args.noise_batch_size}
    output.mkdir(parents=True, exist_ok=True)
    config_path = output / 'run_config.json'
    if config_path.exists():
        if not args.resume:
            raise ValueError('Output exists. Use --resume or a new --output directory.')
        if json.loads(config_path.read_text(encoding='utf-8')) != config:
            raise ValueError('Output checkpoint belongs to different input or settings')
    elif any(output.iterdir()):
        raise ValueError('Output contains files without run_config.json')
    else:
        atomic_json(config_path, config)
    saved, usage = load_checkpoint(output / 'checkpoint.jsonl')
    if client is None:
        from openai import AsyncOpenAI
        from extract_review_aspects import load_api_key_from_env_file
        load_api_key_from_env_file()
        if not os.getenv('OPENAI_API_KEY') or os.getenv('OPENAI_API_KEY') == 'your-api-key':
            raise ValueError('Set OPENAI_API_KEY in the project .env file')
        client = AsyncOpenAI(max_retries=0)
        owns_client = True
    else:
        owns_client = False

    async def execute():
        runner = PaidRunner(client, args, output / 'checkpoint.jsonl', saved, usage)
        try:
            return await paid_refinement(args, records, X, profiles, pairs, selected, runner)
        finally:
            if owns_client:
                await client.close()
    chosen_pairs, decisions, groups, validations, parents, topics, noise = asyncio.run(execute())
    mappings, refined = build_final(records, groups, topics, parents, noise, decisions)
    topic_by_id = {item['topic_id']: item for item in topics}
    canonical = {'parent_categories': parents, 'topics': [
        {**item, 'parent_category_name': next(p['parent_category_name'] for p in parents
                if p['parent_category_id'] == item['parent_category_id']),
         'original_cluster_ids': group['cluster_ids'],
         'representative_descriptions': list(dict.fromkeys(text for cid in group['cluster_ids']
                                         for text in profiles[cid]['examples'][:3]))[:10]}
        for group in groups for item in [topic_by_id[topic_id(group['cluster_ids'])]]],
        'analysis_objective': args.analysis_objective}
    resolved_noise = sum(row['assignment_method'] == 'noise_llm_equivalent' for row in refined)
    report = {'total_original_aspect_clusters': len(profiles), 'canonical_topics': len(topics),
              'accepted_merges': len(profiles) - len(topics),
              'rejected_merges': sum(d['relationship'] in {'distinct', 'related'} for d in decisions),
              'related_decisions': sum(d['relationship'] == 'related' for d in decisions),
              'ambiguous_decisions': sum(d['relationship'] == 'ambiguous' for d in decisions),
              'excluded_topics': sum(t['relevance_status'] == 'exclude' for t in topics),
              'flagged_topics': sum(t['relevance_status'] == 'needs_review' for t in topics),
              'noise_resolved': resolved_noise,
              'noise_retained': sum(row['aspect_cluster_id'] == -1 for row in records) - resolved_noise,
              'api_requests': usage['requests'], 'input_tokens': usage['input_tokens'],
              'output_tokens': usage['output_tokens'],
              'estimated_api_cost_usd': round((usage['input_tokens'] * args.input_cost_per_million +
                                              usage['output_tokens'] * args.output_cost_per_million) / 1_000_000, 6),
              'model': args.model, 'prompt_version': PROMPT_VERSION,
              'partial_evaluation': bool(args.max_clusters and len(selected) < len(profiles)),
              'source_aspects': len(records)}
    atomic_json(output / 'cluster_profiles.json', list(profiles.values()))
    write_parquet(output / 'candidate_pairs.parquet', pairs, PAIR_SCHEMA)
    write_parquet(output / 'pair_decisions.parquet', decisions, DECISION_SCHEMA)
    atomic_json(output / 'validated_merge_groups.json', {'groups': groups, 'group_validations': validations})
    atomic_json(output / 'canonical_topics.json', canonical)
    write_parquet(output / 'cluster_mapping.parquet', mappings, MAPPING_SCHEMA)
    write_refined_aspects(output / 'refined_aspects.parquet', assignments, refined)
    atomic_json(output / 'refinement_report.json', report)
    print(json.dumps(report, indent=2))
    return report


def run(args, client=None):
    if getattr(args, 'strategy', 'pairwise') == 'global':
        from global_aspect_refinement import run_global
        return run_global(args, client=client)
    return run_pairwise(args, client=client)


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, default=Path('aspect-clusters/spotify'))
    parser.add_argument('--output', type=Path)
    parser.add_argument('--strategy', choices=['global', 'pairwise'], default='global')
    parser.add_argument('--embedding-root', type=Path, help='Override embedding folder in Step 7 run_config.json')
    parser.add_argument('--compare-to', type=Path,
                        help='Existing pairwise result folder for an offline baseline comparison')
    parser.add_argument('--model', default='gpt-6.1-sol')
    parser.add_argument('--concurrency', type=int, default=5)
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--max-clusters', type=int)
    parser.add_argument('--similarity-threshold', type=float, default=0.72)
    parser.add_argument('--noise-threshold', type=float, default=0.70)
    parser.add_argument('--duplicate-threshold', type=float, default=0.83,
                        help='Global verification threshold for possible duplicate topics')
    parser.add_argument('--review-threshold', type=float, default=0.86,
                        help='Dry-run similarity threshold for suggested review groups')
    parser.add_argument('--neighbors', type=int, default=7)
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--skip-verification', action='store_true')
    parser.add_argument('--max-repair-attempts', type=int, default=2)
    parser.add_argument('--max-input-tokens', type=int, default=180000)
    parser.add_argument('--max-output-tokens', type=int, default=64000,
                        help='Global preflight budget for the taxonomy response')
    parser.add_argument('--max-cost-usd', type=float)
    parser.add_argument('--analysis-objective', default=DEFAULT_OBJECTIVE)
    parser.add_argument('--pair-batch-size', type=int, default=5)
    parser.add_argument('--topic-batch-size', type=int, default=10)
    parser.add_argument('--noise-batch-size', type=int, default=8)
    parser.add_argument('--retries', type=int, default=3)
    parser.add_argument('--input-cost-per-million', type=float, default=2.0)
    parser.add_argument('--output-cost-per-million', type=float, default=10.0)
    args = parser.parse_args()
    if args.output is None:
        args.output = Path('refined-topics/spotify-global' if args.strategy == 'global'
                           else 'refined-topics/spotify')
    return args


if __name__ == '__main__':
    try:
        run(parse_args())
    except (OSError, ValueError, RuntimeError) as exc:
        print(f'Error: {exc}', file=sys.stderr)
        sys.exit(1)
