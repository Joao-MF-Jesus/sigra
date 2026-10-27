"""Offline persistence doubles: no server, SQLite or PostgreSQL connection."""
from copy import deepcopy
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import SQLAlchemyError

from app import participant_trials as trials


class Store:
    def __init__(self,fail=None):self.fail=fail;self.events=[]
    def add(self,row):self.row=row;self.events.append('add')
    def commit(self):
        self.events.append('commit')
        if self.fail=='commit':raise SQLAlchemyError('synthetic fixture')
        self.saved=deepcopy(self.row.presented_results)
    def refresh(self,row,*,attribute_names):
        self.events.append(('refresh',attribute_names))
        assert attribute_names==['id','created_at']
        if self.fail=='refresh':raise SQLAlchemyError('synthetic fixture')
    def rollback(self):self.events.append('rollback')


def test_receipt_projection_preserves_whole_result_fingerprints_and_commit(monkeypatch):
    monkeypatch.setattr(trials,'system_version',lambda:'synthetic-test-version')
    result={'algorithm_version':'test-v1','nested':{'null':None,'zero':0,'text':'ação\n"quote"'},'rows':list(range(1000))}
    parameters={'scenario':'base'}
    before=deepcopy(result);db=Store()
    answer=trials.record_result(db,SimpleNamespace(id=1),'recommendation',parameters,result)
    assert db.saved==before and result==before
    assert db.row.request_fingerprint==trials.fingerprint(parameters)
    assert db.row.result_fingerprint==trials.fingerprint(before)
    assert db.row.user_id==1
    assert db.events==['add','commit',('refresh',['id','created_at'])]
    assert answer=={**before,'test_run':{'id':db.row.id,'created_at':trials.utc_iso(db.row.created_at),
        'saved':True,'questionnaire_required':False}}


@pytest.mark.parametrize('failure',['commit','refresh'])
def test_existing_error_contract_not_replaced_by_success(monkeypatch,failure):
    monkeypatch.setattr(trials,'system_version',lambda:'synthetic-test-version')
    db=Store(failure)
    with pytest.raises(HTTPException) as error:
        trials.record_result(db,SimpleNamespace(id=1),'recommendation',{}, {'rows':[]})
    assert error.value.status_code==503 and db.events[-1]=='rollback'


def test_owner_filter_remains_required_for_full_detail():
    class Query:
        def filter_by(self,**filters):self.filters=filters;return self
        def first(self):return 'owned_row' if self.filters=={'id':'fictitious','user_id':1} else None
    db=SimpleNamespace(query=lambda *_:Query())
    assert trials.owned_run(db,SimpleNamespace(id=1),'fictitious')=='owned_row'
    with pytest.raises(HTTPException) as error:trials.owned_run(db,SimpleNamespace(id=2),'fictitious')
    assert error.value.status_code==404
