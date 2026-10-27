"""Exact server-side row comparison, not a cache or fingerprint-only audit.

Send the already validated, release-pinned public catalogue as bind data; fetch
only two booleans instead of downloading every payload on every audit. No SQL
writes, new privileges, trust-anchor changes or cross-user/request cache.
"""
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy import bindparam

from app.academic_cohort.contracts import json_document
from app.academic_cohort.revision6_homologation import (
    Revision6Service, audit_snapshot_metadata,
)
from app.academic_cohort.service import AcademicService, AcademicUnavailable


# Identifiers and record types are fixed source code, never supplied by callers.
SPECS = {
    "vehicles": ("cohort_vehicle", (
        ("catalog_id", "integer"), ("canonical_identity_key", "text"),
        ("fipe_code", "text"), ("year_code", "text"), ("label", "text"),
        ("purchase_price_brl", "numeric"), ("reference_month", "text"),
        ("payload", "jsonb"), ("payload_fingerprint", "text"),
        ("operationally_active", "boolean"), ("recommended", "boolean"))),
    "evaluations": ("cohort_evaluation", (
        ("catalog_id", "integer"), ("profile", "text"), ("scenario", "text"),
        ("academic_test_ready", "boolean"), ("score", "numeric"),
        ("monthly_tco_brl", "numeric"), ("payload", "jsonb"),
        ("payload_fingerprint", "text"),
        ("operationally_active", "boolean"), ("recommended", "boolean"))),
}


def comparison_query(kind):
    table, fields = SPECS[kind]
    names = ", ".join(name for name, _ in fields)
    definitions = ", ".join(name + " " + sql_type for name, sql_type in fields)
    # EXCEPT ALL in both directions detects missing, extra, duplicate and
    # changed rows, including full JSONB payload, every scalar and both flags.
    # JSONB equality ignores only object-key order, as Python dict equality did.
    return text(f"""WITH expected AS (
        SELECT * FROM jsonb_to_recordset(CAST(:expected AS jsonb)) AS e({definitions})
    ), actual AS (
        SELECT {names} FROM academic.{table} WHERE snapshot_id = :snapshot_id
    )
    SELECT NOT EXISTS (
        (SELECT {names} FROM actual EXCEPT ALL SELECT {names} FROM expected)
        UNION ALL
        (SELECT {names} FROM expected EXCEPT ALL SELECT {names} FROM actual)
    ) AS exact_match""").bindparams(bindparam("expected", type_=JSONB))


def expected_records(kind, plan):
    rows = (plan.proposal.transport_vehicles if kind == "vehicles"
            else plan.proposal.transport_evaluations)
    fields = {name for name, _ in SPECS[kind][1]} - {"operationally_active", "recommended"}
    # Fail closed if future transport evolves; don't silently drop a new field.
    if any(set(row) != fields for row in rows):
        raise ValueError("Compact audit transport fields differ")
    return json_document([{**row, "operationally_active": False, "recommended": False}
                          for row in rows])


def audit_snapshot_compact(session, snapshot, plan):
    audit_snapshot_metadata(snapshot, plan)  # Includes unchanged full plan validation.
    if session.get_bind().dialect.name != "postgresql":
        raise ValueError("Compact audit requires PostgreSQL")
    for kind in SPECS:
        matched = session.execute(comparison_query(kind), {
            "snapshot_id": snapshot.snapshot_id, "expected": expected_records(kind, plan),
        }).scalar_one()
        if matched is not True:
            raise ValueError("Revision6 persisted evidence/metadata changed")


class PublishedRevision6Service(Revision6Service):
    """Fresh exact audit per snapshot read. No stale-data success fallback."""
    def _snapshot(self, snapshot_id=None):
        row = AcademicService._snapshot(self, snapshot_id)
        try:
            audit_snapshot_compact(self.repository.session, row, self.plan)
        except (ValueError, KeyError, TypeError):
            raise AcademicUnavailable("Candidata de homologação incompatível ou adulterada") from None
        return row
