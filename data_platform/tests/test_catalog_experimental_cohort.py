"""All vehicles and source bytes created here are synthetic unit-test fixtures."""
from decimal import Decimal as D
import hashlib
import json
from pathlib import Path

import pytest

from data_platform.catalog.experimental_cohort import assess_cohort, assess_vehicle, configuration
from data_platform.catalog.experimental_planning import directed_plan, fipe_plan, price_crosswalk, replay_price_aliases
from data_platform.catalog.intake import load_selection
from data_platform.catalog.profile_contracts_v3 import Citation, ProfileVehicle, blank_fields, observed


def citation(provider="manufacturer"):
    return Citation(provider=provider,url="https://example.org/source",sha256="a"*64,
                    document="SYNTHETIC TEST FIXTURE",locator="row=1",collected_at="2026-09-09T00:00:00Z")


def vehicle(identifier=35, *, month="2026-09", conflict=False, pending=False, **extra):
    fields=blank_fields()
    values={"fipe_code":f"{identifier:06d}-1","year_code":"2020-5","commercial_identity":"Synthetic exact trim",
            "reference_month":month,"price_brl":"50000","consumption_city":"12","consumption_highway":"15",
            "fuel":"flex","transmission":"manual",**extra}
    for name,value in values.items():
        provider="fipe" if name in {"fipe_code","year_code","commercial_identity","reference_month","price_brl"} else (
            "pbev" if name in {"consumption_city","consumption_highway","fuel","transmission"} else "manufacturer")
        fields[name]=observed(name,value,(citation(provider),))
    return ProfileVehicle(id=identifier,label="Synthetic fixture",identity_status="identity_approved",fields=fields,
                          source_conflicts=("synthetic conflict",) if conflict else (),
                          human_approval_required=pending,human_approval_status="pending" if pending else "not_applicable")


def body(value="hatchback"):
    return observed("commercial_identity",value,(citation(),)).model_copy(update={"unit":"text"})


@pytest.mark.parametrize("profile,values",[
    ("cidade",{"length_mm":"3800","width_with_mirrors_mm":"1850"}),
    ("app",{"seats":"5","cargo_l":"300"}),
    ("trabalho",{"cargo_l":"300"}),
    ("familia",{"seats":"5","cargo_l":"300","airbags":"4","abs":True,"esc":False}),
    ("estrada",{"airbags":"4","abs":True,"esc":True}),
    ("suv",{"seats":"5","cargo_l":"400","ground_clearance_mm":"180"}),
])
def test_minimum_core_is_sufficient_and_optional_fields_do_not_block(profile,values):
    row=assess_vehicle(vehicle(**values),profile,body_type=body() if profile=="suv" else None)
    assert row["partial_coverage_candidate"]
    assert row["core_coverage"]==1
    assert row["score"] is None and row["confidence"] is None and not row["active"]


def test_same_vehicle_can_be_eligible_for_all_six_without_group_or_name_input():
    values={"length_mm":"3800","width_with_mirrors_mm":"1850","seats":"5","cargo_l":"400",
            "payload_kg":"450","airbags":"4","abs":True,"esc":True,"ground_clearance_mm":"180",
            "weight_kg":"1000","power_gasoline_cv":"100"}
    one=vehicle(**values)
    report=assess_cohort([one],body_types={35:body()},stability_verified=True)
    assert report["partial_coverage_candidate_union"]==[35]
    assert all(ids==[35] for ids in report["partial_coverage_candidate_ids"].values())
    renamed=ProfileVehicle.model_validate({**one.model_dump(),"label":"Preferred SUV winner","provenance":{"collection_group":"SUV"}})
    assert assess_cohort([renamed],body_types={35:body()},stability_verified=True)["partial_coverage_candidate_ids"]==report["partial_coverage_candidate_ids"]


def test_absent_and_optional_are_separate_and_coverage_is_not_score():
    row=assess_vehicle(vehicle(),"app")
    assert set(row["absent_fields"])=={"seats","cargo_l"}
    assert row["core_coverage"]==D("0.6")
    assert not row["partial_coverage_candidate"]
    assert row["costs"]["monthly_tco"] is None
    assert row["costs"]["monthly_budget_eligible"] is None


@pytest.mark.parametrize("kwargs,reason",[
    ({"month":"2026-07"},"FIPE_MONTH_NOT_ALIGNED"),
    ({"conflict":True},"OPEN_SOURCE_CONFLICT"),
    ({"pending":True},"HUMAN_SUBSTITUTION_APPROVAL_PENDING"),
])
def test_independent_gates_remain_blocking(kwargs,reason):
    row=assess_vehicle(vehicle(length_mm="3800",width_with_mirrors_mm="1850",**kwargs),"cidade")
    assert reason in row["blockers"] and not row["partial_coverage_candidate"]


def test_body_type_cannot_be_inferred_or_derived_from_name_collection_or_weak_source():
    v=vehicle(seats="5",cargo_l="400",ground_clearance_mm="180")
    assert "body_type" in assess_vehicle(v,"suv")["absent_fields"]
    derived=body().model_copy(update={"kind":"derived","method_version":"catalog-profile-evidence-v3",
                                      "formula":"name implies body", "inputs":{"x":D(1)}})
    with pytest.raises(ValueError,match="requires individually"):
        assess_vehicle(v,"suv",body_type=derived)


def test_duplicate_canonical_options_fail_closed():
    first=vehicle(35,length_mm="3800",width_with_mirrors_mm="1850")
    second=vehicle(36,length_mm="3900",width_with_mirrors_mm="1900")
    fields={**second.model_dump()["fields"],"fipe_code":first.fields["fipe_code"].model_dump(),
            "year_code":first.fields["year_code"].model_dump()}
    second=ProfileVehicle.model_validate({**second.model_dump(),"fields":fields})
    report=assess_cohort([first,second],stability_verified=True)
    assert report["partial_coverage_candidates"]["cidade"]==0
    assert all("DUPLICATE_CANONICAL_OPTION" in r["blockers"] for r in report["matrix"])


def test_exact_fipe_plan_has_no_network_execution_and_obeys_attempt_cap():
    legacy=[vehicle(i,month="2026-07") for i in range(1,35)]
    candidates=[vehicle(i) for i in range(35,54) if i not in {48,50,53}]+[vehicle(i) for i in (54,55,56)]
    plan=fipe_plan(legacy,candidates)
    assert plan["calls_current_reference_refresh"]==34
    assert plan["calls_executed"]==0
    assert plan["vehicles_pending_temporal_alignment"]==34
    assert plan["attempts_planned"]==34
    assert plan["attempts_executed"]==0
    assert plan["attempts_available"]==34
    assert plan["attempt_budget_is_formally_authorized"] is True
    assert plan["percentage_of_documented_daily_limit"]==D("6.8")
    assert plan["authorized_attempt_limit"]==34
    assert not plan["execution_allowed"] and plan["remaining_quota_verified"] is None
    assert plan["calls_to_discover_years_or_families"]==0
    assert len({r["idempotency_key"] for r in plan["requests"]})==34
    assert fipe_plan(legacy,candidates,remaining_quota=34,access_verified=True,quota_verified=True,month_pin_verified=True)["execution_allowed"]
    with pytest.raises(ValueError,match="attempt limit"):
        fipe_plan(legacy,candidates,attempt_limit=35)


def test_fipe_plan_deduplicates_an_existing_september_key_without_http():
    old=vehicle(1,month="2026-07"); current=vehicle(35)
    fields={**current.model_dump()["fields"],"fipe_code":old.fields["fipe_code"].model_dump(),
            "year_code":old.fields["year_code"].model_dump()}
    current=ProfileVehicle.model_validate({**current.model_dump(),"fields":fields})
    plan=fipe_plan([old],[current])
    assert plan["calls_current_reference_refresh"]==0 and plan["cache_reused"]==[{"vehicle_id":1,"cached_vehicle_id":35}]


def test_legacy_identity_holds_fail_closed_before_silver_or_gold():
    review=price_crosswalk()
    holds={row["id"]:row for row in review["catalog_identity_holds"]}
    pending={row["id"]:row for row in review["additional_review_flags"]}
    assert set(holds)=={6,7,23} and set(pending)=={13,17,21,33}
    assert all(row["resolution_status"]=="blocked_incompatible_catalog_trim" for row in holds.values())
    assert all(not row["silver_identity_compatible"] and not row["gold_publishable"] for row in (*holds.values(),*pending.values()))
    assert all(row["required_evidence"] for row in (*holds.values(),*pending.values()))


def test_price_crosswalk_is_exact_hash_bound_and_never_approves_identity(tmp_path,monkeypatch):
    import data_platform.catalog.experimental_planning as module
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "backend"))
    from app.fipe import FIPE_REFERENCE_PROFILES
    records=[]; vehicles=[]
    special={9:"Corolla GLi 1.8 Flex 16V  Aut.",15:"Civic Sedan EX 2.0 Flex 16V Aut.4p",
             19:"VIRTUS 1.6 MSI Flex 16V 5p Mec.",21:"T-Cross Comfor. 200 TSI 1.0 Flex 5p Aut."}
    for i in range(1,35):
        ref=FIPE_REFERENCE_PROFILES[i]
        records.append({"vehicle_id":i,"code":ref.code,"year_code":ref.year_code+"-5" if "-" not in ref.year_code else ref.year_code,
                        "model":special.get(i,ref.model),"reference_month":"julho de 2026","retrieval_status":"live",
                        "retrieved_at":"2026-07-20T00:00:00Z","source_url":"https://fipe.parallelum.com.br/","price":"50000"})
        vehicles.append(ProfileVehicle(id=i,label="legacy",identity_status="legacy_binding_not_reaudited",fields=blank_fields()))
    records[12]["year_code"]="2017-1"
    cache=tmp_path/"cache.json";cache.write_text(json.dumps(records),encoding="utf-8")
    spec=json.loads(module.PRICE_CROSSWALK_PATH.read_text(encoding="utf-8"));spec["source_sha256"]=hashlib.sha256(cache.read_bytes()).hexdigest()
    path=tmp_path/"crosswalk.json";path.write_text(json.dumps(spec),encoding="utf-8");monkeypatch.setattr(module,"PRICE_CROSSWALK_PATH",path)
    updated,diagnostics=replay_price_aliases(vehicles,cache)
    assert [v.id for v in updated if v.fields["price_brl"].value is not None]==[9,15,19,21]
    assert all(v.identity_status=="legacy_binding_not_reaudited" for v in updated)
    assert all(not r["catalog_identity_approved"] for r in diagnostics)
    records[8]["model"]="similar but not exact";cache.write_text(json.dumps(records),encoding="utf-8")
    spec["source_sha256"]=hashlib.sha256(cache.read_bytes()).hexdigest();path.write_text(json.dumps(spec),encoding="utf-8")
    with pytest.raises(ValueError,match="Exact registered"):
        replay_price_aliases(vehicles,cache)


def test_configuration_tracks_backlog_without_activating_it():
    config=configuration()
    assert config["broad_expansion"]["backlog_ids"]=={"first":57,"last":100}
    assert not config["broad_expansion"]["batch_processing_enabled"]
    assert not config["production_publication_enabled"]


def test_directed_plan_uses_existing_dossiers_before_selecting_another_batch():
    vehicles=[vehicle(identifier) for identifier in range(35,45)]
    assessment=assess_cohort(vehicles,stability_verified=True)
    plan=directed_plan(vehicles,assessment,load_selection())
    assert [row["id"] for row in plan["priority_dossiers"]]==list(range(35,45))
    assert plan["additional_mathematical_lower_bound"]==0
    assert plan["additional_selected_ids"]==[]
    assert plan["wide_expansion_frozen"]
    assert plan["carpedia"]["calls_executed"]==0
    assert plan["carpedia"]["attempt_limit_absolute"]==10
    assert plan["carpedia"]["attempts_remaining"]==10
    assert [row["id"] for row in plan["carpedia"]["candidates"]]==[37,38,39,42,43,44]
    assert plan["carpedia"]["credential_environment"]=="CARPEDIA_API_KEY"
    assert all(candidate["official_external_id"] is None for candidate in plan["carpedia"]["candidates"])
