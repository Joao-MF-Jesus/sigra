"""Read-only plans and exact legacy price-label review; no HTTP or DB client."""
from collections import Counter
from decimal import Decimal
import hashlib
import json
from pathlib import Path

from data_platform.catalog.profile_contracts_v3 import Citation, ProfileVehicle, available, observed
from data_platform.catalog.profile_evidence_v3 import canonical_month

PRICE_CROSSWALK_PATH = Path(__file__).with_name("experimental_legacy_price_crosswalk_v1.json")


def price_crosswalk():
    return json.loads(PRICE_CROSSWALK_PATH.read_text(encoding="utf-8"))


def replay_price_aliases(vehicles, cache_path):
    """Repair four price-label replays in this view only. Never bless trim identity."""
    from app.fipe import FIPE_REFERENCE_PROFILES
    spec=price_crosswalk(); raw=Path(cache_path).read_bytes()
    if hashlib.sha256(raw).hexdigest()!=spec["source_sha256"]: raise ValueError("Legacy cache changed")
    cache=json.loads(raw,parse_float=Decimal)
    if len(cache)!=34 or {r['vehicle_id'] for r in cache}!=set(range(1,35)):
        raise ValueError("Legacy cache must have exactly34 unique IDs")
    reviews={r['id']:r for r in spec['entries']}
    if set(reviews)!={9,15,19,21} or len(spec['entries'])!=4: raise ValueError("Unexpected price alias scope")
    by_id={r['vehicle_id']:r for r in cache}; output=[]; diagnostics=[]
    for v in vehicles:
        fields=dict(v.fields); provenance=dict(v.provenance); entry=reviews.get(v.id)
        if entry:
            row=by_id[v.id]; reference=FIPE_REFERENCE_PROFILES[v.id]
            if (row['code'],row['year_code'],row['model'],reference.model,reference.code,reference.year_code,
                row['reference_month'],row['retrieval_status']) != (
                entry['code'],entry['year_code'],entry['cached_description'],entry['registered_description'],
                entry['code'],entry['year_code'].split('-')[0],spec['reference_month'],'live'):
                raise ValueError("Exact registered price crosswalk mismatch")
            citation=Citation(provider='fipe',url=row['source_url'],sha256=spec['source_sha256'],
                document='Preserved July2026 legacy FIPE cache',locator=f"vehicle_id={v.id}; exact registered price-label alias",collected_at=row['retrieved_at'])
            for field,value in {'fipe_code':row['code'],'year_code':row['year_code'],
                    'commercial_identity':row['model'],'reference_month':canonical_month(row['reference_month']),
                    'price_brl':row['price']}.items():
                fields[field]=observed(field,value,(citation,), 'legacy_reference',('Price reference only; catalog trim not approved',))
            diagnostic={**entry,'status':'PRICE_LABEL_CROSSWALK_VERIFIED','mapping_version':spec['version'],
                        'source_sha256':spec['source_sha256'],'catalog_identity_approved':False,'source_cache_modified':False}
            diagnostics.append(diagnostic); provenance['experimental_price_label_crosswalk']=diagnostic
        holds=[r for r in spec['catalog_identity_holds']+spec['additional_review_flags'] if r['id']==v.id]
        provenance['experimental_catalog_review_flags']=holds
        output.append(ProfileVehicle.model_validate({**v.model_dump(),'fields':fields,'provenance':provenance}))
    return tuple(output),diagnostics


def fipe_plan(legacy, candidates, *, remaining_quota=None, access_verified=False, quota_verified=False,
              month_pin_verified=False, attempt_limit=34):
    """Exact request inventory bounded by the explicitly authorized attempt cap."""
    target='2026-09'; all_rows=tuple(legacy)+tuple(candidates)
    cached={(v.fields['fipe_code'].value,v.fields['year_code'].value):v for v in all_rows
            if available(v,'price_brl') and v.fields['reference_month'].value==target}
    requests=[]; reused=[]
    for v in legacy:
        code,year=v.fields['fipe_code'].value,v.fields['year_code'].value
        if code is None or year is None: raise ValueError('Price-reference target must be explicitly resolved')
        key=(code,year)
        if key in cached:
            reused.append({'vehicle_id':v.id,'cached_vehicle_id':cached[key].id});continue
        requests.append({'vehicle_id':v.id,'fipe_code':code,'year_code':year,
            'path':f'/cars/{code}/years/{year}', 'method':'GET','required_month':target,
            'idempotency_key':f'fipe-v2:{code}:{year}:{target}',
            'existing_month':v.fields['reference_month'].value,
            'price_reference_not_catalog_identity':v.identity_status!='identity_approved',
            'catalog_review_flags':v.provenance.get('experimental_catalog_review_flags',[])})
    if len({r['idempotency_key'] for r in requests})!=len(requests): raise ValueError('Duplicate quota request target')
    if isinstance(attempt_limit,bool) or not isinstance(attempt_limit,int) or not 0<attempt_limit<=34:
        raise ValueError('FIPE attempt limit must be an integer from 1 through 34')
    if remaining_quota is not None and (isinstance(remaining_quota,bool) or not isinstance(remaining_quota,int) or remaining_quota<0):
        raise ValueError('Quota remaining must be a verified integer balance, not the plan limit')
    blockers=[]
    if not access_verified: blockers.append('PROVIDER_CONTRACT_NOT_VERIFIED')
    if len(requests)>attempt_limit: blockers.append('AUTHORIZED_ATTEMPT_LIMIT_EXCEEDED')
    if quota_verified and remaining_quota is not None and remaining_quota<len(requests): blockers.append('PROVIDER_QUOTA_INSUFFICIENT')
    if not month_pin_verified: blockers.append('SEPTEMBER_REFERENCE_PIN_NOT_VERIFIED')
    if any(r['catalog_review_flags'] for r in requests): blockers.append('CATALOG_TARGET_REVIEW_PENDING')
    return {'version':'experimental-fipe-refresh-plan-v1','target_month':target,
        'provider_base_from_existing_client':'https://fipe.parallelum.com.br/api/v2',
        'request_template_from_existing_contract':'/cars/{fipe_code}/years/{year_code}',
        'calls_current_reference_refresh':len(requests),'calls_executed':0,'calls_to_discover_years_or_families':0,
        'vehicles_pending_temporal_alignment':len(requests),
        'attempts_planned':len(requests),'attempts_executed':0,'attempts_available':attempt_limit,
        'attempt_budget_is_formally_authorized':True,
        'cache_reused':reused,'cached_candidate_prices':len(candidates),'requests':requests,
        'authorized_attempt_limit':attempt_limit,
        'attempts_include_searches_details_and_retries':True,
        'provider_documented_unauthenticated_daily_limit':500,
        'percentage_of_documented_daily_limit':Decimal(len(requests))/Decimal(5),
        'remaining_quota_verified':remaining_quota if quota_verified else None,
        'remaining_after_planned_calls':remaining_quota-len(requests) if quota_verified and remaining_quota is not None and remaining_quota>=len(requests) else None,
        'execution_allowed':not blockers,'blockers':blockers,
        'access_limitation':'The official public API documents anonymous access. No FIPE credential is invented or required; the project authorization remains the stricter 34-attempt cap.',
        'cache_protocol':['Keep July cache immutable. Write a new September receipt only after authorization.',
            'Key by API version, exact FIPE code/year and requested month; validate response identity, positive Decimal price and exact month.',
            'Persist SHA256, sanitized URL, timestamp and validated month; atomic new-file receipt. Existing valid same-key receipt means zero repeat calls.',
            'Count each actual HTTP attempt, including failures and retries; retries disabled until separately budgeted.',
            'If a price reference changes during catalog identity review, recompute all request targets and quota before execution.'],
        'plan_is_not_downloader':True}


def collection_estimate(row, vehicle):
    """Planning units, not fabricated network guarantees. Reuse across six rows."""
    gaps={name for group in row['unsatisfied_groups'] for name in group}
    technical=gaps-{'price_brl','fuel','consumption_city','consumption_highway'}
    year=vehicle.fields['year_code'].value
    cycle=int(year.split('-')[0]) if year else None
    pbev_needed=bool(gaps&{'fuel','consumption_city','consumption_highway'})
    existing_oem=bool(vehicle.provenance.get('technical_review_sha256'))
    fipe=int(row['observed_reference_month']!=row['required_reference_month'])
    return {'fipe_price_requests':fipe,'pbev_downloads_estimated':int(pbev_needed and cycle not in {2017,2018,2019,2020,2021}),
            'cached_pbev_review_required':pbev_needed and cycle in {2017,2018,2019,2020,2021},
            'cached_oem_review_first':bool(technical) and existing_oem,
            'provisional_individual_oem_documents':int(bool(technical) and not existing_oem),
            'technical_fields_to_complete':sorted(technical),'guaranteed_total_calls':None,
            'additional_search_or_download_upper_bound':None,
            'basis':'One provisional document per incomplete ficha without cached OEM; a document may cover multiple fields/models or none. Do not sum per-profile rows into a quota budget.',
            'new_calls_now':0}


def directed_plan(vehicles, assessment, selection):
    """Prioritize evidence collection, never preferred recommendation scores."""
    by_id={v.id:v for v in vehicles}
    for row in assessment['matrix']:
        row['estimated_queries']=collection_estimate(row,by_id[row['vehicle_id']])
    # Only reviewed identities without unresolved conflicts or human holds are
    # counted as potential dossiers, not as eligible without their missing facts.
    potential=[v for v in vehicles if v.identity_status=='identity_approved' and not v.source_conflicts
               and not (v.human_approval_required and v.human_approval_status!='human_approved')]
    counts={v.id:sum(o.kind!='unavailable' and o.value is not None for o in v.fields.values()) for v in potential}
    prioritized=sorted(potential,key=lambda v:(-counts[v.id],v.id))
    target=10
    chosen=prioritized[:target]
    dossiers=[{'id':v.id,'vehicle':v.label,'existing_evidence_fields':counts[v.id],
               'cached_oem':bool(v.provenance.get('technical_review_sha256')),
               'profiles_still_missing':[r['profile'] for r in assessment['matrix'] if r['vehicle_id']==v.id and not r['partial_coverage_candidate']],
               'fipe_code':v.fields['fipe_code'].value,'year_code':v.fields['year_code'].value,
               'sources_to_reuse':{s.sha256:s.model_dump(mode='json') for o in v.fields.values() for s in o.sources}}
              for v in chosen]
    if {c.id for c in selection.candidates}!=set(range(35,101)): raise ValueError('Expansion manifest changed')
    backlog=[{'id':c.id,'vehicle':f'{c.brand} {c.model_family} {c.target_version} {c.model_year}',
              'status':'expansion_backlog_not_prepared','active':False} for c in selection.candidates if c.id>=57]
    carpedia_priority_order=(37,38,39,42,43,44,46,47,49)
    carpedia_dossiers=[next(d for d in dossiers if d['id']==identifier)
                       for identifier in carpedia_priority_order if any(d['id']==identifier for d in dossiers)]
    return {'version':'experimental-gap-directed-plan-v1','priority_dossiers':dossiers,
            'potential_existing_without_holds':len(potential),'potential_is_not_ready':True,
            'priority_rule':'Descending count of individually sourced fields, then ID for deterministic scheduling only. No prices, utility scores, collection group or desired ranking used.',
            'same_vehicle_may_cover_all_six':True,'reserve_existing_ids':[v.id for v in prioritized[target:]],
            'additional_selected_ids':[], 'additional_proven_necessary':None,
            'additional_mathematical_lower_bound':max(0,target-len(potential)),
            'additional_decision':'No additional batch selected: insufficient evidence is not proof that the existing pool cannot supply ten. First assess ten existing dossiers; the exact minimal new count is not identifiable yet.',
            'backlog':backlog,'wide_expansion_frozen':True,
            'collection_budget':{'dossiers':len(chosen),'already_with_oem_documents':sum(d['cached_oem'] for d in dossiers),
                'provisional_new_oem_documents':sum(not d['cached_oem'] for d in dossiers),
                'pbev_for_priority':{'new_downloads':0,'existing_cycles_reused':True},
                'fipe_for_priority':{'new_price_calls':0,'already_september':True},
                'source_yield_not_guaranteed':True,'elapsed_hours_estimate':None,
                'reason':'Document discovery, access, exact trim and equipment completeness are not measured; no invented delivery-time estimate.'},
            'carpedia':{'status':'AUTHORIZED_BUT_CREDENTIAL_MISSING','base_url':'https://www.carpedia.com.br',
                'contract_version':'carpedia-api-v1','discovery_endpoint_template':'/api/v1/modelos/{brand}/{model}/versoes',
                'endpoint_template':'/api/v1/ficha/{official_external_id}/{model_year}',
                'credential_environment':'CARPEDIA_API_KEY','attempt_limit_absolute':10,
                'attempts_include_searches_details_and_retries':True,
                'maximum_one_cached_response_per_identity':True,'provisional_specification_calls':None,
                'calls_executed':0,'attempts_remaining':10,
                'provider_documented_monthly_free_requests':200,'official_id_discovery_calls':None,
                'candidates':[{'id':d['id'],'fipe_code':d['fipe_code'],'year_code':d['year_code'],'official_external_id':None,'url':None} for d in carpedia_dossiers],
                'expected_optional_fields':['body_type','seats','cargo_l','length_mm','width_mm','ground_clearance_mm','weight_kg','power_gasoline_cv','airbags','abs','esc','payload_kg'],
                'multi_field_response_possible':True,'response_completeness_guaranteed':False,
                'cache_key':'contract+official_id+year+response_SHA256; immutable receipt, collection timestamp and exact version match',
                'official_confirmation_required':['Exact version/year/engine/fuel/transmission','FIPE identity/price/month','PBEV consumption/powertrain','Any technical conflict with OEM','Equipment trim scope and measurement units'],
                'execution_blockers':['CARPEDIA_API_KEY is not configured','Verified external ID per identity before specification lookup']}}
