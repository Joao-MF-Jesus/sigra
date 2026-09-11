"""Current lifecycle: an identity review is never an activation certificate."""
from copy import deepcopy
from enum import StrEnum

from data_platform.catalog.crosswalk import fingerprint


class CatalogStage(StrEnum):
    IDENTITY = 'identity_approved'
    METHODOLOGY = 'methodology_ready'
    SOURCES = 'source_chain_published'
    POSTGRESQL = 'postgresql_validated'
    UI = 'ui_ready'
    ACTIVE = 'operationally_active'


def current_identity(historical_decision):
    """Translate a freshly computed v1 review, never rewrite historical reports.

    The old approval label meant only a FIPE/PBEV match plus demo imputation.
    Neither a demo formula nor a SQLite fixture promotes any later gate.
    """
    row = deepcopy(historical_decision)
    identity = row['status'] == 'approved_for_activation'
    row.pop('academic', None)
    row.pop('decision_fingerprint', None)
    row['status'] = CatalogStage.IDENTITY.value if identity else 'blocked_with_evidence'
    row['state_schema_version'] = 'catalog-readiness-v2'
    row['gates'] = {stage.value: identity if stage is CatalogStage.IDENTITY else False for stage in CatalogStage}
    row['activated'] = False
    row['human_approval_required'] = bool(row.get('target_changed'))
    row['human_approval_status'] = 'pending' if row['human_approval_required'] else 'not_applicable'
    row['crosswalk_evidence_fingerprint'] = fingerprint(row.get('review'))
    row['decision_fingerprint'] = fingerprint(row)
    return row


def require_operational_readiness(decision):
    """No caller can confuse a dossier status with all independent gates."""
    if decision.get('state_schema_version') != 'catalog-readiness-v2':
        raise ValueError('Current lifecycle evidence is required; historical approval is not activation readiness')
    gates = decision.get('gates', {})
    if any(gates.get(stage.value) is not True for stage in CatalogStage if stage is not CatalogStage.ACTIVE):
        raise ValueError('Identity alone does not satisfy methodology, sources, PostgreSQL and UI gates')
    if decision.get('human_approval_required') and decision.get('human_approval_status') != 'approved':
        raise ValueError('Explicit human approval of the target substitution is required')
    # Actual gate attestations/activation are intentionally not implemented in
    # this offline methodology step. Never permit forged boolean certificates.
    raise ValueError('Operational activation is disabled until verified gate attestations exist')
