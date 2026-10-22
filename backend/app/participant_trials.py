"""Immutable server-calculated trials; owner-scoped history and administrator export."""
import csv
from datetime import datetime, timezone
import hashlib
import hmac
import io
import json
import os
from functools import lru_cache
from pathlib import Path
import re
from uuid import uuid4
from time import monotonic

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.encoders import jsonable_encoder
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, defer

from app import models
from app.auth import current_user, require_admin
from app.database import get_db
from app.financing.routes import financing_comparison, financing_simulation, reverse_financing_simulation
from app.financing.schemas import DirectFinancingRequest, FinancingComparisonRequest, ReverseFinancingRequest
from app.integrated_gold.routes import get_vehicle_cost_simulation_service, simulate_vehicle_cost
from app.integrated_gold.simulation_schemas import VehicleCostSimulationRequest, VehicleCostSimulationResponse
from app.integrated_gold.simulation_service import VehicleCostSimulationService

router = APIRouter(prefix="/api/v1/test-runs", tags=["participant-trials"])
admin_router = APIRouter(prefix="/api/v1/admin", tags=["participant-trials-admin"])


def canonical_json(value):
    return json.dumps(jsonable_encoder(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def fingerprint(value):
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


@lru_cache(maxsize=1)
def system_version():
    label = os.getenv("SIGRA_SYSTEM_VERSION", "")
    if label:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+\-]{0,79}", label):
            raise HTTPException(503, "Identificação da versão do sistema inválida")
        return label
    root = Path(__file__).resolve().parents[1]
    project = root.parent
    paths = sorted([*root.joinpath("app").rglob("*.py"),
                    *project.joinpath("frontend/src").rglob("*.jsx"),
                    *project.joinpath("frontend/src").rglob("*.js"),
                    *project.joinpath("frontend/src").rglob("*.css")])
    if not paths:
        raise HTTPException(503, "Não foi possível identificar a versão do código carregado")
    manifest = {path.relative_to(project).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in paths}
    return "src-" + fingerprint(manifest)


def utc_iso(value):
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def record_result(db: Session, user: models.User, kind: str, parameters, result, *, context=None,
                  elapsed=0, status="succeeded", error_code=None) -> dict:
    parameters = jsonable_encoder(parameters)
    result = jsonable_encoder(result)
    if not isinstance(result, dict):
        raise HTTPException(500, "A execução não possui um resultado estruturado")
    method = result.get("algorithm_version") or result.get("calculation_method_version") or result.get("simulation_policy_version") or result.get("method_version")
    method = str(method or ("integrated-vehicle-cost-v1" if kind == "fuel_simulation" else "financing-price-v1"))
    if result.get("weights_version"):
        method += "/" + str(result["weights_version"])
    run = models.ParticipantTestRun(
        id=str(uuid4()), user_id=user.id, kind=kind,
        created_at=datetime.now(timezone.utc),
        system_version=system_version(),
        method_version=method, snapshot_version=result.get("snapshot_id") or result.get("dataset_version") or result.get("scenario", {}).get("dataset_version"),
        snapshot_fingerprint=result.get("cohort_fingerprint") or result.get("dataset_fingerprint"),
        parameters=parameters, presented_results=result,
        request_fingerprint=fingerprint(parameters), result_fingerprint=fingerprint(result),
    )
    if context is not None:
        from app.study_protocol import technical_record
        run.study_session_id = context.id
        run.technical_record = technical_record(db, context, kind, parameters, result, elapsed, status, error_code)
        run.technical_record.update(execution_id=run.id, timestamp=utc_iso(run.created_at),
            study_session_code=context.id, participant_code=participant_code(user.id, research_export_key()))
    try:
        db.add(run)
        db.commit()
        db.refresh(run)
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(503, "Não foi possível salvar o teste. O resultado não foi registrado.") from None
    # Exact result is stored before attaching the receipt; no client-provided results.
    return {**result, "test_run": {"id": run.id, "created_at": utc_iso(run.created_at), "saved": True,
                                   "questionnaire_required": context is not None and status == "succeeded"}}


def execute_recorded(db, user, request, kind, parameters, calculate):
    from app.study_protocol import require_context
    context = require_context(db, user, request)
    started = monotonic()
    try:
        result = calculate()
    except HTTPException as error:
        if context is not None:
            # Store the failure category, never arbitrary exception text/URLs.
            record_result(db, user, kind, parameters, {"status": "failed", "http_status": error.status_code},
                          context=context, elapsed=monotonic() - started, status="failed",
                          error_code=f"HTTP_{error.status_code}")
        raise
    except Exception as error:
        if context is not None:
            record_result(db, user, kind, parameters, {"status": "failed"}, context=context,
                          elapsed=monotonic() - started, status="failed", error_code=type(error).__name__)
        raise
    return record_result(db, user, kind, parameters, result, context=context, elapsed=monotonic() - started)


def trial_response(run, include_results=False, *, compact=False, technical_summary=None):
    result = {"id": run.id, "kind": run.kind, "created_at": utc_iso(run.created_at),
              "system_version": run.system_version, "method_version": run.method_version,
              "snapshot_version": run.snapshot_version, "snapshot_fingerprint": run.snapshot_fingerprint,
              "parameters": run.parameters, "request_fingerprint": run.request_fingerprint,
              "result_fingerprint": run.result_fingerprint, "feedback_rating": run.feedback_rating,
              "feedback_comment": run.feedback_comment, "feedback_at": utc_iso(run.feedback_at)}
    from app.study_protocol import questionnaire_response, session_response
    from sqlalchemy.orm import object_session
    db = object_session(run)
    context = db.get(models.ParticipantStudySession, run.study_session_id) if run.study_session_id else None
    technical = technical_summary if compact else run.technical_record
    result.update(study_session=session_response(context) if context else None,
                  questionnaire_required=context is not None and (technical or {}).get("status") == "succeeded",
                  questionnaire=questionnaire_response(db, run), technical_record=technical)
    if include_results:
        result["presented_results"] = run.presented_results
    return result


def owned_run(db, user, run_id):
    run = db.query(models.ParticipantTestRun).filter_by(id=run_id, user_id=user.id).first()
    if run is None:
        raise HTTPException(404, "Teste não encontrado no seu histórico")
    return run


@router.get("")
def history(response: Response, limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0),
            compact: bool = Query(False, description="List metadata and technical status only; full immutable data remain in the detail endpoint"),
            user: models.User = Depends(current_user), db: Session = Depends(get_db)):
    response.headers["Cache-Control"] = "no-store"
    query = db.query(models.ParticipantTestRun).filter_by(user_id=user.id)
    total = query.count()
    # Listing never includes presented_results. Do not fetch/decompress it.
    listing = query.options(defer(models.ParticipantTestRun.presented_results))
    if compact:
        listing = listing.options(defer(models.ParticipantTestRun.technical_record))
    runs = listing.order_by(models.ParticipantTestRun.created_at.desc(),
                            models.ParticipantTestRun.id.desc()).offset(offset).limit(limit).all()
    summaries = {}
    if compact and runs:
        # Project only three documented keys, rather than transferring the
        # complete technical record (which includes large vehicle evidence).
        technical = models.ParticipantTestRun.technical_record
        summaries = {row.id: {"status": row.status, "error_code": row.error_code,
                              "analysis_ready": row.analysis_ready}
                     for row in query.with_entities(models.ParticipantTestRun.id,
                         technical["status"].as_string().label("status"),
                         technical["error_code"].as_string().label("error_code"),
                         technical["analysis_ready"].as_boolean().label("analysis_ready"))
                         .filter(models.ParticipantTestRun.id.in_([run.id for run in runs])).all()}
    result = {"total": total, "limit": limit, "offset": offset,
              "items": [trial_response(run, compact=compact, technical_summary=summaries.get(run.id)) for run in runs]}
    if compact:
        result["history_view"] = "compact-v1"
    return result


@router.get("/{run_id}")
def detail(run_id: str, response: Response, user: models.User = Depends(current_user), db: Session = Depends(get_db)):
    response.headers["Cache-Control"] = "no-store"
    return trial_response(owned_run(db, user, run_id), include_results=True)


class Feedback(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rating: int = Field(ge=1, le=5, strict=True)
    comment: str = Field(default="", max_length=4000)


@router.patch("/{run_id}/feedback")
def feedback(run_id: str, payload: Feedback, user: models.User = Depends(current_user), db: Session = Depends(get_db)):
    run = owned_run(db, user, run_id)
    if run.study_session_id:
        raise HTTPException(409, "Responda às quatro questões do instrumento; a nota geral não as substitui")
    run.feedback_rating = payload.rating
    run.feedback_comment = payload.comment.strip()
    run.feedback_at = datetime.now(timezone.utc)
    db.commit()
    return trial_response(run)


from app.study_protocol import Questionnaire, PROTOCOL_VERSION


@router.patch("/{run_id}/questionnaire")
def questionnaire(run_id: str, payload: Questionnaire, user=Depends(current_user), db: Session = Depends(get_db)):
    run = owned_run(db, user, run_id)
    if not run.study_session_id or run.technical_record.get("status") != "succeeded":
        raise HTTPException(409, "Esta execução não possui um resultado do protocolo para avaliar")
    item = db.get(models.ParticipantQuestionnaire, run.id)
    if item is None:
        item = models.ParticipantQuestionnaire(run_id=run.id, version=PROTOCOL_VERSION)
        db.add(item)
    for name, value in payload.model_dump().items():
        setattr(item, name, value.strip() if name == "comment" else value)
    item.answered_at = datetime.now(timezone.utc)
    db.commit()
    return trial_response(run)


@router.post("/financing")
def financing(payload: DirectFinancingRequest, request: Request, user: models.User = Depends(current_user), db: Session = Depends(get_db)):
    return execute_recorded(db, user, request, "financing", payload.model_dump(mode="json"), lambda: financing_simulation(payload, db))


@router.post("/reverse-financing")
def reverse_financing(payload: ReverseFinancingRequest, request: Request, user: models.User = Depends(current_user), db: Session = Depends(get_db)):
    return execute_recorded(db, user, request, "reverse_financing", payload.model_dump(mode="json"), lambda: reverse_financing_simulation(payload))


@router.post("/financing-comparison")
def comparison(payload: FinancingComparisonRequest, request: Request, user: models.User = Depends(current_user), db: Session = Depends(get_db)):
    return execute_recorded(db, user, request, "financing_comparison", payload.model_dump(mode="json"), lambda: financing_comparison(payload, db))


@router.post("/fuel-simulation")
def fuel_simulation(payload: VehicleCostSimulationRequest, request: Request, user: models.User = Depends(current_user),
                    db: Session = Depends(get_db),
                    service: VehicleCostSimulationService = Depends(get_vehicle_cost_simulation_service)):
    def calculate():
        calculated = simulate_vehicle_cost(payload, service)
        return VehicleCostSimulationResponse.model_validate(calculated).model_dump(mode="json")
    return execute_recorded(db, user, request, "fuel_simulation", payload.model_dump(mode="json"), calculate)


def csv_cell(value):
    value = "" if value is None else str(value)
    if value.lstrip().startswith(("=", "+", "-", "@", "\t", "\r")):
        return "'" + value
    return value


def research_export_key() -> bytes:
    key = os.getenv("SIGRA_RESEARCH_PSEUDONYM_KEY", "").encode("utf-8")
    if len(key) < 32:
        raise HTTPException(503, "Configure a chave privada de pseudonimização da pesquisa")
    return key


def participant_code(user_id: int, key: bytes) -> str:
    # Stable across API restarts, domain-separated, not an enumerable ID hash.
    digest = hmac.new(key, f"sigra-tcc-participant-v1:{user_id}".encode("ascii"), hashlib.sha256)
    return "P-" + digest.hexdigest()


@admin_router.get("/test-runs.csv")
def export_trials(_admin: models.User = Depends(require_admin), db: Session = Depends(get_db)):
    from app.academic_cohort.derived_configurations import recorded_configuration
    bind = db.get_bind()
    key = research_export_key()  # Fail before streaming any response if unconfigured.

    def rows():
        buffer = io.StringIO()
        writer = csv.writer(buffer, lineterminator="\r\n")
        columns = ["id", "participant_code", "kind", "created_at",
                   "system_version", "method_version", "snapshot_version", "snapshot_fingerprint",
                   "request_fingerprint", "result_fingerprint", "parameters", "presented_results",
                   "feedback_rating", "feedback_comment", "feedback_at", "study_session_code", "scenario_id",
                   "familiarity", "priorities_before_ranking", "protocol_version", "technical_record",
                   "interface_clarity", "first_vehicle_explanation", "scenario_coherence", "influential_criteria",
                   "questionnaire_comment", "questionnaire_at", "personalization_configuration_id",
                   "personalization_method_version", "personalization_weights", "personalization_weights_normalized",
                   "personalization_weights_adjusted", "evidence_batch_version", "evidence_batch_sha256", "profile", "cost_scenario"]
        writer.writerow(columns)
        yield "\ufeff" + buffer.getvalue()
        with Session(bind=bind) as export_db:
            query = export_db.query(models.ParticipantTestRun).order_by(
                models.ParticipantTestRun.created_at, models.ParticipantTestRun.id)
            for run in query.yield_per(100):
                context = export_db.get(models.ParticipantStudySession, run.study_session_id) if run.study_session_id else None
                answers = export_db.get(models.ParticipantQuestionnaire, run.id)
                values = [run.id, participant_code(run.user_id, key), run.kind, utc_iso(run.created_at),
                          run.system_version, run.method_version, run.snapshot_version, run.snapshot_fingerprint,
                          run.request_fingerprint, run.result_fingerprint, canonical_json(run.parameters),
                          canonical_json(run.presented_results), run.feedback_rating, run.feedback_comment, utc_iso(run.feedback_at)]
                values += [context.id if context else None, context.scenario_id if context else None,
                           context.familiarity if context else None, canonical_json(context.priorities) if context else None,
                           context.protocol_version if context else None, canonical_json(run.technical_record),
                           *(getattr(answers, name, None) for name in ("interface_clarity", "first_vehicle_explanation", "scenario_coherence", "influential_criteria", "comment")),
                           utc_iso(answers.answered_at) if answers else None]
                configuration = recorded_configuration(run.presented_results) or {}
                values += [configuration.get("configuration_id"), configuration.get("method_version"),
                           canonical_json(configuration.get("actual_weights")), canonical_json(configuration.get("normalized_weights_percentage")),
                           configuration.get("weights_adjusted"), configuration.get("evidence_batch_version"),
                           configuration.get("evidence_batch_sha256"), run.parameters.get("use_case"),
                           (run.parameters.get("academic_options") or {}).get("scenario")]
                buffer.seek(0)
                buffer.truncate(0)
                writer.writerow([csv_cell(value) for value in values])
                yield buffer.getvalue()

    return StreamingResponse(rows(), media_type="text/csv; charset=utf-8", headers={
        "Content-Disposition": 'attachment; filename="sigra-testes-tcc.csv"',
        "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
    })
