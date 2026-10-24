"""Global LLM strategy for refine_aspect_clusters.py.

One structured taxonomy request sees all cluster profiles when they fit. The
remaining requests repair invalid coverage, verify questionable groups, and
consider noise aspects. Original Step 7 assignments remain authoritative.
"""

import asyncio
import csv
import hashlib
import json
import os
import re
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Literal

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

import refine_aspect_clusters as core


GLOBAL_VERSION = 'aspect_refinement_global_v3'
MAX_SPLIT_FRACTION = 0.20
MIN_MAPPED_ASPECT_FRACTION = 0.75
GLOBAL_PROMPT = (
    'You are refining a product-feedback taxonomy. Examine ALL supplied cluster profiles together. '
    'Assign every original cluster exactly once to a specific canonical topic, needs_split, or needs_review. '
    'Merge only the same underlying product experience. Keep ad frequency separate from ads despite Premium, '
    'misleading ad-free promises, ad content, and playback failures after ads. Keep queue add, queue remove, '
    'queue reorder, forced shuffle, and shuffle repetition distinct. Keep positive experiences distinguishable '
    'from negative ones. Do not make broad labels joined by unrelated issues. A heterogeneous source cluster '
    'must be needs_split with suggested subtopics; do not guess member-level assignments. '
    'Treat each HDBSCAN cluster as one unit when its examples have a clear dominant product issue. '
    'A few outlying examples, different wording, severity, feature requests, or sentiment about that same issue '
    'do not justify splitting the cluster. Use needs_split only when two or more unrelated issues recur with '
    'multiple clear examples each and no coherent dominant issue. If evidence is truly insufficient, use '
    'clusters_needing_review. Most source clusters should map to specific canonical topics. '
    'Keep specific praise '
    'and feature requests. Exclude only generic/non-product feedback. Use parent_category as a broad category '
    'name. Return concise names and evidence-based definitions. No reasoning outside structured fields.'
)
VERIFY_PROMPT = (
    'Check this proposed canonical topic against descriptions from EVERY member source cluster. '
    'Partition its source_cluster_ids into coherent issue groups. Keep distinct failure modes and opposite '
    'positive/negative experiences separate. For a genuinely mixed single source cluster, return a singleton '
    'with status needs_review. Do not invent member-level assignments.'
)
NOISE_PROMPT = ('Assign an unclustered aspect only if it clearly expresses the SAME specific product experience '
                'as a supplied canonical topic. Otherwise leave topic_id empty and mark ambiguous. '
                'Similarity alone is not proof of equivalence.')


class GlobalTopic(core.StrictModel):
    canonical_name: str
    definition: str
    parent_category: str
    source_cluster_ids: list[int]
    relevance_status: Literal['keep', 'exclude', 'needs_review']
    decision_reason: str
    exclusion_reason: str


class SplitFlag(core.StrictModel):
    cluster_id: int
    reason: str
    suggested_subtopics: list[str]
    distinguishing_descriptions: list[str]


class ReviewFlag(core.StrictModel):
    cluster_id: int
    reason: str


class GlobalResponse(core.StrictModel):
    canonical_topics: list[GlobalTopic]
    clusters_needing_split: list[SplitFlag]
    clusters_needing_review: list[ReviewFlag]


class CheckedPart(core.StrictModel):
    source_cluster_ids: list[int]
    status: Literal['approved', 'needs_review']
    canonical_name: str
    definition: str
    reason: str


class VerifyResponse(core.StrictModel):
    parts: list[CheckedPart]


class DuplicateDecision(core.StrictModel):
    topic_a: str
    topic_b: str
    relationship: Literal['equivalent', 'related', 'distinct', 'ambiguous']
    reason: str
    proposed_name: str
    proposed_definition: str


class DuplicateBatch(core.StrictModel):
    decisions: list[DuplicateDecision]


def compact_profile(profile):
    result = {key: profile[key] for key in (
        'cluster_id', 'aspect_count', 'unique_reviews', 'category_distribution',
        'polarity_distribution', 'top_features', 'potentially_heterogeneous')}
    # The stored profile retains more examples. The global request uses enough
    # evidence to distinguish failure modes without amplifying one-off outliers.
    result['examples'] = profile['examples'][:7]
    result['random_examples'] = profile['random_examples'][:3]
    return result


def profile_payload(profiles, ids):
    return {'cluster_profiles': [compact_profile(profiles[cid]) for cid in sorted(ids)]}


def estimate_tokens(value):
    return (len(json.dumps(value, ensure_ascii=False, separators=(',', ':'))) + len(GLOBAL_PROMPT)) // 4


def grouped_payloads(profiles, budget, output_budget=64000):
    """Category grouped fallback; final reconciliation still sees all proposals."""
    by_category = defaultdict(list)
    for cid, profile in profiles.items():
        by_category[profile['top_category']].append(cid)
    jobs = []
    for category, ids in sorted(by_category.items()):
        pending = []
        for cid in ids:
            candidate = pending + [cid]
            if pending and (estimate_tokens(profile_payload(profiles, candidate)) > budget or
                            len(candidate) * 180 > output_budget):
                jobs.append((f'category:{category}:{pending[0]}', pending))
                pending = [cid]
            else:
                pending = candidate
            if (estimate_tokens(profile_payload(profiles, pending)) > budget or
                    len(pending) * 180 > output_budget):
                raise ValueError(f'Cluster {cid} alone exceeds --max-input-tokens')
        if pending:
            jobs.append((f'category:{category}:{pending[0]}', pending))
    return jobs


def validate_global(proposal, expected_ids, profiles=None,
                    max_split_fraction=MAX_SPLIT_FRACTION,
                    min_mapped_aspect_fraction=MIN_MAPPED_ASPECT_FRACTION):
    if not proposal['canonical_topics']:
        return ['No canonical topics returned']
    errors, assigned = [], []
    for topic in proposal['canonical_topics']:
        ids = topic['source_cluster_ids']
        if not ids:
            errors.append('A canonical topic has no source clusters')
        if not all(str(topic[field]).strip() for field in
                   ('canonical_name', 'definition', 'parent_category', 'decision_reason')):
            errors.append(f'Topic with clusters {ids} lacks a name, definition, parent, or reason')
        if len(topic['canonical_name']) > 105:
            errors.append(f'Topic name is too broad/long for clusters {ids}')
        assigned.extend(ids)
    for item in proposal['clusters_needing_split']:
        assigned.append(item['cluster_id'])
        if len(item['suggested_subtopics']) < 2 or not item['reason'].strip():
            errors.append(f'Incomplete split proposal for cluster {item["cluster_id"]}')
    assigned.extend(item['cluster_id'] for item in proposal['clusters_needing_review'])
    counts = Counter(assigned)
    if missing := set(expected_ids) - set(counts):
        errors.append(f'Missing cluster IDs: {sorted(missing)}')
    if unknown := set(counts) - set(expected_ids):
        errors.append(f'Unknown cluster IDs: {sorted(unknown)}')
    if repeated := sorted(cid for cid, count in counts.items() if count > 1):
        errors.append(f'Duplicate cluster assignments: {repeated}')
    if profiles and set(expected_ids) == set(profiles):
        split_ids = {item['cluster_id'] for item in proposal['clusters_needing_split']}
        total_aspects = sum(profiles[cid]['aspect_count'] for cid in expected_ids)
        mapped_aspects = sum(profiles[cid]['aspect_count'] for topic in proposal['canonical_topics']
                             for cid in topic['source_cluster_ids'] if cid in profiles)
        if len(split_ids) / len(expected_ids) > max_split_fraction:
            errors.append(f'Too many clusters marked needs_split: {len(split_ids)}/{len(expected_ids)}; '
                          'reserve splits for recurring unrelated issues with specific evidence')
        if mapped_aspects / total_aspects < min_mapped_aspect_fraction:
            errors.append(f'Only {mapped_aspects}/{total_aspects} non-noise aspects map to topics; '
                          'reconsider clusters with a dominant specific issue')
    # The hierarchy is parent -> leaf only, so cycles cannot be represented.
    return errors


def semantic_flags(topic, profiles, centroids):
    ids = topic['source_cluster_ids']
    flags = []
    if len(ids) > 1:
        scores = [float(centroids[a] @ centroids[b]) for i, a in enumerate(ids)
                  for b in ids[i + 1:]]
        if scores and min(scores) < 0.55:
            flags.append(f'low_minimum_centroid_similarity:{min(scores):.3f}')
        categories = {profiles[cid]['top_category'] for cid in ids}
        if len(categories) > 1:
            flags.append('mixed_dominant_categories')
        polarities = {profiles[cid]['top_polarity'] for cid in ids}
        if {'positive', 'negative'} <= polarities:
            flags.append('opposite_dominant_polarities')
    name = topic['canonical_name'].casefold()
    if len(name) > 75 or name.count(',') + len(re.findall(r'\b(?:and|including)\b', name)) >= 2:
        flags.append('broad_canonical_name')
    if any(profiles[cid]['potentially_heterogeneous'] for cid in ids):
        flags.append('heterogeneous_source_cluster')
    return flags


def duplicate_candidates(topics, centroids, limit=18, threshold=0.83):
    vectors = {}
    for i, topic in enumerate(topics):
        source_ids = topic['source_cluster_ids']
        vector = np.mean([centroids[cid] for cid in source_ids], axis=0)
        vectors[str(i)] = vector / np.linalg.norm(vector)
    candidates = []
    for i, a in enumerate(topics):
        for j in range(i + 1, len(topics)):
            b = topics[j]
            score = float(vectors[str(i)] @ vectors[str(j)])
            same_parent = a['parent_category'].casefold() == b['parent_category'].casefold()
            if score >= threshold and (same_parent or score >= threshold + 0.08):
                candidates.append({'topic_a': str(i), 'topic_b': str(j),
                                   'similarity': score, 'cross_parent': not same_parent})
    return sorted(candidates, key=lambda item: -item['similarity'])[:limit]


def validate_verify(original_ids, result):
    parts = result['parts']
    if sorted(cid for part in parts for cid in part['source_cluster_ids']) != sorted(original_ids):
        raise ValueError('Verification did not partition all source clusters exactly once')
    if any(not part['source_cluster_ids'] or not part['reason'].strip() for part in parts):
        raise ValueError('Verification returned an empty or unexplained part')
    return parts


def stable_parent_id(name):
    slug = re.sub(r'[^a-z0-9]+', '-', name.casefold()).strip('-')[:45] or 'category'
    return f'{slug}-{hashlib.sha1(name.casefold().encode()).hexdigest()[:6]}'


def assemble_taxonomy(proposal, profiles, flags_by_topic, verification, duplicate_decisions):
    """Apply only verified semantic changes; never merge an ambiguous relationship."""
    topics = []
    for index, original in enumerate(proposal['canonical_topics']):
        value = dict(original)
        flagged = flags_by_topic.get(str(index), [])
        if str(index) in verification:
            parts = validate_verify(value['source_cluster_ids'], verification[str(index)])
            for part in parts:
                topic = {**value, 'source_cluster_ids': sorted(part['source_cluster_ids']),
                         'canonical_name': part['canonical_name'], 'definition': part['definition'],
                         'decision_reason': part['reason']}
                if part['status'] == 'needs_review':
                    topic['relevance_status'] = 'needs_review'
                topics.append(topic)
        else:
            if flagged:
                value['relevance_status'] = 'needs_review'
            topics.append(value)

    # Only non-overlapping high-confidence duplicate decisions may merge here.
    used = set()
    merged = []
    for item in duplicate_decisions:
        if item['relationship'] != 'equivalent':
            continue
        a, b = int(item['topic_a']), int(item['topic_b'])
        if a in used or b in used:
            continue
        if a >= len(proposal['canonical_topics']) or b >= len(proposal['canonical_topics']):
            continue
        left, right = proposal['canonical_topics'][a], proposal['canonical_topics'][b]
        # Verification may have split a topic; do not merge its old proposal.
        if str(a) in verification or str(b) in verification:
            continue
        if left['relevance_status'] != right['relevance_status']:
            continue
        if ({profiles[c]['top_polarity'] for c in left['source_cluster_ids']} == {'positive'} and
                {profiles[c]['top_polarity'] for c in right['source_cluster_ids']} == {'negative'}) or (
                {profiles[c]['top_polarity'] for c in left['source_cluster_ids']} == {'negative'} and
                {profiles[c]['top_polarity'] for c in right['source_cluster_ids']} == {'positive'}):
            continue
        member_ids = sorted(left['source_cluster_ids'] + right['source_cluster_ids'])
        combined = {**left, 'source_cluster_ids': member_ids,
                    'canonical_name': item['proposed_name'] or left['canonical_name'],
                    'definition': item['proposed_definition'] or left['definition'],
                    'decision_reason': item['reason'],
                    'relevance_status': 'needs_review' if left['parent_category'] != right['parent_category'] else left['relevance_status']}
        merged.append(combined)
        used.update((a, b))
    if used:
        used_cluster_sets = [set(item['source_cluster_ids']) for item in merged]
        topics = [item for item in topics if not any(set(item['source_cluster_ids']) <= group
                                                       for group in used_cluster_sets)] + merged

    split_ids = {item['cluster_id'] for item in proposal['clusters_needing_split']}
    review_ids = {item['cluster_id'] for item in proposal['clusters_needing_review']}
    final_ids = [cid for topic in topics for cid in topic['source_cluster_ids']]
    expected = sorted(set(final_ids) | split_ids | review_ids)
    if sorted(final_ids + list(split_ids) + list(review_ids)) != expected:
        raise ValueError('Consolidation duplicated or lost a source cluster')
    parents = {}
    canonical = []
    for topic in sorted(topics, key=lambda item: min(item['source_cluster_ids'])):
        parent = topic['parent_category'].strip()
        pid = stable_parent_id(parent)
        parents[pid] = {'parent_category_id': pid, 'parent_category_name': parent,
                        'definition': f'Product feedback about {parent.casefold()}'}
        ids = sorted(topic['source_cluster_ids'])
        canonical.append({'topic_id': core.topic_id(ids), 'canonical_name': topic['canonical_name'],
                          'definition': topic['definition'], 'parent_category_id': pid,
                          'parent_category_name': parent, 'original_cluster_ids': ids,
                          'relevance_status': topic['relevance_status'],
                          'exclusion_reason': topic.get('exclusion_reason') or 'none',
                          'decision_reason': topic['decision_reason'],
                          'representative_descriptions': list(dict.fromkeys(
                              text for cid in ids for text in profiles[cid]['examples'][:3]))[:10]})
    return {'parent_categories': list(parents.values()), 'topics': canonical,
            'clusters_needing_split': proposal['clusters_needing_split'],
            'clusters_needing_review': proposal['clusters_needing_review']}


def map_aspects(assignments, taxonomy, noise_decisions):
    rows = assignments.to_pylist()
    topics = taxonomy['topics']
    by_cluster = {cid: topic for topic in topics for cid in topic['original_cluster_ids']}
    split = {item['cluster_id'] for item in taxonomy['clusters_needing_split']}
    review = {item['cluster_id'] for item in taxonomy['clusters_needing_review']}
    cluster_ids = {row['aspect_cluster_id'] for row in rows if row['aspect_cluster_id'] >= 0}
    if set(by_cluster) | split | review != cluster_ids or len(by_cluster) + len(split) + len(review) != len(cluster_ids):
        raise ValueError('Cluster mapping is incomplete or overlapping')
    noise_by_id = {item['aspect_id']: item for item in noise_decisions}
    topic_by_id = {topic['topic_id']: topic for topic in topics}
    mapped = []
    for row in rows:
        cid = row['aspect_cluster_id']
        if cid in by_cluster:
            topic = by_cluster[cid]
            mapped.append({'topic_id': topic['topic_id'], 'canonical_topic_name': topic['canonical_name'],
                           'parent_category_id': topic['parent_category_id'],
                           'parent_category_name': topic['parent_category_name'],
                           'relevance_status': topic['relevance_status'],
                           'assignment_method': 'global_cluster_mapping',
                           'assignment_uncertainty': 'none' if topic['relevance_status'] != 'needs_review' else 'Topic needs review'})
        elif cid in split or cid in review:
            status = 'needs_split' if cid in split else 'needs_review'
            mapped.append({'topic_id': None, 'canonical_topic_name': None,
                           'parent_category_id': None, 'parent_category_name': None,
                           'relevance_status': 'needs_review', 'assignment_method': status,
                           'assignment_uncertainty': f'Source cluster {status}'})
        else:
            decision = noise_by_id.get(row['aspect_id'])
            tid = decision['topic_id'] if decision and decision['relationship'] == 'equivalent' and decision['confidence'] == 'high' else ''
            topic = topic_by_id.get(tid)
            mapped.append({'topic_id': tid or None,
                           'canonical_topic_name': topic['canonical_name'] if topic else None,
                           'parent_category_id': topic['parent_category_id'] if topic else None,
                           'parent_category_name': topic['parent_category_name'] if topic else None,
                           'relevance_status': topic['relevance_status'] if topic else 'needs_review',
                           'assignment_method': 'noise_llm_equivalent' if topic else 'noise_unassigned',
                           'assignment_uncertainty': decision['reason'] if decision else 'No clear equivalent topic'})
    table = assignments
    for name, dtype in core.REFINED_FIELDS:
        table = table.append_column(name, pa.array([item[name] for item in mapped], type=dtype))
    mappings = []
    for cid in sorted(cluster_ids):
        topic = by_cluster.get(cid)
        mappings.append({'aspect_cluster_id': cid, 'topic_id': topic['topic_id'] if topic else None,
                         'parent_category_id': topic['parent_category_id'] if topic else None,
                         'refinement_decision': 'global_validated' if topic else 'needs_split' if cid in split else 'needs_review',
                         'relevance_status': topic['relevance_status'] if topic else 'needs_review',
                         'confidence_review_status': 'validated' if topic and topic['relevance_status'] != 'needs_review' else 'needs_review',
                         'merge_reason': topic['decision_reason'] if topic else 'Unresolved source cluster'})
    if table.num_rows != assignments.num_rows or table.column('aspect_id').to_pylist() != assignments.column('aspect_id').to_pylist():
        raise ValueError('Original aspects were lost or reordered')
    return table, mappings


def write_topic_catalog(output, taxonomy, refined):
    """Write a readable list alongside the machine-readable taxonomy."""
    by_topic = defaultdict(list)
    for row in refined.select(['topic_id', 'review_key', 'polarity']).to_pylist():
        if row['topic_id']:
            by_topic[row['topic_id']].append(row)
    rows = []
    for topic in taxonomy['topics']:
        members = by_topic[topic['topic_id']]
        rows.append({
            'topic_id': topic['topic_id'],
            'parent_category': topic['parent_category_name'],
            'canonical_name': topic['canonical_name'],
            'definition': topic['definition'],
            'relevance_status': topic['relevance_status'],
            'unique_sampled_reviews': len({row['review_key'] for row in members}),
            'aspect_observations': len(members),
            'polarity_counts': json.dumps(dict(Counter(row['polarity'] for row in members)),
                                          ensure_ascii=False, sort_keys=True),
            'original_cluster_ids': ','.join(map(str, topic['original_cluster_ids'])),
            'representative_descriptions': ' | '.join(topic['representative_descriptions'][:3]),
        })
    rows.sort(key=lambda item: (item['parent_category'].casefold(),
                                -item['unique_sampled_reviews'], item['canonical_name'].casefold()))
    columns = list(rows[0]) if rows else [
        'topic_id', 'parent_category', 'canonical_name', 'definition', 'relevance_status',
        'unique_sampled_reviews', 'aspect_observations', 'polarity_counts',
        'original_cluster_ids', 'representative_descriptions']
    with (output / 'topic_catalog.csv').open('w', newline='', encoding='utf-8') as fp:
        writer = csv.DictWriter(fp, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)

    def cell(value):
        return str(value).replace('|', '\\|').replace('\n', ' ')

    lines = ['# Canonical topic catalog', '',
             f'{len(rows)} topics. Counts are distinct **sampled** reviews, not Spotify-wide prevalence.',
             'Topics marked `needs_review` and `exclude` remain visible; split clusters are listed below.', '']
    by_parent = defaultdict(list)
    for row in rows:
        by_parent[row['parent_category']].append(row)
    for parent in sorted(by_parent, key=str.casefold):
        lines.extend([f'## {parent}', '',
                      '| ID | Topic | Sampled reviews | Status | Source clusters |',
                      '| --- | --- | ---: | --- | --- |'])
        for row in by_parent[parent]:
            lines.append(f"| {cell(row['topic_id'])} | {cell(row['canonical_name'])} | "
                         f"{row['unique_sampled_reviews']} | {cell(row['relevance_status'])} | "
                         f"{cell(row['original_cluster_ids'])} |")
        lines.append('')
    if taxonomy['clusters_needing_split']:
        lines.extend(['## Source clusters needing split', '',
                      'These clusters do not have a final topic assignment for their individual aspects.', ''])
        for item in taxonomy['clusters_needing_split']:
            lines.append(f"- Cluster {item['cluster_id']}: {item['reason']}")
        lines.append('')
    if taxonomy['clusters_needing_review']:
        lines.extend(['## Source clusters needing review', ''])
        for item in taxonomy['clusters_needing_review']:
            lines.append(f"- Cluster {item['cluster_id']}: {item['reason']}")
        lines.append('')
    (output / 'topic_catalog.md').write_text('\n'.join(lines), encoding='utf-8')
    return rows


def local_review_groups(profiles, centroids, threshold=0.86):
    ids = sorted(profiles)
    graph = {cid: set() for cid in ids}
    pairs = []
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            score = float(centroids[a] @ centroids[b])
            if score >= threshold:
                graph[a].add(b)
                graph[b].add(a)
                pairs.append({'cluster_a': a, 'cluster_b': b, 'cosine_similarity': score,
                              'category_a': profiles[a]['top_category'],
                              'category_b': profiles[b]['top_category']})
    seen, groups = set(), []
    for cid in ids:
        if cid in seen or not graph[cid]:
            continue
        pending, members = [cid], set()
        while pending:
            current = pending.pop()
            if current in members:
                continue
            members.add(current)
            pending.extend(graph[current] - members)
        seen.update(members)
        groups.append({'cluster_ids': sorted(members),
                       'examples': [profiles[item]['examples'][0] for item in sorted(members)],
                       'review_status': 'similarity_suggestion_only'})
    return sorted(groups, key=lambda group: -len(group['cluster_ids'])), sorted(
        pairs, key=lambda item: -item['cosine_similarity'])


def render_dry_review(report):
    lines = [
        '# Global refinement dry run', '',
        f"- Source aspects: {report['source_aspects']:,}",
        f"- Original clusters: {report['source_clusters']}",
        f"- Estimated global input tokens: {report['estimated_global_input_tokens']:,}",
        f"- Single global request feasible: {report['single_global_request_feasible']}",
        f"- Similarity review groups: {len(report['suggested_review_groups'])}",
        f"- Heterogeneous source candidates: {len(report['heterogeneous_cluster_candidates'])}",
        '', 'These groups are suggestions for manual review. Cosine similarity does not approve a merge.',
    ]
    baseline = report.get('pairwise_baseline')
    if baseline:
        lines.extend(['', '## Existing pairwise baseline', '',
                      f"- Canonical topics: {baseline['canonical_topics']}",
                      f"- Merged clusters: {baseline['accepted_merges']}",
                      f"- Recorded API requests: {baseline['api_requests']}",
                      f"- Estimated API cost: ${baseline['estimated_api_cost_usd']:.2f}"])
    lines.extend(['', '## Suggested groups to inspect', ''])
    for group in report['suggested_review_groups']:
        lines.append(f"### Clusters {', '.join(map(str, group['cluster_ids']))}")
        lines.append('')
        for cid, example in zip(group['cluster_ids'], group['examples']):
            lines.append(f'- {cid}: {example}')
        lines.append('')
    lines.extend(['## Potentially heterogeneous clusters', ''])
    for item in report['heterogeneous_cluster_candidates']:
        lines.append(f"- {item['cluster_id']}: {item['examples'][0]}")
    lines.append('')
    return '\n'.join(lines)


async def request_valid_global(runner, profiles, selected, args):
    payload = profile_payload(profiles, selected)
    payload['analysis_objective'] = args.analysis_objective
    input_tokens = estimate_tokens(payload)
    fallback = input_tokens > args.max_input_tokens or len(selected) * 180 > args.max_output_tokens
    async def request(stage, key, request_payload):
        return await runner.call(stage, key, request_payload, GLOBAL_PROMPT,
                                 GlobalResponse, lambda parsed: parsed.model_dump())
    if not fallback:
        proposal = await request('global', 'all', payload)
    else:
        jobs = grouped_payloads({cid: profiles[cid] for cid in selected},
                                args.max_input_tokens, args.max_output_tokens)
        portions = await runner.batches('global_category',
            [(key, {**profile_payload(profiles, ids), 'analysis_objective': args.analysis_objective})
             for key, ids in jobs], GLOBAL_PROMPT, GlobalResponse,
            lambda key, parsed: parsed.model_dump())
        for (_, ids), portion in zip(jobs, portions):
            errors = validate_global(portion, ids)
            if errors:
                raise ValueError(f'Category fallback response invalid for {ids}: {errors}')
        draft = {'canonical_topics': [topic for portion in portions for topic in portion['canonical_topics']],
                 'clusters_needing_split': [item for portion in portions for item in portion['clusters_needing_split']],
                 'clusters_needing_review': [item for portion in portions for item in portion['clusters_needing_review']]}
        compact_draft = [{key: topic[key] for key in ('canonical_name', 'definition',
                          'parent_category', 'source_cluster_ids', 'relevance_status')}
                         for topic in draft['canonical_topics']]
        reconciliation_payload = {'all_source_cluster_ids': selected, 'category_draft_topics': compact_draft,
                                  'category_split_flags': draft['clusters_needing_split'],
                                  'category_review_flags': draft['clusters_needing_review'],
                                  'analysis_objective': args.analysis_objective}
        if estimate_tokens(reconciliation_payload) > args.max_input_tokens:
            raise ValueError('Category fallback draft exceeds --max-input-tokens; increase the limit')
        if len(selected) * 180 > args.max_output_tokens:
            raise ValueError('Final reconciliation output exceeds --max-output-tokens; increase the limit')
        proposal = await request('global_reconciliation', 'all', reconciliation_payload)

    selected_profiles = {cid: profiles[cid] for cid in selected}
    errors = validate_global(proposal, selected, selected_profiles)
    repairs = 0
    while errors and repairs < args.max_repair_attempts:
        repair_payload = {'original_profiles': payload, 'previous_response': proposal,
                          'validation_errors': errors,
                          'instruction': ('Correct the listed errors using the original profile evidence. '
                                          'Reconsider reflexive needs_split flags: reserve them for multiple '
                                          'recurring unrelated issues. Assign a dominant coherent issue to a '
                                          'specific topic; preserve truly mixed clusters as needs_split and '
                                          'uncertain clusters as needs_review. Preserve valid distinctions.')}
        if estimate_tokens(repair_payload) > args.max_input_tokens:
            # The original profiles are already present in the first response.
            repair_payload.pop('original_profiles')
            repair_payload['expected_cluster_ids'] = selected
        proposal = await runner.call('global_repair', f'attempt-{repairs + 1}', repair_payload,
                                     GLOBAL_PROMPT, GlobalResponse, lambda parsed: parsed.model_dump())
        errors = validate_global(proposal, selected, selected_profiles)
        repairs += 1
    if errors:
        raise ValueError(f'Global refinement failed validation after {repairs} repair attempts: {errors}')
    return proposal, {'initial_input_tokens_estimate': input_tokens,
                      'category_fallback': fallback, 'repair_attempts': repairs}


async def verify_suspicious(runner, proposal, profiles, centroids, args):
    flagged = {str(i): semantic_flags(topic, profiles, centroids)
               for i, topic in enumerate(proposal['canonical_topics'])}
    flagged = {key: value for key, value in flagged.items() if value}
    if args.skip_verification:
        return flagged, {}, [], []
    jobs = []
    for key in flagged:
        topic = proposal['canonical_topics'][int(key)]
        members = [compact_profile(profiles[cid]) for cid in topic['source_cluster_ids']]
        jobs.append((key, {'proposed_topic': topic, 'flags': flagged[key],
                           'member_cluster_profiles': members}))
    def validate_group(key, parsed):
        result = parsed.model_dump()
        return {'parts': validate_verify(proposal['canonical_topics'][int(key)]['source_cluster_ids'], result)}
    responses = await runner.batches('verify_group', jobs, VERIFY_PROMPT, VerifyResponse, validate_group)
    verified = dict(zip((key for key, _ in jobs), responses))

    duplicate_pairs = duplicate_candidates(proposal['canonical_topics'], centroids,
                                           threshold=args.duplicate_threshold)
    duplicate_jobs = []
    for batch in core.chunks(duplicate_pairs, args.pair_batch_size):
        key = ','.join(f'{p["topic_a"]}:{p["topic_b"]}' for p in batch)
        payload = [{'topic_a': p['topic_a'], 'topic_b': p['topic_b'],
                    'cosine_similarity': round(p['similarity'], 4),
                    'topic_profile_a': proposal['canonical_topics'][int(p['topic_a'])],
                    'topic_profile_b': proposal['canonical_topics'][int(p['topic_b'])],
                    'examples_a': [text for cid in proposal['canonical_topics'][int(p['topic_a'])]['source_cluster_ids']
                                   for text in profiles[cid]['examples'][:2]][:8],
                    'examples_b': [text for cid in proposal['canonical_topics'][int(p['topic_b'])]['source_cluster_ids']
                                   for text in profiles[cid]['examples'][:2]][:8]}
                   for p in batch]
        duplicate_jobs.append((key, payload))
    def validate_duplicates(key, parsed):
        found = [item.model_dump() for item in parsed.decisions]
        expected = set(key.split(','))
        if len(found) != len(expected) or {f'{item["topic_a"]}:{item["topic_b"]}' for item in found} != expected:
            raise ValueError('Duplicate-topic verification omitted or changed a pair')
        return found
    batches = await runner.batches('verify_duplicates', duplicate_jobs,
        'Compare proposed canonical topics globally. Merge only identical underlying product experiences. '
        'Keep ad frequency, ad-free promises, ads despite Premium, queue add/remove, and shuffle modes distinct. '
        'For an equivalent pair, propose one concise specific name and definition. '
        'For other relationships, leave proposed_name and proposed_definition empty.',
        DuplicateBatch, validate_duplicates)
    duplicate_decisions = [item for batch in batches for item in batch]
    return flagged, verified, duplicate_pairs, duplicate_decisions


async def resolve_noise(runner, records, X, taxonomy, args):
    topics = [topic for topic in taxonomy['topics'] if topic['relevance_status'] == 'keep']
    if not topics:
        return []
    by_cluster = defaultdict(list)
    for i, row in enumerate(records):
        if row['aspect_cluster_id'] >= 0:
            by_cluster[row['aspect_cluster_id']].append(i)
    topic_centroids = {}
    for topic in topics:
        positions = [i for cid in topic['original_cluster_ids'] for i in by_cluster[cid]]
        vector = X[positions].mean(axis=0)
        topic_centroids[topic['topic_id']] = vector / np.linalg.norm(vector)
    ids = sorted(topic_centroids)
    matrix = np.stack([topic_centroids[tid] for tid in ids])
    by_tid = {topic['topic_id']: topic for topic in topics}
    candidates, noise_rows = {}, {}
    for i, row in enumerate(records):
        if row['aspect_cluster_id'] != -1:
            continue
        noise_rows[row['aspect_id']] = row
        scores = matrix @ X[i]
        choices = [(ids[j], float(scores[j])) for j in np.argsort(-scores)[:3]
                   if scores[j] >= args.noise_threshold]
        candidates[row['aspect_id']] = choices
    eligible = [key for key, choices in candidates.items() if choices]
    jobs = []
    for batch in core.chunks(eligible, args.noise_batch_size):
        payload = {'aspects': [{'aspect_id': key, 'description': noise_rows[key]['description'],
                    'polarity': noise_rows[key].get('polarity'),
                    'candidate_topics': [{'topic_id': tid, 'similarity': round(score, 4),
                        'name': by_tid[tid]['canonical_name'],
                        'definition': by_tid[tid]['definition'],
                        'examples': by_tid[tid]['representative_descriptions'][:3]}
                        for tid, score in candidates[key]]} for key in batch]}
        jobs.append((','.join(batch), payload))
    def validate_noise(key, parsed):
        options = {item: {tid for tid, _ in candidates[item]} for item in key.split(',')}
        return core.validate_noise_batch(key.split(','), options, parsed)
    batches = await runner.batches('noise_global', jobs, NOISE_PROMPT, core.NoiseBatch, validate_noise)
    return [item for batch in batches for item in batch]


def run_global(args, client=None):
    started = time.monotonic()
    if args.concurrency < 1 or args.retries < 0 or args.max_repair_attempts < 0:
        raise ValueError('Invalid concurrency, retry, or repair setting')
    if args.max_input_tokens < 100 or args.max_output_tokens < 180 or not 0 <= args.noise_threshold <= 1:
        raise ValueError('Invalid token budget or noise threshold')
    if args.max_cost_usd is not None and args.max_cost_usd <= 0:
        raise ValueError('--max-cost-usd must be positive')
    if args.max_clusters is not None and args.max_clusters < 1:
        raise ValueError('--max-clusters must be positive')
    source, output = args.input.expanduser().resolve(), args.output.expanduser().resolve()
    if source == output or source in output.parents or output in source.parents:
        raise ValueError('Input and output directories must be separate')
    assignments, records, X, reps, _, source_manifest, embedding_path = core.prepare_inputs(
        source, args.embedding_root)
    profiles, centroids = core.build_profiles(records, X, reps)
    selected = sorted(profiles)
    if args.max_clusters is not None and args.max_clusters < len(selected):
        suggested = core.candidate_pairs(profiles, centroids, args.similarity_threshold, args.neighbors)
        selected = core.choose_clusters(profiles, suggested, args.max_clusters)
    payload = profile_payload(profiles, selected)
    payload['analysis_objective'] = args.analysis_objective
    input_estimate = estimate_tokens(payload)
    fallback = input_estimate > args.max_input_tokens or len(selected) * 180 > args.max_output_tokens
    fallback_jobs = grouped_payloads({cid: profiles[cid] for cid in selected},
                                     args.max_input_tokens, args.max_output_tokens) if fallback else []
    review_groups, review_pairs = local_review_groups({cid: profiles[cid] for cid in selected},
                                                       centroids, threshold=args.review_threshold)
    heterogeneous = [{'cluster_id': cid, 'aspect_count': profiles[cid]['aspect_count'],
                      'category_distribution': profiles[cid]['category_distribution'],
                      'polarity_distribution': profiles[cid]['polarity_distribution'],
                      'examples': profiles[cid]['examples'][:5]}
                     for cid in selected if profiles[cid]['potentially_heterogeneous']]
    dry_report = {
        'strategy': 'global', 'model': args.model, 'source_aspects': len(records),
        'source_clusters': len(profiles), 'selected_cluster_ids': selected,
        'estimated_global_input_tokens': input_estimate,
        'estimated_global_output_tokens_upper_bound': len(selected) * 180,
        'single_global_request_feasible': not fallback,
        'maximum_split_fraction': MAX_SPLIT_FRACTION,
        'minimum_mapped_aspect_fraction': MIN_MAPPED_ASPECT_FRACTION,
        'category_fallback_requests': len(fallback_jobs),
        'suggested_review_groups': review_groups,
        'high_similarity_pairs': review_pairs,
        'heterogeneous_cluster_candidates': heterogeneous,
        'note': 'Similarity groups are review suggestions, never automatic merges.'}
    comparison = getattr(args, 'compare_to', None)
    if comparison is not None:
        prior_report = comparison.expanduser().resolve() / 'refinement_report.json'
        if not prior_report.is_file():
            raise ValueError(f'Missing comparison report: {prior_report}')
        dry_report['pairwise_baseline'] = {
            'source': str(prior_report),
            **json.loads(prior_report.read_text(encoding='utf-8'))}
    if args.dry_run:
        output.mkdir(parents=True, exist_ok=True)
        if (output / 'run_config.json').exists():
            raise ValueError('Paid output already exists; choose a separate --output for the dry run')
        core.atomic_json(output / 'dry_run_report.json', dry_report)
        core.atomic_json(output / 'cluster_profiles.json', list(profiles.values()))
        (output / 'dry_run_review.md').write_text(render_dry_review(dry_report), encoding='utf-8')
        print(json.dumps({key: value for key, value in dry_report.items()
                          if key not in {'selected_cluster_ids', 'suggested_review_groups',
                                         'high_similarity_pairs', 'heterogeneous_cluster_candidates'}}, indent=2))
        print(f'Suggested review groups: {len(review_groups)}; heterogeneous candidates: {len(heterogeneous)}')
        print(f'Dry-run report: {output / "dry_run_report.json"}')
        return dry_report

    config = {'strategy': 'global', 'prompt_version': GLOBAL_VERSION, 'model': args.model,
              'source': str(source), 'source_assignment_sha256': core.file_sha256(source / 'aspect_clusters.parquet'),
              'source_embedding_sha256': source_manifest.get('config', {}).get('source_sha256'),
              'embedding_root': str(embedding_path), 'analysis_objective': args.analysis_objective,
              'max_clusters': args.max_clusters, 'max_input_tokens': args.max_input_tokens,
              'max_output_tokens': args.max_output_tokens,
              'max_repair_attempts': args.max_repair_attempts,
              'skip_verification': args.skip_verification, 'duplicate_threshold': args.duplicate_threshold,
              'noise_threshold': args.noise_threshold, 'review_threshold': args.review_threshold,
              'pair_batch_size': args.pair_batch_size, 'noise_batch_size': args.noise_batch_size}
    output.mkdir(parents=True, exist_ok=True)
    config_path = output / 'run_config.json'
    if config_path.exists():
        if not args.resume:
            raise ValueError('Output exists. Use --resume or a new output directory.')
        if json.loads(config_path.read_text(encoding='utf-8')) != config:
            raise ValueError('Output checkpoint belongs to different inputs or settings')
    elif any(path.name not in {'dry_run_report.json', 'dry_run_review.md', 'cluster_profiles.json'}
             for path in output.iterdir()):
        raise ValueError('Output contains unrelated files without a run_config.json')
    else:
        core.atomic_json(config_path, config)
    saved, usage = core.load_checkpoint(output / 'checkpoint.jsonl')
    owns_client = client is None
    if client is None:
        from openai import AsyncOpenAI
        from extract_review_aspects import KEY_PLACEHOLDERS, load_api_key_from_env_file
        load_api_key_from_env_file()
        if not os.getenv('OPENAI_API_KEY') or os.getenv('OPENAI_API_KEY') in KEY_PLACEHOLDERS:
            raise ValueError('Set OPENAI_API_KEY in the project .env file')
        client = AsyncOpenAI(max_retries=0)

    async def execute():
        runner = core.PaidRunner(client, args, output / 'checkpoint.jsonl', saved, usage)
        try:
            proposal, global_meta = await request_valid_global(runner, profiles, selected, args)
            if len(selected) < len(profiles):
                proposal['clusters_needing_review'].extend(
                    {'cluster_id': cid, 'reason': 'Outside --max-clusters evaluation'}
                    for cid in sorted(set(profiles) - set(selected)))
            flagged, verified, duplicate_pairs, duplicate_decisions = await verify_suspicious(
                runner, proposal, profiles, centroids, args)
            taxonomy = assemble_taxonomy(proposal, profiles, flagged, verified, duplicate_decisions)
            # A limited evaluation keeps noise unresolved until all clusters are labeled.
            noise = [] if len(selected) < len(profiles) else await resolve_noise(
                runner, records, X, taxonomy, args)
            return proposal, global_meta, flagged, verified, duplicate_pairs, duplicate_decisions, taxonomy, noise
        finally:
            if owns_client:
                await client.close()

    proposal, global_meta, flagged, verified, dup_pairs, dup_decisions, taxonomy, noise = asyncio.run(execute())
    refined, mappings = map_aspects(assignments, taxonomy, noise)
    assigned_noise = sum(1 for row in refined.to_pylist() if row['aspect_cluster_id'] == -1 and row['topic_id'])
    report = {'strategy': 'global', 'source_aspects': len(records),
              'original_clusters': len(profiles), 'canonical_topics': len(taxonomy['topics']),
              'merged_clusters': sum(len(topic['original_cluster_ids']) - 1 for topic in taxonomy['topics']),
              'excluded_topics': sum(topic['relevance_status'] == 'exclude' for topic in taxonomy['topics']),
              'clusters_needing_split': len(taxonomy['clusters_needing_split']),
              'clusters_needing_review': len(taxonomy['clusters_needing_review']),
              'noise_resolved': assigned_noise,
              'noise_unresolved': sum(row['aspect_cluster_id'] == -1 for row in records) - assigned_noise,
              'api_requests': usage['requests'], 'input_tokens': usage['input_tokens'],
              'output_tokens': usage['output_tokens'],
              'estimated_api_cost_usd': round((usage['input_tokens'] * args.input_cost_per_million +
                                              usage['output_tokens'] * args.output_cost_per_million) / 1_000_000, 6),
              'model': args.model, 'prompt_version': GLOBAL_VERSION,
              'runtime_seconds': round(time.monotonic() - started, 3),
              'partial_evaluation': len(selected) < len(profiles)}
    validation_report = {'coverage_errors': [],
                         'global_request': global_meta,
                         'flagged_topics': flagged, 'verification_responses': verified,
                         'near_duplicate_candidates': dup_pairs,
                         'near_duplicate_decisions': dup_decisions}
    core.atomic_json(output / 'cluster_profiles.json', list(profiles.values()))
    core.atomic_json(output / 'global_refinement_response.json', proposal)
    core.atomic_json(output / 'validation_report.json', validation_report)
    core.atomic_json(output / 'canonical_topics.json', taxonomy)
    core.write_parquet(output / 'cluster_mapping.parquet', mappings, core.MAPPING_SCHEMA)
    pq.write_table(refined, output / 'refined_aspects.parquet')
    write_topic_catalog(output, taxonomy, refined)
    core.atomic_json(output / 'refinement_report.json', report)
    print(json.dumps(report, indent=2))
    return report
