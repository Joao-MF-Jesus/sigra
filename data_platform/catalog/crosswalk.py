"""Individual review gate, explicitly separate from the historical intake v1."""
import hashlib
import json
from decimal import Decimal
from pathlib import Path
import re

from data_platform.catalog.academic import derive
from data_platform.catalog.intake import load_selection
from data_platform.transformation.fipe import parse_brl_price

ALIASES_PATH = Path(__file__).with_name('crosswalk_aliases_v1.json')
REVIEW_PATH = Path(__file__).with_name('batch1_crosswalk_v1.json')
LINK_TYPES = {'exact_trim_powertrain','shared_powertrain_group','versioned_commercial_alias'}


def fingerprint(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,default=str).encode()).hexdigest()


def mechanical_key(row):
    motor = row['motor_description'].upper().replace(',','.')
    displacement = re.search(r'(?<!\d)\d\.\d(?!\d)', motor)
    valves = re.search(r'(\d+)\s*V', motor)
    if not displacement or not valves:
        raise ValueError('Incomplete mechanical evidence')
    registry = json.loads(ALIASES_PATH.read_text(encoding='utf-8'))
    transmission = registry['transmissions'].get(row['transmission_code'])
    if not transmission:
        raise ValueError('Unreviewed transmission code')
    turbo = bool(re.search(r'TURBO|THP|\dT\b',motor))
    return (displacement.group(),int(valves.group(1)),turbo,transmission,row['fuel_type'])


def _raw_decision(candidate, review, *, historical_v1):
    try:
        result = _decide(candidate, review, include_academic=historical_v1)
    except (KeyError, TypeError, ValueError, ArithmeticError, AttributeError):
        result = {'id': candidate.id, 'method_version': 'catalog-identity-crosswalk-v1',
                'status': 'blocked_with_evidence', 'activated': False,
                'blockers': ['MALFORMED_REVIEW'], 'review': review,
                'original': {'year': candidate.model_year, 'version': candidate.target_version}}
    return result


def decide(candidate, review, *, historical_v1=False):
    result = _raw_decision(candidate, review, historical_v1=historical_v1)
    if historical_v1:
        return result
    from data_platform.catalog.readiness import current_identity
    return current_identity(result)


def _decide(candidate, review, *, include_academic=True):
    """A rejected record never changes another record's classification."""
    issues=[]
    decision={'id':candidate.id,'method_version':'catalog-identity-crosswalk-v1','status':'blocked_with_evidence','activated':False,'blockers':issues,'original':{'year':candidate.model_year,'version':candidate.target_version},'review':review}
    def block(code):
        issues.append(code)
    if not review or review.get('id') != candidate.id:
        block('REVIEW_MISSING'); return decision
    if review.get('blocked_reason'):
        block(review['blocked_reason']); return decision
    required={'fipe','pbev','source_references','reviewed_at','reviewed_by','approved_year','approved_version','powertrain','applicable_pbev_rows','link_type','commercial_description','pbev_family','target_change_reason','year_code'}
    if not required.issubset(review):
        block('REVIEW_INCOMPLETE'); return decision
    if review['link_type'] not in LINK_TYPES:
        block('LINK_TYPE_NOT_ALLOWED')
    fipe=review['fipe']; pbev=review['pbev']; approved_year=review['approved_year']
    changed=approved_year != candidate.model_year or review['approved_version'] != candidate.target_version
    decision['target_changed']=changed
    decision['target_version_changed']=review['approved_version'] != candidate.target_version
    if changed and not review['target_change_reason'].strip(): block('TARGET_CHANGE_NOT_EXPLAINED')
    if fipe['AnoModelo'] != approved_year or pbev['raw']['cycle_year'] != approved_year:
        block('YEAR_CONFLICT')
    if fipe['Modelo'] != review['commercial_description'] or pbev['model_name'] != review['pbev_family']:
        block('COMMERCIAL_EVIDENCE_CHANGED')
    if not re.fullmatch(r'\d{6}-\d',fipe['CodigoFipe']): block('FIPE_CODE_INVALID')
    if not re.fullmatch(str(approved_year)+r'-\d+',review['year_code']): block('FIPE_YEAR_CODE_INVALID')
    registry=json.loads(ALIASES_PATH.read_text(encoding='utf-8'))
    fuel=registry['fuels'].get(fipe['Combustivel'])
    if not fuel or fuel != pbev['fuel_type']: block('STRUCTURED_FUEL_CONFLICT')
    if {'1': 'gasoline', '5': 'flex'}.get(review['year_code'].split('-')[-1]) != fuel:
        block('YEAR_CODE_FUEL_CONFLICT')
    if fuel not in {'gasoline','flex'}: block('FUEL_STRATEGY_UNSUPPORTED')
    if pbev.get('propulsion_type') not in (None,'combustion'): block('PROPULSION_CONFLICT')
    try:
        key=mechanical_key(pbev)
        if list(key) != review['powertrain']: block('POWERTRAIN_CONFLICT')
        if 'AUT' in fipe['Modelo'].upper() and key[3]=='manual': block('TRANSMISSION_CONFLICT')
        if 'MEC' in fipe['Modelo'].upper() and key[3]!='manual': block('TRANSMISSION_CONFLICT')
        fipe_engine=re.search(r'\b\d\.\d\b',fipe['Modelo'])
        if not fipe_engine or fipe_engine.group()!=key[0]: block('ENGINE_CONFLICT')
        fipe_valves=re.search(r'(\d+)\s*V\b',fipe['Modelo'],re.IGNORECASE)
        if fipe_valves and int(fipe_valves.group(1))!=key[1]: block('VALVE_COUNT_CONFLICT')
        fipe_turbo=bool(re.search(r'\b(?:TURBO|THP|TB)\b',fipe['Modelo'],re.IGNORECASE))
        if fipe_turbo and not key[2]: block('ASPIRATION_CONFLICT')
        applicable=review['applicable_pbev_rows']
        if not applicable or pbev['raw']['row_hash'] not in {row['raw']['row_hash'] for row in applicable}:
            block('APPLICABLE_SCOPE_INCOMPLETE')
        if any(mechanical_key(row)!=key for row in applicable): block('SHARED_MECHANICAL_CONFLICT')
        metrics={(str(row['fossil_city_km_l']),str(row['fossil_highway_km_l'])) for row in applicable if mechanical_key(row)==key}
        if len(metrics)!=1: block('CONFLICTING_CONSUMPTION_LINES')
    except (ValueError,KeyError,TypeError):
        block('MECHANICAL_EVIDENCE_INVALID')
    alias_id=review.get('alias_id')
    if alias_id:
        alias=registry['aliases'].get(alias_id)
        if alias != {'candidate_id':candidate.id,'commercial_family':candidate.model_family,'pbev_family':review['pbev_family'],'year':approved_year}:
            block('ALIAS_NOT_AUTHORIZED')
    elif review['link_type']=='versioned_commercial_alias': block('EXPLICIT_ALIAS_REQUIRED')
    if review['link_type']=='shared_powertrain_group' and not review.get('shared_group_explanation'):
        block('SHARED_GROUP_NOT_EXPLAINED')
    if review['link_type']=='shared_powertrain_group' and 'shared_trims_as_published' not in review:
        block('SHARED_TRIMS_NOT_RECORDED')
    for field in ('fossil_city_km_l','fossil_highway_km_l'):
        if pbev.get(field) is None or not Decimal(str(pbev[field])).is_finite() or Decimal(str(pbev[field])) <= 0: block('OBSERVED_CONSUMPTION_REQUIRED')
    for reference in review['source_references']:
        if not re.fullmatch(r'[a-f0-9]{64}',reference.get('sha256','')): block('SOURCE_HASH_REQUIRED')
    if len(review['source_references'])<2: block('SOURCE_LINEAGE_INCOMPLETE')
    if issues: return decision
    try:
        price=parse_brl_price(fipe['Valor'])
        if not price.is_finite() or price <= 0:
            raise ValueError('Positive observed price required')
        calculation=derive(price) if include_academic else None
    except ValueError:
        block('PRICE_INVALID'); return decision
    decision.update(status='approved_for_activation',canonical_key=f"fipe:car:{fipe['CodigoFipe']}:{review['year_code']}",observed={'price_brl':price,'reference_month':fipe['MesReferencia'],'city_km_l':pbev['fossil_city_km_l'],'highway_km_l':pbev['fossil_highway_km_l'],'fuel':fuel})
    if include_academic:
        decision['academic'] = calculation
    decision['decision_fingerprint']=fingerprint(decision)
    return decision


def review_batch(reviews=None, *, historical_v1=False):
    reviews=reviews if reviews is not None else json.loads(REVIEW_PATH.read_text(encoding='utf-8'))['reviews']
    candidates=load_selection().candidates[:22]
    decisions=[]
    for candidate in candidates:
        entries=[row for row in reviews if row.get('id')==candidate.id]
        decisions.append(_raw_decision(candidate,entries[0] if len(entries)==1 else None, historical_v1=historical_v1))
    keys={row['canonical_key'] for row in decisions if row['status']=='approved_for_activation'}
    for key in keys:
        duplicates=[row for row in decisions if row.get('canonical_key')==key]
        if len(duplicates)>1:
            for row in duplicates:
                row['status']='blocked_with_evidence';row['blockers'].append('DUPLICATE_CANONICAL_IDENTITY')
                row.pop('decision_fingerprint',None)
    if historical_v1:
        return {'method_version':'catalog-identity-crosswalk-v1','batch_processed':True,'approved':sum(row['status']=='approved_for_activation' for row in decisions),'blocked':sum(row['status']=='blocked_with_evidence' for row in decisions),'activated':0,'decisions':decisions}
    from data_platform.catalog.readiness import CatalogStage, current_identity
    current = [current_identity(row) for row in decisions]
    return {'method_version': 'catalog-identity-crosswalk-v1', 'state_schema_version': 'catalog-readiness-v2',
            'batch_processed': True, 'counts': {stage.value: sum(row['gates'][stage.value] for row in current) for stage in CatalogStage},
            'blocked': sum(row['status'] == 'blocked_with_evidence' for row in current), 'decisions': current}
