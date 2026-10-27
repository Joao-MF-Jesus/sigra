"""Fictitious ranking rows only: no engine, database or operational data."""
from copy import deepcopy
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app import study_protocol


def record(monkeypatch, row):
    monkeypatch.setattr(study_protocol, "current_migration_revision", lambda _: "test-only-revision")
    context = SimpleNamespace(protocol_version="test-only", scenario_id="A",
                              environment_tag="homologation_synthetic", priorities=[])
    result = {"snapshot_id": "test-only-snapshot", "algorithm_version": "test-only-method",
              "weights_version": "test-only-weights", "recommendations": [row]}
    before = deepcopy(result)
    value = study_protocol.technical_record(SimpleNamespace(get_bind=lambda: object()), context,
                                           "recommendation", {}, result, .01, "succeeded", None)
    assert result == before
    assert value["ranking_trace_version"] == "ranking-basis-v1"
    return value["ranking"][0]


def test_unavailable_personalization_never_attributes_diagnostic_factors_to_reference(monkeypatch):
    reference = {"criterion": "price", "contribution": Decimal("12")}
    diagnostic = {"component": "comfort", "contribution": Decimal("25"),
                  "calculation_scope": "diagnostic_only", "used_in_final_score": False}
    row = {"vehicle": {"catalog_id": 999}, "score": Decimal("60"),
           "baseline_score": Decimal("60"), "explanations": [reference],
           "multifactor": {"status": "unavailable", "final_score": None, "components": [diagnostic]}}
    value = record(monkeypatch, row)
    assert value["score"] is value["personalized_score"] is None
    assert value["score_basis"] == "reference"
    assert value["displayed_score"] == value["reference_score"] == 60
    assert value["top_positive_factors"] == [reference]
    assert diagnostic not in value["top_positive_factors"]


@pytest.mark.parametrize("score", [Decimal("0"), Decimal("65")])
def test_ranked_score_uses_personalized_factors_even_at_zero(monkeypatch, score):
    applied = {"component": "total_cost", "contribution": Decimal("15"), "used_in_final_score": True}
    excluded = {"component": "safety", "contribution": Decimal("90"), "used_in_final_score": False}
    row = {"vehicle": {"catalog_id": 999}, "score": score, "baseline_score": Decimal("80"),
           "explanations": [{"criterion": "price", "contribution": 99}],
           "multifactor": {"status": "ranked", "final_score": score, "components": [applied, excluded]}}
    value = record(monkeypatch, row)
    assert value["score_basis"] == "personalized"
    assert value["score"] == value["personalized_score"] == value["displayed_score"] == score
    assert value["reference_score"] == 80
    assert value["top_positive_factors"] == [applied]


def test_unpersonalized_response_keeps_reference_score_and_factors(monkeypatch):
    positive = {"criterion": "price", "contribution": 10}
    negative = {"criterion": "test-only-penalty", "contribution": -3}
    row = {"vehicle": {"catalog_id": 999}, "score": 40, "explanations": [positive, negative]}
    value = record(monkeypatch, row)
    assert value["score"] == value["displayed_score"] == value["reference_score"] == 40
    assert value["personalized_score"] is None and value["score_basis"] == "reference"
    assert value["top_positive_factors"] == [positive]
    assert value["top_negative_factors"] == [negative]


@pytest.mark.parametrize("explanations", [[], {"not": "a-list"}])
def test_missing_reference_explanations_do_not_fall_back_to_diagnostic_scores(monkeypatch, explanations):
    value = record(monkeypatch, {"vehicle": {"catalog_id": 999}, "score": 40,
        "explanations": explanations, "multifactor": {"status": "unavailable", "final_score": None,
            "components": [{"component": "comfort", "contribution": 15}]}})
    assert value["top_positive_factors"] == value["top_negative_factors"] == []
    assert value["personalized_score"] is None


def test_original_ranked_components_without_new_flags_remain_compatible(monkeypatch):
    factor = {"component": "total_cost", "contribution": 15}
    value = record(monkeypatch, {"vehicle": {"catalog_id": 999}, "score": 65,
        "multifactor": {"status": "ranked", "final_score": 65, "components": [factor]}})
    assert value["score_basis"] == "personalized"
    assert value["top_positive_factors"] == [factor]
    assert value["reference_score"] is None  # No invented baseline.
