"""Real v4 calculations on synthetic observations; never connect to PostgreSQL."""
from copy import deepcopy
from decimal import Decimal
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError
from fastapi.testclient import TestClient

from app import main
from app.academic_cohort.contracts import PROFILE_COUNTS, method_manifest
from app.academic_cohort.recommendation import live_evaluation, recommend_academic, validated_weights
from app.academic_cohort.service import AcademicService, AcademicUnavailable
from data_platform.catalog.academic_cohort_v6 import V6ProfileVehicle, _evaluate_extended_v4
from data_platform.catalog.profile_contracts_v3 import blank_fields, observed, Citation
from data_platform.catalog.profile_pilot_v4 import fingerprint


def synthetic_vehicle(index):
    fields = blank_fields()
    values = {"fipe_code": f"{index:06d}-1", "year_code": "2020-5",
              "commercial_identity": f"Synthetic exact trim {index}", "reference_month": "2026-09",
              "price_brl": str(40000 + index * 1000), "fuel": "flex", "transmission": "manual",
              "consumption_city": str(10 + index % 6), "consumption_highway": "15",
              "seats": "5", "cargo_l": str(250 + index * 5), "length_mm": "4200", "width_mm": "1750",
              "wheelbase_mm": str(2400 + index * 5), "width_with_mirrors_mm": "2000",
              "payload_kg": "450", "ground_clearance_mm": "160", "weight_kg": "1200",
              "power_gasoline_cv": "110"}
    # Only one exact safety inventory; all others stay unknown, never false.
    if index == 1:
        values.update(airbags="6", abs=True, esc=True)
    for key, value in values.items():
        provider = ("fipe" if key in {"fipe_code", "year_code", "commercial_identity", "reference_month", "price_brl"}
                    else "pbev" if key in {"fuel", "transmission", "consumption_city", "consumption_highway"} else "manufacturer")
        source = Citation(provider=provider, url="https://example.test/synthetic", sha256="a" * 64,
                          document="Synthetic unit observation, not production", locator=key,
                          collected_at=datetime(2026, 9, 1, tzinfo=timezone.utc))
        fields[key] = observed(key, value, (source,))
    return V6ProfileVehicle(id=index, label=f"Synthetic vehicle {index}", identity_status="identity_approved", fields=fields)


class MemoryRepository:
    def __init__(self):
        self.snapshot_id = uuid4()
        self.rows = []
        for i in range(1, 61):
            vehicle = synthetic_vehicle(i)
            payload = vehicle.model_dump(mode="json")
            self.rows.append(SimpleNamespace(catalog_id=i, payload=payload, payload_fingerprint=fingerprint(payload),
                fipe_code=payload["fields"]["fipe_code"]["value"], year_code="2020-5", label=vehicle.label,
                reference_month="2026-09", purchase_price_brl=vehicle.fields["price_brl"].value,
                operationally_active=False, recommended=False))
        self.reads = 0

    def snapshot(self, snapshot_id):
        return SimpleNamespace(snapshot_id=self.snapshot_id, selected_count=60, operationally_active=False,
             recommended=False, profile_counts=PROFILE_COUNTS, source_manifest=method_manifest(),
             method_fingerprint=fingerprint(method_manifest()), cohort_fingerprint="a"*64,
             inventory_summary={"inventory_count": 81, "selected_ids": list(range(1, 61)),
                                "holdout_ids": list(range(70, 87)), "outside_selection": list(range(70, 91))})

    def vehicles(self, *_):
        self.reads += 1
        return self.rows, len(self.rows)

    def evaluations(self, _, *, profile, scenario):
        # Deliberately nonsense frozen scores/TCOs. They must NOT affect live output.
        result = []
        for row in self.rows:
            payload = {"id": row.catalog_id, "profile": profile, "scenario": scenario,
                "academic_test_ready": row.catalog_id <= PROFILE_COUNTS[profile],
                "preview_score": "999999", "scenario_monthly_tco_brl": "999999",
                "operationally_active": False, "recommended": False}
            result.append(SimpleNamespace(catalog_id=row.catalog_id, profile=profile, scenario=scenario,
                academic_test_ready=payload["academic_test_ready"], monthly_tco_brl=Decimal("999999"),
                score=Decimal("999999"), payload=payload, payload_fingerprint=fingerprint(payload),
                operationally_active=False, recommended=False))
        return result


@pytest.fixture
def service():
    return AcademicService(MemoryRepository())


def request(service, **changes):
    body = {"budget": 1000000, "monthly_limit": 100000, "use_case": "app",
            "monthly_mileage": 1000, "fuel_price": 6, "candidate_source": "academic_v6",
            "academic_options": {"snapshot_id": str(service.repository.snapshot_id)}}
    body.update(changes)
    return main.RecommendationRequest.model_validate(body)


def test_all_sixty_use_live_motor_not_stored_evaluations(service):
    result = recommend_academic(service, request(service))
    assert result["considered_count"] == result["eligible_count"] == 60
    assert len({r["vehicle"]["catalog_id"] for r in result["recommendations"]}) == 60
    assert result["ranking_executed"] and not result["stored_scores_used"]
    assert all(r["vehicle"]["operational_vehicle_id"] is None and "id" not in r["vehicle"] for r in result["recommendations"])
    assert all(Decimal(r["score"]) <= 100 and Decimal(r["monthly_total_cost"]) < 999999 for r in result["recommendations"])
    assert result["operationally_active"] is result["recommended"] is False


def test_fuel_and_distance_change_costs_and_scores(service):
    by_id = lambda result: {r["vehicle"]["catalog_id"]: r for r in result["recommendations"]}
    first = by_id(recommend_academic(service, request(service)))
    second = by_id(recommend_academic(service, request(service, monthly_mileage=2000, fuel_price=9)))
    for identifier in first:
        a, b = first[identifier]["evaluation"], second[identifier]["evaluation"]
        consumption = Decimal(service.repository.rows[identifier - 1].payload["fields"]["consumption_city"]["value"])
        assert Decimal(b["scenario_costs"]["components"]["fuel"]["value"]) == (Decimal(2000) / consumption * 9).quantize(Decimal("0.01"))
        assert Decimal(b["scenario_monthly_tco_brl"]) > Decimal(a["scenario_monthly_tco_brl"])
        assert a["preview_score"] != b["preview_score"]


def test_budgets_are_effective_eliminatory_filters(service):
    result = recommend_academic(service, request(service, budget=43000))
    assert result["eligible_count"] == 3
    assert all("PURCHASE_BUDGET" in r["reasons"] for r in result["excluded"])
    empty = recommend_academic(service, request(service, monthly_limit=1))
    assert empty["eligible_count"] == 0 and empty["recommendations"] == [] and empty["empty_reason"]
    assert all("MONTHLY_BUDGET" in r["reasons"] for r in empty["excluded"])


def test_weights_recompute_scores_and_positions_without_loosening_documents(service):
    options = {"snapshot_id": service.repository.snapshot_id, "criterion_weights":
               {"urban_fuel": 0, "passenger_space": 0, "cargo": 0, "price": 1}}
    result = recommend_academic(service, request(service, academic_options=options))
    assert [r["vehicle"]["catalog_id"] for r in result["recommendations"]] == list(range(1, 61))
    assert all(r["explanations"][0]["criterion"] == "price" for r in result["recommendations"])
    assert all(r["evaluation"]["coverage"]["original_weight_by_nature"]["observed"] == "1"
               for r in result["recommendations"])
    options["criterion_weights"] = {"seats": 1, "cargo": 0, "safety": 0, "price": 0}
    family = recommend_academic(service, request(service, use_case="familia", academic_options=options))
    assert family["eligible_count"] == 1


@pytest.mark.parametrize("profile,count", PROFILE_COUNTS.items())
def test_documentary_eligibility_is_not_sixty_for_every_profile(service, profile, count):
    result = recommend_academic(service, request(service, use_case=profile))
    assert result["documentary_eligible_count"] == result["eligible_count"] == count


def test_three_scenarios_and_lowest_cost_strategy(service):
    totals = []
    for scenario in ("low", "base", "high"):
        options = {"snapshot_id": service.repository.snapshot_id, "scenario": scenario}
        result = recommend_academic(service, request(service, academic_options=options, recommendation_strategy="lowest_cost"))
        totals.append({r["vehicle"]["catalog_id"]: Decimal(r["monthly_total_cost"]) for r in result["recommendations"]})
        order = [Decimal(r["monthly_total_cost"]) for r in result["recommendations"]]
        assert order == sorted(order)
    assert all(totals[0][i] < totals[1][i] < totals[2][i] for i in totals[0])


def test_default_recomposition_matches_unchanged_existing_method():
    vehicle = synthetic_vehicle(1)
    fresh = live_evaluation(vehicle, "app", "base", Decimal(1000), Decimal(6), validated_weights("app", None))
    previous = _evaluate_extended_v4(vehicle, "app", "base", "2026-09")
    assert fresh["preview_score"] == previous["preview_score"]
    assert fresh["utilities"] == previous["utilities"] and fresh["contributions"] == previous["contributions"]


@pytest.mark.parametrize("changes", [
    {"monthly_mileage": 0}, {"recommendation_strategy": "comfort_space"},
    {"academic_options": None},
    {"academic_options": {"snapshot_id": str(uuid4()), "criterion_weights": {"unknown": 1}}},
    {"academic_options": {"snapshot_id": str(uuid4()), "criterion_weights": {"urban_fuel": -1, "passenger_space": 1, "cargo": 1, "price": 1}}},
    {"candidate_source": "operational"},  # academic options must not silently disappear
])
def test_disconnected_or_invalid_preferences_are_rejected(service, changes):
    with pytest.raises(ValidationError):
        request(service, **changes)


def test_idempotence_and_no_mutation(service):
    before = fingerprint([r.payload for r in service.repository.rows])
    first = recommend_academic(service, request(service))
    second = recommend_academic(service, request(service))
    first.pop("generated_at"); second.pop("generated_at")
    assert first == second and before == fingerprint([r.payload for r in service.repository.rows])


def test_incomplete_or_tampered_candidates_fail_closed(service):
    service.repository.rows.pop()
    with pytest.raises(AcademicUnavailable):
        recommend_academic(service, request(service))


def test_duplicate_canonical_code_cannot_count_as_another_candidate(service):
    service.repository.rows[1].fipe_code = service.repository.rows[0].fipe_code
    with pytest.raises(AcademicUnavailable):
        recommend_academic(service, request(service))


def test_main_endpoint_does_not_query_operational_or_refresh_sources(service, monkeypatch):
    monkeypatch.setenv("ACADEMIC_COHORT_ENABLED", "true")
    monkeypatch.setattr(main, "get_academic_service", lambda db: service)
    monkeypatch.setattr(main, "ensure_fipe_prices_current", lambda: pytest.fail("Academic recommendation invoked FIPE"))
    main.app.dependency_overrides[main.get_db] = lambda: object()
    try:
        client = TestClient(main.app)
        response = client.post("/recommendations?envelope=true", json=request(service).model_dump(mode="json"))
        assert response.status_code == 200 and response.json()["eligible_count"] == 60
    finally:
        main.app.dependency_overrides.pop(main.get_db, None)
