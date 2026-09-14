"""Offline experimental cores over v3 evidence; no inference, score or writes."""
from collections import Counter
from decimal import Decimal
import json
from pathlib import Path

from data_platform.catalog.profile_contracts_v3 import Observation, available
from data_platform.catalog.profile_costs_v3 import cost_evidence
from data_platform.catalog.profile_scoring_v3 import configuration as v3_configuration

CONFIG_PATH = Path(__file__).with_name("experimental_core_v1.json")


def configuration():
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def assess_vehicle(vehicle, profile, *, body_type=None, config=None):
    config = configuration() if config is None else config
    core = config["profiles"][profile]
    if body_type is None:
        body_type = Observation(unit="text",reason="No individually reviewed body style; no inference from collection group")
    if body_type.unit != "text":
        raise ValueError("Body type must be a sourced descriptive text")
    if body_type.kind != "unavailable" and (
        body_type.kind != "observed" or body_type.applicability not in {"exact_variant", "model_nominal"}
        or any(s.provider not in {"manufacturer","carpedia"} for s in body_type.sources)
    ):
        raise ValueError("Body type requires individually applicable technical evidence")
    fields = {**vehicle.fields, "body_type":body_type}
    def present(name):
        o = fields[name]
        return o.value is not None and o.kind != "unavailable"
    mandatory = core["all"] + [field for group in core["any"] for field in group]
    groups = [[name] for name in core["all"]] + core["any"]
    unsatisfied = [group for group in groups if not any(present(name) for name in group)]
    coverage = Decimal(len(groups)-len(unsatisfied))/Decimal(len(groups))
    coverage_blockers = []
    if unsatisfied: coverage_blockers.append("MANDATORY_CORE_EVIDENCE_MISSING")
    eligibility_blockers = []
    if vehicle.identity_status != "identity_approved": eligibility_blockers.append("CATALOG_IDENTITY_NOT_APPROVED")
    month = vehicle.fields["reference_month"].value
    if month != config["target_month"]: eligibility_blockers.append("FIPE_MONTH_NOT_ALIGNED")
    if vehicle.source_conflicts: eligibility_blockers.append("OPEN_SOURCE_CONFLICT")
    if vehicle.human_approval_required and vehicle.human_approval_status != "human_approved":
        eligibility_blockers.append("HUMAN_SUBSTITUTION_APPROVAL_PENDING")
    if "fuel" in mandatory and vehicle.fields["fuel"].value not in {"gasoline","flex"}:
        eligibility_blockers.append("GASOLINE_SCENARIO_COMPATIBILITY_UNPROVEN")
    if not all(present(name) for name in ("fipe_code","year_code","commercial_identity")):
        eligibility_blockers.append("CANONICAL_KEY_OR_DESCRIPTION_MISSING")
    if not all(fields[name].sources for name in mandatory if present(name)):
        eligibility_blockers.append("UNTRACEABLE_CORE_FIELD")
    sources = {name: fields[name] for name in dict.fromkeys(mandatory+core["optional"])}
    known_count = sum(present(name) for name in sources)
    key = (vehicle.fields["fipe_code"].value,vehicle.fields["year_code"].value)
    identity_resolved = vehicle.identity_status == "identity_approved" and all(
        present(name) for name in ("fipe_code", "year_code", "commercial_identity")
    )
    partial = known_count > 0
    core_complete = not unsatisfied
    blockers = eligibility_blockers + coverage_blockers
    return {"vehicle_id":vehicle.id,"vehicle":vehicle.label,"profile":profile,
            "core_version":config["version"],"canonical_key":key,
            "mandatory_fields":core["all"],"mandatory_any":core["any"],
            "present_fields":[name for name in mandatory if present(name)],
            "absent_fields":[name for name in mandatory if not present(name)],
            "unsatisfied_groups":unsatisfied,"optional_fields":core["optional"],
            "optional_absent":[name for name in core["optional"] if not present(name)],
            "sources":sources,"core_coverage":coverage,
            "full_field_coverage":Decimal(known_count)/Decimal(len(sources)),
            "observed_reference_month":month,"required_reference_month":config["target_month"],
            "identity_resolved":identity_resolved,
            "partial_coverage_candidate":partial,
            "core_coverage_complete":core_complete,
            "profile_eligible":not eligibility_blockers,
            "methodology_ready":False,
            "recommended":False,
            "coverage_blockers":coverage_blockers,
            "eligibility_blockers":eligibility_blockers,
            "blockers":blockers,
            "source_conflicts":vehicle.source_conflicts,"score":None,"score_not_computed":True,
            "confidence":None,"active":False,
            "costs":cost_evidence(vehicle,v3_configuration()["scenario"])}


def assess_cohort(vehicles, *, body_types=None, stability_verified=False):
    config=configuration(); vehicles=tuple(vehicles); body_types=body_types or {}
    if len({v.id for v in vehicles}) != len(vehicles): raise ValueError("Duplicate vehicle ID")
    if any(v.id in {48,50,53} for v in vehicles): raise ValueError("Blocked identity in experimental pool")
    rows=[assess_vehicle(v,p,body_type=body_types.get(v.id)) for v in vehicles for p in config["profiles"]]
    keys=Counter((v.fields["fipe_code"].value,v.fields["year_code"].value) for v in vehicles
                 if available(v,"fipe_code") and available(v,"year_code"))
    for row in rows:
        if keys[row["canonical_key"]]>1:
            row["blockers"].append("DUPLICATE_CANONICAL_OPTION")
            row["eligibility_blockers"].append("DUPLICATE_CANONICAL_OPTION")
            row["profile_eligible"]=False
    partial={p:sorted(r["vehicle_id"] for r in rows if r["profile"]==p and r["partial_coverage_candidate"]) for p in config["profiles"]}
    complete={p:sorted(r["vehicle_id"] for r in rows if r["profile"]==p and r["core_coverage_complete"]) for p in config["profiles"]}
    eligible={p:sorted(r["vehicle_id"] for r in rows if r["profile"]==p and r["profile_eligible"]) for p in config["profiles"]}
    eligible_complete={p:sorted(set(complete[p]) & set(eligible[p])) for p in config["profiles"]}
    gaps={p:max(0,config["minimum_options_per_profile"]-len(ids)) for p,ids in eligible_complete.items()}
    overlap={a:{b:sorted(set(left)&set(right)) for b,right in partial.items()} for a,left in partial.items()}
    return {"version":config["version"],"pool_count":len(vehicles),"target_month":config["target_month"],
            "matrix":rows,"partial_coverage_candidate_ids":partial,
            "partial_coverage_candidates":{p:len(ids) for p,ids in partial.items()},
            "core_coverage_complete_ids":complete,
            "core_coverage_complete_candidates":{p:len(ids) for p,ids in complete.items()},
            "profile_eligible_ids":eligible,
            "core_coverage_complete_and_eligible_ids":eligible_complete,
            "core_coverage_complete_and_eligible_candidates":{p:len(ids) for p,ids in eligible_complete.items()},
            "gaps_to_ten_core_coverage_complete":gaps,"partial_coverage_overlap":overlap,
            "partial_coverage_candidate_union":sorted({i for ids in partial.values() for i in ids}),
            "missing_by_profile":{p:dict(Counter(name for r in rows if r["profile"]==p for group in r["unsatisfied_groups"] for name in group)) for p in partial},
            "blockers_by_profile":{p:dict(Counter(b for r in rows if r["profile"]==p for b in r["blockers"])) for p in partial},
            "pool_temporally_aligned":all(v.fields["reference_month"].value==config["target_month"] and available(v,"price_brl") for v in vehicles),
            "stability_318_verified":stability_verified,
            "core_coverage_capacity_gate_passed":not any(gaps.values()) and stability_verified,
            "partial_coverage_capacity_gate_passed":not any(gaps.values()) and stability_verified,
            "operational_publication_authorized":False,
            "interpretation":"Partial coverage means some profile evidence only. Complete core, profile eligibility, methodology readiness, complete TCO and recommendation are separate gates. No ranking mixes July and September prices."}
