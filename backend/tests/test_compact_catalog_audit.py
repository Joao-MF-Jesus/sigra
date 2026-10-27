"""No SQL connections. SQL contract + independent in-memory row oracle only."""
from collections import Counter
from copy import deepcopy
from decimal import Decimal
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from app.academic_cohort import compact_audit as c, revision6_homologation as h
from app.academic_cohort.contracts import json_document
from app.academic_cohort.service import AcademicUnavailable


def fixture():
    vehicle={'catalog_id':1,'canonical_identity_key':'a'*64,'fipe_code':'000001-0',
        'year_code':'2018-5','label':'Fictitious','purchase_price_brl':Decimal('15000.00'),
        'reference_month':'2026-09','payload':{'id':1,'nested':{'unknown':None,'zero':0,'false':False}},
        'payload_fingerprint':'b'*64}
    evaluation={'catalog_id':1,'profile':'cidade','scenario':'base','academic_test_ready':True,
        'score':None,'monthly_tco_brl':Decimal('0.00'),'payload':{'id':1,'notes':['quote "','line\nbreak','ação']},
        'payload_fingerprint':'c'*64}
    proposal=SimpleNamespace(transport_vehicles=[vehicle],transport_evaluations=[evaluation])
    return SimpleNamespace(proposal=proposal),SimpleNamespace(snapshot_id=uuid4())


class MemoryComparison:
    """Models both-direction EXCEPT ALL; never a PostgreSQL claim."""
    def __init__(self,plan,snapshot):
        self.calls=[];self.snapshot=snapshot.snapshot_id
        self.rows={kind:deepcopy(c.expected_records(kind,plan)) for kind in c.SPECS}
    def get_bind(self):return SimpleNamespace(dialect=SimpleNamespace(name='postgresql'))
    def execute(self,query,params):
        sql=str(query);kind=next(k for k,(table,_) in c.SPECS.items() if 'academic.'+table+' ' in sql)
        self.calls.append((kind,params['snapshot_id']))
        assert params['snapshot_id']==self.snapshot
        names=[name for name,_ in c.SPECS[kind][1]]
        def bag(rows):
            return Counter(json.dumps({k:row.get(k) for k in names},sort_keys=True,ensure_ascii=False) for row in rows)
        equal=bag(self.rows[kind])==bag(params['expected'])
        return SimpleNamespace(scalar_one=lambda:equal)


def setup(monkeypatch):
    plan,snapshot=fixture()
    monkeypatch.setattr(c,'audit_snapshot_metadata',lambda s,p:None)
    return plan,snapshot,MemoryComparison(plan,snapshot)


@pytest.mark.parametrize('kind',c.SPECS)
def test_query_is_snapshot_scoped_exact_two_way_full_row_readonly(kind):
    query=c.comparison_query(kind)
    sql=str(query.compile(dialect=postgresql.dialect()))
    assert sql.count('EXCEPT ALL')==2 and 'UNION ALL' in sql
    assert 'WHERE snapshot_id = %(snapshot_id)s' in sql
    assert 'jsonb_to_recordset(CAST(%(expected)s::JSONB AS jsonb))' in sql
    assert 'SELECT NOT EXISTS' in sql and 'AS exact_match' in sql
    assert not any(word in sql for word in ('INSERT ','UPDATE ','DELETE ','CREATE ','GRANT '))
    for name,_ in c.SPECS[kind][1]:assert name in sql
    assert 'payload jsonb' in sql and 'payload_fingerprint text' in sql


def test_exact_match_returns_only_two_boolean_results(monkeypatch):
    p,s,db=setup(monkeypatch)
    c.audit_snapshot_compact(db,s,p)
    assert db.calls==[('vehicles',s.snapshot_id),('evaluations',s.snapshot_id)]


@pytest.mark.parametrize('kind',c.SPECS)
@pytest.mark.parametrize('mutation',['payload','fingerprint','flag','missing','extra','duplicate','scalar'])
def test_each_real_change_still_blocks_even_with_original_fingerprint(monkeypatch,kind,mutation):
    p,s,db=setup(monkeypatch);rows=db.rows[kind]
    if mutation=='payload':rows[0]['payload']['id']=999 # Fingerprint deliberately unchanged.
    elif mutation=='fingerprint':rows[0]['payload_fingerprint']='d'*64
    elif mutation=='flag':rows[0]['recommended']=True
    elif mutation=='missing':rows.clear()
    elif mutation in {'extra','duplicate'}:
        row=deepcopy(rows[0])
        if mutation=='extra':row['catalog_id']=2
        rows.append(row)
    elif mutation=='scalar':rows[0]['catalog_id']=7
    with pytest.raises(ValueError,match='persisted evidence/metadata changed'):
        c.audit_snapshot_compact(db,s,p)


def test_payload_key_order_not_a_real_change(monkeypatch):
    p,s,db=setup(monkeypatch)
    db.rows['vehicles'][0]['payload']={'nested':{'false':False,'zero':0,'unknown':None},'id':1}
    c.audit_snapshot_compact(db,s,p)


def test_no_cross_request_or_negative_cache(monkeypatch):
    p,s,db=setup(monkeypatch)
    c.audit_snapshot_compact(db,s,p)
    db.rows['evaluations'][0]['payload']['notes'].append('changed')
    with pytest.raises(ValueError):c.audit_snapshot_compact(db,s,p)
    assert len(db.calls)==4


def test_validated_header_precedes_query_and_no_fallback(monkeypatch):
    p,s,db=setup(monkeypatch)
    def reject(*_):raise ValueError('snapshot identity changed')
    monkeypatch.setattr(c,'audit_snapshot_metadata',reject)
    with pytest.raises(ValueError,match='identity'):c.audit_snapshot_compact(db,s,p)
    assert not db.calls


@pytest.mark.parametrize('value',[None,1,'true',False])
def test_invalid_or_false_result_is_not_success(monkeypatch,value):
    p,s,db=setup(monkeypatch)
    db.execute=lambda *a,**k:SimpleNamespace(scalar_one=lambda:value)
    with pytest.raises(ValueError):c.audit_snapshot_compact(db,s,p)


def test_non_postgresql_bind_blocks(monkeypatch):
    p,s,db=setup(monkeypatch)
    db.get_bind=lambda:SimpleNamespace(dialect=SimpleNamespace(name='sqlite'))
    with pytest.raises(ValueError,match='requires PostgreSQL'):c.audit_snapshot_compact(db,s,p)


def test_transport_fields_never_silently_discarded():
    p,_=fixture();p.proposal.transport_vehicles[0]['new_protected_field']='unexpected'
    with pytest.raises(ValueError,match='fields differ'):c.expected_records('vehicles',p)


def test_decimal_null_zero_and_comments_preserved():
    p,_=fixture();rows=c.expected_records('evaluations',p)
    assert rows[0]['score'] is None and rows[0]['monthly_tco_brl']=='0.00'
    assert rows[0]['payload']['notes']==['quote "','line\nbreak','ação']
    assert p.proposal.transport_evaluations[0]['monthly_tco_brl']==Decimal('0.00')


def test_published_service_fresh_audit_and_error_contract(monkeypatch):
    p,s,db=setup(monkeypatch)
    monkeypatch.setattr(c.AcademicService,'_snapshot',lambda *a,**k:s)
    service=object.__new__(c.PublishedRevision6Service)
    service.plan=p;service.repository=SimpleNamespace(session=db)
    assert service._snapshot(s.snapshot_id) is s
    db.rows['vehicles'][0]['operationally_active']=True
    with pytest.raises(AcademicUnavailable):service._snapshot(s.snapshot_id)


def test_regular_homologation_keeps_original_full_auditor(monkeypatch):
    p,s=fixture();called=[]
    service=object.__new__(h.Revision6Service);service.plan=p;service.repository=SimpleNamespace(session=object())
    monkeypatch.setattr(c.AcademicService,'_snapshot',lambda *a,**k:s)
    monkeypatch.setattr(h,'audit_snapshot',lambda *a:called.append(a))
    assert service._snapshot() is s and len(called)==1


@pytest.mark.parametrize('provider,expected_class',[('neon','cached'),('supabase','original')])
def test_deployment_factory_keeps_preflight_and_scopes_change_to_neon(monkeypatch,provider,expected_class):
    from app import deployment as d
    events=[]
    from app.academic_cohort import catalog_cache
    configured=SimpleNamespace(target={'provider':provider,'database_oid':24581,
        'runtime_role':'runtime','project_id':'synthetic-local-project'},
        url=SimpleNamespace(host='synthetic.invalid',port=5432),real_collection=False,
        plan_path='public-pinned-fixture',plan_sha256='a'*64)
    session=SimpleNamespace(connection=lambda:'synthetic_connection_not_a_database')
    monkeypatch.setattr(d,'settings',lambda:configured)
    monkeypatch.setattr(d,'database_preflight',lambda *a:events.append('preflight'))
    monkeypatch.setattr(d,'load_plan',lambda *a:events.append('pinned_plan') or object())
    def cached(*a,**kwargs):
        assert kwargs['scope']==('synthetic.invalid',5432,24581,'runtime','synthetic-local-project','a'*64)
        events.append('cached');return SimpleNamespace()
    def original(*a):events.append('original');return SimpleNamespace()
    monkeypatch.setattr(catalog_cache,'CachedPublishedRevision6Service',cached)
    monkeypatch.setattr(h,'Revision6Service',original)
    d.service_for_session(session)
    assert events==['preflight','pinned_plan',expected_class]
