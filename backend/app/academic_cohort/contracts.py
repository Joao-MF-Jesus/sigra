"""Transport boundary for the approved replay, not a new scoring methodology."""
from dataclasses import dataclass
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re

from data_platform.catalog import academic_cohort_v6 as v6
from data_platform.catalog.profile_pilot_v4 import fingerprint

APPROVED_FINGERPRINT = "d974f86d2deef3903ac052263c7edc406c5b2c21d794721e5220ed5d99acc05d"
PROFILES = ("cidade", "app", "trabalho", "suv", "familia", "estrada")
SCENARIOS = ("low", "base", "high")
PROFILE_COUNTS = dict(zip(PROFILES, (10, 60, 10, 24, 1, 1)))
LIMITATIONS = [
    "Academic-only preview; not an operational recommendation or Gold activation.",
    "TCO is a versioned scenario estimate, not an observed cost.",
    "academic_habitability_proxy is derived, not measured interior space.",
    "Ranking groups with different evidence/protocols are not comparable.",
    "Family and road have one eligible configuration each, not sixty.",
]


def json_document(value):
    # Same Decimal representation used by the unchanged canonical fingerprint.
    def encode(item):
        if isinstance(item, Decimal):
            return str(item)
        if hasattr(item, "model_dump"):
            return item.model_dump(mode="json")
        raise TypeError(type(item).__name__)
    return json.loads(json.dumps(value, default=encode))


def method_manifest():
    root = v6.ROOT
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.iterdir()) if p.suffix in {".py", ".json"}}


@dataclass(frozen=True)
class MaterializationPlan:
    cohort_fingerprint: str
    source_manifest: dict
    summary: dict
    vehicles: tuple[dict, ...]
    evaluations: tuple[dict, ...]


def validate_replay(replay: dict) -> MaterializationPlan:
    """Whole-replay trust anchor prevents admitting edited/partial cached results."""
    if fingerprint(replay) != APPROVED_FINGERPRINT:
        raise ValueError("Replay differs from the approved v6 fingerprint")
    config = v6.configuration()
    selected = config["baseline_ready_ids"] + config["additional_selected_ids"]
    if (replay["version"] != v6.VERSION or replay["decision"] != "ACADEMIC_COHORT_V6_COMPLETE"
            or replay["inventory_count"] != 81 or replay["cohort_size"] != 60
            or replay["academic_test_ready_count"] != 60 or replay["profile_counts"] != PROFILE_COUNTS
            or set(replay["selected_ids"]) != set(selected) or len(replay["selected_ids"]) != 60
            or replay["holdout_ids"] != list(v6.HOLDOUTS)
            or replay["operationally_active"] != 0 or replay["recommended"] != 0
            or replay["operational_ranking"] != []):
        raise ValueError("Inconsistent v6 membership or operational flags")
    states = {r["id"]: r for r in replay["states"]}
    if len(states) != 81 or len(replay["states"]) != 81:
        raise ValueError("Invalid inventory grain")
    rows, evaluations, codes, identifiers = [], [], set(), set()
    for item in replay["academic_payload"]:
        vehicle = v6.V6ProfileVehicle.model_validate(item["vehicle"])
        fields = vehicle.fields
        identifier = vehicle.id
        if identifier in identifiers or identifier not in selected or identifier in v6.HOLDOUTS or identifier in {101, 103, 111}:
            raise ValueError("Duplicate, holdout or nonselected identity")
        identifiers.add(identifier)
        code = fields["fipe_code"].value
        if not re.fullmatch(r"\d{6}-\d", code) or code in codes:
            raise ValueError("Duplicate or invalid canonical FIPE code")
        codes.add(code)
        if item["mode"] != "academic_only" or item["operationally_active"] is not False or item["recommended"] is not False:
            raise ValueError("Academic payload cannot activate operational records")
        state = states[identifier]
        if not state["academic_cohort_selected"] or state["legacy_holdout"] or not state["academic_test_ready"]:
            raise ValueError("Selected state inconsistent")
        raw = json_document(item["vehicle"])
        rows.append({"catalog_id": identifier, "canonical_identity_key": fingerprint({k: fields[k].value for k in
                     ("fipe_code", "year_code", "commercial_identity", "fuel", "transmission")}),
                     "fipe_code": code, "year_code": fields["year_code"].value, "label": vehicle.label,
                     "purchase_price_brl": fields["price_brl"].value,
                     "reference_month": v6.price_reference_month(fields["reference_month"].value),
                     "payload": raw, "payload_fingerprint": fingerprint(raw)})
        if set(item["evaluations"]) != set(SCENARIOS):
            raise ValueError("Three academic cost scenarios required")
        for scenario in SCENARIOS:
            if set(item["evaluations"][scenario]) != set(PROFILES):
                raise ValueError("Six profiles required")
            for profile in PROFILES:
                result = json_document(item["evaluations"][scenario][profile])
                if fingerprint(result) != fingerprint(state["evaluations"][scenario][profile]):
                    raise ValueError("Payload/state evaluation mismatch")
                if (result["id"] != identifier or result["profile"] != profile or result["scenario"] != scenario
                        or result["operationally_active"] is not False or result["recommended"] is not False
                        or result["operational_ranking"] != []
                        or not result["scenario_tco_complete"]):
                    raise ValueError("Invalid evaluation context")
                costs = result["scenario_costs"]
                if costs["scenario_total"]["nature"] != "scenario_estimate" or costs["operational_activation_allowed"]:
                    raise ValueError("Scenario cannot masquerade as observed cost")
                score = None if result["preview_score"] is None else Decimal(result["preview_score"])
                total = Decimal(result["scenario_monthly_tco_brl"])
                if not total.is_finite() or total < 0 or score is not None and (not score.is_finite() or not 0 <= score <= 100):
                    raise ValueError("Invalid score or monthly cost")
                evaluations.append({"catalog_id": identifier, "profile": profile, "scenario": scenario,
                                    "academic_test_ready": result["academic_test_ready"], "score": score,
                                    "monthly_tco_brl": total, "payload": result,
                                    "payload_fingerprint": fingerprint(result)})
    if len(rows) != 60 or identifiers != set(selected) or len(evaluations) != 1080:
        raise ValueError("Incomplete snapshot")
    for scenario in SCENARIOS:
        for profile in PROFILES:
            count = sum(r["academic_test_ready"] for r in evaluations if r["profile"] == profile and r["scenario"] == scenario)
            if count != PROFILE_COUNTS[profile]:
                raise ValueError("Profile coverage differs from canonical replay")
    summary = {"inventory_count": 81, "selected_ids": sorted(identifiers), "holdout_ids": list(v6.HOLDOUTS),
               "outside_selection": [{"id": i, "state_fingerprint": fingerprint(state),
                                       "legacy_holdout": state["legacy_holdout"],
                                       "rejection_reasons": state.get("rejection_reasons", [])}
                                      for i, state in sorted(states.items()) if i not in identifiers]}
    return MaterializationPlan(APPROVED_FINGERPRINT, method_manifest(), summary, tuple(rows), tuple(evaluations))


def load_replay(path: Path) -> MaterializationPlan:
    return validate_replay(json.loads(Path(path).read_text(encoding="utf-8")))
