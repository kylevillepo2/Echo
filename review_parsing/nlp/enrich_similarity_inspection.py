#!/usr/bin/env python3
"""Join inspection predictions to readable topic names and definitions."""
import argparse
import csv
import json
import os
from pathlib import Path


def enrich_rows(rows, catalog):
    def names(ids):
        return '\n'.join(catalog[tid]['canonical_name'] for tid in ids) or 'No tags'

    result = []
    for row in rows:
        assigned = json.loads(row['predicted_topic_ids'])
        reference = json.loads(row['true_topic_ids'])
        extra = json.loads(row['false_positive_topics'])
        missed = json.loads(row['false_negative_topics'])
        scores = json.loads(row['similarity_scores'])
        unknown = (set(assigned + reference + extra + missed) | set(scores)) - set(catalog)
        if unknown:
            raise ValueError(f'Unknown topic IDs for {row["review_key"]}: {sorted(unknown)}')
        if set(assigned) - set(scores):
            raise ValueError('Assigned tag score missing from inspection data')
        readable = {
            'review_text': row['review_text'],
            'assigned_tags': names(assigned),
            'assigned_tag_scores': '\n'.join(f"{catalog[tid]['canonical_name']}: {scores[tid]:.4f}" for tid in assigned) or 'No tags',
            'assigned_tag_definitions': '\n\n'.join(f"{catalog[tid]['canonical_name']}: {catalog[tid]['definition']}" for tid in assigned) or 'No tags',
            'earlier_llm_tags_not_human_verified': names(reference),
            'earlier_llm_tag_definitions': '\n\n'.join(f"{catalog[tid]['canonical_name']}: {catalog[tid]['definition']}" for tid in reference) or 'No tags',
            'extra_tags_vs_earlier_llm': names(extra) if extra else 'None',
            'missed_tags_vs_earlier_llm': names(missed) if missed else 'None',
            'human_verdict': row.get('human_verdict', ''),
            'human_notes': row.get('human_notes', ''),
            'top_candidate_scores_including_unassigned': '\n'.join(f"{catalog[tid]['canonical_name']}: {float(s):.4f}" for tid, s in scores.items()),
            'review_key': row['review_key'],
        }
        # Keep original IDs, exact score JSON, inspection reasons, and label provenance.
        result.append({**readable, **{k: v for k, v in row.items() if k not in readable}})
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--inspection', type=Path, required=True)
    p.add_argument('--catalog', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    with args.inspection.open(newline='', encoding='utf-8-sig') as f:
        rows = list(csv.DictReader(f))
    with args.catalog.open(newline='', encoding='utf-8-sig') as f:
        topics = list(csv.DictReader(f))
    catalog = {t['topic_id']: t for t in topics}
    if len(catalog) != len(topics):
        raise ValueError('Duplicate topic IDs in catalog')
    merged = enrich_rows(rows, catalog)
    if not merged:
        raise ValueError('Inspection file has no rows')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temp = args.output.with_name(args.output.name + '.tmp')
    with temp.open('w', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=list(merged[0]))
        writer.writeheader()
        writer.writerows(merged)
    with temp.open(newline='', encoding='utf-8-sig') as f:
        verified = list(csv.DictReader(f))
    assert len(verified) == len(rows)
    for original, output in zip(rows, verified):
        assert all(output[k] == v for k, v in original.items())
    os.replace(temp, args.output)
    print(f'Merged {len(merged)} reviews with readable topic names: {args.output}')


if __name__ == '__main__':
    main()
