"""Explain evidence gates without changing eligibility or manufacturing scores."""
from decimal import Decimal
from collections.abc import Mapping

from app.multifactor_recommendation import (
    MULTIFACTOR_COMPONENTS, _legacy_component_scores, normalize_multifactor_weights,
)
from data_platform.catalog.profile_scoring_v3 import CRITERION_FIELDS, configuration


PERSONALIZATION_LABELS = {
    "total_cost": "Custo de combustível no cenário", "usage_fit": "Adequação ao uso",
    "comfort": "Conforto", "safety": "Segurança", "performance": "Desempenho rodoviário",
    "efficiency": "Economia e eficiência", "legacy_quality": "Qualidade histórica",
}
PERSONALIZATION_INPUTS = {
    "total_cost": ("simulation.projected_horizon_cost_brl",),
    "efficiency": ("simulation.weighted_consumption_km_l",),
    "usage_fit": ("score_components.usage_score",),
    "comfort": ("vehicle.comfort_score",), "safety": ("vehicle.safety_score",),
    "performance": ("vehicle.road_score",),
    "legacy_quality": tuple("score_components." + key for key in (
        "maintenance_score", "reliability_score", "parts_score", "resale_score")),
}
PERSONALIZATION_REQUIREMENTS = {
    "usage_fit": "Faltam avaliações específicas do uso escolhido e uma classificação de usos comprovada para esta versão.",
    "comfort": "Falta uma avaliação documentada de conforto desta versão; dimensões externas não comprovam conforto medido.",
    "safety": "Falta uma avaliação de segurança na escala da política original; inventário de equipamentos não é essa nota.",
    "performance": "Falta uma avaliação documentada de comportamento rodoviário; potência isolada não comprova esse critério.",
    "legacy_quality": "Manutenção e desvalorização são calculáveis no cenário; faltam confiabilidade histórica e disponibilidade comprovada de peças.",
    "total_cost": "Informe preço e consumo compatíveis com o combustível do cenário.",
    "efficiency": "Falta consumo comprovado ou informado explicitamente para o combustível escolhido.",
}
FIELD_LABELS = {
    "width_with_mirrors_mm": "largura com os retrovisores abertos",
    "length_mm": "comprimento", "airbags": "quantidade de airbags da versão",
    "abs": "presença ou ausência comprovada de ABS",
    "esc": "presença ou ausência comprovada de controle de estabilidade",
    "ground_clearance_mm": "vão livre do solo", "seats": "quantidade de lugares",
    "cargo_l": "capacidade do porta-malas", "payload_kg": "carga útil",
    "consumption_city": "consumo urbano", "consumption_highway": "consumo rodoviário",
    "fuel": "combustível", "price_brl": "preço FIPE",
    "wheelbase_mm": "entre-eixos", "width_mm": "largura da carroceria",
    "rear_legroom_mm": "espaço medido para pernas atrás",
    "interior_width_mm": "largura interna medida",
}


def personalization_evidence(item, simulation, weights):
    """Coverage means positive requested weights, not the v4 profile's coverage.

    Reuse the original policy's evidence reader. Available inputs are not scores:
    min/max normalization and final composition remain exclusively in the motor.
    Missing zero-weight criteria do not block; missing positive weights do.
    """
    normalized = normalize_multifactor_weights(weights)
    scores = _legacy_component_scores(item)
    criteria = []
    for key in MULTIFACTOR_COMPONENTS:
        inputs = {}
        for path in PERSONALIZATION_INPUTS[key]:
            scope, name = path.split(".", 1)
            container = item.get(scope)
            inputs[path] = (getattr(simulation, name, None) if scope == "simulation"
                            else container.get(name) if isinstance(container, Mapping) else None)
        available = simulation is not None if key in {"total_cost", "efficiency"} else scores[key] is not None
        requested = normalized[key] > 0
        criteria.append({"criterion": key, "label": PERSONALIZATION_LABELS[key],
            "requested": requested, "input_weight": weights[key],
            "normalized_weight_percentage": normalized[key] * 100,
            "available": available, "inputs": inputs,
            "missing_inputs": [path for path, value in inputs.items() if value is None],
            "requirement_message": PERSONALIZATION_REQUIREMENTS[key] if not available else None,
            "calculated_subcriteria": item.get("calculations", {}) if key == "legacy_quality" else {},
            "nature": "scenario_estimate" if key == "total_cost" else "derived" if key == "efficiency" else "unavailable" if not available else "validated_legacy_score",
            "missing_reason": "scenario_evidence_unavailable" if not available and key in {"total_cost", "efficiency"} else "original_method_inputs_unavailable" if not available else None})
    requested = [row for row in criteria if row["requested"]]
    evaluated = [row for row in requested if row["available"]]
    return {"policy_version": "user-profile-multifactor-v1", "criteria": criteria,
        "requested_count": len(requested), "evaluated_count": len(evaluated),
        "weighted": sum((normalized[row["criterion"]] for row in evaluated), Decimal(0)),
        "missing": [row["criterion"] for row in requested if not row["available"]],
        "complete": len(evaluated) == len(requested)}


def documentary_evidence(vehicle, profile, evaluation, published_eligible):
    coverage = evaluation["coverage"]
    missing_criteria = list(dict.fromkeys(coverage["required_missing"] + [
        key for group in coverage["required_any_missing"] for key in group]))
    missing_fields = []
    for criterion in missing_criteria:
        fields = CRITERION_FIELDS[criterion]
        if criterion == "passenger_space" and evaluation["academic_path"] == "academic_habitability_proxy":
            fields = ("seats", "wheelbase_mm", "width_mm")
        for name in fields:
            field = vehicle.fields[name]
            if field.value is None:
                missing_fields.append({"criterion": criterion, "field": name,
                    "label": FIELD_LABELS.get(name, name), "value": None, "unit": field.unit,
                    "nature": field.kind, "reason": "admissible_source_evidence_unavailable"})
    labels = list(dict.fromkeys(row["label"] for row in missing_fields))
    message = ("Falta comprovação de " + ", ".join(labels) + " para este perfil." if labels
               else "As evidências desta versão não estão aprovadas para este perfil." if not published_eligible
               else "Os requisitos documentais deste perfil estão comprovados.")
    return {"profile": profile, "rule_version": configuration()["method_version"],
        "published_eligible": published_eligible, "live_eligible": evaluation["academic_test_ready"],
        "required_missing": missing_criteria, "required_any_missing": coverage["required_any_missing"],
        "missing_fields": missing_fields, "message": message}
