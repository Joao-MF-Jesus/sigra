"""Composicao stateless do ranking legado com o custo Gold configuravel."""
from __future__ import annotations

from copy import deepcopy
from decimal import Decimal, ROUND_HALF_UP
import math
from typing import Callable, Iterable, Mapping, Sequence

from app.recommendation_identity import resolve_recommendation_identity

from data_platform.integrated_vehicle_cost.simulation_contracts import (
    VehicleCostSimulationBatch,
    VehicleCostSimulationResult,
)


MULTIFACTOR_POLICY_VERSION = "user-profile-multifactor-v1"
SCORE_QUANTUM = Decimal("0.0001")
PERCENT_QUANTUM = Decimal("0.0001")
MULTIFACTOR_COMPONENTS = (
    "total_cost",
    "usage_fit",
    "comfort",
    "safety",
    "performance",
    "efficiency",
    "legacy_quality",
)
COMPONENT_LABELS = {
    "total_cost": "custo de combustível no cenário",
    "usage_fit": "adequacao ao uso",
    "comfort": "conforto",
    "safety": "seguranca",
    "performance": "desempenho rodoviario",
    "efficiency": "economia e eficiencia",
    "legacy_quality": "qualidade historica do recomendador",
}
COMPONENT_SOURCES = {
    "total_cost": "calculated_from_published_gold_and_user_scenario",
    "usage_fit": "legacy_recommender_usage_score",
    "comfort": "legacy_vehicle_comfort_evidence",
    "safety": "legacy_vehicle_safety_evidence",
    "performance": "legacy_vehicle_road_score",
    "efficiency": "calculated_from_pbev_gold",
    "legacy_quality": "legacy_non_overlapping_quality_criteria",
}
LEGACY_QUALITY_COMPONENTS = (
    "maintenance_score",
    "reliability_score",
    "parts_score",
    "resale_score",
)


class MultifactorRecommendationError(ValueError):
    """Contrato multifator inconsistente sem detalhes internos sensiveis."""


def _decimal(value: object, field_name: str) -> Decimal:
    if isinstance(value, bool):
        raise MultifactorRecommendationError(f"{field_name} is unavailable")
    try:
        result = value if isinstance(value, Decimal) else Decimal(str(value))
    except (ArithmeticError, ValueError, TypeError) as exc:
        raise MultifactorRecommendationError(f"{field_name} is unavailable") from exc
    if not result.is_finite():
        raise MultifactorRecommendationError(f"{field_name} is unavailable")
    return result


def normalize_multifactor_weights(
    weights: Mapping[str, Decimal],
) -> dict[str, Decimal]:
    if set(weights) != set(MULTIFACTOR_COMPONENTS):
        raise MultifactorRecommendationError("multifactor weight contract is incomplete")
    normalized_input = {
        code: _decimal(weights[code], f"weight.{code}")
        for code in MULTIFACTOR_COMPONENTS
    }
    if any(value < 0 for value in normalized_input.values()):
        raise MultifactorRecommendationError("multifactor weights must be non-negative")
    total = sum(normalized_input.values(), Decimal("0"))
    if total <= 0:
        raise MultifactorRecommendationError("at least one multifactor weight must be positive")
    return {code: value / total for code, value in normalized_input.items()}


def _score(value: object, field_name: str) -> Decimal | None:
    try:
        result = _decimal(value, field_name)
    except MultifactorRecommendationError:
        return None
    if result < 0 or result > 100:
        return None
    return result


def _average(values: Iterable[Decimal]) -> Decimal:
    items = tuple(values)
    if not items:
        raise MultifactorRecommendationError("score evidence is unavailable")
    return sum(items, Decimal("0")) / Decimal(len(items))


def _normalize_positive(
    value: Decimal,
    minimum: Decimal,
    maximum: Decimal,
) -> Decimal:
    if maximum == minimum:
        return Decimal("100")
    return ((value - minimum) / (maximum - minimum) * Decimal("100")).quantize(
        SCORE_QUANTUM,
        rounding=ROUND_HALF_UP,
    )


def _normalize_cost(
    value: Decimal,
    minimum: Decimal,
    maximum: Decimal,
) -> Decimal:
    if maximum == minimum:
        return Decimal("100")
    return ((maximum - value) / (maximum - minimum) * Decimal("100")).quantize(
        SCORE_QUANTUM,
        rounding=ROUND_HALF_UP,
    )


def _legacy_component_scores(item: Mapping[str, object]) -> dict[str, Decimal | None]:
    score_components = item.get("score_components")
    vehicle = item.get("vehicle")
    if not isinstance(score_components, Mapping) or not isinstance(vehicle, Mapping):
        return {code: None for code in MULTIFACTOR_COMPONENTS}
    legacy_values = [
        _score(score_components.get(code), f"score_components.{code}")
        for code in LEGACY_QUALITY_COMPONENTS
    ]
    legacy_quality = (
        _average(value for value in legacy_values if value is not None)
        if all(value is not None for value in legacy_values)
        else None
    )
    return {
        "total_cost": None,
        "usage_fit": _score(score_components.get("usage_score"), "usage_score"),
        "comfort": _score(vehicle.get("comfort_score"), "comfort_score"),
        "safety": _score(vehicle.get("safety_score"), "safety_score"),
        "performance": _score(vehicle.get("road_score"), "road_score"),
        "efficiency": None,
        "legacy_quality": legacy_quality,
    }


def _unavailable(
    item: Mapping[str, object],
    *,
    baseline_position: int,
    reason_code: str,
    detail: str,
    identity_diagnostic: Mapping | None = None,
) -> dict[str, object]:
    output = deepcopy(dict(item))
    output["baseline_score"] = item.get("score")
    output["multifactor"] = {
        "enabled": True,
        "status": "unavailable",
        "position": None,
        "final_score": None,
        "baseline_position": baseline_position,
        "baseline_score": item.get("score"),
        "reason_code": reason_code,
        "detail": detail,
        "policy_version": MULTIFACTOR_POLICY_VERSION,
        "identity_diagnostic": dict(identity_diagnostic) if identity_diagnostic else None,
    }
    output["is_best_choice"] = False
    return output


def _cost_payload(result: VehicleCostSimulationResult) -> dict[str, object]:
    return {
        "vehicle_sk": result.vehicle_sk,
        "monthly_fuel_cost_brl": result.monthly_fuel_cost_brl,
        "annual_fuel_cost_brl": result.annual_fuel_cost_brl,
        "fuel_cost_per_km_brl": result.fuel_cost_per_km_brl,
        "projected_horizon_cost_brl": result.projected_horizon_cost_brl,
        "estimated_monthly_liters": result.estimated_monthly_liters,
        "estimated_annual_liters": result.estimated_annual_liters,
        "weighted_consumption_km_l": result.weighted_consumption_km_l,
        "fuel_price_per_liter_brl": result.fuel_price_per_liter_brl,
        "fuel_price_origin": result.fuel_price_origin.value,
        "fuel_code": result.fuel_code.value,
        "horizon_months": result.horizon_months,
        "canonical_scenario_code": result.canonical_scenario_code,
        "monthly_cost_difference_brl": result.monthly_cost_difference_brl,
        "monthly_cost_difference_percentage": result.monthly_cost_difference_percentage,
        "sources": {
            "integrated_dataset_version": result.sources.integrated_dataset_version,
            "fipe_dataset_version": result.sources.fipe_dataset_version,
            "pbev_dataset_version": result.sources.pbev_dataset_version,
            "anp_dataset_version": result.sources.anp_dataset_version,
        },
        "warnings": result.warnings,
        "limitations": result.limitations,
    }


def apply_multifactor_ranking(
    baseline_results: Iterable[Mapping[str, object]],
    simulation: VehicleCostSimulationBatch,
    weights: Mapping[str, Decimal],
    *,
    gold_identities: Sequence[Mapping] | None = None,
    catalog_references: Mapping[int, Mapping] | None = None,
    evidence_resolver: Callable | None = None,
) -> list[dict[str, object]]:
    """Reordena somente o caminho opt-in sem modificar o ranking de origem."""
    baseline = list(baseline_results)
    normalized_weights = normalize_multifactor_weights(weights)
    normalized_percentages = {
        code: (normalized_weights[code] * Decimal("100")).quantize(
            PERCENT_QUANTUM,
            rounding=ROUND_HALF_UP,
        )
        for code in MULTIFACTOR_COMPONENTS
    }
    residual = Decimal("100.0000") - sum(
        normalized_percentages.values(),
        Decimal("0"),
    )
    residual_target = next(
        code
        for code in reversed(MULTIFACTOR_COMPONENTS)
        if normalized_weights[code] > 0
    )
    normalized_percentages[residual_target] += residual
    candidates: list[dict[str, object]] = []
    unavailable: list[dict[str, object]] = []
    for baseline_position, item in enumerate(baseline, start=1):
        vehicle = item.get("vehicle")
        if not isinstance(vehicle, Mapping):
            unavailable.append(
                _unavailable(
                    item,
                    baseline_position=baseline_position,
                    reason_code="LEGACY_IDENTITY_UNAVAILABLE",
                    detail="legacy vehicle identity is unavailable",
                )
            )
            continue
        # An explicit source adapter may supply already-validated, request-local
        # simulation evidence. It must not manufacture a public/Gold identity.
        gold, identity_diagnostic = evidence_resolver(item) if evidence_resolver else resolve_recommendation_identity(
            vehicle, simulation.results, gold_identities=gold_identities,
            reference=(catalog_references or {}).get(vehicle.get("id")),
        )
        if gold is None:
            rejection = identity_diagnostic["rejection_reason"]
            reason_code = {
                "ambiguous_identity": "GOLD_IDENTITY_AMBIGUOUS",
                "ambiguous_mapping": "GOLD_IDENTITY_AMBIGUOUS",
                "required_identity_missing": "LEGACY_IDENTITY_UNAVAILABLE",
                "scenario_evidence_unavailable": "MULTIFACTOR_EVIDENCE_UNAVAILABLE",
            }.get(rejection, "GOLD_IDENTITY_NOT_FOUND")
            unavailable.append(
                _unavailable(
                    item,
                    baseline_position=baseline_position,
                    reason_code=reason_code,
                    detail="published identity or scenario evidence is unavailable",
                    identity_diagnostic=identity_diagnostic,
                )
            )
            continue
        raw_scores = _legacy_component_scores(item)
        missing = [
            code
            for code, score in raw_scores.items()
            if code not in {"total_cost", "efficiency"}
            and normalized_weights[code] > 0
            and score is None
        ]
        if missing:
            unavailable.append(
                _unavailable(
                    item,
                    baseline_position=baseline_position,
                    reason_code="MULTIFACTOR_EVIDENCE_UNAVAILABLE",
                    detail="required evidence is unavailable: " + ", ".join(missing),
                    identity_diagnostic=identity_diagnostic,
                )
            )
            continue
        candidates.append(
            {
                "item": item,
                "baseline_position": baseline_position,
                "gold": gold,
                "identity_diagnostic": identity_diagnostic,
                "scores": raw_scores,
            }
        )

    if not candidates:
        # No personalized score means the original ordering and badges survive.
        for output, original in zip(unavailable, baseline):
            if "is_best_choice" in original:
                output["is_best_choice"] = original["is_best_choice"]
        return unavailable

    costs = [candidate["gold"].projected_horizon_cost_brl for candidate in candidates]
    efficiencies = [candidate["gold"].weighted_consumption_km_l for candidate in candidates]
    min_cost, max_cost = min(costs), max(costs)
    min_efficiency, max_efficiency = min(efficiencies), max(efficiencies)
    ranked: list[dict[str, object]] = []
    for candidate in candidates:
        gold = candidate["gold"]
        raw_scores = dict(candidate["scores"])
        raw_scores["total_cost"] = _normalize_cost(
            gold.projected_horizon_cost_brl,
            min_cost,
            max_cost,
        )
        raw_scores["efficiency"] = _normalize_positive(
            gold.weighted_consumption_km_l,
            min_efficiency,
            max_efficiency,
        )
        rows = []
        contributions: list[Decimal] = []
        for code in MULTIFACTOR_COMPONENTS:
            score = raw_scores[code]
            if score is None:
                score = Decimal("0")
            contribution = (score * normalized_weights[code]).quantize(
                SCORE_QUANTUM,
                rounding=ROUND_HALF_UP,
            )
            contributions.append(contribution)
            rows.append(
                {
                    "component": code,
                    "label": COMPONENT_LABELS[code],
                    "source": COMPONENT_SOURCES[code],
                    "raw_score": score.quantize(SCORE_QUANTUM),
                    "input_weight": _decimal(weights[code], f"weight.{code}"),
                    "normalized_weight_percentage": normalized_percentages[code],
                    "contribution": contribution,
                    "available": candidate["scores"].get(code) is not None
                    or code in {"total_cost", "efficiency"},
                }
            )
        final_score = sum(contributions, Decimal("0")).quantize(
            SCORE_QUANTUM,
            rounding=ROUND_HALF_UP,
        )
        output = deepcopy(dict(candidate["item"]))
        baseline_score = candidate["item"].get("score")
        output["baseline_score"] = baseline_score
        output["score"] = final_score
        output["final_score"] = final_score
        output["is_best_choice"] = False
        output["is_best_available_reference"] = False
        output["multifactor"] = {
            "enabled": True,
            "status": "ranked",
            "position": 0,
            "final_score": final_score,
            "baseline_position": candidate["baseline_position"],
            "baseline_score": _decimal(baseline_score, "baseline_score"),
            "components": rows,
            "cost": _cost_payload(gold),
            "scenario_fingerprint": simulation.fingerprint,
            "policy_version": MULTIFACTOR_POLICY_VERSION,
            "identity_diagnostic": candidate["identity_diagnostic"],
            "tie_breakers": (
                "higher_multifactor_score",
                "better_baseline_position",
                "lower_vehicle_id",
            ),
            "warnings": tuple(gold.warnings),
            "limitations": tuple(gold.limitations),
        }
        vehicle_id = output.get("vehicle", {}).get("id") if isinstance(output.get("vehicle"), Mapping) else None
        ranked.append(
            {
                "output": output,
                "sort_key": (
                    -final_score,
                    int(candidate["baseline_position"]),
                    int(vehicle_id) if isinstance(vehicle_id, int) else math.inf,
                ),
            }
        )

    ranked.sort(key=lambda row: row["sort_key"])
    for position, row in enumerate(ranked, start=1):
        output = row["output"]
        output["multifactor"]["position"] = position
        output["multifactor"]["baseline_position_delta"] = (
            output["multifactor"]["baseline_position"] - position
        )
        output["is_best_choice"] = position == 1
    unavailable.sort(key=lambda item: item["multifactor"]["baseline_position"])
    return [row["output"] for row in ranked] + unavailable
