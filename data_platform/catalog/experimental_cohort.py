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
    blockers = []
    if unsatisfied: blockers.append("MANDATORY_CORE_EVIDENCE_MISSING")
    if vehicle.identity_status != "identity_approved": blockers.append("CATALOG_IDENTITY_NOT_APPROVED")
    month = vehicle.fields["reference_month"].value
    if month != config["target_month"]: blockers.append("FIPE_MONTH_NOT_ALIGNED")
    if vehicle.source_conflicts: blockers.append("OPEN_SOURCE_CONFLICT")
    if vehicle.human_approval_required and vehicle.human_approval_status != "human_approved":
        blockers.append("HUMAN_SUBSTITUTION_APPROVAL_PENDING")
    if "fuel" in mandatory and vehicle.fields["fuel"].value not in {"gasoline","flex"}:
        blockers.append("GASOLINE_SCENARIO_COMPATIBILITY_UNPROVEN")
    if not all(present(name) for name in ("fipe_code","year_code","commercial_identity")):
        blockers.append("CANONICAL_KEY_OR_DESCRIPTION_MISSING")
    if not all(fields[name].sources for name in mandatory if present(name)):
        blockers.append("UNTRACEABLE_CORE_FIELD")
    sources = {name: fields[name] for name in dict.fromkeys(mandatory+core["optional"])}
    known_count = sum(present(name) for name in sources)
    key = (vehicle.fields["fipe_code"].value,vehicle.fields["year_code"].value)
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
            "partial_coverage_candidate":not blockers,"blockers":blockers,
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
            row["partial_coverage_candidate"]=False
    partial={p:sorted(r["vehicle_id"] for r in rows if r["profile"]==p and r["partial_coverage_candidate"]) for p in config["profiles"]}
    gaps={p:max(0,config["minimum_options_per_profile"]-len(ids)) for p,ids in partial.items()}
    overlap={a:{b:sorted(set(left)&set(right)) for b,right in partial.items()} for a,left in partial.items()}
    return {"version":config["version"],"pool_count":len(vehicles),"target_month":config["target_month"],
            "matrix":rows,"partial_coverage_candidate_ids":partial,
            "partial_coverage_candidates":{p:len(ids) for p,ids in partial.items()},
            "gaps_to_ten_partial_coverage_candidates":gaps,"partial_coverage_overlap":overlap,
            "partial_coverage_candidate_union":sorted({i for ids in partial.values() for i in ids}),
            "missing_by_profile":{p:dict(Counter(name for r in rows if r["profile"]==p for group in r["unsatisfied_groups"] for name in group)) for p in partial},
            "blockers_by_profile":{p:dict(Counter(b for r in rows if r["profile"]==p for b in r["blockers"])) for p in partial},
            "pool_temporally_aligned":all(v.fields["reference_month"].value==config["target_month"] and available(v,"price_brl") for v in vehicles),
            "stability_318_verified":stability_verified,
            "partial_coverage_capacity_gate_passed":not any(gaps.values()) and stability_verified,
            "operational_publication_authorized":False,
            "interpretation":"Partial core coverage permits overlap, but never means methodology-ready or recommendation-ready. No ranking mixes July and September prices."}
