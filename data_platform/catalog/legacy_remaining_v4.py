"""Read-only closure audit; no new identity approvals or source substitutions.

The disposition table describes the current evidence gap, not an eligibility
rule. Readiness is always replayed by the unchanged academic v4 evaluator.
"""
from data_platform.catalog.intake import load_selection
from data_platform.catalog.legacy_academic_v4 import legacy_matrix_v4, replay_legacy_v4
from data_platform.catalog.legacy_technical_v4 import augment_legacy_technical_v4

VERSION = "legacy-remaining-v4-audit-v1"
DISPOSITIONS = {
    1: "MISSING_PBEV_BINDING",
    6: "IDENTITY_CONFLICT", 7: "IDENTITY_CONFLICT",
    9: "MISSING_TECHNICAL_EVIDENCE",
    11: "MISSING_EXACT_IDENTITY", 12: "MISSING_PBEV_BINDING",
    13: "IDENTITY_CONFLICT", 17: "MISSING_EXACT_IDENTITY",
    18: "MISSING_PBEV_BINDING", 19: "MISSING_EXACT_IDENTITY",
    21: "IDENTITY_CONFLICT", 23: "IDENTITY_CONFLICT",
    24: "MISSING_EXACT_IDENTITY", 25: "MISSING_EXACT_IDENTITY",
    26: "MISSING_PBEV_BINDING", 27: "MISSING_EXACT_IDENTITY",
    28: "MISSING_PBEV_BINDING", 33: "MISSING_TECHNICAL_EVIDENCE",
}


def ready_ids(replay):
    """Require the same profile to pass in all three scenarios, not just base."""
    if set(replay) != {"low", "base", "high"}:
        raise ValueError("Exactly three scenarios required")
    profiles = set(replay["base"])
    if not profiles or any(set(value) != profiles for value in replay.values()):
        raise ValueError("Scenario profiles differ")
    result = set()
    for profile in profiles:
        sets = []
        expected = None
        for scenario in ("low", "base", "high"):
            rows = replay[scenario][profile]
            ids = [row["id"] for row in rows]
            if len(ids) != len(set(ids)) or (expected is not None and set(ids) != expected):
                raise ValueError("Duplicate or missing replay identity")
            expected = set(ids)
            for row in rows:
                if row["operationally_active"] or row["recommended"]:
                    raise ValueError("Operational result prohibited")
                if row["academic_test_ready"] and not row["scenario_tco_complete"]:
                    raise ValueError("Academic readiness without complete scenario TCO")
            sets.append({row["id"] for row in rows if row["academic_test_ready"]})
        result.update(set.intersection(*sets))
    return sorted(result)


def audit_remaining(archive):
    """Hash-verified local replay of all 34; retain every input field unchanged."""
    vehicles = augment_legacy_technical_v4(legacy_matrix_v4(archive), archive)
    replay = replay_legacy_v4(vehicles)
    canonical = {v.id for v in load_selection().baseline}
    promoted = ready_ids(replay)
    remaining = sorted(canonical - set(promoted))
    if set(remaining) != set(DISPOSITIONS):
        raise ValueError("Evidence changed: review closure dispositions before use")
    rows = []
    for vehicle in vehicles:
        if vehicle.id not in remaining:
            continue
        review = vehicle.provenance["legacy_v4_review"]
        technical = vehicle.provenance.get("legacy_technical_v4", {})
        reason = review["blocker"] or "; ".join(technical.get("blockers", ()))
        if not reason:
            raise ValueError("A blocked disposition requires an evidenced reason")
        rows.append({
            "id": vehicle.id, "catalog": review["catalog"],
            "classification_before": DISPOSITIONS[vehicle.id],
            "classification_after": DISPOSITIONS[vehicle.id], "reason": reason,
            "identity_status": vehicle.identity_status,
            "fields": {key: value.model_dump(mode="json") for key, value in vehicle.fields.items()},
            "source_review": review, "technical_review": technical,
            "scenarios": {s: {p: next(r for r in records if r["id"] == vehicle.id)
                              for p, records in profiles.items()} for s, profiles in replay.items()},
            "academic_test_ready": False, "operationally_active": False, "recommended": False,
        })
    return {"version": VERSION, "decision": "LEGACY_V4_REMAINING_BLOCKED",
            "canonical_ids": sorted(canonical), "prior_promoted_ids": promoted,
            "remaining_ids": remaining, "newly_promoted_ids": [], "rows": rows,
            "authenticated_calls_authorized": 0, "authenticated_calls_executed": 0,
            "evidence_admissions": [], "publication_authorized": False}
