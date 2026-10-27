"""Reproducible comparisons; do not demand six different rankings."""
from decimal import Decimal
from datetime import date
from itertools import combinations
import json
from pathlib import Path

from data_platform.catalog.crosswalk import review_batch, fingerprint
from data_platform.catalog.evidence_v2 import configuration, decimal, score_cohort


def change_control():
    control = json.loads(Path(__file__).with_name('change_control_v2.json').read_text(encoding='utf-8'))
    decisions = {row['id']: row for row in review_batch()['decisions']}
    result = []
    for change in control['changes']:
        row = decisions[change['candidate_id']]; review = row['review']
        if change['original'] != row['original'] or change['proposed'] != {'version': review['approved_version'], 'year': review['approved_year']}:
            raise ValueError('Change-control target differs from immutable review')
        if change['human_approval_required'] is not True or change['human_approval_status'] not in {'pending', 'human_approved'}:
            raise ValueError('Invalid human approval state')
        receipt = change.get('approval_receipt')
        if change['human_approval_status'] == 'human_approved':
            if not isinstance(receipt, dict) or receipt.get('decision') != 'human_approved':
                raise ValueError('Approved substitution requires an explicit receipt')
            if not isinstance(change.get('justification'), str) or not change['justification'].strip():
                raise ValueError('Human approval justification is required')
            if not all(isinstance(receipt.get(key), str) and receipt[key].strip()
                       for key in ('approved_by', 'recorded_at', 'authorization_reference', 'scope')):
                raise ValueError('Human approval receipt is incomplete')
            date.fromisoformat(receipt['recorded_at'])
        elif receipt is not None:
            raise ValueError('Pending substitution cannot carry an approval receipt')
        result.append({**change, 'reason': review['target_change_reason'], 'sources': review['source_references'],
                       'review_fingerprint': fingerprint(review), 'fipe_description': review['fipe']['Modelo'],
                       'structured_fipe_fuel': review['fipe']['Combustivel'], 'pbev_fuel': review['pbev']['fuel_type'],
                       'sources_exhaustive_family_inventory_sha256': review.get('family_inventory_sha256')})
    if {row['candidate_id'] for row in result} != {40, 41, 45, 56}:
        raise ValueError('Unexpected substitution inventory')
    return {'version': control['schema_version'], 'changes': result}


def similarity(left, right):
    a = {row['id']: row['preview_score'] for row in left['ranking']}
    b = {row['id']: row['preview_score'] for row in right['ranking']}
    common = sorted(a.keys() & b.keys())
    top_left, top_right = set(left['top10_boundary_ids']), set(right['top10_boundary_ids'])
    if not a or not b:
        return {'jaccard_top10': None, 'kendall_tau_b': None, 'common_scored': 0, 'reason': 'ranking unavailable, not zero similarity'}
    jaccard = Decimal(len(top_left & top_right)) / Decimal(len(top_left | top_right))
    concordant = discordant = ties_left = ties_right = 0
    for i, j in combinations(common, 2):
        x, y = a[i] - a[j], b[i] - b[j]
        if x == 0 and y == 0:
            continue
        if x == 0:
            ties_left += 1
        elif y == 0:
            ties_right += 1
        elif (x > 0) == (y > 0):
            concordant += 1
        else:
            discordant += 1
    denominator = Decimal((concordant + discordant + ties_left) * (concordant + discordant + ties_right)).sqrt()
    tau = Decimal(concordant - discordant) / denominator if denominator else None
    return {'jaccard_top10': jaccard, 'kendall_tau_b': tau, 'common_scored': len(common),
            'concordant': concordant, 'discordant': discordant, 'ties_left_only': ties_left, 'ties_right_only': ties_right,
            'scope': 'tau-b: common scored IDs with score ties; Jaccard: boundary-tie-expanded top10'}


def sensitivity(vehicles, profile, baseline):
    config = configuration(); weights = config['reference_weights']; result = {}
    before = {row['id']: row for row in baseline['records']}
    for dimension in weights:
        changed = {key: decimal(value) for key, value in weights.items()}
        changed[dimension] *= Decimal(2)
        after = score_cohort(vehicles, profile, changed)
        result[dimension] = {'perturbation': 'original weight x2; unchanged inputs/cohort; not fitted',
            'similarity': similarity(baseline, after),
            'deltas': [{
                'id': row['id'], 'before': before[row['id']]['preview_score'], 'after': row['preview_score'],
                'delta': row['preview_score'] - before[row['id']]['preview_score']
                    if row['preview_score'] is not None and before[row['id']]['preview_score'] is not None else None,
                'effective_weight_before': before[row['id']]['effective_weights'][dimension],
                'effective_weight_after': row['effective_weights'][dimension],
            } for row in after['records']],
            'available_vehicles': sum(dimension in row['available_criteria'] for row in after['records'])}
    return result


def analyze_cohort(vehicles):
    profiles = {profile: score_cohort(vehicles, profile) for profile in configuration()['profile_requirements']}
    matrix = {a: {b: similarity(left, right) for b, right in profiles.items()} for a, left in profiles.items()}
    signatures = {tuple(row['id'] for row in result['top10']) for result in profiles.values() if result['top10']}
    complete_tco = sum(row['monthly_tco']['status'] == 'complete' for row in next(iter(profiles.values()))['records'])
    return {'count': len(vehicles), 'profiles': profiles, 'similarity_matrix': matrix,
            'sensitivity': {name: sensitivity(vehicles, name, preview) for name, preview in profiles.items()},
            'gate': {'status': 'BLOCKED_INSUFFICIENT_EVIDENCE', 'methodology_ready': 0,
                     'distinct_top10': len(signatures), 'profile_collapse': len(signatures) == 1,
                     'complete_tco_count': complete_tco,
                     'explanation': 'Only available evidence enters the diagnostic. Profile-specific attributes and validated preference rubrics are absent; identical observed inputs/weights legitimately give identical previews. Diversity is not an acceptance target.',
                     'missing_attributes_by_profile': {name: sorted({field for row in preview['records'] for field in row['profile_required_missing']}) for name, preview in profiles.items()}}}
