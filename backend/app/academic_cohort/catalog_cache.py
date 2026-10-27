"""Bounded public-catalog reuse, validated against fresh PostgreSQL row versions.

No session, user, permission, history or recommendation result enters this cache.
A hit still requires a successful database stamp read. Expiry, DDL/row/version
changes or a failed stamp never fall back to stale data. No schema changes.
"""
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
import json
from threading import RLock
from time import monotonic
from types import SimpleNamespace
from uuid import UUID

from sqlalchemy import literal_column, select

from app.academic_cohort.contracts import json_document
from app.academic_cohort.models import CohortSnapshot, CohortVehicle, CohortEvaluation
from app.academic_cohort.revision6_homologation import (
    Revision6Service, audit_snapshot, audit_snapshot_metadata,
)
from app.academic_cohort.service import AcademicUnavailable, AcademicNotFound


# These are MVCC invalidation stamps, not content hashes/trust anchors. Full
# protected-field equality remains the existing audit_snapshot on every miss.
# PK + tableoid + xmin + ctid changes on UPDATE even if payload_fingerprint is
# left untouched. Structural metadata and the current 64-bit xid epoch prevent
# reuse across rewrites/schema evolution/wraparound. TTL is an additional bound.
STAMP = """encode(sha256(convert_to(jsonb_build_array(
    s.tableoid::text, s.xmin::text, s.ctid::text,
    (SELECT array_agg(ARRAY[v.catalog_id::text,v.tableoid::text,v.xmin::text,v.ctid::text]
        ORDER BY v.catalog_id) FROM academic.cohort_vehicle v WHERE v.snapshot_id=s.snapshot_id),
    (SELECT array_agg(ARRAY[e.catalog_id::text,e.profile,e.scenario,e.tableoid::text,e.xmin::text,e.ctid::text]
        ORDER BY e.catalog_id,e.profile,e.scenario) FROM academic.cohort_evaluation e WHERE e.snapshot_id=s.snapshot_id),
    (SELECT array_agg(ARRAY[c.oid::text,c.relfilenode::text,a.attnum::text,a.attname,
        a.atttypid::text,a.atttypmod::text,a.attnotnull::text,a.attisdropped::text]
        ORDER BY c.oid,a.attnum) FROM pg_catalog.pg_class c JOIN pg_catalog.pg_attribute a ON a.attrelid=c.oid
        WHERE c.oid IN ('academic.cohort_snapshot'::regclass,'academic.cohort_vehicle'::regclass,
            'academic.cohort_evaluation'::regclass) AND a.attnum>0)
    )::text,'UTF8')),'hex')"""


def read_stamp(session, plan, snapshot_id=None):
    if session.get_bind().dialect.name != "postgresql":
        raise ValueError("Catalogue reuse requires PostgreSQL")
    s = CohortSnapshot.__table__.alias("s")
    query = select(s, literal_column(STAMP).label("catalog_stamp"),
        literal_column("floor(pg_snapshot_xmax(pg_current_snapshot())::text::numeric / 4294967296)::bigint").label("xid_epoch"),
        literal_column("has_table_privilege(current_user,'academic.cohort_snapshot','SELECT') AND "
                       "has_table_privilege(current_user,'academic.cohort_vehicle','SELECT') AND "
                       "has_table_privilege(current_user,'academic.cohort_evaluation','SELECT')").label("catalog_read_allowed"))
    query = query.where(s.c.cohort_version == plan.proposal.candidate_version,
                        s.c.cohort_fingerprint == plan.proposal.candidate_fingerprint)
    if snapshot_id is not None:
        query = query.where(s.c.snapshot_id == snapshot_id)
    row = session.execute(query.order_by(s.c.created_at.desc(), s.c.snapshot_id).limit(1)).mappings().first()
    if row is None:
        if snapshot_id is not None:
            raise AcademicNotFound("Snapshot acadêmico não encontrado")
        raise AcademicUnavailable("Coorte acadêmica ainda não materializada")
    values = dict(row)
    if values.pop("catalog_read_allowed") is not True:
        raise ValueError("Current catalogue read permission unavailable; reuse prohibited")
    token = (values.pop("catalog_stamp"), values.pop("xid_epoch"))
    if not isinstance(token[0], str) or len(token[0]) != 64 or type(token[1]) is not int:
        raise ValueError("Catalogue version stamp unavailable")
    return SimpleNamespace(**values), token


def encode_row(model, row):
    # Explicit catalogue model columns only. Never ORM state or relationships.
    values = {column.name: getattr(row, column.name) for column in model.__table__.columns}
    values = {key: str(value) if isinstance(value, UUID) else value.isoformat() if isinstance(value, datetime)
              else value for key, value in values.items()}
    document = json_document(values)
    return json.dumps(document, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def decode_row(model, raw):
    document = json.loads(raw)
    document["snapshot_id"] = UUID(document["snapshot_id"])
    if model is CohortSnapshot:
        document["created_at"] = datetime.fromisoformat(document["created_at"])
    elif model is CohortVehicle:
        document["purchase_price_brl"] = Decimal(document["purchase_price_brl"])
    else:
        document["monthly_tco_brl"] = Decimal(document["monthly_tco_brl"])
        document["score"] = None if document["score"] is None else Decimal(document["score"])
    return SimpleNamespace(**document)


class _Capture:
    def __init__(self, session):
        self.session, self.rows = session, {}

    def scalars(self, query):
        model = query.column_descriptions[0]["entity"]
        if model not in (CohortVehicle, CohortEvaluation) or model in self.rows:
            raise ValueError("Unexpected catalogue audit query")
        # Ignore any stale ORM identity-map state in a reused caller transaction.
        rows = self.session.scalars(query.execution_options(populate_existing=True)).all()
        self.rows[model] = rows
        return SimpleNamespace(all=lambda: rows)


@dataclass(frozen=True, repr=False)
class Entry:
    stamp: tuple
    expires: float
    snapshot: bytes
    vehicles: tuple
    evaluations: tuple


class CatalogCache:
    def __init__(self, *, ttl=60.0, max_entries=2, clock=monotonic, lock_timeout=15.0):
        if ttl <= 0 or max_entries < 1:
            raise ValueError("Bounded catalogue cache required")
        self.ttl, self.maximum, self.clock, self.lock_timeout = ttl, max_entries, clock, lock_timeout
        self._entries, self._lock = OrderedDict(), RLock()

    def acquire(self, session, plan, scope, snapshot_id=None):
        # Holding this process-local lock single-flights concurrent cold loads.
        # No PostgreSQL locks, writes, retries or shared user state are involved.
        if not self._lock.acquire(timeout=self.lock_timeout):
            raise AcademicUnavailable("Validação do catálogo ocupada; nenhuma leitura antiga foi reutilizada")
        try:
            snapshot, stamp = read_stamp(session, plan, snapshot_id)
            audit_snapshot_metadata(snapshot, plan)  # Unchanged complete plan/header checks, including on hits.
            key = (tuple(scope), str(snapshot.snapshot_id), plan.proposal.candidate_version,
                   plan.proposal.candidate_fingerprint)
            now = self.clock()
            entry = self._entries.pop(key, None)
            if entry is not None and entry.stamp == stamp and now < entry.expires:
                self._entries[key] = entry
                return CatalogView(entry, session), snapshot, "hit"
            # Expired/changed entries are discarded before loading. No stale fallback.
            capture = _Capture(session)
            audit_snapshot(capture, snapshot, plan)  # Full original field comparison, two real SELECTs.
            after, after_stamp = read_stamp(session, plan, snapshot.snapshot_id)
            if stamp != after_stamp:
                raise AcademicUnavailable("Catálogo alterado durante a validação; resultado não reutilizado")
            audit_snapshot_metadata(after, plan)
            vehicles = tuple((row.catalog_id, encode_row(CohortVehicle, row))
                             for row in capture.rows[CohortVehicle])
            evaluations = tuple((row.catalog_id, row.profile, row.scenario, row.academic_test_ready,
                                 row.monthly_tco_brl, encode_row(CohortEvaluation, row))
                                for row in capture.rows[CohortEvaluation])
            entry = Entry(stamp, self.clock() + self.ttl, encode_row(CohortSnapshot, after), vehicles, evaluations)
            self._entries[key] = entry
            while len(self._entries) > self.maximum:
                self._entries.popitem(last=False)
            return CatalogView(entry, session), after, "miss"
        finally:
            self._lock.release()

    def clear(self):
        with self._lock:
            self._entries.clear()


class CatalogView:
    """Request-owned lazy clones of immutable public bytes, never an ORM session cache."""
    def __init__(self, entry, session):
        self.entry, self.session = entry, session

    def snapshot(self, snapshot_id=None):
        row = decode_row(CohortSnapshot, self.entry.snapshot)
        return row if snapshot_id is None or row.snapshot_id == snapshot_id else None

    def vehicles(self, snapshot_id, filters, limit, offset):
        rows = [decode_row(CohortVehicle, raw) for _, raw in self.entry.vehicles]
        rows = [r for r in rows if r.snapshot_id == snapshot_id
                and (filters.fipe_code is None or r.fipe_code == filters.fipe_code)
                and (filters.reference_month is None or r.reference_month == filters.reference_month)
                and (filters.max_purchase_price_brl is None or r.purchase_price_brl <= filters.max_purchase_price_brl)]
        if filters.profile is not None or filters.max_monthly_tco_brl is not None:
            eligible = {identifier for identifier, profile, scenario, ready, cost, _ in self.entry.evaluations
                        if profile == (filters.profile or "app") and scenario == filters.scenario and ready
                        and (filters.max_monthly_tco_brl is None or cost <= filters.max_monthly_tco_brl)}
            rows = [r for r in rows if r.catalog_id in eligible]
        rows.sort(key=lambda row: row.catalog_id)
        return rows[offset:offset+limit], len(rows)

    def vehicle(self, snapshot_id, catalog_id):
        for identifier, raw in self.entry.vehicles:
            if identifier == catalog_id:
                row = decode_row(CohortVehicle, raw)
                return row if row.snapshot_id == snapshot_id else None
        return None

    def evaluations(self, snapshot_id, *, profile=None, scenario=None, catalog_ids=None, ready_only=False):
        records = sorted(self.entry.evaluations, key=lambda r: (r[0], r[2], r[1]))
        return [row for identifier, p, s, ready, _, raw in records
                if (profile is None or p == profile) and (scenario is None or s == scenario)
                and (catalog_ids is None or identifier in catalog_ids) and (not ready_only or ready)
                and (row := decode_row(CohortEvaluation, raw)).snapshot_id == snapshot_id]


PUBLIC_CATALOG_CACHE = CatalogCache()


class CachedPublishedRevision6Service(Revision6Service):
    def __init__(self, repository, plan, *, scope, cache=None):
        super().__init__(repository, plan)
        self._source_repository, self._scope = repository, tuple(scope)
        self._cache = cache if cache is not None else PUBLIC_CATALOG_CACHE

    def _snapshot(self, snapshot_id=None):
        try:
            view, snapshot, _ = self._cache.acquire(self._source_repository.session, self.plan, self._scope, snapshot_id)
        except (ValueError, KeyError, TypeError):
            raise AcademicUnavailable("Candidata de homologação incompatível ou adulterada") from None
        self.repository = view
        return snapshot
