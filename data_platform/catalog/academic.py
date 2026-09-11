"""Explicit academic projection; no database, network, startup or legacy mutation."""
from dataclasses import asdict, replace
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import json
from pathlib import Path

PARAMETER_PATH = Path(__file__).with_name('academic_demo_v1.json')
SCORE_FIELDS = ('reliability_score', 'parts_availability_score', 'comfort_score', 'space_score', 'safety_score', 'urban_score', 'road_score', 'family_score', 'app_score')


def method():
    return json.loads(PARAMETER_PATH.read_text(encoding='utf-8'))


def derive(price_brl):
    """Only the recorded price is an input; no model, brand or collection group."""
    if price_brl is None or isinstance(price_brl, bool):
        raise ValueError('academic maintenance requires a recorded price')
    price = Decimal(str(price_brl))
    if not price.is_finite() or price <= 0:
        raise ValueError('academic maintenance requires a finite positive price')
    specification = method()
    p = {key:Decimal(value) for key,value in specification['parameters'].items()}
    values = {field:p['neutral_score'] for field in SCORE_FIELDS}
    values.update(annual_maintenance_cost=(price*p['annual_maintenance_price_fraction']).quantize(p['money_quantum'],rounding=ROUND_HALF_UP), depreciation_rate=p['annual_depreciation_percent'],segment_level=int(p['neutral_segment_level']))
    return {
        'method_version':specification['method_version'],
        'parameter_sha256':hashlib.sha256(PARAMETER_PATH.read_bytes()).hexdigest(),
        'classification':'demonstrative', 'confidence':p['demonstrative_confidence'],
        'inputs':{'price_brl':price}, 'values':values,
        'formulas':specification['formulas'], 'parameters':specification['parameters'],
        'label':specification['label'], 'limitations':specification['limitations'],
    }


def project_legacy(vehicles):
    """Return a new experimental dataset; never update the original records."""
    baseline = [asdict(vehicle) for vehicle in vehicles]
    projected = []
    evidence = []
    for vehicle in vehicles:
        calculation = derive(vehicle.price)
        # The unchanged legacy recommender accepts native real numbers, not
        # Decimal; conversion happens only at its existing DTO boundary.
        values = {key:int(value) if key=='segment_level' else float(value) for key,value in calculation['values'].items()}
        projected.append(replace(vehicle, **values, use_cases=tuple(method()['neutral_use_cases'])))
        evidence.append({'id':vehicle.id, 'original_input_provenance':'legacy-demo-v0', **calculation})
    assert baseline == [asdict(vehicle) for vehicle in vehicles]
    return {'version':method()['dataset_version'],'baseline_version':'legacy-demo-v0','baseline':baseline,'vehicles':tuple(projected),'evidence':evidence}


def project_candidates(decisions):
    """In-memory ranking preview, NOT persisted or published catalog entries."""
    from app.recommender import Vehicle
    from data_platform.catalog.intake import load_selection
    candidates = {row.id: row for row in load_selection().candidates}
    result = []
    for decision in decisions:
        if decision.get('status') != 'approved_for_activation':
            raise ValueError('Blocked candidates cannot participate in an academic preview')
        candidate = candidates[decision['id']]
        values = {key: int(value) if key == 'segment_level' else float(value)
                  for key, value in derive(decision['observed']['price_brl'])['values'].items()}
        result.append(Vehicle(
            id=candidate.id, brand=candidate.brand,
            model=candidate.model_family + ' ' + decision['review']['approved_version'],
            year=decision['review']['approved_year'], price=float(decision['observed']['price_brl']),
            fuel_efficiency_km_l=float(decision['observed']['city_km_l']),
            use_cases=tuple(method()['neutral_use_cases']), chronic_issues=(), image_url='',
            category=candidate.category, **values,
            price_reference='FIPE observada; indicadores complementares academic-demo-v1',
            price_reference_month=decision['observed']['reference_month'],
            fipe_code=decision['review']['fipe']['CodigoFipe'],
            fipe_model=decision['review']['commercial_description'], price_is_fipe=True,
        ))
    return tuple(result)


def compare_rankings(legacy, decisions):
    """Controlled offline comparison; never a claim about a published ranking."""
    from app.recommender import RecommendationProfile, recommend
    projection = project_legacy(legacy)
    additions = project_candidates(decisions)
    result = {}
    for use_case in method()['neutral_use_cases']:
        profile = RecommendationProfile(100000, 1750, use_case, 1000, 6)
        stages = {}
        for name, vehicles in (
            ('legacy_34', legacy), ('academic_34', projection['vehicles']),
            ('academic_expanded_preview', projection['vehicles'] + additions),
        ):
            metadata = {}
            ranking = recommend(vehicles, profile, processing_metadata=metadata)
            if metadata['ignored'] or len(ranking) != len(vehicles):
                raise ValueError('Ranking preview lost candidate evidence')
            stages[name] = {'processing': metadata, 'ranking': [
                {**row, 'vehicle': asdict(row['vehicle'])} for row in ranking
            ]}
        positions = {
            name: {row['vehicle']['id']: index + 1 for index, row in enumerate(stage['ranking'])}
            for name, stage in stages.items()
        }
        attribution = []
        for vehicle in projection['vehicles'] + additions:
            identifier = vehicle.id
            previous = positions['legacy_34'].get(identifier)
            academic = positions['academic_34'].get(identifier)
            expanded = positions['academic_expanded_preview'][identifier]
            attribution.append({
                'id': identifier, 'legacy_position': previous,
                'academic_34_position': academic, 'expanded_position': expanded,
                'method_position_delta': academic - previous if previous is not None else None,
                'expansion_position_delta': expanded - academic if academic is not None else None,
                'reason': 'new candidate preview' if previous is None else
                    'legacy->academic34: method only; academic34->expanded: larger normalization universe',
            })
        result[use_case] = {
            'profile': asdict(profile), 'stages': stages, 'attribution': attribution,
            'status': 'offline_preview_not_published',
            'method_confidence': method()['parameters']['demonstrative_confidence'],
            'warning': method()['label'],
            'confidence_scope': 'method_confidence describes evidence; the unchanged recommender confidence is not proof of market accuracy',
        }
    return result
