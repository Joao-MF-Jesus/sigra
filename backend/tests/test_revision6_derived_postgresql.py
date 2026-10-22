"""Opt-in real PostgreSQL checks; no migrations, reset, downgrade or SQLite.

These tests complement the four Revision6 tests. They do NOT replace a real
API-process/browser journey or an OS-level API restart.
"""
from decimal import Decimal
import os

import pytest
from sqlalchemy.orm import Session

from backend.tests.test_revision6_postgresql import target
from app.academic_cohort import revision6_homologation as h
from app.academic_cohort import derived_configurations as configs
from app.academic_cohort.recommendation import recommend_academic

COUNTS = {configs.BASE: {"cidade":10,"app":60,"trabalho":10,"suv":24,"familia":9,"estrada":9},
          configs.EXPANDED: {"cidade":0,"app":8,"trabalho":0,"suv":3,"familia":8,"estrada":8}}


def preferences(profile,scenario,identifier,snapshot_id):
    from app.main import RecommendationRequest
    return RecommendationRequest.model_validate({"vehicle_type":"car","budget":1000000,"monthly_limit":100000,
        "use_case":profile,"monthly_mileage":1000,"fuel_price":6,"recommendation_strategy":"cost_benefit",
        "candidate_source":"academic_v6","academic_options":{"snapshot_id":str(snapshot_id),"scenario":scenario},
        "multifactor_profile":{"enabled":True,"policy_version":"academic-derived-seven-v1","configuration_id":identifier,
            "scenario":{"monthly_distance_km":"1000","city_percentage":"50","highway_percentage":"50",
                "state_code":"SP","reference_week_start":"2026-09-01","fuel_strategy":"gasoline_c_common",
                "horizon_months":12,"manual_fuel_price_brl":"6"}}})


@pytest.mark.parametrize("identifier",[configs.BASE,configs.EXPANDED])
def test_real_derived_counts_provenance_and_documentary_gates(target,identifier,monkeypatch):
    monkeypatch.setenv("SIGRA_DERIVED_PERSONALIZATION_ENABLED","true")
    _,_,plan,engine=target
    with Session(engine) as session:
        service=h.service_for_session(session)
        snapshot=service._snapshot()
        for scenario in ("low","base","high"):
            for profile,expected in COUNTS[identifier].items():
                result=recommend_academic(service,preferences(profile,scenario,identifier,snapshot.snapshot_id))
                assert result["considered_count"]==60
                assert len({r["catalog_id"] for r in result["candidate_diagnostics"]})==60
                assert result["documentary_eligible_count"]==plan.proposal.profile_counts[profile]
                assert result["multifactor_profile"]["ranked_count"]==expected
                record=configs.recorded_configuration(result)
                assert record["configuration_id"]==identifier and record["selection_explicit"]
                # Lossless JSON transport represents Decimal values as strings.
                assert sum(Decimal(str(v)) for v in record["normalized_weights_percentage"].values())==100
                assert record["evidence_batch_sha256"] and record["method_version"]=="academic-derived-seven-v1"
                assert not result["operationally_active"] and not result["recommended"]
                if identifier==configs.BASE:
                    assert Decimal(str(record["actual_weights"]["performance"]))==Decimal(str(record["actual_weights"]["safety"]))==0
                if identifier==configs.EXPANDED and profile in {"familia","estrada"}:
                    focus=next(r for r in result["recommendations"] if r["vehicle"]["catalog_id"]==80)
                    assert focus["multifactor"]["final_score"] is None
