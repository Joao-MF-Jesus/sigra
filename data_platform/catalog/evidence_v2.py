"""Versioned availability layer; no mandatory-number DTO, persistence or HTTP.

The diagnostic uses an explicit observed field whitelist. Display identities and
selection strata never enter the score. No v1 imputation is imported.
"""
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import json
from pathlib import Path

from data_platform.catalog.contracts import FieldEvidence, EvidenceReference
from data_platform.catalog.crosswalk import review_batch

CONFIG_PATH = Path(__file__).with_name('academic_evidence_v2.json')
EXTRA_UNITS = {'consumption_highway': 'km/l', 'segment_level': 'level/5',
               'ipva_annual_brl': 'BRL/year', 'insurance_annual_brl': 'BRL/year'}


def configuration():
    return json.loads(CONFIG_PATH.read_text(encoding='utf-8'))


def decimal(value):
    if isinstance(value, (bool, float)):
        raise ValueError('Exact decimal input required')
    result = Decimal(value)
    if not result.is_finite():
        raise ValueError('Finite decimal required')
    return result


@dataclass(frozen=True)
class EvidenceVehicle:
    identifier: int
    label: str
    fields: dict[str, FieldEvidence]
    provenance: dict


def unavailable(unit):
    return FieldEvidence(value=None, unit=unit, kind='unavailable')


def blank_fields():
    units = {dim['field']: dim['unit'] for dim in configuration()['dimensions'].values()}
    return {name: unavailable(unit) for name, unit in {**units, **EXTRA_UNITS}.items()}


def usable(vehicle, name, unit=None):
    evidence = vehicle.fields.get(name)
    if evidence is None or evidence.kind != 'observed' or evidence.value is None:
        return False
    if unit is not None and evidence.unit != unit:
        raise ValueError('Evidence unit mismatch: ' + name)
    if evidence.value < 0 or (name in {'price_brl', 'consumption_city', 'consumption_highway'} and evidence.value <= 0):
        raise ValueError('Invalid observed measure: ' + name)
    if evidence.unit == 'score/100' and evidence.value > 100:
        raise ValueError('Invalid observed rubric score: ' + name)
    return True


def candidate_evidence(archive):
    """Only retained FIPE/PBEV observations; no category/manual score copying."""
    from data_platform.catalog.adapter import prepare_batch
    decisions = [row for row in review_batch()['decisions'] if row['status'] == 'identity_approved']
    prepare_batch(decisions, archive)  # Pinned review + immutable source validation.
    result = []
    for row in decisions:
        review = row['review']
        sources = review['source_references']
        refs = [EvidenceReference(source_url=source['url'], sha256=source['sha256'],
                                  locator='FIPE full response' if index == 0 else 'PBEV row ' + review['pbev']['raw']['row_hash'],
                                  collected_at=source['collected_at']) for index, source in enumerate(sources[:2])]
        fields = blank_fields()
        fields['price_brl'] = FieldEvidence(value=str(row['observed']['price_brl']), unit='BRL', kind='observed', references=(refs[0],))
        for field, observed in (('consumption_city', 'city_km_l'), ('consumption_highway', 'highway_km_l')):
            fields[field] = FieldEvidence(value=str(row['observed'][observed]), unit='km/l', kind='observed', references=(refs[1],))
        result.append(EvidenceVehicle(row['id'], review['commercial_description'], fields, {
            'identity_status': row['status'], 'fipe_code': review['fipe']['CodigoFipe'],
            'year_code': review['year_code'], 'price_reference_month': row['observed']['reference_month'],
            'human_approval_required': row['human_approval_required'], 'human_approval_status': row['human_approval_status'],
            'evidence_kind': 'cached_raw_observation', 'state_schema_version': row['state_schema_version'],
        }))
    return tuple(result)


def legacy_evidence(cache_path, expected_sha256):
    """Recorded FIPE replay only. Static sample prices and scores are not evidence.

    A missing/mismatched cache item remains unavailable instead of falling back
    to the sample. PBEV demo_fixture is not accepted as observed consumption.
    """
    from app.fipe import FIPE_REFERENCE_PROFILES
    from data_platform.catalog.intake import load_selection
    content = Path(cache_path).read_bytes()
    actual_sha = hashlib.sha256(content).hexdigest()
    if actual_sha != expected_sha256:
        raise ValueError('Legacy price cache changed')
    cache = json.loads(content, parse_float=Decimal)
    result = []
    for vehicle in load_selection().baseline:
        fields = blank_fields()
        expected = FIPE_REFERENCE_PROFILES[vehicle.id]
        entries = [row for row in cache if row.get('vehicle_id') == vehicle.id]
        provenance = {'evidence_kind': 'legacy_cache_replay', 'price_reference_month': None,
                      'consumption_reason': 'legacy sample/demo_fixture is not observed PBEV evidence',
                      'identity_status': 'existing_explicit_fipe_binding_not_reaudited',
                      'cache_sha256': actual_sha, 'excluded': 'all legacy demo scores, maintenance, depreciation, category and use_cases',
                      'expected_price_reference': {'fipe_code': expected.code, 'model': expected.model, 'year': expected.year_code},
                      'price_rejection_reasons': []}
        if len(entries) != 1:
            provenance['price_rejection_reasons'].append('PRICE_CACHE_MISSING_OR_AMBIGUOUS')
        if len(entries) == 1:
            row = entries[0]
            provenance['found_price_reference'] = {key: row.get(key) for key in ('code', 'year_code', 'model', 'reference_month')}
            checks = {'FIPE_CODE_MISMATCH': row.get('code') == expected.code,
                      'YEAR_CODE_MISMATCH': row.get('year_code') in {expected.year_code + '-1', expected.year_code + '-5'},
                      'PRICE_REFERENCE_DESCRIPTION_MISMATCH': row.get('model') == expected.model,
                      'LIVE_SOURCE_METADATA_MISSING': row.get('retrieval_status') == 'live' and bool(row.get('reference_month')) and bool(row.get('retrieved_at'))}
            provenance['price_rejection_reasons'] = [key for key, passed in checks.items() if not passed]
            if not provenance['price_rejection_reasons']:
                reference = EvidenceReference(source_url=row['source_url'], sha256=actual_sha,
                    locator=f'legacy FIPE cache vehicle_id={vehicle.id}; code={expected.code}; year_code={row["year_code"]}', collected_at=row['retrieved_at'])
                fields['price_brl'] = FieldEvidence(value=str(row['price']), unit='BRL', kind='observed', references=(reference,))
                provenance.update(price_reference_month=row['reference_month'], fipe_code=expected.code, year_code=row['year_code'])
        result.append(EvidenceVehicle(vehicle.id, f'{vehicle.brand} {vehicle.model} {vehicle.year}', fields, provenance))
    return tuple(result)


def monthly_cost_evidence(vehicle, scenario=None):
    config = configuration()
    scenario = scenario or config['scenario']
    km, fuel_price = decimal(scenario['monthly_km']), decimal(scenario['gasoline_brl_per_l'])
    if km < 0 or fuel_price <= 0 or scenario['cycle'] != 'urban':
        raise ValueError('Unsupported or invalid controlled scenario')
    quantum = decimal(config['precision']['money_quantum'])
    divisor = decimal(config['precision']['annual_to_monthly_divisor'])
    raw = {'fuel': km / vehicle.fields['consumption_city'].value * fuel_price if usable(vehicle, 'consumption_city', 'km/l') else None}
    derivations = {'fuel': {'formula': config['formulas']['monthly_fuel_brl'], 'inputs': {'monthly_km': km, 'gasoline_brl_per_l': fuel_price, 'consumption_city': vehicle.fields.get('consumption_city')}, 'input_units': ['km/month', 'BRL/l', 'km/l']}}
    for component, field in (('maintenance', 'maintenance_annual_brl'), ('ipva', 'ipva_annual_brl'), ('insurance', 'insurance_annual_brl'), ('depreciation', 'depreciation_annual_brl')):
        evidence = vehicle.fields.get(field)
        raw[component] = evidence.value / divisor if usable(vehicle, field, 'BRL/year') else None
        derivations[component] = {'formula': field + ' / 12 exactly once', 'inputs': {field: evidence}, 'input_units': ['BRL/year']}
    missing = [key for key, value in raw.items() if value is None]
    total = sum(raw.values(), Decimal(0)) if not missing else None
    return {'monthly_tco_brl': total.quantize(quantum, rounding=ROUND_HALF_UP) if total is not None else None,
            'status': 'incomplete' if missing else 'complete', 'unit': 'BRL/month', 'missing_components': missing,
            'components_brl_per_month': {key: value.quantize(quantum, rounding=ROUND_HALF_UP) if value is not None else None for key, value in raw.items()},
            'monthly_viable': total <= decimal(scenario['monthly_budget_brl']) if total is not None else None,
            'method_version': config['method_version'], 'rounding': config['precision'], 'derivations': derivations,
            'limitation': 'Available components are not a complete TCO; missing is not zero'}


def validated_weights(weights, dimensions):
    if set(weights) != set(dimensions):
        raise ValueError('Explicit weight for every dimension is required')
    values = {name: decimal(weights[name]) for name in dimensions}
    if any(value < 0 for value in values.values()) or sum(values.values()) <= 0:
        raise ValueError('Weights must be nonnegative and have a positive sum')
    return values


def score_cohort(vehicles, profile, weights=None):
    """Diagnostic only. Equal scoring evidence/units are required for comparison."""
    config = configuration()
    if profile not in config['profile_requirements']:
        raise ValueError('Unknown profile')
    identifiers = [vehicle.identifier for vehicle in vehicles]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError('Duplicate vehicle identity in scoring cohort')
    dims = config['dimensions']
    weights = validated_weights(config['reference_weights'] if weights is None else weights, dims)
    ranges = {}
    for name, dim in dims.items():
        values = [vehicle.fields[dim['field']].value for vehicle in vehicles if usable(vehicle, dim['field'], dim['unit'])]
        ranges[name] = (min(values), max(values)) if values and min(values) != max(values) else None
    months = {vehicle.provenance.get('price_reference_month') for vehicle in vehicles if usable(vehicle, 'price_brl', 'BRL')}
    temporal_block = len(months) > 1 or None in months
    records = []
    for vehicle in vehicles:
        available = [key for key, dim in dims.items() if usable(vehicle, dim['field'], dim['unit'])]
        used = [] if temporal_block else [key for key in available if ranges[key] is not None and weights[key] > 0]
        effective = {key: Decimal(0) for key in dims}
        denominator = sum((weights[key] for key in used), Decimal(0))
        if denominator:
            for key in used[:-1]:
                effective[key] = (weights[key] / denominator).quantize(decimal(config['precision']['weight_quantum']), rounding=ROUND_HALF_UP)
            effective[used[-1]] = Decimal(1) - sum(effective.values())
        criteria = {}; contributions = {}
        for key in used:
            low, high = ranges[key]; value = vehicle.fields[dims[key]['field']].value
            criteria[key] = Decimal(100) * ((value - low) if dims[key]['direction'] == 'higher' else (high - value)) / (high - low)
            contributions[key] = (criteria[key] * effective[key]).quantize(decimal(config['precision']['score_quantum']), rounding=ROUND_HALF_UP)
        missing = [key for key in dims if key not in available]
        required_missing = [field for field in config['profile_requirements'][profile] if not usable(vehicle, field)]
        cost = monthly_cost_evidence(vehicle)
        score = sum(contributions.values(), Decimal(0)) if used and not temporal_block else None
        records.append({'id': vehicle.identifier, 'label': vehicle.label, 'preview_score': score,
            'final_recommendation_score': None, 'monthly_tco': cost, 'criteria': criteria,
            'contributions': contributions, 'original_weights': weights, 'effective_weights': effective,
            'available_criteria': available, 'missing_criteria': missing, 'non_discriminating_criteria': [key for key in available if ranges[key] is None],
            'coverage': {'weighted_evidence_fraction': sum((weights[key] for key in available), Decimal(0)) / sum(weights.values()),
                         'weighted_discriminating_fraction': denominator / sum(weights.values()), 'not_statistical_confidence': True},
            'confidence': {'value': None, 'status': 'not_calibrated', 'provenance': vehicle.provenance},
            'profile_required_missing': required_missing, 'methodology_ready': False,
            'evidence_fields': vehicle.fields, 'gate_reasons': ['UNVALIDATED_PREFERENCE_RUBRIC'] +
                (['LEGACY_PRICE_BINDING_NOT_REAUDITED'] if vehicle.provenance.get('evidence_kind') == 'legacy_cache_replay' else []) +
                (['PROFILE_EVIDENCE_INCOMPLETE'] if required_missing else []) +
                (['MONTHLY_TCO_INCOMPLETE'] if cost['monthly_tco_brl'] is None else []) +
                (['PRICE_REFERENCE_MONTH_MISMATCH'] if temporal_block else [])})
    ranked = sorted((row for row in records if row['preview_score'] is not None), key=lambda row: (-row['preview_score'], row['id']))
    top10 = ranked[:10]
    boundary_ids = [row['id'] for row in ranked if top10 and row['preview_score'] >= top10[-1]['preview_score']]
    return {'version': config['method_version'], 'profile': profile, 'status': 'blocked_for_recommendation',
            'comparison_scope': 'same observed subset only; not total suitability',
            'temporal_comparison_blocked': temporal_block, 'price_reference_months': sorted(month for month in months if month),
            'records': records, 'ranking': ranked, 'top10': top10, 'top10_boundary_ids': boundary_ids,
            'unranked_ids': [row['id'] for row in records if row['preview_score'] is None],
            'tie_rule': 'ID is a deterministic display ordering ONLY; ordinal similarity uses score ties, not IDs',
            'methodology_ready': 0}
