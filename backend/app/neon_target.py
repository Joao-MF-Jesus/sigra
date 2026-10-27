"""Fail-closed Neon preview contract. No inferred endpoint, network or DDL here.

An independently pinned receipt and explicit identity confirmations are required.
Direct means non-PgBouncer, not a claim that Neon's proxy is bypassed.
"""
import os
from pathlib import Path
import re
from uuid import UUID

from sqlalchemy.engine import make_url

PROJECT_NAME = 'sigra-tcc-preview-ficticio'
DATABASE = 'sigra_tcc_research'  # existing separate-target name; fictitious only
OWNER = 'sigra_research_owner'
RUNTIME = 'sigra_research_runtime'
MARKER_PREFIX = 'sigra-neon-preview-v1:'


def require(condition, code):
    if not condition:
        from app.deployment import DeploymentBlocked
        raise DeploymentBlocked(code)


def validate_target(values, target):
    from app.neon_transport import validate_selection
    validate_selection(values, target)
    require(values.get('SIGRA_DEPLOY_PROVIDER') == 'neon', 'EXPLICIT_NEON_PROVIDER_REQUIRED')
    require(target.get('schema') == 'sigra-neon-deploy-target-v1'
            and target.get('provider') == 'neon' and target.get('confirmed') is True,
            'CONFIRMED_NEON_RECEIPT_REQUIRED')
    for field, env in (
        ('organization_id','SIGRA_NEON_ORGANIZATION_ID'),
        ('project_id','SIGRA_NEON_PROJECT_ID'), ('branch_id','SIGRA_NEON_BRANCH_ID'),
        ('endpoint_id','SIGRA_NEON_ENDPOINT_ID'), ('host','SIGRA_NEON_HOST'),
    ):
        value=target.get(field)
        require(isinstance(value,str) and bool(re.fullmatch(r'[a-z0-9][a-z0-9.-]{3,253}',value))
                and not any(word in value for word in ('placeholder','unconfigured','example','replace'))
                and value == values.get(env), 'NEON_EXPLICIT_IDENTITY_CONFIRMATION_DIFFERS')
    require(target['branch_id'].startswith('br-') and target['endpoint_id'].startswith('ep-'),
            'NEON_BRANCH_OR_ENDPOINT_ID_INVALID')
    require(target.get('project_name') == PROJECT_NAME and target.get('region') == 'aws-sa-east-1'
            and target.get('plan') == 'free' and target.get('purpose') == 'fictitious_preview',
            'NEON_PREVIEW_PLAN_REGION_OR_PURPOSE_DIFFERS')
    host=target['host']
    # Suffix/region checks alone never authorize a host: exact external match above
    # and pinned target bytes remain mandatory. Do not infer any hostname here.
    require(host.startswith(target['endpoint_id']+'.')
            and host.endswith('.sa-east-1.aws.neon.tech') and '-pooler' not in host
            and target.get('endpoint_mode') == 'direct' and type(target.get('port')) is int
            and target['port'] == 5432, 'EXACT_DIRECT_NEON_ENDPOINT_REQUIRED')
    require(target.get('profile') == 'research' and target.get('database') == DATABASE
            and target.get('owner_role') == OWNER and target.get('runtime_role') == RUNTIME
            and target.get('research_release_authorized') is False
            and values.get('SIGRA_RESEARCH_COLLECTION_ENABLED') == 'false'
            and values.get('SIGRA_TCC_COLLECTION_MODE') == 'homologation', 'NEON_FICTITIOUS_ONLY')
    require(type(target.get('database_oid')) is int and target['database_oid']>0
            and str(target['database_oid']) == values.get('SIGRA_NEON_DATABASE_OID')
            and target.get('alembic_revision') == '20261007_0015', 'NEON_DATABASE_OID_OR_REVISION_REQUIRED')
    marker=target.get('database_comment','')
    try:
        valid=marker.startswith(MARKER_PREFIX) and str(UUID(marker[len(MARKER_PREFIX):])) == marker[len(MARKER_PREFIX):]
    except (ValueError,TypeError,AttributeError):
        valid=False
    require(valid and marker == values.get('SIGRA_NEON_DATABASE_COMMENT'), 'NEON_DATABASE_MARKER_REQUIRED')
    require(target.get('quota_checked') is True and target.get('sslmode') == 'verify-full'
            and isinstance(target.get('ca_sha256'),str)
            and bool(re.fullmatch('[0-9a-f]{64}',target['ca_sha256'])), 'NEON_TLS_OR_QUOTA_RECEIPT_REQUIRED')


def runtime_url(values, target):
    validate_target(values,target)
    require(not any(values.get(k) for k in ('PGHOSTADDR','PGSERVICE','PGSERVICEFILE')),
            'NEON_AMBIENT_CONNECTION_OVERRIDE_FORBIDDEN')
    try:
        url=make_url(values.get('DATABASE_URL',''))
    except Exception:
        require(False,'PRIVATE_NEON_RUNTIME_URL_REQUIRED')
    require(url.drivername=='postgresql+psycopg' and url.host==target['host']
            and url.port==5432 and url.database==DATABASE and url.username==RUNTIME
            and bool(url.password), 'NEON_RUNTIME_IDENTITY_DIFFERS')
    require(set(url.query)=={'sslmode','sslrootcert','sslsni','channel_binding'}
            and url.query['sslmode']=='verify-full' and url.query['sslsni']=='1'
            and url.query['channel_binding']=='require'
            and isinstance(url.query['sslrootcert'],str) and Path(url.query['sslrootcert']).is_absolute(),
            'NEON_VERIFY_FULL_CA_AND_SNI_REQUIRED')
    return url


def validate_tls(connection, target, backend_tls):
    """Client TLS and PostgreSQL backend TLS are separate observations, even direct."""
    driver=connection.connection.driver_connection
    from app.neon_transport import effective_parameters, backend_evidence
    parameters=effective_parameters(driver)
    require(driver.pgconn.ssl_in_use is True, 'NEON_CLIENT_TLS_NOT_ESTABLISHED')
    require(connection.engine.url.username in {OWNER,RUNTIME}, 'NEON_CONNECTION_ROLE_DIFFERS')
    expected={'host':target['host'],'port':'5432','dbname':target['database'],
              'user':connection.engine.url.username,'sslmode':'verify-full',
              'sslrootcert':connection.engine.url.query['sslrootcert'],'sslsni':'1','channel_binding':'require'}
    require(all(parameters.get(k)==v for k,v in expected.items()), 'NEON_EFFECTIVE_TLS_OR_SNI_DIFFERS')
    require(not os.environ.get('PGHOSTADDR'), 'NEON_AMBIENT_CONNECTION_OVERRIDE_FORBIDDEN')
    return {'endpoint_mode':'direct_non_pgbouncer', **backend_evidence(target,backend_tls)}


def validate_marker(connection, target):
    from sqlalchemy import text
    observed=connection.execute(text("SELECT pg_catalog.shobj_description("
        "(SELECT oid FROM pg_database WHERE datname=current_database()),'pg_database')")).scalar_one()
    require(observed == target['database_comment'], 'NEON_DATABASE_MARKER_DIFFERS')
