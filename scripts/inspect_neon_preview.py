"""READ ONLY checks for a separately confirmed Neon target, no provisioning."""
import argparse
import json
import os
from pathlib import Path
import re
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'backend'),str(ROOT)]
from sqlalchemy import create_engine,text
from app import deployment as d
from app import neon_target as n
from app.release_manifest import verify_release


def inspect_empty(connection,configured):
    t=configured.target
    n.require(connection.engine.url==configured.url,'ENGINE_TARGET_DIFFERS')
    row=connection.execute(text("SELECT current_database(),current_user,(SELECT oid FROM pg_database WHERE datname=current_database()),"
        "b.pid,s.pid,s.ssl,s.version,s.cipher FROM (SELECT pg_backend_pid() AS pid)b LEFT JOIN pg_stat_ssl s ON s.pid=b.pid")).one()
    n.require(tuple(row[:3])==(n.DATABASE,n.RUNTIME,t['database_oid']), 'NEON_DATABASE_ROLE_OR_OID_DIFFERS')
    n.require(row[4] is not None and row[3]==row[4], 'NEON_OWN_BACKEND_TLS_ROW_REQUIRED')
    links=d.validate_connection_transport(connection,t,tuple(row[5:8]))
    n.validate_marker(connection,t)
    owner=connection.execute(text("SELECT r.rolname FROM pg_database db JOIN pg_roles r ON r.oid=db.datdba WHERE db.datname=current_database()")).scalar_one()
    n.require(owner==n.OWNER,'NEON_DATABASE_OWNER_DIFFERS')
    flags=connection.execute(text("SELECT rolname,rolcanlogin,rolsuper,rolbypassrls,rolcreatedb,rolcreaterole,rolreplication "
        "FROM pg_roles WHERE rolname IN ('sigra_research_owner','sigra_research_runtime') ORDER BY rolname")).all()
    n.require([tuple(r) for r in flags]==[(n.OWNER,True,False,False,False,False,False),
        (n.RUNTIME,True,False,False,False,False,False)],'NEON_CUSTOM_ROLES_NOT_MINIMAL')
    memberships=connection.execute(text("SELECT count(*) FROM pg_auth_members WHERE member IN "
        "(SELECT oid FROM pg_roles WHERE rolname IN ('sigra_research_owner','sigra_research_runtime'))")).scalar_one()
    n.require(memberships==0,'NEON_CUSTOM_ROLE_MEMBERSHIPS_FORBIDDEN')
    version=connection.execute(text("SELECT current_setting('server_version_num')::int")).scalar_one()
    n.require(version//10000==17,'NEON_EXPECTED_POSTGRES_MAJOR_DIFFERS')
    count=connection.execute(text("SELECT count(*) FROM pg_class c JOIN pg_namespace ns ON ns.oid=c.relnamespace "
        "WHERE ns.nspname NOT IN ('pg_catalog','information_schema') AND ns.nspname NOT LIKE 'pg_%' AND c.relkind IN ('r','p','v','m','S','f')")).scalar_one()
    n.require(count==0,'NEON_TARGET_NOT_NEW_EMPTY')
    return {'status':'NEON_EMPTY_TARGET_READONLY_APPROVED','database':n.DATABASE,'runtime':n.RUNTIME,
        'owner':n.OWNER,'database_oid':t['database_oid'],'tls':links,'application_relations':count,
        'migrations_applied':False,'database_modified':False}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--phase',choices=('empty','materialized'),required=True)
    args=parser.parse_args(argv)
    engine=None;stage='offline_release_and_identity'
    try:
        manifest=json.loads((ROOT/'release/manifest.json').read_text('utf-8'))
        verify_release(ROOT,ROOT/'release/manifest.json',manifest['release_id'])
        configured=d.settings()
        n.require(configured.target.get('provider')=='neon','NEON_ONLY')
        stage='readonly_connection'
        engine=create_engine(configured.url,echo=False,connect_args={'connect_timeout':8})
        with engine.connect() as connection, connection.begin():
            connection.execute(text('SET TRANSACTION READ ONLY'))
            stage='readonly_identity_tls_permissions_and_state'
            if args.phase=='empty':
                result=inspect_empty(connection,configured)
            else:
                result={'status':'NEON_MATERIALIZED_TARGET_READONLY_APPROVED',**d.database_preflight(connection,configured)}
                # Same approved full audit; do not reduce integrity checks to save egress.
                from sqlalchemy.orm import Session
                with Session(bind=connection) as session:
                    snapshot=d.service_for_session(session)._snapshot()
                    result.update(selected_count=snapshot.selected_count,profile_counts=snapshot.profile_counts)
                result['database_bytes']=connection.execute(text('SELECT pg_database_size(current_database())')).scalar_one()
        print(json.dumps(result));return 0
    except Exception as error:
        state=getattr(error,'sqlstate',None)
        if state is None:state=getattr(getattr(error,'orig',None),'sqlstate',None)
        print(json.dumps({'status':'NEON_READONLY_PREFLIGHT_BLOCKED','stage':stage,
            'code':error.code if isinstance(error,d.DeploymentBlocked) else 'NEON_READONLY_OPERATION_FAILED',
            'exception_kind':type(error).__name__,'sqlstate':state if isinstance(state,str) and re.fullmatch('[A-Z0-9]{5}',state) else None,
            'database_modified':False,'automatic_retry':False,'secret_values_reported':False}));return 1
    finally:
        if engine is not None:engine.dispose()


if __name__=='__main__':raise SystemExit(main())
