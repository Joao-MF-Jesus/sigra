"""Offline v2 diagnostics and historical reproduction, not publication proof."""
from copy import deepcopy
from dataclasses import replace
from decimal import Decimal
import hashlib
import json
from pathlib import Path

import pytest

from data_platform.catalog.academic import compare_rankings, derive, method
from data_platform.catalog.activation import activate_catalog, build_manifest
from data_platform.catalog.adapter import prepare_source
from data_platform.catalog.contracts import EvidenceReference, FieldEvidence
from data_platform.catalog.crosswalk import fingerprint, review_batch
from data_platform.catalog.evidence_analysis import analyze_cohort, change_control, sensitivity, similarity
from data_platform.catalog.evidence_v2 import EvidenceVehicle, blank_fields, configuration, legacy_evidence, monthly_cost_evidence, score_cohort
from data_platform.catalog.readiness import CatalogStage, require_operational_readiness


REF = EvidenceReference(source_url='https://example.org/fixture', sha256='a'*64,
                        locator='synthetic unit test only', collected_at='2026-09-09T00:00:00+00:00')


def observed(value, unit):
    return FieldEvidence(value=str(value), unit=unit, kind='observed', references=(REF,))


def vehicle(identifier, price=None, consumption=None, **others):
    fields = blank_fields()
    if price is not None:
        fields['price_brl'] = observed(price, 'BRL')
    if consumption is not None:
        fields['consumption_city'] = observed(consumption, 'km/l')
    for key, value in others.items():
        fields[key] = value
    return EvidenceVehicle(identifier, 'fixture only', fields, {'price_reference_month': 'setembro de 2026'})


def pair():
    return (vehicle(1, 80000, 20), vehicle(2, 40000, 10))


def test_current_identity_is_not_activation_or_methodology():
    result = review_batch()
    assert result['counts'] == {stage.value: 19 if stage is CatalogStage.IDENTITY else 0 for stage in CatalogStage}
    assert result['blocked'] == 3
    for row in result['decisions']:
        assert 'academic' not in row and not row['activated']
        assert row['status'] in {'identity_approved', 'blocked_with_evidence'}
        with pytest.raises(ValueError):
            require_operational_readiness(row)
    assert {row['id'] for row in result['decisions'] if row['human_approval_required']} == {40, 41, 45, 56}


def test_identity_does_not_execute_demo_imputation(monkeypatch):
    def forbidden(*args):
        raise AssertionError('Identity must not use academic demo formulas')
    monkeypatch.setattr('data_platform.catalog.crosswalk.derive', forbidden)
    assert review_batch()['counts']['identity_approved'] == 19


def test_default_adapter_rejects_historical_activation_label():
    old = next(row for row in review_batch(historical_v1=True)['decisions'] if row['id'] == 35)
    with pytest.raises(ValueError, match='Blocked'):
        prepare_source(old, None)
    current = next(row for row in review_batch()['decisions'] if row['id'] == 35)
    class Archive:
        def validate(self, review): assert review == current['review']
        def bytes(self, reference): return json.dumps(current['review']['fipe'], ensure_ascii=False).encode()
    assert prepare_source(current, Archive())['status'] == 'prepared_not_published'
    with pytest.raises(ValueError, match='disabled'):
        activate_catalog(None, [current], None, None)
    with pytest.raises(ValueError, match='historical only'):
        build_manifest(None, [current], None)


def test_forged_later_state_flags_cannot_authorize_operational_activation():
    row = deepcopy(review_batch()['decisions'][0])
    row['gates'] = {stage.value: True for stage in CatalogStage}
    with pytest.raises(ValueError, match='disabled'):
        require_operational_readiness(row)


def test_historical_v1_results_are_identical_and_explicit():
    from app.sample_data import VEHICLES
    old = review_batch(historical_v1=True)
    assert fingerprint(old) == 'e4f8e4dde136b8999542c0d127f6eb47c1b95f16e8937bb72eff1987a6a7f92e'
    ranking = compare_rankings(VEHICLES, [row for row in old['decisions'] if row['status'] == 'approved_for_activation'])
    assert fingerprint(ranking) == '11476a59acc18839aa7dca730b428e1b0bededee845008644c32a525c8383454'
    assert derive('60000')['values']['annual_maintenance_cost'] == Decimal('1500.00')
    assert method()['method_version'] == 'academic-demo-v1'


def test_change_control_records_approved_substitutions_and_preserves_qq_hold():
    control = change_control()
    assert {row['candidate_id'] for row in control['changes']} == {40, 41, 45, 56}
    assert all(row['human_approval_required'] and row['sources'] for row in control['changes'])
    by_id = {row['candidate_id']: row for row in control['changes']}
    assert {identifier for identifier, row in by_id.items() if row['human_approval_status'] == 'human_approved'} == {40, 45, 56}
    assert all(by_id[identifier]['approval_receipt']['decision'] == 'human_approved' for identifier in (40, 45, 56))
    assert all(by_id[identifier]['justification'] for identifier in (40, 45, 56))
    assert all(by_id[identifier]['approval_receipt']['recorded_at'] == '2026-09-11' for identifier in (40, 45, 56))
    qq = next(row for row in control['changes'] if row['candidate_id'] == 41)
    assert qq['human_approval_status'] == 'pending' and 'approval_receipt' not in qq
    assert qq['silver_publication_status'] == 'blocked_pending_human_decision'
    assert qq['gold_publishable'] is False and '2018 to 2017' in qq['decision_required']
    assert 'Flex' in qq['fipe_description'] and qq['structured_fipe_fuel'] == 'Gasolina' and qq['pbev_fuel'] == 'gasoline'


def test_missing_evidence_never_becomes_neutral_or_zero():
    result = score_cohort([vehicle(1)], 'cidade')['records'][0]
    assert result['preview_score'] is None and result['monthly_tco']['monthly_tco_brl'] is None
    assert result['criteria'] == {} and result['contributions'] == {}
    assert all(field.value is None for field in result['evidence_fields'].values())
    assert result['evidence_fields']['segment_level'].value is None
    assert sum(result['effective_weights'].values()) == 0
    assert result['confidence']['value'] is None
    assert result['monthly_tco']['monthly_viable'] is None


def test_effective_weights_and_contributions_reconcile():
    result = score_cohort(pair(), 'cidade')
    for row in result['records']:
        assert sum(row['effective_weights'].values()) == 1
        assert row['effective_weights']['purchase_price'] == row['effective_weights']['consumption'] == Decimal('.5')
        assert sum(row['contributions'].values()) == row['preview_score']
        assert row['coverage']['weighted_evidence_fraction'] == Decimal(2) / 9
        assert row['preview_score'] == 50  # Real tie between observed normalized values, NOT an imputation.
        assert row['confidence']['value'] is None and not row['methodology_ready']


def test_doubling_consumption_weight_improves_relative_margin_of_more_efficient_vehicle():
    weights = configuration()['reference_weights']
    before = score_cohort(pair(), 'cidade')['records']
    changed = {**weights, 'consumption': '2'}
    after = score_cohort(pair(), 'cidade', changed)['records']
    assert after[0]['preview_score'] > before[0]['preview_score']
    assert after[0]['preview_score'] - after[1]['preview_score'] > before[0]['preview_score'] - before[1]['preview_score']


def test_unavailable_space_weight_cannot_change_score_or_effective_available_weights():
    before = score_cohort(pair(), 'familia')['records']
    weights = {**configuration()['reference_weights'], 'space': '999'}
    after = score_cohort(pair(), 'familia', weights)['records']
    for a, b in zip(before, after):
        assert a['preview_score'] == b['preview_score'] and a['effective_weights'] == b['effective_weights']
        assert a['coverage'] != b['coverage']  # Explicit coverage changes; vehicle values do not.


def test_space_weight_only_changes_with_observed_capacity():
    pool = (vehicle(1, 80000, 20, cargo_l=observed('600', 'l')), vehicle(2, 40000, 10, cargo_l=observed('200', 'l')))
    before = score_cohort(pool, 'familia')['records']
    after = score_cohort(pool, 'familia', {**configuration()['reference_weights'], 'space': '2'})['records']
    assert after[0]['preview_score'] > before[0]['preview_score']
    assert after[1]['preview_score'] < before[1]['preview_score']


def test_demo_field_is_excluded_even_when_numeric():
    base = pair()
    fields = {**base[0].fields, 'reliability': FieldEvidence(value='50', unit='score/100', kind='demonstrative', references=(REF,))}
    altered = (replace(base[0], fields=fields), base[1])
    result = score_cohort(altered, 'cidade')['records'][0]
    assert 'reliability' in result['missing_criteria'] and 'reliability' not in result['criteria']


def test_group_brand_labels_do_not_influence_scores():
    base = pair()
    changed = tuple(replace(v, label='arbitrary desired name', provenance={**v.provenance, 'collection_group': 'SUV', 'brand': 'arbitrary', 'expected_position': 1}) for v in base)
    a, b = score_cohort(base, 'cidade'), score_cohort(changed, 'cidade')
    assert [(r['id'], r['preview_score']) for r in a['ranking']] == [(r['id'], r['preview_score']) for r in b['ranking']]


def test_determinism_and_constant_dimension_not_imputed():
    pool = (vehicle(1, 60000, 20), vehicle(2, 60000, 10))
    a = score_cohort(pool, 'cidade')
    assert a == score_cohort(pool, 'cidade')
    for row in a['records']:
        assert row['non_discriminating_criteria'] == ['purchase_price']
        assert 'purchase_price' not in row['criteria']
        assert row['effective_weights']['consumption'] == 1


def test_tco_requires_all_observed_components_and_divides_annual_once():
    partial = monthly_cost_evidence(vehicle(1, 60000, 10, maintenance_annual_brl=observed('1200', 'BRL/year')))
    assert partial['components_brl_per_month']['maintenance'] == 100
    assert partial['components_brl_per_month']['fuel'] == 600
    assert partial['monthly_tco_brl'] is None
    full = monthly_cost_evidence(vehicle(1, 60000, 10, maintenance_annual_brl=observed('1200', 'BRL/year'),
        ipva_annual_brl=observed('1200', 'BRL/year'), insurance_annual_brl=observed('1200', 'BRL/year'), depreciation_annual_brl=observed('1200', 'BRL/year')))
    assert full['monthly_tco_brl'] == 1000 and full['monthly_viable'] is True


def test_units_and_unsafe_numeric_inputs_are_rejected():
    with pytest.raises(ValueError, match='unit mismatch'):
        monthly_cost_evidence(vehicle(1, 60000, 10, maintenance_annual_brl=observed('100', 'BRL/month')))
    for bad in ('NaN', '-1', True, 0.1):
        with pytest.raises(ValueError):
            score_cohort(pair(), 'cidade', {**configuration()['reference_weights'], 'space': bad})


def test_mixed_months_block_joint_preview_not_silently_compare():
    pool = list(pair())
    pool[1] = replace(pool[1], provenance={'price_reference_month': 'julho de 2026'})
    result = score_cohort(pool, 'cidade')
    assert result['temporal_comparison_blocked'] and result['top10'] == []
    assert result['unranked_ids'] == [1, 2]
    assert all(not row['contributions'] and sum(row['effective_weights'].values()) == 0 for row in result['records'])


def test_jaccard_and_kendall_direction_and_ties():
    def result(scores):
        rows = [{'id': i, 'preview_score': Decimal(str(score))} for i, score in enumerate(scores)]
        return {'ranking': rows, 'top10_boundary_ids': list(range(len(rows)))}
    a = result([3, 2, 1]); reverse = result([1, 2, 3])
    assert similarity(a, a)['kendall_tau_b'] == 1
    assert similarity(a, reverse)['kendall_tau_b'] == -1
    assert similarity(a, reverse)['jaccard_top10'] == 1
    tied = result([1, 1, 1])
    assert similarity(tied, tied)['kendall_tau_b'] is None
    assert similarity(a, result([]))['jaccard_top10'] is None


def test_collapse_diagnosed_not_fixed_by_artificial_profile_variation():
    pool = (vehicle(1, 80000, 20), vehicle(2, 40000, 12), vehicle(3, 60000, 10))
    result = analyze_cohort(pool)
    assert result['gate']['profile_collapse']
    assert result['gate']['methodology_ready'] == 0
    assert len(result['profiles']) == 6
    assert all(result['gate']['missing_attributes_by_profile'].values())
    missing_space = sensitivity(pool, 'familia', result['profiles']['familia'])['space']
    assert missing_space['available_vehicles'] == 0
    assert all(row['delta'] == 0 for row in missing_space['deltas'])


def test_legacy_cache_mismatch_never_falls_back_to_sample(tmp_path):
    cache = tmp_path / 'cache.json'
    cache.write_text('[]', encoding='utf-8')
    rows = legacy_evidence(cache, hashlib.sha256(cache.read_bytes()).hexdigest())
    assert len(rows) == 34
    assert all(field.value is None for row in rows for field in row.fields.values())
    with pytest.raises(ValueError, match='changed'):
        legacy_evidence(cache, '0' * 64)
