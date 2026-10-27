from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace as NS
from uuid import uuid4

import pytest

from app.academic_cohort import catalog_cache as c


def fixture(monkeypatch):
    sid=uuid4()
    snapshot=NS(snapshot_id=sid,created_at=datetime.now(timezone.utc),cohort_version='v1',
        cohort_fingerprint='a'*64,method_fingerprint='b'*64,selected_count=1,
        profile_counts={},source_manifest={},inventory_summary={},operationally_active=False,recommended=False)
    vehicle=NS(snapshot_id=sid,catalog_id=1,fipe_code='fixture',reference_month='2026-10',
        canonical_identity_key='i'*64,year_code='2026-1',
        label='fixture',purchase_price_brl=Decimal('100'),payload={'nested':{'value':1}},
        payload_fingerprint='c'*64,operationally_active=False,recommended=False)
    evaluation=NS(snapshot_id=sid,catalog_id=1,profile='cidade',scenario='base',score=Decimal('1'),
        monthly_tco_brl=Decimal('20'),academic_test_ready=True,payload={'nested':{'value':2}},
        payload_fingerprint='d'*64,operationally_active=False,recommended=False)
    state={'stamp':('e'*64,0),'audit':0,'fail_read':False,'bad':False,'time':0}
    def read(*args):
        if state['fail_read']:raise RuntimeError('database unavailable')
        return deepcopy(snapshot),state['stamp']
    def audit(capture,*_):
        state['audit']+=1
        if state['bad']:raise ValueError('protected payload differs')
        capture.rows={c.CohortVehicle:[vehicle],c.CohortEvaluation:[evaluation]}
    monkeypatch.setattr(c,'read_stamp',read)
    monkeypatch.setattr(c,'audit_snapshot_metadata',lambda *_:None)
    monkeypatch.setattr(c,'audit_snapshot',audit)
    plan=NS(proposal=NS(candidate_version='v1',candidate_fingerprint='a'*64))
    cache=c.CatalogCache(clock=lambda:state['time'])
    return cache,state,plan,sid


def test_cold_and_hit_are_request_owned_clones(monkeypatch):
    cache,state,plan,sid=fixture(monkeypatch)
    first,_,mode=cache.acquire(object(),plan,('scope',),sid)
    assert mode=='miss'
    first.vehicle(sid,1).payload['nested']['value']=9
    second,_,mode=cache.acquire(object(),plan,('scope',),sid)
    assert mode=='hit' and state['audit']==1
    assert second.vehicle(sid,1).payload=={'nested':{'value':1}}
    assert first.session is not second.session
    assert not hasattr(next(iter(cache._entries.values())),'session')
    assert second.evaluations(sid,profile='cidade',scenario='base')[0].monthly_tco_brl==Decimal('20')


@pytest.mark.parametrize('cause',['stamp','ttl','scope','plan_version'])
def test_invalidation_forces_complete_comparison(monkeypatch,cause):
    cache,state,plan,sid=fixture(monkeypatch)
    cache.acquire(object(),plan,('scope',),sid)
    scope=('scope',)
    if cause=='stamp':state['stamp']=('f'*64,0)
    elif cause=='ttl':state['time']=60
    elif cause=='scope':scope=('other',)
    else:plan.proposal.candidate_version='v2'
    assert cache.acquire(object(),plan,scope,sid)[2]=='miss'
    assert state['audit']==2


def test_real_payload_change_unchanged_fingerprint_has_no_stale_fallback(monkeypatch):
    cache,state,plan,sid=fixture(monkeypatch)
    cache.acquire(object(),plan,('scope',),sid)
    state.update(stamp=('f'*64,0),bad=True)
    with pytest.raises(ValueError,match='protected payload'):cache.acquire(object(),plan,('scope',),sid)
    assert not cache._entries


def test_database_failure_cannot_reuse_warm_entry(monkeypatch):
    cache,state,plan,sid=fixture(monkeypatch)
    cache.acquire(object(),plan,('scope',),sid)
    state['fail_read']=True
    with pytest.raises(RuntimeError,match='database unavailable'):cache.acquire(object(),plan,('scope',),sid)
    assert state['audit']==1


def test_commit_during_audit_rejects_without_retry(monkeypatch):
    cache,state,plan,sid=fixture(monkeypatch)
    original=c.audit_snapshot
    def changed(*args):
        original(*args);state['stamp']=('f'*64,0)
    monkeypatch.setattr(c,'audit_snapshot',changed)
    with pytest.raises(c.AcademicUnavailable,match='alterado durante'):cache.acquire(object(),plan,('scope',),sid)
    assert not cache._entries and state['audit']==1


def test_concurrent_cold_load_single_flights_and_bounds_scopes(monkeypatch):
    cache,state,plan,sid=fixture(monkeypatch)
    with ThreadPoolExecutor(max_workers=2) as pool:
        modes=list(pool.map(lambda _:cache.acquire(object(),plan,('scope',),sid)[2],range(2)))
    assert sorted(modes)==['hit','miss'] and state['audit']==1
    cache.acquire(object(),plan,('scope2',),sid)
    cache.acquire(object(),plan,('scope3',),sid)
    assert len(cache._entries)==2


def test_read_stamp_contains_all_row_versions_and_schema_not_just_declared_hash():
    for token in ('xmin','ctid','tableoid','catalog_id','profile','scenario','pg_attribute','relfilenode'):
        assert token in c.STAMP
    assert 'payload_fingerprint' not in c.STAMP


@pytest.mark.parametrize('permission',[False,None,1])
def test_stamp_requires_live_read_permission_not_cached_permission(permission):
    row={'catalog_stamp':'a'*64,'xid_epoch':0,'catalog_read_allowed':permission}
    session=NS(get_bind=lambda:NS(dialect=NS(name='postgresql')),
        execute=lambda query:NS(mappings=lambda:NS(first=lambda:row)))
    plan=NS(proposal=NS(candidate_version='v1',candidate_fingerprint='a'*64))
    with pytest.raises(ValueError,match='read permission'):c.read_stamp(session,plan)
