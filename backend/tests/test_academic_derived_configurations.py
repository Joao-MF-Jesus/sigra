"""Versioned configurations; synthetic test evidence and storage doubles only."""
from copy import deepcopy
import csv
from decimal import Decimal, ROUND_HALF_UP
import io
import json
from types import SimpleNamespace

from fastapi import Response
from fastapi.testclient import TestClient
from pydantic import ValidationError
import pytest

from app import main, models, participant_trials as trials, study_protocol
from app.academic_cohort import derived_configurations as configs, derived_personalization as method
from app.academic_cohort.recommendation import recommend_academic, recommendation_method
from app.multifactor_schemas import MultifactorRecommendationProfile, DEFAULT_MULTIFACTOR_WEIGHTS
from backend.tests.test_academic_recommendation import service, request
from backend.tests.test_academic_derived_personalization import metrics, row
from backend.tests.test_academic_personalization import personalization


@pytest.fixture(autouse=True)
def isolated_configuration(monkeypatch):
    monkeypatch.setenv("SIGRA_DERIVED_PERSONALIZATION_ENABLED", "true")


def selected(identifier=configs.BASE, weights=None):
    value = {**personalization(), "policy_version": method.VERSION, "configuration_id": identifier}
    value.pop("weights", None)
    if weights is not None:
        value["weights"] = weights
    return value


def test_fixed_presets_and_rounding_are_method_choices_not_missing_data_rules():
    registry = configs.configuration()
    assert registry["enabled_by_default"] is False
    assert configs.preset(configs.EXPANDED)["weights"] == {k: str(v) for k, v in DEFAULT_MULTIFACTOR_WEIGHTS.items()}
    active = [k for k in configs.KEYS if k not in {"safety", "performance"}]
    expected = {k: (DEFAULT_MULTIFACTOR_WEIGHTS[k] * 100 / 75).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP) for k in active}
    expected[active[-1]] += 100 - sum(expected.values())
    base = {k: Decimal(v) for k, v in configs.preset(configs.BASE)["weights"].items()}
    assert sum(base.values()) == 100 and base["safety"] == base["performance"] == 0
    assert {k: base[k] for k in active} == expected
    assert "Project methodological choice" in configs.preset(configs.BASE)["justification"]


@pytest.mark.parametrize("identifier", [configs.BASE, configs.EXPANDED])
def test_explicit_preset_without_weights_is_uniform_and_lossless(identifier):
    value = selected(identifier)
    before = deepcopy(value)
    parsed = MultifactorRecommendationProfile.model_validate(value)
    assert value == before
    assert parsed.weights.as_mapping() == {k: Decimal(v) for k, v in configs.preset(identifier)["weights"].items()}
    record = configs.execution_metadata(identifier, parsed.weights.as_mapping())
    assert record["selection_explicit"] and not record["weights_adjusted"]
    assert record["configuration_id"] == identifier and record["evidence_batch_version"]
    assert sum(record["normalized_weights_percentage"].values()) == 100


@pytest.mark.parametrize("change", [
    {"configuration_id": "invented"}, {"policy_version": method.REFERENCE},
    {"weights": {"safety": "0"}}, {"weights": None},
    {"weights": {**DEFAULT_MULTIFACTOR_WEIGHTS, "invented": "1"}},
    {"weights": {**DEFAULT_MULTIFACTOR_WEIGHTS, "comfort": "NaN"}},
    {"weights": {**DEFAULT_MULTIFACTOR_WEIGHTS, "comfort": -1}},
])
def test_configuration_contract_rejects_unknown_partial_or_implicit_weights(change):
    with pytest.raises(ValidationError):
        MultifactorRecommendationProfile.model_validate({**selected(), **change})


def test_legacy_requests_do_not_silently_select_a_new_preset():
    parsed = MultifactorRecommendationProfile.model_validate({**personalization(), "policy_version": method.VERSION})
    assert parsed.configuration_id is None
    assert parsed.weights.as_mapping() == DEFAULT_MULTIFACTOR_WEIGHTS
    assert not configs.execution_metadata(None, parsed.weights.as_mapping())["selection_explicit"]


@pytest.mark.parametrize("profile,maximum", [("cidade", 10), ("app", 60), ("trabalho", 10), ("suv", 24), ("familia", 1), ("estrada", 1)])
@pytest.mark.parametrize("scenario", ["low", "base", "high"])
def test_base_all_synthetic_profiles_preserves_documentary_gates_and_costs(service, profile, maximum, scenario):
    options = {"snapshot_id": service.repository.snapshot_id, "scenario": scenario}
    original = recommend_academic(service, request(service, use_case=profile, academic_options=options, multifactor_profile=personalization()))
    result = recommend_academic(service, request(service, use_case=profile, academic_options=options, multifactor_profile=selected()))
    assert result["documentary_eligible_count"] == result["eligible_count"] == maximum
    assert result["multifactor_profile"]["ranked_count"] == maximum
    assert result["considered_count"] == 60 and not result["operationally_active"] and not result["recommended"]
    assert {r["vehicle"]["catalog_id"]: r["monthly_total_cost"] for r in result["recommendations"]} == {r["vehicle"]["catalog_id"]: r["monthly_total_cost"] for r in original["recommendations"]}
    preset = result["multifactor_profile"]["configuration"]
    for row in result["recommendations"]:
        assert row["multifactor"]["configuration"] == preset
        assert row["multifactor"]["criterion_calculations"]["requested_count"] == 5


@pytest.mark.parametrize("criterion", configs.KEYS)
def test_explicit_adjustments_do_not_impute_or_redistribute(criterion):
    values, scenario, _ = metrics()
    values[criterion].update(available=False, value=None)
    weights = {k: Decimal(v) for k, v in configs.preset(configs.BASE)["weights"].items()}
    weights[criterion] = Decimal(5)
    result = method.score_group([row(1)], {1: values}, weights, scenario, configuration_id=configs.BASE)[0]["multifactor"]
    assert result["final_score"] is None and result["reference_order_preserved"]
    assert result["configuration"]["weights_adjusted"]
    assert result["configuration"]["actual_weights"] == weights
    assert not result["criterion_calculations"]["weights_redistributed"]


def test_expanded_synthetic_unknown_is_not_zero_score(service):
    result = recommend_academic(service, request(service, multifactor_profile=selected(configs.EXPANDED)))
    assert result["multifactor_profile"]["ranked_count"] == 1
    unknown = next(r for r in result["recommendations"] if r["vehicle"]["catalog_id"] == 2)
    assert unknown["multifactor"]["final_score"] is None and unknown["multifactor"]["status"] == "unavailable"
    assert "safety" in unknown["multifactor"]["evidence_coverage"]["missing"]


def test_http_configurations_and_disabled_gate(service, monkeypatch):
    monkeypatch.setenv("ACADEMIC_COHORT_ENABLED", "true")
    monkeypatch.setattr(main, "get_academic_service", lambda _: service)
    previous = dict(main.app.dependency_overrides)
    main.app.dependency_overrides[main.get_db] = lambda: object()
    try:
        http = TestClient(main.app)  # Deliberately no lifespan/DB initialization.
        for identifier, count in ((configs.BASE, 60), (configs.EXPANDED, 1)):
            body = request(service, multifactor_profile=selected(identifier)).model_dump(mode="json")
            response = http.post("/recommendations?envelope=true", json=body)
            assert response.status_code == 200, response.text
            result = response.json()
            assert result["multifactor_profile"]["ranked_count"] == count
            assert result["multifactor_profile"]["configuration"]["configuration_id"] == identifier
            assert result["preferences_applied"]["multifactor_profile"]["weights"] == configs.preset(identifier)["weights"]
        monkeypatch.delenv("SIGRA_DERIVED_PERSONALIZATION_ENABLED")
        assert http.post("/recommendations?envelope=true", json=body).status_code == 422
        assert recommendation_method()["alternative_personalization"]["available"] is False
    finally:
        main.app.dependency_overrides.clear()
        main.app.dependency_overrides.update(previous)


@pytest.mark.parametrize("identifier", [configs.BASE, configs.EXPANDED])
def test_record_history_instrument_feedback_and_csv_keep_server_configuration(service, monkeypatch, identifier):
    """No SQL engine: verifies existing JSON storage/protocol/export with doubles."""
    import sqlalchemy.orm
    from app.academic_cohort.derived_configurations import recorded_configuration
    result = recommend_academic(service, request(service, multifactor_profile=selected(identifier)))
    parameters = result["preferences_applied"]
    context = models.ParticipantStudySession(id="synthetic-session", user_id=7, scenario_id="A", familiarity="low", priorities=["total_cost"],
        protocol_version="tcc-appendices-cd-v1", presentation_version="draft", environment_tag="homologation_synthetic")
    class QueryDouble:
        def __init__(self, db): self.db, self.filters = db, {}
        def filter_by(self, **values): self.filters = values; return self
        def first(self):
            return next((r for r in self.db.runs if all(getattr(r, k) == v for k, v in self.filters.items())), None)
        def order_by(self, *_): return self
        def yield_per(self, _): return iter(self.db.runs)
    class StoreDouble:
        def __init__(self): self.runs, self.answers = [], {}
        def add(self, value):
            if isinstance(value, models.ParticipantTestRun): self.runs.append(value)
            else: self.answers[value.run_id] = value
        def commit(self): pass
        def refresh(self, _): pass
        def get_bind(self): return object()
        def query(self, _): return QueryDouble(self)
        def get(self, model, identifier):
            return context if model == models.ParticipantStudySession else self.answers.get(identifier)
        def __enter__(self): return self
        def __exit__(self, *_): pass
    db = StoreDouble()
    monkeypatch.setattr(trials, "system_version", lambda: "test-only-version")
    monkeypatch.setattr(study_protocol, "current_migration_revision", lambda _: "synthetic-not-postgresql")
    monkeypatch.setenv("SIGRA_RESEARCH_PSEUDONYM_KEY", "test-only-pseudonym-key-at-least-32-bytes")
    monkeypatch.setattr(sqlalchemy.orm, "object_session", lambda _: db)
    user = models.User(id=7, name="Fictitious confidential name", email="not-exported@example.test", role="participant")
    receipt = trials.record_result(db, user, "recommendation", parameters, result, context=context)
    run = db.runs[0]
    assert receipt["test_run"]["saved"] and run.presented_results == result
    assert run.technical_record["personalization_configuration"] == recorded_configuration(result)
    assert run.technical_record["cost_scenario"] == "base" and run.technical_record["scenario_id"] == "A"
    for indexed, presented in zip(run.technical_record["ranking"], result["recommendations"]):
        ranked = presented["multifactor"]["status"] == "ranked"
        assert indexed["score_basis"] == ("personalized" if ranked else "reference")
        assert indexed["displayed_score"] == presented["score"]
        assert indexed["personalized_score"] == presented["multifactor"]["final_score"]
        if not ranked:
            assert all(factor in presented["explanations"] for factor in indexed["top_positive_factors"])
    assert trials.owned_run(db, user, run.id) is run
    from fastapi import HTTPException
    with pytest.raises(HTTPException): trials.owned_run(db, SimpleNamespace(id=8), run.id)
    answers = trials.Questionnaire(**dict.fromkeys(study_protocol.QUESTIONS, 4), comment="Synthetic response")
    saved = trials.questionnaire(run.id, answers, user, db)
    assert saved["questionnaire"]["interface_clarity"] == 4
    assert saved["technical_record"]["personalization_configuration"]["configuration_id"] == identifier
    assert trials.detail(run.id, Response(), user, db)["presented_results"] == result
    monkeypatch.setattr(trials, "Session", lambda **_: db)
    # Consume the real CSV generator; HTTP streaming and PostgreSQL are separate
    # integration gates. No event-loop sockets or SQL connection in this test.
    monkeypatch.setattr(trials, "StreamingResponse", lambda content, **options:
                        SimpleNamespace(body_iterator=iter(content), **options))
    exported = trials.export_trials(SimpleNamespace(role="admin"), db)
    assert exported.media_type == "text/csv; charset=utf-8"
    assert exported.headers["Cache-Control"] == "no-store"
    contents = "".join(exported.body_iterator)
    # The existing lossless export includes full sixty-vehicle JSON responses;
    # do not truncate them to fit Python csv's small default parser limit.
    old_limit = csv.field_size_limit()
    try:
        csv.field_size_limit(50_000_000)
        analytical = next(csv.DictReader(io.StringIO(contents.lstrip("\ufeff"))))
    finally:
        csv.field_size_limit(old_limit)
    assert analytical["participant_code"].startswith("P-")
    assert analytical["personalization_configuration_id"] == identifier
    assert json.loads(analytical["personalization_weights"])["safety"] == configs.preset(identifier)["weights"]["safety"]
    assert json.loads(analytical["technical_record"]) == json.loads(trials.canonical_json(run.technical_record))
    assert analytical["evidence_batch_version"] and analytical["profile"] == "app" and analytical["cost_scenario"] == "base"
    assert user.email not in contents and user.name not in contents
    assert run.result_fingerprint == trials.fingerprint(result)
