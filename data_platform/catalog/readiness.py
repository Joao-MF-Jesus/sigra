"""Current lifecycle: an identity review is never an activation certificate."""
from copy import deepcopy
from datetime import date
from enum import StrEnum
import json
from pathlib import Path

from data_platform.catalog.crosswalk import fingerprint


CHANGE_CONTROL_PATH = Path(__file__).with_name('change_control_v2.json')


def _human_approval(decision):
    if not decision.get('target_changed'):
        return False, 'not_applicable'
    control = json.loads(CHANGE_CONTROL_PATH.read_text(encoding='utf-8'))
    matches = [row for row in control['changes'] if row['candidate_id'] == decision['id']]
    if len(matches) != 1 or matches[0].get('human_approval_required') is not True:
        raise ValueError('Changed catalog target requires one change-control entry')
    change = matches[0]
    status = change.get('human_approval_status')
    if status not in {'pending', 'human_approved'}:
        raise ValueError('Invalid human approval status')
    if status == 'human_approved':
        receipt = change.get('approval_receipt')
        if not isinstance(receipt, dict) or receipt.get('decision') != 'human_approved':
            raise ValueError('Approved substitution requires an explicit receipt')
        if not all(isinstance(receipt.get(key), str) and receipt[key].strip()
                   for key in ('approved_by', 'recorded_at', 'authorization_reference', 'scope')):
            raise ValueError('Human approval receipt is incomplete')
        if not isinstance(change.get('justification'), str) or not change['justification'].strip():
            raise ValueError('Human approval justification is required')
        date.fromisoformat(receipt['recorded_at'])
    elif change.get('approval_receipt') is not None:
        raise ValueError('Pending substitution cannot carry an approval receipt')
    return True, status


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
    row['human_approval_required'], row['human_approval_status'] = _human_approval(row)
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
    if decision.get('human_approval_required') and decision.get('human_approval_status') != 'human_approved':
        raise ValueError('Explicit human approval of the target substitution is required')
    # Actual gate attestations/activation are intentionally not implemented in
    # this offline methodology step. Never permit forged boolean certificates.
    raise ValueError('Operational activation is disabled until verified gate attestations exist')
