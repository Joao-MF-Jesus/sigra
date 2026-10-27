import math
import logging
from dataclasses import dataclass
from numbers import Real
from typing import Iterable

from app.tco import calculate_tco


LOGGER = logging.getLogger(__name__)

VALID_USE_CASES = {"cidade", "familia", "trabalho", "estrada", "app", "suv"}
VALID_VEHICLE_CATEGORIES = {
    "compact",
    "subcompact",
    "compact_hatch",
    "compact_sedan",
    "compact_minivan",
    "minivan",
    "midsize_sedan",
    "compact_suv",
    "suv",
}
SCORE_FIELDS = (
    "reliability_score",
    "parts_availability_score",
    "comfort_score",
    "space_score",
    "safety_score",
    "urban_score",
    "road_score",
    "family_score",
    "app_score",
)


PROFILE_MATCH_BONUS = 4
PROFILE_MISMATCH_PENALTY = 8
HIGH_RELIABILITY_BONUS = 3

RECOMMENDATION_STRATEGIES = {
    "lowest_cost",
    "budget_economy",
    "cost_benefit",
    "balanced",
    "comfort_space",
    "best_within_budget",
}

STRATEGY_LABELS = {
    "lowest_cost": "menor custo possível",
    "budget_economy": "econômico dentro do orçamento",
    "cost_benefit": "custo-benefício",
    "balanced": "equilibrado",
    "comfort_space": "conforto e espaço",
    "best_within_budget": "melhor categoria dentro do orçamento",
}

CRITERIA_LABELS = {
    "financial_score": "aderência ao orçamento",
    "tco_score": "custo total mensal",
    "usage_score": "aderência ao perfil de uso",
    "maintenance_score": "facilidade de manutenção",
    "reliability_score": "confiabilidade",
    "parts_score": "disponibilidade de peças",
    "resale_score": "menor desvalorização",
    "risk_score": "baixo risco geral",
    "segment_score": "categoria, conforto e espaço",
    "purchase_intent_score": "prioridade de compra informada",
    "monthly_capacity_score": "capacidade mensal informada",
}

STATUS_LABELS = {
    "recommended": "Recomendado",
    "good_option": "Boa opção",
    "attention": "Requer atenção",
    "not_recommended": "Não recomendado",
}

USE_CASE_TEXT = {
    "cidade": "uso urbano",
    "familia": "uso familiar",
    "trabalho": "uso de trabalho",
    "estrada": "uso em estrada",
    "app": "uso em aplicativo",
    "suv": "perfil SUV",
}

EXPLANATION_SCORE_KEYS = set(CRITERIA_LABELS)

STRATEGY_WEIGHTS = {
    "lowest_cost": {
        "financial_score": 0.18,
        "tco_score": 0.30,
        "usage_score": 0.10,
        "maintenance_score": 0.12,
        "reliability_score": 0.08,
        "parts_score": 0.07,
        "segment_score": 0.03,
        "purchase_intent_score": 0.12,
    },
    "budget_economy": {
        "financial_score": 0.14,
        "tco_score": 0.22,
        "usage_score": 0.12,
        "maintenance_score": 0.11,
        "reliability_score": 0.12,
        "parts_score": 0.07,
        "segment_score": 0.12,
        "purchase_intent_score": 0.10,
    },
    "cost_benefit": {
        "financial_score": 0.17,
        "tco_score": 0.22,
        "usage_score": 0.13,
        "maintenance_score": 0.11,
        "reliability_score": 0.11,
        "parts_score": 0.07,
        "segment_score": 0.08,
        "purchase_intent_score": 0.11,
    },
    "balanced": {
        "financial_score": 0.14,
        "tco_score": 0.18,
        "usage_score": 0.14,
        "maintenance_score": 0.10,
        "reliability_score": 0.13,
        "parts_score": 0.08,
        "segment_score": 0.13,
        "purchase_intent_score": 0.10,
    },
    "comfort_space": {
        "financial_score": 0.09,
        "tco_score": 0.12,
        "usage_score": 0.15,
        "maintenance_score": 0.08,
        "reliability_score": 0.12,
        "parts_score": 0.06,
        "segment_score": 0.24,
        "purchase_intent_score": 0.14,
    },
    "best_within_budget": {
        "financial_score": 0.03,
        "tco_score": 0.04,
        "usage_score": 0.08,
        "maintenance_score": 0.05,
        "reliability_score": 0.16,
        "parts_score": 0.04,
        "segment_score": 0.32,
        "purchase_intent_score": 0.28,
    },
}


@dataclass(frozen=True)
class Vehicle:
    id: int
    brand: str
    model: str
    year: int
    price: float
    fuel_efficiency_km_l: float
    annual_maintenance_cost: float
    reliability_score: float
    parts_availability_score: float
    depreciation_rate: float
    use_cases: tuple[str, ...]
    chronic_issues: tuple[str, ...]
    image_url: str = ""
    category: str = "compact"
    segment_level: int = 2
    comfort_score: float = 60
    space_score: float = 60
    safety_score: float = 60
    urban_score: float = 70
    road_score: float = 60
    family_score: float = 60
    app_score: float = 60
    price_reference: str = "Referencia demonstrativa SIGRA"
    price_reference_month: str = ""
    fipe_code: str = ""
    fipe_model: str = ""
    price_is_fipe: bool = False
    vehicle_type: str = "car"


@dataclass(frozen=True)
class RecommendationProfile:
    budget: float
    monthly_limit: float
    use_case: str
    monthly_mileage: float = 1000
    fuel_price: float = 6.0
    recommendation_strategy: str = "cost_benefit"


def clamp_score(value: float) -> float:
    return max(0.0, min(100.0, value))


def _valid_number(value: object, *, positive: bool = False) -> bool:
    if isinstance(value, bool) or not isinstance(value, Real):
        return False
    number = float(value)
    return math.isfinite(number) and (number > 0 if positive else number >= 0)


def validate_vehicle_data(vehicle: Vehicle) -> list[str]:
    """Retorna todos os erros que impedem uma recomendacao segura."""
    errors = []
    if not isinstance(vehicle.brand, str) or not vehicle.brand.strip():
        errors.append("brand ausente")
    if not isinstance(vehicle.model, str) or not vehicle.model.strip():
        errors.append("model ausente")
    if isinstance(vehicle.id, bool) or not isinstance(vehicle.id, int) or vehicle.id <= 0:
        errors.append("id invalido")
    if isinstance(vehicle.year, bool) or not isinstance(vehicle.year, int) or not 1990 <= vehicle.year <= 2035:
        errors.append("year invalido")
    required_numbers = {
        "price": (vehicle.price, True),
        "fuel_efficiency_km_l": (vehicle.fuel_efficiency_km_l, True),
        "annual_maintenance_cost": (vehicle.annual_maintenance_cost, False),
        "depreciation_rate": (vehicle.depreciation_rate, False),
    }
    for name, (value, positive) in required_numbers.items():
        if not _valid_number(value, positive=positive):
            errors.append(f"{name} invalido")
    for name in SCORE_FIELDS:
        value = getattr(vehicle, name)
        if not _valid_number(value):
            errors.append(f"{name} invalido")
        elif float(value) > 100:
            errors.append(f"{name} fora da faixa 0-100")
    if isinstance(vehicle.segment_level, bool) or not isinstance(vehicle.segment_level, int) or not 1 <= vehicle.segment_level <= 5:
        errors.append("segment_level invalido")
    if not isinstance(vehicle.category, str) or vehicle.category not in VALID_VEHICLE_CATEGORIES:
        errors.append("category invalida")
    if not isinstance(vehicle.use_cases, (tuple, list)) or not vehicle.use_cases:
        errors.append("use_cases ausente")
    elif any(not isinstance(item, str) or item not in VALID_USE_CASES for item in vehicle.use_cases):
        errors.append("use_cases invalido")
    if not isinstance(vehicle.chronic_issues, (tuple, list)) or any(
        not isinstance(item, str) for item in vehicle.chronic_issues
    ):
        errors.append("chronic_issues invalido")
    if not isinstance(vehicle.price_is_fipe, bool):
        errors.append("price_is_fipe invalido")
    if vehicle.vehicle_type != "car":
        errors.append("vehicle_type invalido para recomendador de automoveis")
    return errors


def validate_profile_data(profile: RecommendationProfile) -> None:
    required = {
        "budget": (profile.budget, True),
        "monthly_limit": (profile.monthly_limit, True),
        "monthly_mileage": (profile.monthly_mileage, False),
        "fuel_price": (profile.fuel_price, True),
    }
    errors = [name for name, (value, positive) in required.items() if not _valid_number(value, positive=positive)]
    if errors:
        raise ValueError("Perfil invalido: " + ", ".join(errors))
    if profile.use_case not in USE_CASE_TEXT:
        raise ValueError("Perfil invalido: use_case")
    if profile.recommendation_strategy not in RECOMMENDATION_STRATEGIES:
        allowed = ", ".join(sorted(RECOMMENDATION_STRATEGIES))
        raise ValueError(
            f"Perfil invalido: recommendation_strategy={profile.recommendation_strategy!r}; "
            f"valores permitidos: {allowed}"
        )


def normalize_strategy(strategy: str | None) -> str:
    if strategy not in RECOMMENDATION_STRATEGIES:
        allowed = ", ".join(sorted(RECOMMENDATION_STRATEGIES))
        raise ValueError(f"Estrategia invalida: {strategy!r}; valores permitidos: {allowed}")
    return strategy


def normalize_positive(value: float, min_value: float, max_value: float) -> float:
    if max_value == min_value:
        return 100.0
    return ((value - min_value) / (max_value - min_value)) * 100


def normalize_cost(value: float, min_value: float, max_value: float) -> float:
    if max_value == min_value:
        return 100.0
    return ((max_value - value) / (max_value - min_value)) * 100


def normalize_monthly_fit(monthly_cost: float, monthly_limit: float) -> float:
    if monthly_limit <= 0:
        return 0.0
    return clamp_score((1 - (monthly_cost / monthly_limit)) * 100)


def calculate_monthly_capacity_score(monthly_limit: float, tco_values: Iterable[float]) -> float:
    values = list(tco_values)
    if not values or monthly_limit <= 0:
        return 0.0
    affordable = len([value for value in values if value <= monthly_limit])
    return round((affordable / len(values)) * 100, 2)


def calculate_purchase_capacity_score(budget: float, vehicles: Iterable["Vehicle"]) -> float:
    vehicle_list = list(vehicles)
    if not vehicle_list or budget <= 0:
        return 0.0
    affordable = len([vehicle for vehicle in vehicle_list if vehicle.price <= budget])
    return round((affordable / len(vehicle_list)) * 100, 2)


def classify_financial_capacity(
    profile: "RecommendationProfile",
    vehicles: Iterable["Vehicle"],
    tco_by_vehicle: dict[int, dict[str, float]],
) -> dict[str, float | str]:
    vehicle_list = list(vehicles)
    monthly_capacity_score = calculate_monthly_capacity_score(
        profile.monthly_limit,
        [tco["total_monthly_cost"] for tco in tco_by_vehicle.values()],
    )
    purchase_capacity_score = calculate_purchase_capacity_score(profile.budget, vehicle_list)
    superior_pool = [
        vehicle
        for vehicle in vehicle_list
        if vehicle.segment_level >= 4 or vehicle.category in {"midsize_sedan", "compact_suv", "suv"}
    ]
    superior_viable = [
        vehicle
        for vehicle in superior_pool
        if vehicle.price <= profile.budget and tco_by_vehicle[vehicle.id]["total_monthly_cost"] <= profile.monthly_limit
    ]
    superior_monthly_capacity = round((len(superior_viable) / len(superior_pool)) * 100, 2) if superior_pool else 0.0

    if purchase_capacity_score < 35 and monthly_capacity_score < 35:
        financial_capacity_profile = "restricted"
    elif purchase_capacity_score >= 80 and monthly_capacity_score < 35:
        financial_capacity_profile = "purchase_high_monthly_low"
    elif purchase_capacity_score >= 85 and monthly_capacity_score >= 85:
        financial_capacity_profile = "high_capacity"
    elif purchase_capacity_score >= 65 and monthly_capacity_score >= 60:
        financial_capacity_profile = "comfortable"
    else:
        financial_capacity_profile = "balanced"

    return {
        "financial_capacity_profile": financial_capacity_profile,
        "monthly_capacity_score": monthly_capacity_score,
        "purchase_capacity_score": purchase_capacity_score,
        "superior_monthly_capacity_score": superior_monthly_capacity,
    }


def profile_fit_score(vehicle: Vehicle, profile: RecommendationProfile) -> float:
    if profile.use_case == "app":
        if "app" in vehicle.use_cases:
            return 100.0
        if vehicle.app_score >= 80:
            return 85.0
        if "trabalho" in vehicle.use_cases or "familia" in vehicle.use_cases:
            return 70.0
        return 35.0
    if profile.use_case == "suv":
        if "suv" in vehicle.use_cases:
            return 100.0
        if "familia" in vehicle.use_cases and "estrada" in vehicle.use_cases:
            return 35.0
        return 10.0
    if profile.use_case == "cidade":
        if "cidade" in vehicle.use_cases:
            return 100.0
        if is_superior_vehicle(vehicle) and vehicle.urban_score >= 60:
            return 72.0
        if vehicle.urban_score >= 70:
            return 65.0
    return 100.0 if profile.use_case in vehicle.use_cases else 25.0


def use_case_specific_score(vehicle: Vehicle, profile: RecommendationProfile) -> float:
    scores = {
        "cidade": vehicle.urban_score,
        "familia": vehicle.family_score,
        "trabalho": (vehicle.urban_score * 0.45) + (vehicle.app_score * 0.30) + (vehicle.space_score * 0.25),
        "estrada": vehicle.road_score,
        "app": vehicle.app_score,
        "suv": (vehicle.road_score * 0.25) + (vehicle.family_score * 0.25) + (vehicle.space_score * 0.25) + (vehicle.comfort_score * 0.25),
    }
    return scores.get(profile.use_case, vehicle.urban_score)


def calculate_vehicle_tco(vehicle: Vehicle, profile: RecommendationProfile) -> dict[str, float]:
    return calculate_tco(
        vehicle_price=vehicle.price,
        fuel_efficiency_km_l=vehicle.fuel_efficiency_km_l,
        monthly_mileage=profile.monthly_mileage,
        fuel_price=profile.fuel_price,
        annual_maintenance_cost=vehicle.annual_maintenance_cost,
        annual_depreciation_rate=vehicle.depreciation_rate,
    )


def estimate_monthly_cost(vehicle: Vehicle, profile: RecommendationProfile) -> float:
    """Compatibilidade com o MVP: agora representa o TCO mensal total."""
    return calculate_vehicle_tco(vehicle, profile)["total_monthly_cost"]


def calculate_segment_score(vehicle: Vehicle, profile: RecommendationProfile) -> float:
    segment_level_score = clamp_score(((vehicle.segment_level - 1) / 4) * 100)
    category_bonus = 0
    strategy = normalize_strategy(profile.recommendation_strategy)
    if profile.use_case == "suv" and "suv" in vehicle.category:
        category_bonus = 12
    elif profile.use_case == "familia" and vehicle.category in {"compact_suv", "suv", "minivan", "midsize_sedan", "compact_sedan"}:
        category_bonus = 8
    elif profile.use_case == "estrada" and vehicle.category in {"midsize_sedan", "compact_suv", "suv"}:
        category_bonus = 8
    elif profile.use_case in {"cidade", "app"} and vehicle.category in {"subcompact", "compact_hatch", "compact_sedan"}:
        category_bonus = 6

    if profile.use_case == "app" and strategy != "lowest_cost":
        if vehicle.category in {"compact_sedan", "midsize_sedan", "compact_minivan", "minivan"}:
            category_bonus += 10
        elif vehicle.category == "compact_suv":
            category_bonus += 5
        if vehicle.segment_level <= 1:
            category_bonus -= 12

    if strategy == "best_within_budget" and vehicle.category in {"midsize_sedan", "compact_suv", "suv"}:
        category_bonus += 10
    if strategy == "best_within_budget" and vehicle.segment_level >= 4:
        category_bonus += 8

    if strategy == "best_within_budget":
        score = (
            segment_level_score * 0.34
            + vehicle.comfort_score * 0.20
            + vehicle.space_score * 0.17
            + vehicle.safety_score * 0.21
            + use_case_specific_score(vehicle, profile) * 0.08
            + category_bonus
        )
    else:
        score = (
            segment_level_score * 0.23
            + vehicle.comfort_score * 0.19
            + vehicle.space_score * 0.19
            + vehicle.safety_score * 0.19
            + use_case_specific_score(vehicle, profile) * 0.20
            + category_bonus
        )
    return round(clamp_score(score), 2)


def app_professional_score(vehicle: Vehicle, segment_score: float) -> float:
    score = (
        vehicle.app_score * 0.26
        + vehicle.comfort_score * 0.17
        + vehicle.space_score * 0.20
        + vehicle.safety_score * 0.17
        + clamp_score(((vehicle.segment_level - 1) / 4) * 100) * 0.10
        + segment_score * 0.10
    )
    if vehicle.category in {"compact_sedan", "midsize_sedan", "compact_minivan", "minivan"}:
        score += 8
    elif vehicle.category == "compact_suv":
        score += 4
    if vehicle.segment_level <= 1:
        score -= 14
    return round(clamp_score(score), 2)


def score_budget_band(price: float, budget: float, low_ratio: float, high_ratio: float) -> float:
    if budget <= 0:
        return 0.0
    low = budget * low_ratio
    high = budget * high_ratio
    if price > budget:
        return max(0.0, 40 - ((price - budget) / budget) * 120)
    if low <= price <= high:
        center = (low + high) / 2
        distance = abs(price - center) / max(1, (high - low) / 2)
        return 100 - distance * 12
    if price < low:
        return max(0.0, 55 - ((low - price) / max(1, low)) * 120)
    return max(0.0, 75 - ((price - high) / max(1, budget - high)) * 55)


def is_superior_vehicle(vehicle: Vehicle) -> bool:
    return vehicle.segment_level >= 4 or vehicle.category in {"midsize_sedan", "compact_suv", "suv"}


def has_direct_use_match(vehicle: Vehicle, profile: RecommendationProfile) -> bool:
    return profile.use_case in vehicle.use_cases or (
        profile.use_case == "suv" and "suv" in vehicle.use_cases
    )


def high_capacity_quality_bonus(vehicle: Vehicle, profile: RecommendationProfile) -> float:
    """Valoriza categoria somente quando ela tambem faz sentido para o uso informado."""
    fit_score = profile_fit_score(vehicle, profile)
    specific_score = use_case_specific_score(vehicle, profile)

    if is_superior_vehicle(vehicle):
        if profile.use_case == "cidade" and fit_score >= 65:
            return min(50.0, 40.0 + max(0.0, specific_score - 60.0))
        if fit_score >= 90:
            return 24.0
        if fit_score >= 65 and specific_score >= 75:
            return 16.0
        if fit_score >= 65:
            return 10.0
        return 2.0
    if vehicle.segment_level >= 3:
        return 10.0 if fit_score >= 90 else 4.0
    return 0.0


def use_case_priority_adjustment(vehicle: Vehicle, profile: RecommendationProfile) -> float:
    """Diferencia perfis sem transformar o criterio de uso em uma caixa-preta."""
    specific_score = use_case_specific_score(vehicle, profile)
    direct_match = has_direct_use_match(vehicle, profile)
    adjustment = (specific_score - 70) * 0.16

    if direct_match:
        adjustment += 5
    elif profile.use_case == "app":
        adjustment += 2 if specific_score >= 80 else (-4 if specific_score >= 70 else -10)
    elif profile.use_case == "cidade":
        adjustment -= 2 if specific_score >= 70 else 6
    else:
        adjustment -= 8

    preferred_categories = {
        "cidade": {"compact_hatch", "compact_sedan", "compact_minivan"},
        "familia": {"compact_sedan", "midsize_sedan", "compact_suv", "suv", "minivan", "compact_minivan"},
        "trabalho": {"compact_sedan", "midsize_sedan", "compact_minivan", "minivan"},
        "estrada": {"compact_sedan", "midsize_sedan", "compact_suv", "suv"},
        "app": {"compact_sedan", "midsize_sedan", "compact_minivan", "minivan"},
        "suv": {"compact_suv", "suv"},
    }
    if vehicle.category in preferred_categories.get(profile.use_case, set()):
        adjustment += 4 if profile.use_case != "app" else 6
    elif profile.use_case in {"app", "trabalho"} and vehicle.category in {"compact_suv", "suv"}:
        adjustment -= 4

    return round(adjustment, 2)


def calculate_purchase_intent_score(
    vehicle: Vehicle,
    profile: RecommendationProfile,
    components: dict[str, float],
    segment_score: float,
) -> float:
    strategy = normalize_strategy(profile.recommendation_strategy)
    app_score = app_professional_score(vehicle, segment_score) if profile.use_case == "app" else 0
    if strategy == "lowest_cost":
        score = components["price"] * 0.45 + components["tco"] * 0.40 + components["maintenance_cost"] * 0.15
    elif strategy == "budget_economy":
        if profile.use_case == "app":
            score = (
                score_budget_band(vehicle.price, profile.budget, 0.25, 0.80) * 0.22
                + components["tco"] * 0.24
                + components["reliability"] * 0.17
                + components["maintenance_cost"] * 0.10
                + app_score * 0.27
            )
        else:
            score = (
                score_budget_band(vehicle.price, profile.budget, 0.35, 0.90) * 0.36
                + components["tco"] * 0.26
                + components["reliability"] * 0.16
                + segment_score * 0.17
                + components["maintenance_cost"] * 0.05
            )
    elif strategy == "cost_benefit":
        score = (
            score_budget_band(vehicle.price, profile.budget, 0.15, 0.75) * 0.20
            + components["tco"] * 0.18
            + components["profile_fit"] * 0.14
            + components["reliability"] * 0.18
            + components["maintenance_cost"] * 0.08
            + segment_score * 0.22
        )
    elif strategy == "balanced":
        score = (
            components["tco"] * 0.22
            + components["profile_fit"] * 0.18
            + components["reliability"] * 0.18
            + components["parts_availability"] * 0.12
            + components["depreciation"] * 0.10
            + segment_score * 0.20
        )
    elif strategy == "comfort_space":
        if profile.use_case == "app":
            score = (
                app_score * 0.34
                + segment_score * 0.22
                + vehicle.comfort_score * 0.14
                + vehicle.space_score * 0.15
                + vehicle.safety_score * 0.10
                + components["profile_fit"] * 0.05
            )
        else:
            score = (
                segment_score * 0.42
                + vehicle.comfort_score * 0.16
                + vehicle.space_score * 0.16
                + vehicle.safety_score * 0.14
                + components["profile_fit"] * 0.12
            )
    elif strategy == "best_within_budget":
        if profile.use_case == "app":
            score = (
                score_budget_band(vehicle.price, profile.budget, 0.30, 0.95) * 0.16
                + app_score * 0.34
                + segment_score * 0.18
                + components["reliability"] * 0.16
                + vehicle.comfort_score * 0.06
                + vehicle.safety_score * 0.06
                + components["tco"] * 0.04
            )
        else:
            score = (
                score_budget_band(vehicle.price, profile.budget, 0.35, 0.85) * 0.18
                + segment_score * 0.42
                + components["reliability"] * 0.18
                + vehicle.comfort_score * 0.10
                + vehicle.safety_score * 0.10
                + components["tco"] * 0.02
            )
    else:
        score = (
            components["price"] * 0.20
            + components["tco"] * 0.28
            + components["profile_fit"] * 0.12
            + components["reliability"] * 0.15
            + components["maintenance_cost"] * 0.10
            + segment_score * 0.15
        )
    return round(clamp_score(score), 2)


def build_score_components(
    components: dict[str, float],
    segment_score: float,
    purchase_intent_score: float,
    vehicle: Vehicle,
    profile: RecommendationProfile,
    tco: dict[str, float],
    part_feedback: dict | None = None,
) -> dict[str, float]:
    part_feedback = part_feedback or {}
    maintenance_absolute = clamp_score(100 - (vehicle.annual_maintenance_cost / 70))
    maintenance_index = part_feedback.get("maintenance_index", maintenance_absolute)
    supplier_score = part_feedback.get("supplier_availability_score", vehicle.parts_availability_score)
    variation_risk = part_feedback.get("price_variation_risk", 50)
    monthly_ratio = tco["total_monthly_cost"] / profile.monthly_limit if profile.monthly_limit > 0 else 10
    if monthly_ratio <= 1:
        monthly_affordability = 100 - (monthly_ratio * 20)
    else:
        monthly_affordability = 80 - ((monthly_ratio - 1) * 120)
    monthly_affordability = clamp_score(monthly_affordability)
    if vehicle.price <= profile.budget:
        purchase_affordability = 100.0
    else:
        purchase_affordability = clamp_score(100 - (((vehicle.price / profile.budget) - 1) * 120))

    absolute_reliability = clamp_score(vehicle.reliability_score)
    absolute_parts = clamp_score(vehicle.parts_availability_score)
    use_specific = use_case_specific_score(vehicle, profile)
    score_components = {
        "financial_score": (purchase_affordability * 0.35) + (monthly_affordability * 0.65),
        "tco_score": (components["tco"] * 0.45) + (monthly_affordability * 0.55),
        "usage_score": (components["profile_fit"] * 0.55) + (use_specific * 0.45),
        "maintenance_score": (components["maintenance_cost"] * 0.25) + (maintenance_absolute * 0.35) + (maintenance_index * 0.40),
        "reliability_score": (absolute_reliability * 0.65) + (components["reliability"] * 0.35),
        "parts_score": (absolute_parts * 0.65) + (supplier_score * 0.35),
        "resale_score": components["depreciation"],
        "risk_score": (monthly_affordability * 0.35) + (absolute_reliability * 0.35) + ((100 - variation_risk) * 0.30),
        "segment_score": segment_score,
        "purchase_intent_score": purchase_intent_score,
    }
    return {key: round(clamp_score(value), 2) for key, value in score_components.items()}


def effective_strategy_weights(score_components: dict[str, float], profile: RecommendationProfile) -> dict[str, float]:
    strategy = normalize_strategy(profile.recommendation_strategy)
    financial_profile = score_components.get("financial_capacity_profile")
    if strategy == "cost_benefit" and financial_profile in {"comfortable", "high_capacity"}:
        return {
            "financial_score": 0.10,
            "tco_score": 0.12,
            "usage_score": 0.16,
            "maintenance_score": 0.09,
            "reliability_score": 0.15,
            "parts_score": 0.07,
            "segment_score": 0.16,
            "purchase_intent_score": 0.15,
        }
    return STRATEGY_WEIGHTS[strategy]


def calculate_final_score(score_components: dict[str, float], profile: RecommendationProfile) -> float:
    weights = effective_strategy_weights(score_components, profile)
    return sum(score_components[key] * weights[key] for key in weights)


def build_score_breakdown(score_components: dict[str, float], profile: RecommendationProfile) -> dict[str, object]:
    """Explicita a nota base e a contribuicao ponderada de cada criterio."""
    strategy = normalize_strategy(profile.recommendation_strategy)
    rows = []
    for key, weight in effective_strategy_weights(score_components, profile).items():
        score = round(float(score_components[key]), 2)
        contribution = round(score * weight, 2)
        rows.append(
            {
                "criterion": key,
                "label": CRITERIA_LABELS[key],
                "score": score,
                "weight": round(weight * 100, 2),
                "contribution": contribution,
            }
        )
    return {
        "method": "MCDA ponderada com ajustes limitados e travas de coerencia",
        "strategy": strategy,
        "criteria": rows,
        "base_score": round(sum(row["contribution"] for row in rows), 2),
    }


def select_primary_factors(
    score_breakdown: dict[str, object],
    penalties: list[str],
) -> dict[str, object]:
    """Seleciona vantagem e risco pelo impacto efetivo na nota final."""
    criteria = list(score_breakdown.get("criteria", []))
    if not criteria:
        return {
            "advantage": "criterios ponderados",
            "advantage_source": "weighted_criterion",
            "advantage_impact": 0.0,
            "risk": penalties[0] if penalties else "nenhum fator limitante relevante",
            "risk_source": "penalty" if penalties else "weighted_criterion",
            "risk_impact": 0.0,
        }

    advantage_row = max(criteria, key=lambda row: float(row["contribution"]))
    advantage = str(advantage_row["label"])
    advantage_source = "weighted_criterion"
    advantage_impact = float(advantage_row["contribution"])

    context_adjustment = float(score_breakdown.get("context_adjustment", 0) or 0)
    evidence_adjustment = float(score_breakdown.get("evidence_adjustment", 0) or 0)
    for label, source, impact in (
        ("ajuste contextual favorável", "context_adjustment", context_adjustment),
        ("evidências favoráveis", "evidence_adjustment", evidence_adjustment),
    ):
        if impact > advantage_impact:
            advantage, advantage_source, advantage_impact = label, source, impact

    risk_row = max(
        criteria,
        key=lambda row: (100.0 - float(row["score"])) * (float(row["weight"]) / 100.0),
    )
    risk = str(risk_row["label"])
    risk_source = "weighted_criterion"
    risk_impact = (100.0 - float(risk_row["score"])) * (float(risk_row["weight"]) / 100.0)

    negative_candidates = [
        (abs(context_adjustment), "context_adjustment", penalties[0] if penalties else "ajuste contextual desfavorável"),
        (abs(evidence_adjustment), "evidence_adjustment", "evidências desfavoráveis"),
    ]
    preliminary_score = (
        float(score_breakdown.get("base_score", 0) or 0)
        + context_adjustment
        + evidence_adjustment
    )
    guardrail_impact = max(0.0, preliminary_score - float(score_breakdown.get("final_score", preliminary_score) or 0))
    guardrails = list(score_breakdown.get("guardrails", []))
    negative_candidates.append(
        (guardrail_impact, "guardrail", guardrails[0] if guardrails else "trava de coerencia")
    )
    for impact, source, label in negative_candidates:
        if impact > risk_impact and (
            (source == "context_adjustment" and context_adjustment < 0)
            or (source == "evidence_adjustment" and evidence_adjustment < 0)
            or source == "guardrail"
        ):
            risk, risk_source, risk_impact = label, source, impact

    return {
        "advantage": advantage,
        "advantage_source": advantage_source,
        "advantage_impact": round(advantage_impact, 2),
        "risk": risk,
        "risk_source": risk_source,
        "risk_impact": round(risk_impact, 2),
    }


def apply_score_guardrails(
    score: float,
    score_components: dict[str, float],
    feedback_adjustment: float,
) -> tuple[float, list[str]]:
    """Impede nota alta quando um requisito essencial esta fraco ou inviavel."""
    caps: list[tuple[float, str]] = []
    purchase_viable = bool(score_components.get("purchase_viable"))
    monthly_viable = bool(score_components.get("monthly_viable"))

    if not purchase_viable and not monthly_viable:
        caps.append((49.0, "Compra e TCO mensal excedem os limites informados."))
    elif not purchase_viable or not monthly_viable:
        caps.append((69.0, "A opção não atende simultaneamente aos limites de compra e custo mensal."))
    if not monthly_viable:
        monthly_cost = float(score_components.get("total_monthly_cost", 0) or 0)
        monthly_gap = float(score_components.get("monthly_limit_gap", 0) or 0)
        monthly_limit = monthly_cost + monthly_gap
        monthly_ratio = monthly_cost / monthly_limit if monthly_limit > 0 else 10
        if monthly_ratio > 1.50:
            caps.append((49.0, "O TCO mensal supera o limite informado em mais de 50%."))
        elif monthly_ratio > 1.25:
            caps.append((59.0, "O TCO mensal supera o limite informado em mais de 25%."))
    if score_components["usage_score"] < 50:
        caps.append((69.0, "A aderência ao uso informado é insuficiente para uma recomendação forte."))
    if score_components["financial_score"] < 35:
        caps.append((74.0, "A eficiência financeira comparativa é baixa."))
    if score_components["parts_score"] < 35:
        caps.append((79.0, "A evidência de disponibilidade de peças é fraca."))
    if feedback_adjustment <= -5:
        caps.append((84.0, "Relatos reais relevantes impedem classificação de excelência."))

    essential_scores = [
        score_components["financial_score"],
        score_components["usage_score"],
        score_components["maintenance_score"],
        score_components["reliability_score"],
        score_components["parts_score"],
    ]
    weakest_essential = min(essential_scores)
    if weakest_essential < 60:
        excellence_cap = 89.0 - min(8.0, (60.0 - weakest_essential) * 0.15)
        caps.append((excellence_cap, "Existe ao menos um critério essencial abaixo de 60/100."))

    applied = []
    guarded_score = score
    for cap, reason in sorted(caps, key=lambda item: item[0]):
        if guarded_score > cap:
            guarded_score = cap
            applied.append(f"Nota limitada a {cap:.0f}: {reason}")
    return round(clamp_score(guarded_score), 2), applied


def build_confidence_assessment(feedback: dict, parts_feedback: dict) -> dict[str, object]:
    """Separa qualidade da recomendacao da quantidade de evidencia disponivel."""
    score = 46.0
    reasons = ["Base técnica e custos do MVP são demonstrativos."]

    if parts_feedback:
        score += 15
        reasons.append("Há análise estruturada de peças e fornecedores para o modelo.")
    else:
        reasons.append("Não há análise detalhada de peças para o modelo.")

    stats = feedback.get("stats", {}) if feedback else {}
    report_count = int(stats.get("report_count", 0) or 0)
    if report_count:
        score += min(15, report_count * 3)
        reasons.append(f"Foram considerados {report_count} relato(s) de usuários.")
    else:
        reasons.append("Ainda não há relatos suficientes de usuários para validar o histórico do modelo.")
    if stats.get("consumption_gap_percent") is not None:
        score += 5
        reasons.append("Há comparação entre consumo informado e consumo observado.")

    score = round(min(80.0, score), 2)
    level = "moderada" if score >= 60 else "baixa"
    return {
        "score": score,
        "level": level,
        "basis": "demonstrative" if score < 80 else "mixed",
        "reasons": reasons,
        "disclaimer": "A confiança mede a cobertura dos dados, não garante preço, custo ou ausência de falhas.",
    }


def build_sort_key(
    vehicle: Vehicle,
    profile: RecommendationProfile,
    final_score: float,
    score_components: dict[str, float],
    tco: dict[str, float],
    components: dict[str, float],
) -> tuple:
    strategy = normalize_strategy(profile.recommendation_strategy)
    fully_viable = bool(score_components.get("fully_viable"))
    total_monthly_cost = tco["total_monthly_cost"]
    if strategy == "lowest_cost":
        return (
            fully_viable,
            final_score,
            -total_monthly_cost,
            score_components["maintenance_score"],
            components["fuel_efficiency"],
            -vehicle.price,
            -vehicle.id,
        )
    if strategy == "budget_economy":
        return (
            fully_viable,
            final_score,
            score_components["tco_score"],
            score_components["reliability_score"],
            vehicle.segment_level,
            components["fuel_efficiency"],
            score_components["maintenance_score"],
            -vehicle.id,
        )
    if strategy == "best_within_budget":
        if not fully_viable:
            return (
                fully_viable,
                final_score,
                -total_monthly_cost,
                score_components["tco_score"],
                score_components["maintenance_score"],
                score_components["reliability_score"],
                -vehicle.price,
                -vehicle.id,
            )
        return (
            fully_viable,
            final_score,
            vehicle.segment_level,
            vehicle.reliability_score,
            vehicle.safety_score,
            vehicle.space_score,
            -total_monthly_cost,
            vehicle.parts_availability_score,
            -vehicle.depreciation_rate,
            -vehicle.id,
        )
    return (
        fully_viable,
        final_score,
        score_components["segment_score"],
        score_components["reliability_score"],
        score_components["tco_score"],
        -total_monthly_cost,
        -vehicle.id,
    )


def best_component(score_components: dict[str, float]) -> tuple[str, float]:
    visible_components = {
        key: value
        for key, value in score_components.items()
        if key in EXPLANATION_SCORE_KEYS and isinstance(value, (int, float)) and not isinstance(value, bool)
    }
    return max(visible_components.items(), key=lambda item: item[1])


def weakest_component(score_components: dict[str, float]) -> tuple[str, float]:
    visible_components = {
        key: value
        for key, value in score_components.items()
        if key in EXPLANATION_SCORE_KEYS and isinstance(value, (int, float)) and not isinstance(value, bool)
    }
    return min(visible_components.items(), key=lambda item: item[1])


def strategy_explanation(strategy: str) -> str:
    messages = {
        "lowest_cost": "A recomendação priorizou o menor custo mensal e preço de compra.",
        "budget_economy": "A recomendação buscou opções econômicas dentro de uma faixa racional do orçamento, evitando escolher apenas o carro mais barato.",
        "cost_benefit": "A recomendação equilibrou TCO, preço, uso, confiabilidade e manutenção.",
        "balanced": "A recomendação distribuiu o peso entre custo, uso, confiabilidade, peças e categoria.",
        "comfort_space": "A recomendação valorizou conforto, espaço, segurança e aderência ao uso.",
        "best_within_budget": "A recomendação buscou a melhor categoria possível dentro do orçamento informado.",
    }
    return messages.get(strategy, messages["cost_benefit"])


def build_recommendation_summary(
    vehicle: Vehicle,
    profile: RecommendationProfile,
    score_components: dict[str, float],
    tco: dict[str, float],
    status: str,
    penalties: list[str],
    score_breakdown: dict[str, object],
) -> dict[str, object]:
    strategy = normalize_strategy(profile.recommendation_strategy)
    primary_factors = select_primary_factors(score_breakdown, penalties)
    fits_monthly = tco["total_monthly_cost"] <= profile.monthly_limit
    fits_budget = vehicle.price <= profile.budget
    use_case_label = USE_CASE_TEXT.get(profile.use_case, profile.use_case)
    main_advantage = str(primary_factors["advantage"])
    main_risk = str(primary_factors["risk"])
    financial_profile = score_components.get("financial_capacity_profile", "balanced")
    monthly_gap = score_components.get("monthly_limit_gap", 0)
    return {
        "why_recommended": (
            f"{vehicle.brand} {vehicle.model} foi avaliado para {use_case_label} com a prioridade "
            f"de {STRATEGY_LABELS[strategy]}, considerando TCO, uso, manutenção, segmento e risco."
        ),
        "strategy_explanation": strategy_explanation(strategy),
        "main_advantage": main_advantage,
        "main_risk": main_risk,
        "main_advantage_source": primary_factors["advantage_source"],
        "main_advantage_impact": primary_factors["advantage_impact"],
        "main_risk_source": primary_factors["risk_source"],
        "main_risk_impact": primary_factors["risk_impact"],
        "fits_monthly_budget": fits_monthly,
        "fits_purchase_budget": fits_budget,
        "financial_capacity_profile": financial_profile,
        "monthly_capacity_score": score_components.get("monthly_capacity_score", 0),
        "monthly_limit_gap": monthly_gap,
        "financial_status": financial_status_text(fits_budget, fits_monthly),
        "use_case_fit": profile_fit_score(vehicle, profile),
        "best_for": use_case_label if profile_fit_score(vehicle, profile) >= 90 else "perfil alternativo",
        "status_label": STATUS_LABELS[status],
    }


def financial_status_text(fits_purchase: bool, fits_monthly: bool) -> str:
    if fits_purchase and fits_monthly:
        return "Cabe na compra e na manutenção."
    if fits_purchase and not fits_monthly:
        return "Cabe na compra, mas pesa no mensal."
    if not fits_purchase and fits_monthly:
        return "Cabe no mensal, mas passa do orçamento de compra."
    return "Acima do orçamento de compra e do limite mensal."


def suggested_monthly_limit(results: list[dict], profile: RecommendationProfile) -> int | None:
    in_budget_costs = [
        item["tco"]["total_monthly_cost"]
        for item in results
        if item["vehicle"].price <= profile.budget
    ]
    candidate_costs = in_budget_costs or [item["tco"]["total_monthly_cost"] for item in results]
    if not candidate_costs:
        return None
    return int(math.ceil(min(candidate_costs) / 100) * 100)


def build_viability_summary(results: list[dict], profile: RecommendationProfile) -> dict[str, object]:
    total_count = len(results)
    viable_count = len([item for item in results if item["score_components"].get("fully_viable")])
    monthly_viable_count = len([item for item in results if item["score_components"].get("monthly_viable")])
    has_viable_options = viable_count > 0
    no_monthly_options = monthly_viable_count == 0
    summary = {
        "has_viable_options": has_viable_options,
        "viable_count": viable_count,
        "total_count": total_count,
        "message": "",
        "suggested_monthly_limit": None,
        "suggested_strategy": None,
    }
    if has_viable_options and not no_monthly_options:
        return summary

    minimum_limit = suggested_monthly_limit(results, profile)
    strategy = normalize_strategy(profile.recommendation_strategy)
    suggested_strategy = "lowest_cost" if strategy in {"best_within_budget", "comfort_space"} else None
    message = (
        "Nenhum veículo da base ficou totalmente viável dentro do limite mensal informado. "
        "O orçamento de compra pode ser suficiente, mas o custo mensal estimado ultrapassa sua capacidade mensal."
    )
    if minimum_limit is not None:
        message += f" Para encontrar opções viáveis, considere um limite mensal a partir de aproximadamente R$ {minimum_limit:,.0f}."
    if suggested_strategy is not None:
        message += " Outra opção é escolher Menor custo possível ou Econômico dentro do orçamento."

    summary.update(
        {
            "has_viable_options": False,
            "viable_count": 0,
            "message": message,
            "suggested_monthly_limit": minimum_limit,
            "suggested_strategy": suggested_strategy,
        }
    )
    return summary


def recommend(
    vehicles: Iterable[Vehicle],
    profile: RecommendationProfile,
    model_feedback: dict[int, dict] | None = None,
    parts_feedback: dict[int, dict] | None = None,
    processing_metadata: dict[str, object] | None = None,
) -> list[dict]:
    """Retorna ranking explicavel com TCO mensal, segmentos e estrategia de compra."""
    validate_profile_data(profile)
    source_vehicles = list(vehicles)
    vehicle_list = []
    ignored_records = []
    ignored_reasons: dict[str, int] = {}
    for vehicle in source_vehicles:
        validation_errors = validate_vehicle_data(vehicle)
        if validation_errors:
            LOGGER.warning(
                "Veiculo %s ignorado na recomendacao: %s",
                getattr(vehicle, "id", "sem-id"),
                "; ".join(validation_errors),
            )
            for reason in validation_errors:
                ignored_reasons[reason] = ignored_reasons.get(reason, 0) + 1
            ignored_records.append(
                {
                    "vehicle_id": getattr(vehicle, "id", None),
                    "vehicle": " ".join(
                        value
                        for value in (
                            getattr(vehicle, "brand", "") if isinstance(getattr(vehicle, "brand", ""), str) else "",
                            getattr(vehicle, "model", "") if isinstance(getattr(vehicle, "model", ""), str) else "",
                        )
                        if value
                    )
                    or "Registro sem identificacao",
                    "reasons": validation_errors,
                }
            )
            continue
        vehicle_list.append(vehicle)
    if processing_metadata is not None:
        processing_metadata.update(
            {
                "total_found": len(source_vehicles),
                "evaluated": len(vehicle_list),
                "ignored": len(ignored_records),
                "ignored_reasons": ignored_reasons,
                "ignored_records": ignored_records,
            }
        )
    if not vehicle_list:
        return []

    strategy = normalize_strategy(profile.recommendation_strategy)
    profile = RecommendationProfile(
        budget=profile.budget,
        monthly_limit=profile.monthly_limit,
        use_case=profile.use_case,
        monthly_mileage=profile.monthly_mileage,
        fuel_price=profile.fuel_price,
        recommendation_strategy=strategy,
    )

    tco_by_vehicle = {vehicle.id: calculate_vehicle_tco(vehicle, profile) for vehicle in vehicle_list}
    financial_capacity = classify_financial_capacity(profile, vehicle_list, tco_by_vehicle)
    financial_capacity_profile = str(financial_capacity["financial_capacity_profile"])
    ranges = {
        "price": (min(v.price for v in vehicle_list), max(v.price for v in vehicle_list)),
        "fuel_efficiency": (
            min(v.fuel_efficiency_km_l for v in vehicle_list),
            max(v.fuel_efficiency_km_l for v in vehicle_list),
        ),
        "maintenance_cost": (
            min(v.annual_maintenance_cost for v in vehicle_list),
            max(v.annual_maintenance_cost for v in vehicle_list),
        ),
        "reliability": (
            min(v.reliability_score for v in vehicle_list),
            max(v.reliability_score for v in vehicle_list),
        ),
        "parts_availability": (
            min(v.parts_availability_score for v in vehicle_list),
            max(v.parts_availability_score for v in vehicle_list),
        ),
        "depreciation": (
            min(v.depreciation_rate for v in vehicle_list),
            max(v.depreciation_rate for v in vehicle_list),
        ),
        "tco": (
            min(tco_by_vehicle[v.id]["total_monthly_cost"] for v in vehicle_list),
            max(tco_by_vehicle[v.id]["total_monthly_cost"] for v in vehicle_list),
        ),
    }

    results = []
    model_feedback = model_feedback or {}
    parts_feedback = parts_feedback or {}
    for vehicle in vehicle_list:
        tco = tco_by_vehicle[vehicle.id]
        monthly_cost = tco["total_monthly_cost"]
        part_feedback = parts_feedback.get(vehicle.id, {})
        components = {
            "price": normalize_cost(vehicle.price, *ranges["price"]),
            "fuel_efficiency": normalize_positive(vehicle.fuel_efficiency_km_l, *ranges["fuel_efficiency"]),
            "monthly_fit": normalize_monthly_fit(monthly_cost, profile.monthly_limit),
            "tco": normalize_cost(monthly_cost, *ranges["tco"]),
            "profile_fit": profile_fit_score(vehicle, profile),
            "maintenance_cost": normalize_cost(vehicle.annual_maintenance_cost, *ranges["maintenance_cost"]),
            "reliability": normalize_positive(vehicle.reliability_score, *ranges["reliability"]),
            "parts_availability": normalize_positive(vehicle.parts_availability_score, *ranges["parts_availability"]),
            "depreciation": normalize_cost(vehicle.depreciation_rate, *ranges["depreciation"]),
        }

        segment_score = calculate_segment_score(vehicle, profile)
        purchase_score = calculate_purchase_intent_score(vehicle, profile, components, segment_score)
        score_components = build_score_components(
            components,
            segment_score,
            purchase_score,
            vehicle,
            profile,
            tco,
            part_feedback,
        )
        purchase_viable = vehicle.price <= profile.budget
        monthly_limit_gap = round(profile.monthly_limit - monthly_cost, 2)
        monthly_viable = monthly_limit_gap >= 0
        fully_viable = purchase_viable and monthly_viable
        score_components.update(
            {
                "purchase_viable": purchase_viable,
                "monthly_viable": monthly_viable,
                "fully_viable": fully_viable,
                "monthly_capacity_score": financial_capacity["monthly_capacity_score"],
                "financial_capacity_profile": financial_capacity_profile,
                "monthly_limit_gap": monthly_limit_gap,
                "total_monthly_cost": monthly_cost,
            }
        )
        weighted_score = calculate_final_score(score_components, profile)
        penalties = []

        if vehicle.price > profile.budget:
            over_budget_percent = (vehicle.price - profile.budget) / profile.budget
            weighted_score -= min(35, over_budget_percent * 30)
            penalties.append("Está acima do orçamento de compra informado.")

        if monthly_cost > profile.monthly_limit:
            over_limit_percent = (monthly_cost - profile.monthly_limit) / profile.monthly_limit
            weighted_score -= min(40, over_limit_percent * 35)
            penalties.append("TCO mensal estimado acima do limite informado.")

        if financial_capacity_profile == "purchase_high_monthly_low":
            if not monthly_viable:
                over_limit_percent = (monthly_cost - profile.monthly_limit) / profile.monthly_limit
                weighted_score -= min(55, 18 + (over_limit_percent * 30))
                penalties.append("Apesar do orçamento de compra elevado, o limite mensal informado restringe opções com custo de manutenção mais alto.")
            elif vehicle.segment_level >= 3:
                weighted_score += 4

        if financial_capacity_profile in {"comfortable", "high_capacity"}:
            if strategy in {"best_within_budget", "comfort_space"} and fully_viable:
                if vehicle.segment_level >= 5:
                    weighted_score += 14
                elif vehicle.segment_level >= 4:
                    weighted_score += 11
                elif vehicle.segment_level >= 3:
                    weighted_score += 3
                if vehicle.category in {"midsize_sedan", "compact_suv", "suv"}:
                    weighted_score += 7
            if strategy == "best_within_budget" and vehicle.price < profile.budget * 0.45:
                weighted_score -= 2 if is_superior_vehicle(vehicle) else 10
            if strategy == "budget_economy" and vehicle.price >= profile.budget * 0.35 and vehicle.segment_level >= 3:
                weighted_score += 3
            if strategy in {"cost_benefit", "balanced", "comfort_space"} and fully_viable:
                if is_superior_vehicle(vehicle):
                    quality_bonus = high_capacity_quality_bonus(vehicle, profile)
                    weighted_score += quality_bonus if strategy in {"cost_benefit", "balanced"} else min(8, quality_bonus)
                elif vehicle.segment_level >= 3:
                    weighted_score += high_capacity_quality_bonus(vehicle, profile)
                if vehicle.price < profile.budget * 0.25:
                    if is_superior_vehicle(vehicle):
                        weighted_score -= 4
                        penalties.append("Apesar de custar pouco frente ao orçamento informado, ainda compete por categoria superior.")
                    elif vehicle.segment_level >= 3 and has_direct_use_match(vehicle, profile):
                        weighted_score -= 18
                        penalties.append("Está abaixo da faixa ideal do orçamento, mas permanece competitiva pela aderência ao uso informado.")
                    else:
                        weighted_score -= 34 if vehicle.segment_level >= 3 else 38
                        penalties.append("Com orçamento alto, perdeu pontos por ser uma escolha muito abaixo da capacidade de compra informada.")
                elif vehicle.price < profile.budget * 0.35 and not is_superior_vehicle(vehicle):
                    weighted_score -= 18 if strategy in {"cost_benefit", "balanced"} else 6
                    penalties.append("Fica abaixo da faixa ideal para aproveitar melhor o orçamento informado.")

        if profile.use_case == "app" and financial_capacity_profile in {"comfortable", "high_capacity"} and strategy != "lowest_cost":
            if vehicle.segment_level <= 1:
                weighted_score -= 24
                penalties.append("Apesar do baixo custo, perdeu pontos por oferecer menor conforto e espaço para uso recorrente em aplicativo.")
            elif vehicle.segment_level >= 3 and fully_viable:
                weighted_score += 9
                if vehicle.category in {"compact_sedan", "midsize_sedan", "compact_minivan", "minivan"}:
                    weighted_score += 5
            if strategy in {"best_within_budget", "comfort_space"} and fully_viable and vehicle.category in {"midsize_sedan", "compact_suv"}:
                weighted_score += 4

        if (
            financial_capacity_profile in {"comfortable", "high_capacity"}
            and strategy in {"cost_benefit", "balanced", "comfort_space"}
        ):
            weighted_score += use_case_priority_adjustment(vehicle, profile)

        if strategy == "budget_economy":
            if vehicle.price < profile.budget * 0.30:
                weighted_score -= 7
                penalties.append("Está muito abaixo da faixa desejada para essa prioridade de compra.")
            elif vehicle.price < profile.budget * 0.40:
                weighted_score -= 3
                penalties.append("Está abaixo da faixa ideal para aproveitar o orçamento informado.")

        if strategy == "best_within_budget":
            if vehicle.price < profile.budget * 0.30:
                if is_superior_vehicle(vehicle):
                    weighted_score -= 4
                    penalties.append("Apesar de estar abaixo da faixa ideal do orçamento, compete por categoria, conforto e confiabilidade.")
                elif vehicle.segment_level >= 3:
                    weighted_score -= 18
                    penalties.append("Está abaixo da faixa desejada para buscar uma categoria realmente superior dentro do orçamento.")
                else:
                    weighted_score -= 34
                    penalties.append("Está muito abaixo da faixa desejada para buscar a melhor categoria dentro do orçamento.")
            elif vehicle.price < profile.budget * 0.40:
                if is_superior_vehicle(vehicle):
                    weighted_score -= 2
                    penalties.append("Fica abaixo da faixa ideal do orçamento, mas entrega categoria superior.")
                elif vehicle.segment_level >= 3:
                    weighted_score -= 10
                    penalties.append("Está abaixo da faixa ideal para buscar categoria superior dentro do orçamento.")
                else:
                    weighted_score -= 18
                    penalties.append("Está abaixo da faixa ideal para buscar categoria superior dentro do orçamento.")

        fit_score = profile_fit_score(vehicle, profile)
        if fit_score >= 90:
            profile_bonus = PROFILE_MATCH_BONUS
            if strategy == "best_within_budget" and financial_capacity_profile in {"comfortable", "high_capacity"}:
                profile_bonus = 2
            weighted_score += profile_bonus
            if profile.use_case == "suv" and "suv" in vehicle.use_cases:
                weighted_score += 12
            if profile.use_case in {"familia", "estrada", "trabalho"} and vehicle.reliability_score >= 90:
                weighted_score += HIGH_RELIABILITY_BONUS
        else:
            mismatch_penalty = PROFILE_MISMATCH_PENALTY
            if (
                strategy in {"cost_benefit", "balanced", "comfort_space", "best_within_budget"}
                and financial_capacity_profile in {"comfortable", "high_capacity"}
                and profile.use_case == "cidade"
                and is_superior_vehicle(vehicle)
                and fit_score >= 65
            ):
                mismatch_penalty = 2
            weighted_score -= mismatch_penalty
            if profile.use_case == "suv" and "suv" not in vehicle.use_cases:
                weighted_score -= 45
            if mismatch_penalty >= PROFILE_MISMATCH_PENALTY:
                penalties.append("Perfil de uso não é o ponto forte do modelo.")
            else:
                penalties.append("Não é o modelo mais urbano da base, mas compete por categoria superior.")

        feedback = model_feedback.get(vehicle.id, {})
        feedback_adjustment = feedback.get("net_adjustment", 0)
        weighted_score += feedback_adjustment
        if feedback_adjustment < 0:
            penalties.append("Dados reais de usuários reduziram a nota do modelo.")

        parts_adjustment = part_feedback.get("score_adjustment", 0)
        weighted_score += parts_adjustment
        if part_feedback:
            components["maintenance_index"] = part_feedback.get("maintenance_index", components["parts_availability"])
            components["shared_parts_score"] = part_feedback.get("shared_parts_score", 50)
            components["supplier_availability_score"] = part_feedback.get("supplier_availability_score", components["parts_availability"])
            components["price_variation_risk"] = 100 - part_feedback.get("price_variation_risk", 50)
            if parts_adjustment < 0:
                penalties.append("Análise de peças reduziu a nota por custo, variação ou baixa disponibilidade.")

        score_breakdown = build_score_breakdown(score_components, profile)
        base_score = float(score_breakdown["base_score"])
        evidence_adjustment = max(-12.0, min(8.0, float(feedback_adjustment))) + max(
            -8.0, min(7.0, float(parts_adjustment))
        )
        raw_context_adjustment = weighted_score - base_score - feedback_adjustment - parts_adjustment
        context_ceiling = 8.0
        purchase_ratio = vehicle.price / profile.budget if profile.budget > 0 else 10
        if (
            financial_capacity_profile in {"comfortable", "high_capacity"}
            and strategy in {"cost_benefit", "balanced", "comfort_space", "best_within_budget"}
            and not is_superior_vehicle(vehicle)
        ):
            if purchase_ratio < 0.15:
                context_ceiling = -6.0 if vehicle.segment_level >= 3 else -10.0
            elif purchase_ratio < 0.25:
                context_ceiling = -3.0 if vehicle.segment_level >= 3 else -7.0
            elif purchase_ratio < 0.35:
                context_ceiling = 0.0 if vehicle.segment_level >= 3 else -5.0
        context_adjustment = max(-18.0, min(context_ceiling, raw_context_adjustment))
        grounded_score = base_score + context_adjustment + evidence_adjustment
        final_score, guardrails = apply_score_guardrails(
            grounded_score,
            score_components,
            float(feedback_adjustment),
        )
        score_breakdown.update(
            {
                "raw_context_adjustment": round(raw_context_adjustment, 2),
                "context_adjustment": round(context_adjustment, 2),
                "context_adjustment_limit": {"minimum": -18.0, "maximum": context_ceiling},
                "evidence_adjustment": round(evidence_adjustment, 2),
                "guardrails": guardrails,
                "final_score": final_score,
            }
        )
        confidence = build_confidence_assessment(feedback, part_feedback)
        sort_key = build_sort_key(vehicle, profile, final_score, score_components, tco, components)
        score_components["final_score"] = final_score
        value_score = calculate_value_score(vehicle, profile, monthly_cost, final_score, components)
        decision_score = calculate_decision_score(final_score, value_score)
        status = classify_recommendation(vehicle, profile, monthly_cost, final_score)
        recommendation_summary = build_recommendation_summary(
            vehicle,
            profile,
            score_components,
            tco,
            status,
            penalties,
            score_breakdown,
        )
        recommendation_summary["confidence"] = confidence
        explanations = build_explanations(vehicle, score_components, tco, recommendation_summary, penalties, status, strategy)
        explanations.extend(
            [
                (
                    f"Preço FIPE de referência: R$ {vehicle.price:,.2f}, "
                    f"{vehicle.price_reference_month}, código {vehicle.fipe_code}."
                    if vehicle.price_is_fipe
                    else "Preço de compra ainda demonstrativo; pareamento FIPE da versão pendente."
                ),
                f"Nota base ponderada: {score_breakdown['base_score']:.2f}/100.",
                f"Ajuste contextual limitado: {score_breakdown['context_adjustment']:+.2f} ponto(s).",
                f"Ajuste por evidências: {score_breakdown['evidence_adjustment']:+.2f} ponto(s).",
                f"Confiança dos dados: {confidence['level']} ({confidence['score']:.0f}/100).",
                str(confidence["disclaimer"]),
            ]
        )
        explanations.extend(score_breakdown["guardrails"])
        if part_feedback:
            explanations.extend(build_parts_explanations(part_feedback))

        results.append(
            {
                "vehicle": vehicle,
                "score": final_score,
                "final_score": final_score,
                "value_score": value_score,
                "decision_score": decision_score,
                "sort_key": sort_key,
                "recommendation_status": status,
                "recommendation_strategy": strategy,
                "monthly_cost": monthly_cost,
                "tco": tco,
                "components": {key: round(value, 2) for key, value in components.items()},
                "score_components": score_components,
                "penalties": penalties,
                "feedback_adjustment": feedback,
                "parts_feedback": part_feedback,
                "score_breakdown": score_breakdown,
                "confidence": confidence,
                "recommendation_summary": recommendation_summary,
                "explanations": explanations,
            }
        )

    results = sorted(results, key=lambda item: item["sort_key"], reverse=True)
    awards = build_category_awards(results, profile)
    viability_summary = build_viability_summary(results, profile)
    for result in results:
        result["category_awards"] = awards.get(result["vehicle"].id, [])
        result["recommendation_summary"].update(viability_summary)
    for result in results:
        result.pop("sort_key", None)
    return results


def build_category_awards(results: list[dict], profile: RecommendationProfile) -> dict[int, list[dict]]:
    eligible = [item for item in results if item["recommendation_status"] != "not_recommended"]
    if not eligible:
        eligible = results

    categories = {
        "Melhor custo-benefício": max(eligible, key=lambda item: item["value_score"]),
        "Menor TCO mensal": min(eligible, key=lambda item: item["tco"]["total_monthly_cost"]),
        "Mais econômico": max(eligible, key=lambda item: item["components"]["fuel_efficiency"]),
        "Mais confiável": max(eligible, key=lambda item: item["score_components"]["reliability_score"]),
        "Menor custo de manutenção": max(eligible, key=lambda item: item["score_components"]["maintenance_score"]),
        "Melhor dentro do orçamento": max(
            eligible,
            key=lambda item: (
                item["vehicle"].price <= profile.budget,
                item["tco"]["total_monthly_cost"] <= profile.monthly_limit,
                item["score_components"]["purchase_intent_score"],
                item["score"],
            ),
        ),
    }
    with_parts = [item for item in eligible if item.get("parts_feedback")]
    if with_parts:
        categories["Mais fácil de manter"] = max(with_parts, key=lambda item: item["parts_feedback"]["maintenance_index"])
        categories["Melhor disponibilidade de peças"] = max(with_parts, key=lambda item: item["parts_feedback"]["supplier_availability_score"])
        categories["Menor risco de preço abusivo"] = min(with_parts, key=lambda item: item["parts_feedback"]["price_variation_risk"])

    family_pool = [item for item in eligible if "familia" in item["vehicle"].use_cases]
    if family_pool:
        categories["Melhor para família"] = max(family_pool, key=lambda item: item["score_components"]["usage_score"] + item["score_components"]["reliability_score"])

    city_pool = [item for item in eligible if "cidade" in item["vehicle"].use_cases]
    if city_pool:
        categories["Melhor para uso urbano"] = max(city_pool, key=lambda item: item["components"]["fuel_efficiency"] + item["score_components"]["financial_score"])

    awards: dict[int, list[dict]] = {}
    for label, item in categories.items():
        awards.setdefault(item["vehicle"].id, []).append({"label": label, "reason": award_reason(label)})
    return awards


def award_reason(label: str) -> str:
    reasons = {
        "Melhor custo-benefício": "combina nota SIGRA, TCO e aderência ao perfil.",
        "Menor TCO mensal": "tem menor custo total mensal estimado.",
        "Mais econômico": "apresenta melhor indicador de consumo no ranking.",
        "Mais confiável": "tem melhor indicador de confiabilidade.",
        "Menor custo de manutenção": "tem melhor relação entre manutenção e facilidade de peças.",
        "Melhor dentro do orçamento": "equilibra faixa de compra, TCO e qualidade do segmento.",
        "Melhor para família": "prioriza aderência familiar e confiabilidade.",
        "Melhor para uso urbano": "prioriza consumo e custo para cidade.",
        "Mais fácil de manter": "combina peças, fornecedores e custo de manutenção.",
        "Melhor disponibilidade de peças": "tem mais fornecedores e peças demonstrativas disponíveis.",
        "Menor risco de preço abusivo": "apresenta menor variação de preço nas peças analisadas.",
    }
    return reasons.get(label, "destaque calculado pelo SIGRA.")


def calculate_decision_score(compatibility_score: float, value_score: float) -> float:
    return round((compatibility_score * 0.80) + (value_score * 0.20), 2)


def calculate_value_score(
    vehicle: Vehicle,
    profile: RecommendationProfile,
    monthly_cost: float,
    compatibility_score: float,
    components: dict[str, float],
) -> float:
    monthly_fit = components["monthly_fit"]
    budget_penalty = 0 if vehicle.price <= profile.budget else min(45, ((vehicle.price - profile.budget) / profile.budget) * 100)
    value_score = compatibility_score * 0.45 + components["price"] * 0.20 + monthly_fit * 0.20 + components["tco"] * 0.15 - budget_penalty
    return round(clamp_score(value_score), 2)


def classify_recommendation(vehicle: Vehicle, profile: RecommendationProfile, monthly_cost: float, score: float) -> str:
    profile_matches = profile.use_case in vehicle.use_cases or (profile.use_case == "suv" and "suv" in vehicle.use_cases)
    if vehicle.price > profile.budget * 1.35 or monthly_cost > profile.monthly_limit * 1.35:
        return "not_recommended"
    if score < 25 and not profile_matches:
        return "not_recommended"
    if vehicle.price > profile.budget or monthly_cost > profile.monthly_limit:
        return "attention"
    if score >= 85:
        return "recommended"
    if score >= 70:
        return "good_option"
    if score < 55:
        return "not_recommended"
    return "attention"


def build_explanations(
    vehicle: Vehicle,
    score_components: dict[str, float],
    tco: dict[str, float],
    summary: dict[str, object],
    penalties: list[str],
    status: str,
    strategy: str,
) -> list[str]:
    messages = [
        summary["why_recommended"],
        strategy_explanation(strategy),
        (
            f"Principal vantagem: {summary['main_advantage']} "
            f"(impacto de {float(summary.get('main_advantage_impact', 0)):.2f} ponto(s))."
        ),
        (
            f"Principal fator limitante: {summary['main_risk']} "
            f"(impacto de {float(summary.get('main_risk_impact', 0)):.2f} ponto(s))."
        ),
        f"TCO mensal estimado: R$ {tco['total_monthly_cost']:,.2f}.",
        f"Cabe no limite mensal: {'sim' if summary['fits_monthly_budget'] else 'não'}.",
        f"Classificação final: {STATUS_LABELS[status]}.",
    ]
    if summary.get("fits_purchase_budget") and summary.get("fits_monthly_budget"):
        messages.append("O veículo cabe no orçamento de compra e no limite mensal informado.")
    financial_profile = summary.get("financial_capacity_profile")
    if financial_profile in {"comfortable", "high_capacity"} and strategy in {"best_within_budget", "comfort_space"}:
        messages.append("Subiu no ranking porque o perfil financeiro informado permite manter um veículo de categoria superior.")
        messages.append("O limite mensal informado permite considerar veículos de maior segmento disponíveis na base.")
    if financial_profile == "purchase_high_monthly_low":
        messages.append("Apesar do orçamento de compra elevado, o limite mensal informado restringe opções com custo mensal mais alto.")
    if "aplicativo" in str(summary.get("why_recommended", "")):
        if strategy == "lowest_cost":
            messages.append("Priorizado pelo baixo custo mensal, manutenção simples e bom consumo para uso em aplicativo.")
        elif financial_profile in {"comfortable", "high_capacity"}:
            messages.append("Subiu no ranking por equilibrar conforto, confiabilidade e custo mensal compatível para uso profissional.")
    if strategy == "budget_economy" and summary.get("fits_monthly_budget"):
        messages.append("Foi priorizado por equilibrar boa categoria e custo mensal compatível.")
    if vehicle.chronic_issues:
        messages.append("Pontos de atenção: " + "; ".join(vehicle.chronic_issues) + ".")
    messages.extend(penalties)
    return messages


def build_parts_explanations(part_feedback: dict) -> list[str]:
    messages = []
    maintenance_index = part_feedback.get("maintenance_index")
    availability = part_feedback.get("supplier_availability_score")
    shared = part_feedback.get("shared_parts_score")
    variation = part_feedback.get("price_variation_risk")
    if maintenance_index is not None:
        messages.append(f"Índice SIGRA de Manutenção: {maintenance_index}/100.")
    if availability is not None and shared is not None and availability >= 70 and shared >= 65:
        messages.append("Boa disponibilidade de peças, fornecedores variados e compatibilidade com outros modelos.")
    if variation is not None and variation >= 55:
        messages.append("Ponto de atenção: peças com alta variação de preço entre fornecedores. Compare antes de comprar.")
    if shared is not None and shared < 55:
        messages.append("Compatibilidade de peças mais limitada, podendo depender de fornecedores específicos.")
    return messages
