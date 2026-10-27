"""Explicit, dedicated PostgreSQL homologation of an INACTIVE documentary snapshot.

This module never changes the approved V6 loader or its trust anchor. The
preparation proposal still rejects writes; only this separate, guarded importer
can persist a validated Revision6 in a new, dedicated test database.
"""
from copy import deepcopy
from dataclasses import dataclass
from functools import lru_cache
import os
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.academic_cohort.contracts import method_manifest, validate_replay
from app.academic_cohort.materialization import MaterializationReceipt
from app.academic_cohort.models import CohortSnapshot, CohortVehicle, CohortEvaluation
from app.academic_cohort.repository import AcademicRepository
from app.academic_cohort.service import AcademicService, AcademicUnavailable
from app.academic_cohort import safety_revision6 as preparation
from app.config import _boolean
from app.tcc_supabase import APP_SCHEMAS, PRIVATE_TABLES, PERSONAL_SEQUENCES
from data_platform.catalog.profile_pilot_v4 import fingerprint

DATABASE = "sigra_revision6_homologation_test"
OWNER = "sigra_revision6_owner"
RUNTIME = "sigra_revision6_runtime"
ALEMBIC_HEAD = "20261007_0015"


def enabled(values=None):
    values = os.environ if values is None else values
    return _boolean(values.get("SIGRA_REVISION6_HOMOLOGATION_ENABLED"), default=False,
                    variable_name="SIGRA_REVISION6_HOMOLOGATION_ENABLED")


@dataclass(frozen=True, repr=False)
class DedicatedTarget:
    migration_url: object
    runtime_url: object
    remote_confirmation: object = None

    def check_bind(self, bind, *, writer=False):
        expected = self.migration_url if writer else self.runtime_url
        # str(URL) masks the password; compare URL objects, never their rendering.
        if bind.dialect.name != "postgresql" or bind.url != expected:
            raise ValueError("Revision6 bind is not the dedicated target/role")
        if self.remote_confirmation is not None:
            from app.academic_cohort.revision6_supabase_target import validate_url
            validate_url(expected, OWNER if writer else RUNTIME, self.remote_confirmation)


def target_configuration(values=None):
    """Offline validation only. Neither a credential nor a URL is logged."""
    values = os.environ if values is None else values
    if (values.get("SIGRA_REVISION6_CONFIRM_DATABASE") != DATABASE
            or values.get("SIGRA_REVISION6_PARTICIPANTS") != "fictitious_only"
            or values.get("DATABASE_ENV") not in {"test", "integration"}
            or values.get("SIGRA_TCC_COLLECTION_MODE", "disabled") not in {"disabled", "homologation"}):
        raise ValueError("Explicit dedicated test target/fictitious collection configuration required")
    urls = []
    kind = values.get("SIGRA_REVISION6_TARGET_KIND", "local")
    if kind not in {"local", "supabase"}:
        raise ValueError("Unknown Revision6 target kind")
    remote = None
    if kind == "supabase":
        from app.academic_cohort.revision6_supabase_target import load_confirmation
        remote = load_confirmation(values)
    for name, role in (("SIGRA_REVISION6_MIGRATION_URL", OWNER), ("SIGRA_REVISION6_RUNTIME_URL", RUNTIME)):
        wire_username = remote.username_for(role) if remote is not None else role
        try:
            url = make_url(values.get(name, ""))
        except Exception:
            raise ValueError(f"{name} missing or invalid; value withheld") from None
        if (url.drivername not in {"postgresql", "postgresql+psycopg"}
                or (remote is None and url.host not in {"localhost", "127.0.0.1", "::1"}) or url.database != DATABASE
                or url.username != wire_username or not url.password or url.port is None):
            raise ValueError(f"{name} must identify the exact NEW dedicated PostgreSQL target and role; value withheld")
        if any(key not in {"sslmode", "sslrootcert"} for key in url.query):
            raise ValueError("Unexpected database URL options")
        if any(not isinstance(value, str) for value in url.query.values()):
            raise ValueError("Duplicate database URL option")
        if remote is not None:
            from app.academic_cohort.revision6_supabase_target import validate_url
            validate_url(url, role, remote)
        urls.append(url.set(drivername="postgresql+psycopg"))
    if (urls[0].host, urls[0].port, urls[0].database) != (urls[1].host, urls[1].port, urls[1].database):
        raise ValueError("Migration/runtime endpoints differ")
    return DedicatedTarget(*urls, remote_confirmation=remote)


def require_runtime(values=None):
    values = os.environ if values is None else values
    target = target_configuration(values)
    try:
        actual = make_url(values.get("DATABASE_URL", "")).set(drivername="postgresql+psycopg")
    except Exception:
        raise ValueError("Runtime DATABASE_URL missing; no fallback") from None
    if actual != target.runtime_url:
        raise ValueError("DATABASE_URL differs from the pinned runtime target")
    return target


def assert_fictitious_email(email):
    if enabled():
        require_runtime()
        if not str(email).casefold().endswith((".test", ".invalid")):
            raise ValueError("Revision6 homologation accepts fictitious .test/.invalid accounts only")


@dataclass(frozen=True)
class Revision6Plan:
    proposal: preparation.InactiveRevision6Proposal
    replay: dict
    approved_replay: dict

    @property
    def source_manifest(self):
        return method_manifest()

    @property
    def summary(self):
        result = deepcopy(validate_replay(self.approved_replay).summary)
        result["revision6_homologation"] = {
            "candidate_fingerprint": self.proposal.candidate_fingerprint,
            "approved_reference_fingerprint": self.proposal.approved_reference_fingerprint,
            "source_inventory_sha256": self.proposal.source_inventory_sha256,
            "coverage_decision": deepcopy(self.proposal.coverage_decision),
            "homologation_write_scope": "new_dedicated_local_test_only",
            "real_collection_enabled": False, "candidate_approved": False,
        }
        return result


def build_plan(bundle, decision):
    proposal = preparation.prepare_revision6(bundle, decision)
    root = Path(bundle).resolve(strict=True)
    plan = Revision6Plan(proposal, preparation._read(root / "experimental/replay.json"),
                         preparation._read(root / preparation.APPROVED_PATH))
    validate_plan(plan)
    return plan


def validate_plan(plan):
    """A frozen dataclass is not sufficient: nested dicts may still be changed."""
    policy = preparation._read(preparation.CONTRACT)
    if not isinstance(plan, Revision6Plan):
        raise ValueError("Separate Revision6 plan required")
    preparation._validate_payloads(plan.approved_replay, plan.replay, plan.proposal.coverage_decision, policy)
    if (plan.proposal.candidate_version != policy["candidate_version"]
            or plan.proposal.candidate_fingerprint != policy["candidate_fingerprint"]
            or plan.proposal.approved_reference_fingerprint != policy["approved_v6_fingerprint"]
            or plan.proposal.source_inventory_sha256 != policy["bundle_inventory_sha256"]
            or plan.proposal.profile_counts != policy["profile_counts"]):
        raise ValueError("Revision6 metadata changed")
    vehicles = plan.proposal.transport_vehicles
    evaluations = plan.proposal.transport_evaluations
    if (len(vehicles) != 60 or len(evaluations) != 1080
            or len({r["catalog_id"] for r in vehicles}) != 60
            or len({(r["catalog_id"], r["profile"], r["scenario"]) for r in evaluations}) != 1080):
        raise ValueError("Incomplete or duplicate transport")
    by_id = {item["vehicle"]["id"]: item for item in plan.replay["academic_payload"]}
    for row in vehicles:
        payload = by_id[row["catalog_id"]]["vehicle"]
        fields = payload["fields"]
        expected = {"catalog_id": payload["id"], "payload": payload,
                    "payload_fingerprint": fingerprint(payload), "label": payload["label"],
                    "fipe_code": fields["fipe_code"]["value"], "year_code": fields["year_code"]["value"],
                    "reference_month": fields["reference_month"]["value"],
                    "purchase_price_brl": fields["price_brl"]["value"],
                    "canonical_identity_key": fingerprint({key: fields[key]["value"] for key in
                        ("fipe_code", "year_code", "commercial_identity", "fuel", "transmission")})}
        if fingerprint(row) != fingerprint(expected):
            raise ValueError("Vehicle transport differs from pinned replay")
    for row in evaluations:
        payload = by_id[row["catalog_id"]]["evaluations"][row["scenario"]][row["profile"]]
        expected = {"catalog_id": payload["id"], "profile": payload["profile"], "scenario": payload["scenario"],
                    "academic_test_ready": payload["academic_test_ready"], "score": payload["preview_score"],
                    "monthly_tco_brl": payload["scenario_monthly_tco_brl"],
                    "payload": payload, "payload_fingerprint": fingerprint(payload)}
        if fingerprint(row) != fingerprint(expected):
            raise ValueError("Evaluation transport differs from pinned replay")


def audit_snapshot_metadata(snapshot, plan):
    validate_plan(plan)
    if (snapshot.cohort_version != plan.proposal.candidate_version
            or snapshot.cohort_fingerprint != plan.proposal.candidate_fingerprint
            or snapshot.selected_count != 60 or snapshot.profile_counts != plan.proposal.profile_counts
            or snapshot.source_manifest != plan.source_manifest
            or snapshot.method_fingerprint != fingerprint(plan.source_manifest)
            or snapshot.inventory_summary != plan.summary
            or snapshot.operationally_active or snapshot.recommended):
        raise ValueError("Revision6 snapshot differs from the pinned plan")


def audit_snapshot(session, snapshot, plan):
    audit_snapshot_metadata(snapshot, plan)
    for model, expected, key in (
        (CohortVehicle, plan.proposal.transport_vehicles, lambda row: row.catalog_id),
        (CohortEvaluation, plan.proposal.transport_evaluations, lambda row: (row.catalog_id, row.profile, row.scenario)),
    ):
        actual = session.scalars(select(model).where(model.snapshot_id == snapshot.snapshot_id)).all()
        expected_by_key = {row["catalog_id"] if model is CohortVehicle else
                           (row["catalog_id"], row["profile"], row["scenario"]): row for row in expected}
        if len(actual) != len(expected) or {key(row) for row in actual} != set(expected_by_key):
            raise ValueError("Revision6 persisted grain differs")
        for row in actual:
            if row.operationally_active or row.recommended:
                raise ValueError("Candidate operational flags prohibited")
            for field, value in expected_by_key[key(row)].items():
                if getattr(row, field) != value:
                    raise ValueError("Revision6 persisted evidence/metadata changed")


def _materialize_plan(session, plan):
    """Caller owns the atomic transaction; only called after target/proof checks."""
    validate_plan(plan)
    existing = session.scalar(select(CohortSnapshot).where(
        CohortSnapshot.cohort_version == plan.proposal.candidate_version,
        CohortSnapshot.cohort_fingerprint == plan.proposal.candidate_fingerprint))
    if existing is not None:
        audit_snapshot(session, existing, plan)
        return MaterializationReceipt("already_materialized", existing.snapshot_id,
                                      plan.proposal.candidate_fingerprint, 60, 1080, False)
    snapshot = CohortSnapshot(snapshot_id=uuid4(), cohort_version=plan.proposal.candidate_version,
        cohort_fingerprint=plan.proposal.candidate_fingerprint, method_fingerprint=fingerprint(plan.source_manifest),
        source_manifest=plan.source_manifest, inventory_summary=plan.summary, selected_count=60,
        profile_counts=deepcopy(plan.proposal.profile_counts), operationally_active=False, recommended=False)
    session.add(snapshot)
    session.flush()
    session.add_all(CohortVehicle(snapshot_id=snapshot.snapshot_id, **deepcopy(row),
                    operationally_active=False, recommended=False) for row in plan.proposal.transport_vehicles)
    session.flush()
    session.add_all(CohortEvaluation(snapshot_id=snapshot.snapshot_id, **deepcopy(row),
                    operationally_active=False, recommended=False) for row in plan.proposal.transport_evaluations)
    session.flush()
    audit_snapshot(session, snapshot, plan)
    return MaterializationReceipt("materialized", snapshot.snapshot_id,
                                  plan.proposal.candidate_fingerprint, 60, 1080, True)


def _connection_target(connection, target=None):
    if target is None and getattr(connection, "engine", None) is not None:
        target = target_configuration()
    return target


def require_database_identity(connection, *, writer=False, target=None):
    target = _connection_target(connection, target)
    if target is not None:
        target.check_bind(connection.engine, writer=writer)
    expected = OWNER if writer else RUNTIME
    identity = connection.execute(text("SELECT current_database(), current_user")).one()
    if tuple(identity) != (DATABASE, expected):
        raise ValueError("Connected database/role differs from dedicated target")
    flags = connection.execute(text("SELECT rolsuper, rolbypassrls, rolcreatedb, rolcreaterole, rolreplication "
                                    "FROM pg_roles WHERE rolname = current_user")).one()
    if any(flags):
        raise ValueError("Dedicated roles must not be privileged")
    if target is not None and target.remote_confirmation is not None:
        from app.academic_cohort.revision6_supabase_target import validate_connection_tls
        tls = connection.execute(text("SELECT ssl, version, cipher FROM pg_stat_ssl WHERE pid=pg_backend_pid()")).one()
        validate_connection_tls(target.remote_confirmation,
            bool(getattr(connection.connection.driver_connection.pgconn, "ssl_in_use", False)), tls)
    return int(connection.execute(text("SELECT oid FROM pg_database WHERE datname=current_database()")).scalar_one())


def require_empty_target(connection, target=None):
    target = _connection_target(connection, target)
    oid = require_database_identity(connection, writer=True, target=target)
    existing = connection.execute(text("SELECT n.nspname, c.relname FROM pg_class c "
        "JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname NOT IN ('pg_catalog','information_schema') "
        "AND n.nspname NOT LIKE 'pg_%' AND c.relkind IN ('r','p','v','m','S','f')")).all()
    if existing:
        raise ValueError("Target is not NEW and empty; no migrations permitted")
    proof = {"database": DATABASE, "database_oid": oid, "initially_empty": True, "alembic_head": ALEMBIC_HEAD}
    if target is not None and target.remote_confirmation is not None:
        proof["remote_target"] = target.remote_confirmation.binding()
    return proof


def check_proof(connection, proof, *, writer=False):
    target = _connection_target(connection)
    oid = require_database_identity(connection, writer=writer, target=target)
    expected = {"database": DATABASE, "database_oid": oid, "initially_empty": True, "alembic_head": ALEMBIC_HEAD}
    if target is not None and target.remote_confirmation is not None:
        expected["remote_target"] = target.remote_confirmation.binding()
    if fingerprint(proof) != fingerprint(expected):
        raise ValueError("New-target preparation proof missing or inconsistent")
    if connection.execute(text("SELECT version_num FROM public.alembic_version")).scalars().all() != [ALEMBIC_HEAD]:
        raise ValueError("Dedicated target migrations not at the expected head")


def grant_runtime(connection):
    """Fixed grants, only after an empty-target preflight and migrations."""
    require_database_identity(connection, writer=True)
    flags = connection.execute(text("SELECT rolcanlogin, rolsuper, rolbypassrls, rolcreatedb, rolcreaterole "
                                    "FROM pg_roles WHERE rolname=:role"), {"role": RUNTIME}).one_or_none()
    if flags is None or tuple(flags) != (True, False, False, False, False):
        raise ValueError("Provision the nonprivileged dedicated runtime role first")
    membership = connection.execute(text("SELECT count(*) FROM pg_auth_members m JOIN pg_roles r "
        "ON r.oid=m.member WHERE r.rolname=:role"), {"role": RUNTIME}).scalar_one()
    if membership:
        raise ValueError("Runtime must not inherit another role")
    target = _connection_target(connection)
    if target is not None and target.remote_confirmation is not None:
        # Fixed SIGRA schemas only; never alter Supabase managed schemas/roles.
        connection.execute(text(f'REVOKE ALL ON DATABASE "{DATABASE}" FROM PUBLIC, {RUNTIME}'))
        connection.execute(text(f'GRANT CONNECT ON DATABASE "{DATABASE}" TO {OWNER}, {RUNTIME}'))
        principals = connection.execute(text("SELECT rolname FROM pg_roles WHERE rolname IN ('anon','authenticated')")).scalars().all()
        present = set(connection.execute(text("SELECT nspname FROM pg_namespace")).scalars().all())
        for schema in APP_SCHEMAS:
            if schema not in present:
                continue
            for principal in ("PUBLIC", *principals):
                connection.execute(text(f'REVOKE ALL ON SCHEMA "{schema}" FROM {principal}'))
                for kind in ("TABLES", "SEQUENCES", "FUNCTIONS"):
                    connection.execute(text(f'REVOKE ALL ON ALL {kind} IN SCHEMA "{schema}" FROM {principal}'))
                    connection.execute(text(f'ALTER DEFAULT PRIVILEGES IN SCHEMA "{schema}" REVOKE ALL ON {kind} FROM {principal}'))
    connection.execute(text(f"REVOKE CREATE ON SCHEMA public FROM PUBLIC, {RUNTIME}"))
    connection.execute(text("REVOKE ALL ON SCHEMA academic FROM PUBLIC"))
    connection.execute(text(f"GRANT USAGE ON SCHEMA public, academic TO {RUNTIME}"))
    connection.execute(text("REVOKE ALL ON ALL TABLES IN SCHEMA academic FROM PUBLIC"))
    connection.execute(text(f"GRANT SELECT ON ALL TABLES IN SCHEMA academic TO {RUNTIME}"))
    connection.execute(text(f"REVOKE INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER "
                            f"ON ALL TABLES IN SCHEMA academic FROM PUBLIC, {RUNTIME}"))
    for name in PRIVATE_TABLES:
        connection.execute(text(f'REVOKE ALL ON public."{name}" FROM PUBLIC'))
        connection.execute(text(f'ALTER TABLE public."{name}" ENABLE ROW LEVEL SECURITY'))
        connection.execute(text(f'ALTER TABLE public."{name}" FORCE ROW LEVEL SECURITY'))
        connection.execute(text(f'CREATE POLICY revision6_trusted_backend ON public."{name}" '
                                f'TO {RUNTIME} USING (true) WITH CHECK (true)'))
        connection.execute(text(f'GRANT SELECT, INSERT, UPDATE, DELETE ON public."{name}" TO {RUNTIME}'))
    for name in PERSONAL_SEQUENCES:
        connection.execute(text(f'GRANT USAGE, SELECT ON SEQUENCE public."{name}_id_seq" TO {RUNTIME}'))
    connection.execute(text(f"GRANT SELECT ON public.alembic_version, public.vehicles, public.motorcycles TO {RUNTIME}"))


def audit_runtime_permissions(connection):
    require_database_identity(connection)
    for name in ("cohort_snapshot", "cohort_vehicle", "cohort_evaluation"):
        relation = f"academic.{name}"
        if not connection.execute(text("SELECT has_table_privilege(current_user,:relation,'SELECT')"),
                                  {"relation": relation}).scalar_one():
            raise ValueError("Runtime cannot read the dedicated snapshot")
        for privilege in ("INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER"):
            if connection.execute(text("SELECT has_table_privilege(current_user,:relation,:privilege)"),
                                  {"relation": relation, "privilege": privilege}).scalar_one():
                raise ValueError("Runtime can modify academic data")
    for name in PRIVATE_TABLES:
        flags = connection.execute(text("SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
                                        "WHERE oid=to_regclass(:relation)"), {"relation": f"public.{name}"}).one()
        if tuple(flags) != (True, True):
            raise ValueError("Participant RLS not enforced")
        policies = connection.execute(text("SELECT p.polname, p.polroles = ARRAY[r.oid], p.polcmd "
            "FROM pg_policy p JOIN pg_roles r ON r.rolname=current_user "
            "WHERE p.polrelid=to_regclass(:relation)"), {"relation": f"public.{name}"}).all()
        if [tuple(row) for row in policies] != [("revision6_trusted_backend", True, "*")]:
            raise ValueError("Unexpected participant RLS policy or grantee")
        public_grants = connection.execute(text("SELECT count(*) FROM pg_class c, LATERAL "
            "aclexplode(COALESCE(c.relacl, acldefault('r',c.relowner))) a "
            "WHERE c.oid=to_regclass(:relation) AND a.grantee=0"), {"relation": f"public.{name}"}).scalar_one()
        if public_grants:
            raise ValueError("Participant table still has PUBLIC grants")
    membership = connection.execute(text("SELECT count(*) FROM pg_auth_members m JOIN pg_roles r "
        "ON r.oid=m.member WHERE r.rolname=current_user")).scalar_one()
    owns_relations = connection.execute(text("SELECT count(*) FROM pg_class c JOIN pg_roles r "
        "ON r.oid=c.relowner WHERE r.rolname=current_user")).scalar_one()
    creates_schema = connection.execute(text("SELECT has_schema_privilege(current_user,'public','CREATE') "
        "OR has_schema_privilege(current_user,'academic','CREATE')")).scalar_one()
    if membership or owns_relations or creates_schema:
        raise ValueError("Runtime inherits privileges, owns relations or can create objects")
    target = _connection_target(connection)
    if target is not None and target.remote_confirmation is not None:
        creates_objects = connection.execute(text("""
            SELECT has_database_privilege(current_user,current_database(),'CREATE,TEMPORARY')
            OR EXISTS (SELECT 1 FROM pg_namespace WHERE nspname NOT LIKE 'pg_%'
                AND nspname <> 'information_schema'
                AND has_schema_privilege(current_user,oid,'CREATE'))
        """)).scalar_one()
        if creates_objects:
            raise ValueError("Runtime can create database/schema/temporary objects")
        leaks = connection.execute(text("""
            SELECT n.nspname, c.relname, a.privilege_type FROM pg_class c
            JOIN pg_namespace n ON n.oid=c.relnamespace
            CROSS JOIN LATERAL aclexplode(COALESCE(c.relacl,acldefault('r',c.relowner))) a
            LEFT JOIN pg_roles r ON r.oid=a.grantee
            WHERE n.nspname IN ('public','academic','bronze','silver','gold','meta')
            AND c.relkind IN ('r','p','v','m')
            AND (a.grantee=0 OR r.rolname IN ('anon','authenticated'))
        """)).all()
        if leaks:
            raise ValueError("PUBLIC/Data API still has SIGRA relation grants")
        writable = connection.execute(text("""
            SELECT n.nspname,c.relname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname IN ('academic','bronze','silver','gold','meta') AND c.relkind IN ('r','p','v','m')
            AND has_table_privilege(current_user,c.oid,'INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')
        """)).all()
        if writable:
            raise ValueError("Runtime can write immutable SIGRA relations/views")
    return {"academic_runtime_read_only": True, "participant_rls_forced": True,
            "participant_isolation": "FastAPI owner checks; runtime is a trusted service role"}


def materialize(engine, bundle, decision, target, proof):
    target.check_bind(engine, writer=True)
    plan = build_plan(bundle, decision)  # All evidence validation before connecting.
    with Session(engine) as session, session.begin():
        check_proof(session.connection(), proof, writer=True)
        session.execute(text("SELECT pg_advisory_xact_lock(:key)"),
                        {"key": int(plan.proposal.candidate_fingerprint[:15], 16)})
        return _materialize_plan(session, plan)


class Revision6Repository(AcademicRepository):
    def snapshot(self, snapshot_id=None):
        policy = preparation._read(preparation.CONTRACT)
        query = select(CohortSnapshot).where(CohortSnapshot.cohort_version == policy["candidate_version"],
                                            CohortSnapshot.cohort_fingerprint == policy["candidate_fingerprint"])
        if snapshot_id is not None:
            query = query.where(CohortSnapshot.snapshot_id == snapshot_id)
        return self.session.scalar(query.order_by(CohortSnapshot.created_at.desc(), CohortSnapshot.snapshot_id).limit(1))


class Revision6Service(AcademicService):
    def __init__(self, repository, plan):
        super().__init__(repository)
        validate_plan(plan)
        self.plan = plan
        self.profile_counts = deepcopy(plan.proposal.profile_counts)
        self.limitations = ["Homologação Revision6 inativa: somente contas fictícias; coleta real bloqueada.",
                            "Família e Estrada têm nove inventários completos; a meta histórica de dez não foi atingida.",
                            "Completude documental não significa equipamentos presentes ou segurança iguais.",
                            "TCO é estimativa de cenário; habitabilidade é derivada.", *plan.proposal.limitations]
        self.recommendation_context = {"cohort_version": plan.proposal.candidate_version,
            "homologation_candidate": "safety_revision6", "candidate_approved": False,
            "real_collection_enabled": False, "default_snapshot_replaced": False}

    def _snapshot(self, snapshot_id=None):
        row = super()._snapshot(snapshot_id)
        try:
            audit_snapshot(self.repository.session, row, self.plan)
        except (ValueError, KeyError, TypeError):
            raise AcademicUnavailable("Candidata de homologação incompatível ou adulterada") from None
        return row


@lru_cache(maxsize=1)
def _runtime_plan(bundle, decision):
    return build_plan(bundle, decision)


def service_for_session(session):
    """Called only by the existing factory when the explicit flag is true."""
    target = require_runtime()
    target.check_bind(session.get_bind())
    proof = preparation._read(os.environ.get("SIGRA_REVISION6_TARGET_PROOF", ""))
    check_proof(session.connection(), proof)
    audit_runtime_permissions(session.connection())
    bundle, decision = os.environ.get("SIGRA_REVISION6_BUNDLE", ""), os.environ.get("SIGRA_REVISION6_DECISION", "")
    if not bundle or not decision:
        raise ValueError("Explicit verified bundle/coverage decision paths required")
    return Revision6Service(Revision6Repository(session), _runtime_plan(bundle, decision))
