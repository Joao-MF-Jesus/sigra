"""Diagnostics only: fixed-scale sensitivity, traceability and blocked pooling."""
from copy import deepcopy
from decimal import Decimal

from data_platform.catalog.evidence_analysis import similarity
from data_platform.catalog.profile_contracts_v3 import UNITS, available
from data_platform.catalog.profile_scoring_v3 import configuration, score_cohort


def _compact(preview):
    return {"ranking": [{"id": r["id"], "preview_score": r["preview_score"]} for r in preview["ranking"]],
            "top10_boundary_ids": preview["top10_boundary_ids"]}


def sensitivity(vehicles, profile, month, baseline):
    config = configuration()
    before = {r["id"]: r for r in baseline["records"]}
    result = []
    def record(kind, key, multiplier, changed):
        result.append({"kind": kind, "criterion": key, "multiplier": multiplier,
                       "similarity": similarity(baseline, changed),
                       "methodology_ready_ids": changed["methodology_ready_ids"],
                       "score_deltas": [{"id": r["id"], "before": before[r["id"]]["preview_score"],
                                         "after": r["preview_score"],
                                         "delta": r["preview_score"]-before[r["id"]]["preview_score"]
                                         if r["preview_score"] is not None and before[r["id"]]["preview_score"] is not None else None}
                                        for r in changed["records"]]})
    for criterion, weight in config["profiles"][profile]["weights"].items():
        for multiplier in config["sensitivity"]["weight_multipliers"]:
            weights = dict(config["profiles"][profile]["weights"])
            weights[criterion] = Decimal(weight)*Decimal(multiplier)
            record("one_weight", criterion, multiplier, score_cohort(vehicles, profile, month, weights=weights))
        scale = config["scales"][criterion]
        if "lower" not in scale:
            continue
        for multiplier in config["sensitivity"]["absolute_anchor_multipliers"]:
            changed = deepcopy(config)
            for bound in ("lower", "upper"):
                changed["scales"][criterion][bound] = str(Decimal(scale[bound])*Decimal(multiplier))
            record("both_absolute_anchors", criterion, multiplier, score_cohort(vehicles, profile, month, config=changed))
    return result


def analyze_cohort(vehicles, month):
    vehicles = tuple(vehicles)
    profiles = {name: score_cohort(vehicles, name, month) for name in configuration()["profiles"]}
    ready = sorted({identifier for p in profiles.values() for identifier in p["methodology_ready_ids"]})
    coverage = {name: {kind: sum(v.fields[name].kind == kind for v in vehicles)
                       for kind in ("observed", "derived", "unavailable")} for name in UNITS}
    # Remove/reinsert real vehicles. No synthetic vehicle is added to the pilot.
    stability = []
    for profile, full in profiles.items():
        original = {r["id"]: r["preview_score"] for r in full["records"]}
        for excluded in vehicles:
            retained = score_cohort([v for v in vehicles if v.id != excluded.id], profile, month)
            unchanged = all(r["preview_score"] == original[r["id"]] for r in retained["records"])
            expected_order = [r["id"] for r in full["ranking"] if r["id"] != excluded.id]
            stable_order = expected_order == [r["id"] for r in retained["ranking"]]
            if not unchanged or not stable_order:
                raise AssertionError("Cohort-dependent score or order")
            stability.append({"profile": profile, "removed_then_reinserted_id": excluded.id,
                              "unchanged_scores": unchanged, "unchanged_relative_order": stable_order})
    evidence_groups = {}
    for name, preview in profiles.items():
        groups = {}
        for row in preview["records"]:
            groups.setdefault("|".join(row["used_criteria"]) or "none", []).append(row["id"])
        evidence_groups[name] = groups
    status_names = (
        "identity_resolved", "partial_coverage_candidate", "profile_scoreable",
        "profile_eligible", "methodology_ready", "tco_complete", "recommendable", "recommended",
    )
    status_ids = {
        name: {
            status: [row["id"] for row in preview["records"] if row[status]]
            for status in status_names
        }
        for name, preview in profiles.items()
    }
    return {"count": len(vehicles), "month": month, "profiles": profiles,
            "field_coverage": coverage,
            "vehicle_coverage": [{"id": v.id, "observed_fields": sum(o.kind == "observed" for o in v.fields.values()),
                                  "derived_fields": sum(o.kind == "derived" for o in v.fields.values()),
                                  "unavailable_fields": [name for name in UNITS if not available(v, name)],
                                  "ready_profiles": [name for name, p in profiles.items() if v.id in p["methodology_ready_ids"]]}
                                 for v in vehicles],
            "similarity_matrix": {a: {b: similarity(_compact(left), _compact(right)) for b, right in profiles.items()}
                                  for a, left in profiles.items()},
            "sensitivity": {name: sensitivity(vehicles, name, month, p) for name, p in profiles.items()},
            "cohort_stability": {"checks": len(stability), "all_passed": True, "details": stability},
            "evidence_mask_groups": evidence_groups,
            "status_ids_by_profile": status_ids,
            "status_counts_by_profile": {
                name: {status: len(ids) for status, ids in statuses.items()}
                for name, statuses in status_ids.items()
            },
            "methodology_ready_ids": ready, "methodology_ready": len(ready), "active": 0,
            "interpretation": "Partial-score top10s are diagnostics, not equally evidenced suitability rankings. Different orders do not prove efficacy.",
            "ready_preview_by_profile": {name: [r["id"] for r in p["ranking"] if r["methodology_ready"]][:10]
                                         for name, p in profiles.items()},
            "blocked_profiles": [name for name, p in profiles.items() if not p["methodology_ready_ids"]]}


def combined_preview(legacy, candidates, month):
    combined = tuple(legacy) + tuple(candidates)
    months = sorted({v.fields["reference_month"].value for v in combined if available(v, "reference_month")})
    aligned = all(available(v, "price_brl") and v.fields["reference_month"].value == month for v in combined)
    if not aligned:
        return {"status": "BLOCKED_TEMPORAL_ALIGNMENT", "count": len(combined), "observed_months": months,
                "target_month": month, "profiles": None, "active": 0,
                "reason": "Every identity must have verified FIPE price at the same month before any joint preview."}
    return {"status": "diagnostic_only", **analyze_cohort(combined, month)}
