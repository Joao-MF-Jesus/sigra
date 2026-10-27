"""Appendices C/D, homologation only. This instrument never changes ranking inputs."""
from datetime import datetime, timezone
from typing import Literal
import os
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session

from app import models
from app.auth import COOKIE_NAME, _digest, current_user
from app.database import current_migration_revision, get_db

PROTOCOL_VERSION = "tcc-appendices-cd-v1"
PRESENTATION_VERSION = "appendix-c-homologation-draft-v1"
RESEARCH_PRESENTATION_VERSION = "appendix-c-research-v1"
QUESTIONS = {
    "interface_clarity": "A interface foi clara para mim.",
    "first_vehicle_explanation": "Entendi por que o primeiro veículo foi recomendado.",
    "scenario_coherence": "O resultado parece coerente com o cenário apresentado.",
    "influential_criteria": "Consigo identificar os critérios que mais influenciaram a recomendação.",
}
# Existing personalization controls; not new weights or hidden scenario assignments.
PRIORITIES = {"total_cost": "Custo no cenário", "usage_fit": "Adequação ao uso",
              "comfort": "Conforto", "safety": "Segurança", "performance": "Desempenho rodoviário",
              "efficiency": "Economia e eficiência", "legacy_quality": "Qualidade histórica"}
PRESENTATION = ("Esta atividade avalia um sistema acadêmico de apoio à decisão. Não é recomendação comercial "
                "nem orientação para compra. A participação é voluntária e pode ser interrompida a qualquer momento. "
                "O registro é usado para analisar o comportamento do sistema e a clareza das explicações.")
router = APIRouter(prefix="/api/v1/study-sessions", tags=["tcc-study-instrument"])


def collection_mode():
    mode = os.getenv("SIGRA_TCC_COLLECTION_MODE", "disabled")
    if mode == "research":
        from app.deployment import research_collection_allowed
        try:
            if research_collection_allowed():
                return mode
        except ValueError:
            pass
        raise HTTPException(503, "Coleta real desativada: liberação técnica e destino de pesquisa não confirmados")
    if mode not in {"disabled", "homologation"}:
        raise HTTPException(503, "Modo de coleta não habilitado nesta entrega")
    return mode


class BeforeRanking(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scenario_id: Literal["A", "B", "C", "D", "E"]
    familiarity: Literal["none", "low", "medium", "high"]
    priorities: list[str] = Field(max_length=3)
    presentation_acknowledged: Literal[True]

    @field_validator("priorities")
    @classmethod
    def exact_priorities(cls, values):
        if len(set(values)) != len(values) or any(v not in PRIORITIES for v in values):
            raise ValueError("Selecione até três características distintas apresentadas no formulário")
        return values


class Questionnaire(BaseModel):
    model_config = ConfigDict(extra="forbid")
    interface_clarity: int = Field(ge=1, le=5, strict=True)
    first_vehicle_explanation: int = Field(ge=1, le=5, strict=True)
    scenario_coherence: int = Field(ge=1, le=5, strict=True)
    influential_criteria: int = Field(ge=1, le=5, strict=True)
    comment: str = Field(default="", max_length=4000)


def session_response(session):
    from app.participant_trials import utc_iso
    return {name: getattr(session, name) for name in
            ("id", "scenario_id", "familiarity", "priorities", "protocol_version", "presentation_version", "environment_tag")} | {
                "created_at": utc_iso(session.created_at)}


def current_context(db, user, request):
    mode = collection_mode()
    if mode == "disabled":
        return None
    # User and login-session linkage come from the validated cookie, never a body ID.
    return db.query(models.ParticipantStudySession).filter_by(user_id=user.id,
        auth_session_digest=_digest(request.cookies[COOKIE_NAME]),
        environment_tag="research_participant" if mode == "research" else "homologation_synthetic").order_by(
            models.ParticipantStudySession.created_at.desc(), models.ParticipantStudySession.id.desc()).first()


def require_context(db, user, request):
    context = current_context(db, user, request)
    if collection_mode() in {"homologation", "research"} and context is None:
        raise HTTPException(409, "Registre cenário, familiaridade e prioridades antes do resultado")
    return context


@router.get("/metadata")
def metadata(response: Response):
    response.headers["Cache-Control"] = "no-store"
    mode = collection_mode()
    return {"mode": mode, "protocol_version": PROTOCOL_VERSION,
            "real_collection_enabled": mode == "research", "presentation": PRESENTATION,
            "presentation_version": RESEARCH_PRESENTATION_VERSION if mode == "research" else PRESENTATION_VERSION,
            "scenarios": list("ABCDE"),
            "priorities": PRIORITIES, "questions": QUESTIONS,
            "limitations": (["A–E identificam o roteiro aprovado; não alteram os pesos do recomendador.",
                              "Não inclua informações pessoais no comentário."] if mode == "research" else
                             ["A–E são identificadores do roteiro e não alteram as preferências do formulário.",
                              "Use somente contas fictícias. Ciência da apresentação não substitui consentimento aprovado."])}


@router.get("/current")
def current(request: Request, response: Response, user=Depends(current_user), db: Session = Depends(get_db)):
    response.headers["Cache-Control"] = "no-store"
    context = current_context(db, user, request)
    return {"session": session_response(context) if context else None}


@router.post("", status_code=201)
def before_ranking(payload: BeforeRanking, request: Request, user=Depends(current_user), db: Session = Depends(get_db)):
    mode = collection_mode()
    if mode not in {"homologation", "research"}:
        raise HTTPException(409, "Instrumento de homologação desabilitado")
    from app.participant_trials import research_export_key
    research_export_key()  # Require a stable pseudonym key before collecting anything.
    context = models.ParticipantStudySession(id=str(uuid4()), user_id=user.id,
        auth_session_digest=_digest(request.cookies[COOKIE_NAME]), scenario_id=payload.scenario_id,
        familiarity=payload.familiarity, priorities=payload.priorities, protocol_version=PROTOCOL_VERSION,
        presentation_version=RESEARCH_PRESENTATION_VERSION if mode == "research" else PRESENTATION_VERSION,
        environment_tag="research_participant" if mode == "research" else "homologation_synthetic")
    db.add(context)
    db.commit()
    db.refresh(context)
    return session_response(context)


def questionnaire_response(db, run):
    item = db.get(models.ParticipantQuestionnaire, run.id)
    if item is None:
        return None
    from app.participant_trials import utc_iso
    return {name: getattr(item, name) for name in (*QUESTIONS, "comment", "version")} | {
        "answered_at": utc_iso(item.answered_at)}


def technical_record(db, context, kind, parameters, result, elapsed, status, error_code):
    """Lossless inputs/results stay in the run. This is an analysis-oriented index."""
    rows = result.get("recommendations", [])
    excluded = result.get("excluded", [])
    dataset = result.get("snapshot_id") or result.get("dataset_version")
    algorithm = result.get("algorithm_version") or result.get("calculation_method_version") or result.get("simulation_policy_version")
    weights = result.get("weights_version")
    revision = current_migration_revision(db.get_bind())
    def identity(row):
        vehicle = row.get("vehicle", row)
        return vehicle.get("catalog_id", vehicle.get("id"))
    ranks = []
    for position, row in enumerate(rows, 1):
        multifactor = row.get("multifactor") or {}
        personalized = multifactor.get("status") == "ranked" and multifactor.get("final_score") is not None
        # Partial diagnostic contributions do not explain the reference ranking.
        contributions = multifactor.get("components", []) if personalized else row.get("explanations", [])
        if not isinstance(contributions, list):
            contributions = []  # Exact original structure remains in presented_results.
        if personalized:
            contributions = [v for v in contributions if v.get("used_in_final_score") is not False]
        ranks.append({"rank": position, "group_rank": row.get("group_position"),
            "comparison_group": row.get("comparison_group"), "vehicle_id": identity(row),
            "score": multifactor.get("final_score", row.get("score")),
            "score_basis": "personalized" if personalized else "reference",
            "displayed_score": row.get("score"),
            "personalized_score": multifactor.get("final_score") if personalized else None,
            "reference_score": row.get("baseline_score", row.get("score") if not personalized else None),
            "top_positive_factors": sorted([v for v in contributions if v.get("contribution") is not None and float(v["contribution"]) > 0], key=lambda v: -float(v["contribution"]))[:3],
            "top_negative_factors": sorted([v for v in contributions if v.get("contribution") is not None and float(v["contribution"]) < 0], key=lambda v: float(v["contribution"]))[:3]})
    mandatory = {"dataset_version": dataset, "algorithm_version": algorithm, "weights_version": weights}
    from app.academic_cohort.derived_configurations import recorded_configuration
    return {"record_version": "appendix-d-v1", "ranking_trace_version": "ranking-basis-v1", "protocol_version": context.protocol_version,
        "scenario_id": context.scenario_id, "environment_tag": context.environment_tag,
        **mandatory, "alembic_revision": revision, "status": status, "duration_ms": round(elapsed * 1000, 3),
        "personalization_configuration": recorded_configuration(result),
        "cost_scenario": (parameters.get("academic_options") or {}).get("scenario"),
        "error_code": error_code, "analysis_ready": status == "succeeded" and all(mandatory.values()) and revision is not None,
        "missing_analysis_versions": [k for k, v in mandatory.items() if not v],
        "profile": parameters.get("use_case"), "budget": parameters.get("budget"),
        "usage_intensity": parameters.get("monthly_mileage"), "priorities": context.priorities,
        "active_parameters": parameters, "eligible_count": result.get("eligible_count"),
        "eligible_vehicle_ids": [identity(v) for v in rows], "excluded_vehicle_ids": [identity(v) for v in excluded],
        "exclusion_reasons": excluded, "ranking": ranks,
        "methodology_ready": {str(identity(v)): v.get("evaluation", {}).get("methodology_ready") for v in rows},
        "warnings": result.get("limitations", []), "unavailable_fields": result.get("candidate_diagnostics", []),
        "source_references": {"snapshot_id": dataset, "cohort_fingerprint": result.get("cohort_fingerprint")}}
