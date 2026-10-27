"""Explicit transport evidence models. Never upgrades an observation to true.

Only the exact, separately accepted fictitious Neon target may use documentary
internal-transport assurance. The strict PostgreSQL TLS model is unchanged.
"""
import hashlib
import json
import os
from pathlib import Path

STRICT = 'strict-postgresql-tls-v1'
MANAGED = 'neon-managed-preview-v1'
# Filled from the separate, immutable human decision when this candidate is sealed.
ACCEPTANCE_SHA256 = '8d278f21d9bc4e8be02b06f2e88ef0d3542acc07a2c2b99454cd36c6d7d4e839'
IDENTITY = {
    'organization_id': 'org-morning-wave-65946706',
    'project_id': 'young-haze-62223574',
    'branch_id': 'br-icy-frog-b6jetlre',
    'endpoint_id': 'ep-round-glade-b6bhigmc',
    'host': 'ep-round-glade-b6bhigmc.c-2.sa-east-1.aws.neon.tech',
}
KEYS = ('host', 'port', 'dbname', 'user', 'sslmode', 'sslrootcert', 'sslsni', 'channel_binding')


def require(condition, code):
    if not condition:
        from app.deployment import DeploymentBlocked
        raise DeploymentBlocked(code)


def acceptance():
    configured = os.environ.get('SIGRA_NEON_TRANSPORT_ACCEPTANCE_FILE')
    path = Path(configured) if configured else Path(__file__).resolve().parents[2] / 'release/neon-transport-acceptance.json'
    try:
        data = path.read_bytes()
    except OSError:
        require(False, 'NEON_TRANSPORT_ACCEPTANCE_UNREADABLE')
    require(hashlib.sha256(data).hexdigest() == ACCEPTANCE_SHA256, 'NEON_TRANSPORT_ACCEPTANCE_CHANGED')
    value = json.loads(data)
    require(value.get('decision') == 'accepted_by_user_explicitly'
            and value.get('model') == MANAGED
            and value.get('internal_mechanism_verified') is False
            and value.get('postgres_tls_equivalence_claimed') is False
            and value.get('real_collection_authorized') is False,
            'NEON_TRANSPORT_ACCEPTANCE_INVALID')
    return value


def validate_selection(values, target):
    model = target.get('transport_model', STRICT)
    selected = values.get('SIGRA_NEON_TRANSPORT_MODEL', STRICT)
    require(selected == model and model in {STRICT, MANAGED}, 'NEON_EXPLICIT_TRANSPORT_SELECTION_DIFFERS')
    if model == MANAGED:
        validate_managed_target(target)
        require(values.get('SIGRA_NEON_TRANSPORT_ACCEPTANCE_SHA256') == ACCEPTANCE_SHA256,
                'NEON_EXPLICIT_TRANSPORT_ACCEPTANCE_REQUIRED')
        require(values.get('SIGRA_RESEARCH_COLLECTION_ENABLED') == 'false'
                and values.get('SIGRA_TCC_COLLECTION_MODE') == 'homologation', 'NEON_MANAGED_FICTITIOUS_ONLY')
    return model


def validate_managed_target(target):
    accepted = acceptance()
    require(target.get('transport_acceptance_sha256') == ACCEPTANCE_SHA256,
            'NEON_EXPLICIT_TRANSPORT_ACCEPTANCE_REQUIRED')
    require(target.get('provider') == 'neon'
            and all(target.get(key) == value == accepted.get(key) for key, value in IDENTITY.items())
            and target.get('plan') == accepted.get('plan') == 'free'
            and target.get('purpose') == accepted.get('purpose') == 'fictitious_preview'
            and target.get('research_release_authorized') is False,
            'NEON_MANAGED_ACCEPTED_TARGET_DIFFERS')


def effective_parameters(driver):
    """Full live PQconninfo, not get_parameters()'s default-filtered view."""
    allowed = {key.encode('ascii'): key for key in KEYS}
    values = {}
    for option in driver.pgconn.info:
        key = allowed.get(option.keyword)
        if key is not None:
            require(key not in values, 'NEON_EFFECTIVE_PARAMETER_DUPLICATE')
            values[key] = option.val.decode('utf-8') if option.val is not None else None
    return values


def backend_evidence(target, backend_tls):
    require(isinstance(backend_tls, (tuple, list)) and len(backend_tls) == 3
            and type(backend_tls[0]) is bool, 'NEON_BACKEND_TLS_OBSERVATION_MALFORMED')
    secured, version, cipher = backend_tls
    model = target.get('transport_model', STRICT)
    require(model in {STRICT, MANAGED}, 'NEON_EXPLICIT_TRANSPORT_SELECTION_DIFFERS')
    if model == MANAGED:
        validate_managed_target(target)
    if secured:
        require(version in {'TLSv1.2', 'TLSv1.3'} and isinstance(cipher, str) and bool(cipher),
                'NEON_BACKEND_TLS_VERSION_OR_CIPHER_MISSING')
    elif model == STRICT:
        require(False, 'NEON_BACKEND_TLS_NOT_CONFIRMED')
    else:
        require(version is None and cipher is None, 'NEON_FALSE_BACKEND_TLS_DETAILS_INCONSISTENT')
    result = {
        'model': model, 'client_tls': True,
        'client_tls_scope': 'client_to_neon_endpoint',
        'backend_tls': secured, 'postgres_observed_ssl': secured,
        'postgres_observed_version': version, 'postgres_cipher_present': bool(cipher),
        'backend_tls_scope': 'postgresql_backend_connection',
        'all_observed_links_tls': secured,
        'uninterrupted_end_to_end_tls_claimed': False,
        'postgres_tls_equivalence_claimed': False,
    }
    if model == MANAGED:
        result.update(acceptance_sha256=ACCEPTANCE_SHA256,
                      internal_transport_basis='documentary_provider_assurance',
                      internal_transport_source='https://neon.com/security',
                      internal_mechanism_verified=False,
                      real_collection_authorized=False)
    else:
        result['internal_transport_basis'] = 'postgresql_observation'
    return result
