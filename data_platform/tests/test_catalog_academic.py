"""Offline review/projection tests. They are not PostgreSQL publication proof."""
from copy import deepcopy
from dataclasses import asdict, replace
from decimal import Decimal
from functools import partial
import hashlib
import inspect
import json

import pytest

from data_platform.catalog.academic import compare_rankings, derive, method, project_candidates, project_legacy
from data_platform.catalog.adapter import SourceArchive, activate_prepared, prepare_batch, prepare_source
from data_platform.catalog.crosswalk import decide, review_batch
from data_platform.catalog.intake import load_selection

# Explicitly frozen v1 reproduction. Current lifecycle tests live in v2 tests.
review_batch = partial(review_batch, historical_v1=True)
decide = partial(decide, historical_v1=True)
prepare_batch = partial(prepare_batch, historical_v1=True)
prepare_source = partial(prepare_source, historical_v1=True)


def reviewed(identifier=35):
    return deepcopy(next(row for row in review_batch()['decisions'] if row['id'] == identifier))


def candidate(identifier=35):
    return next(row for row in load_selection().candidates if row.id == identifier)


def test_individual_classification_does_not_block_other_candidates():
    result = review_batch()
    assert result['batch_processed']
    assert result['approved'] + result['blocked'] == 22
    assert result['approved'] == 19
    assert {row['id'] for row in result['decisions'] if row['status'] == 'blocked_with_evidence'} == {48, 50, 53}
    assert result['activated'] == 0


@pytest.mark.parametrize('identifier', [35, 36, 37, 38, 43, 46, 51, 52])
def test_exact_trim_mechanical_evidence(identifier):
    decision = reviewed(identifier)
    assert decision['status'] == 'approved_for_activation'
    assert decision['review']['link_type'] == 'exact_trim_powertrain'
    assert decision['review']['pbev']['raw']['row_hash']


@pytest.mark.parametrize('identifier', [39, 40, 41, 44, 47, 49, 54])
def test_shared_powertrain_records_group_and_rejects_conflicting_consumption(identifier):
    review = reviewed(identifier)['review']
    assert 'shared_trims_as_published' in review
    assert review['shared_group_explanation']
    conflict = deepcopy(review['pbev'])
    conflict['fossil_city_km_l'] = '99'
    review['applicable_pbev_rows'].append(conflict)
    result = decide(candidate(identifier), review)
    assert result['status'] == 'blocked_with_evidence'
    assert 'CONFLICTING_CONSUMPTION_LINES' in result['blockers']


@pytest.mark.parametrize('identifier', [41, 42, 44, 55])
def test_only_versioned_aliases_are_accepted(identifier):
    review = reviewed(identifier)['review']
    assert review['alias_id']
    review['alias_id'] = 'unreviewed-similar-name'
    assert 'ALIAS_NOT_AUTHORIZED' in decide(candidate(identifier), review)['blockers']


@pytest.mark.parametrize('change,blocker', [
    ({'Combustivel': 'Gasolina'}, 'STRUCTURED_FUEL_CONFLICT'),
    ({'Modelo': 'KWID Zen 1.0 Flex 12V Aut.'}, 'TRANSMISSION_CONFLICT'),
    ({'Modelo': 'KWID Zen 1.6 Flex 12V Mec.'}, 'ENGINE_CONFLICT'),
    ({'Modelo': 'KWID Zen 1.0 Flex 16V Mec.'}, 'VALVE_COUNT_CONFLICT'),
])
def test_conflicting_mechanics_rejected(change, blocker):
    review = reviewed()['review']
    review['fipe'].update(change)
    assert blocker in decide(candidate(), review)['blockers']


@pytest.mark.parametrize('identifier', [40, 41, 45, 56])
def test_target_changes_are_explicit(identifier):
    decision = reviewed(identifier)
    assert decision['target_changed']
    assert decision['review']['target_change_reason']
    changed = deepcopy(decision['review'])
    changed['target_change_reason'] = ''
    assert 'TARGET_CHANGE_NOT_EXPLAINED' in decide(candidate(identifier), changed)['blockers']


@pytest.mark.parametrize('review', [None, {}, {'id': 35, 'fipe': None}])
def test_missing_review_is_individual_block(review):
    assert decide(candidate(), review)['status'] == 'blocked_with_evidence'


@pytest.mark.parametrize('value', [None, 0, -1, float('nan'), float('inf'), True])
def test_missing_or_invalid_price_never_becomes_zero(value):
    with pytest.raises(ValueError):
        derive(value)


def test_method_deterministic_parameters_and_confidence():
    result = derive('60000.00')
    assert result == derive(Decimal('60000.00'))
    assert result['values']['annual_maintenance_cost'] == Decimal('1500.00')
    assert result['values']['reliability_score'] == Decimal('50')
    assert result['classification'] == 'demonstrative'
    assert result['confidence'] < Decimal(method()['parameters']['observed_source_confidence'])
    assert 'collection_group' not in inspect.getsource(derive)
    assert 'brand' not in inspect.signature(derive).parameters
    assert result['parameter_sha256']


def test_uniform_method_preserves_legacy_and_divides_maintenance_once():
    from app.sample_data import VEHICLES
    from app.recommender import RecommendationProfile, calculate_vehicle_tco
    before = [asdict(row) for row in VEHICLES]
    result = project_legacy(VEHICLES)
    assert result['baseline_version'] == 'legacy-demo-v0'
    assert result['baseline'] == before == [asdict(row) for row in VEHICLES]
    profile = RecommendationProfile(100000, 5000, 'cidade')
    for vehicle in result['vehicles']:
        cost = calculate_vehicle_tco(vehicle, profile)
        assert cost['monthly_maintenance_cost'] == round(vehicle.annual_maintenance_cost / 12, 2)
        assert vehicle.use_cases == tuple(method()['neutral_use_cases'])


def test_preview_uses_same_method_and_never_persists():
    decisions = [row for row in review_batch()['decisions'] if row['status'] == 'approved_for_activation']
    projected = project_candidates(decisions)
    assert len(projected) == 19
    assert {row.id for row in projected}.isdisjoint(range(1, 35))
    for vehicle in projected:
        assert vehicle.annual_maintenance_cost == float(derive(vehicle.price)['values']['annual_maintenance_cost'])
        assert vehicle.reliability_score == 50
    with pytest.raises(ValueError):
        project_candidates([reviewed(48)])


class ObservationFixtureArchive:
    """Test-only isolated reader; real immutable snapshots are checked separately."""
    def __init__(self, decision):
        self.decision = decision

    def validate(self, review):
        assert review == self.decision['review']

    def bytes(self, _reference):
        return json.dumps(self.decision['review']['fipe'], ensure_ascii=False).encode()


def test_adapter_preserves_raw_payload_uses_real_bronze_and_silver_gates():
    decision = reviewed()
    plan = prepare_source(decision, ObservationFixtureArchive(decision))
    assert plan['status'] == 'prepared_not_published'
    assert plan['raw'].payload == decision['review']['fipe']
    assert plan['silver_candidate'].bronze.payload == plan['raw'].payload
    assert plan['silver_candidate'].mapping_status == 'matched'
    assert plan['silver_candidate'].price.price_amount == decision['observed']['price_brl']
    assert plan['normalization']['original_payload_preserved'] is True
    assert plan['silver_candidate'].bronze.fipe_raw_id == 0  # Explicitly NOT persisted.


def test_adapter_rejects_blocked_changed_and_duplicate_dossiers():
    with pytest.raises(ValueError, match='Blocked'):
        prepare_source(reviewed(48), None)
    good = reviewed()
    changed = deepcopy(good)
    changed['observed']['price_brl'] = 1
    with pytest.raises(ValueError, match='changed'):
        prepare_source(changed, None)
    with pytest.raises(ValueError, match='Duplicate'):
        prepare_batch([good, good], ObservationFixtureArchive(good))


def test_archive_detects_tampering_and_path_escape(tmp_path):
    content = b'{"public_fixture":true}'
    (tmp_path / 'fixture.json').write_bytes(content)
    archive = SourceArchive([tmp_path])
    reference = {'cache_file': 'fixture.json', 'sha256': hashlib.sha256(content).hexdigest()}
    assert archive.bytes(reference) == content
    with pytest.raises(ValueError):
        archive.bytes({**reference, 'sha256': '0' * 64})
    with pytest.raises(ValueError):
        archive.bytes({**reference, 'cache_file': '../fixture.json'})


def test_preparation_is_not_activation_or_publication():
    from sqlalchemy import create_engine
    with pytest.raises(ValueError, match='Operational activation disabled'):
        activate_prepared(create_engine('sqlite:///:memory:'), [], None, 'unused', dry_run=False)


def test_six_ranking_previews_have_exact_counts_and_explained_position_deltas():
    from app.sample_data import VEHICLES
    decisions = [row for row in review_batch()['decisions'] if row['status'] == 'approved_for_activation']
    result = compare_rankings(VEHICLES, decisions)
    assert set(result) == set(method()['neutral_use_cases'])
    for comparison in result.values():
        assert len(comparison['attribution']) == 53
        assert [stage['processing']['evaluated'] for stage in comparison['stages'].values()] == [34, 34, 53]
        for item in comparison['attribution']:
            assert item['expanded_position'] in range(1, 54)
            if item['id'] <= 34:
                assert item['legacy_position'] in range(1, 35)
                assert item['academic_34_position'] in range(1, 35)
                assert item['method_position_delta'] + item['expansion_position_delta'] == item['expanded_position'] - item['legacy_position']
