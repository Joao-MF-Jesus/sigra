from decimal import Decimal

from app.financing.calculator import money
from app.financing.domain import DISCLAIMER, FINANCING_MODULE_VERSION


COMPARISON_CRITERIA = (
    ("lowest_installment", "maximum_installment_in_schedule", "minimum", "currency_monthly"),
    ("lowest_total_acquisition_outflow", "total_acquisition_outflow", "minimum", "currency"),
    ("lowest_total_financing_addition", "total_financing_addition", "minimum", "currency"),
    ("lowest_total_installments", "total_installments", "minimum", "currency"),
    ("shortest_term", "term_months", "minimum", "months"),
    ("lowest_budget_commitment", "budget_commitment_percentage", "minimum", "percentage"),
    ("highest_down_payment", "down_payment", "maximum", "currency"),
)
FINANCIAL_CONTEXT_CRITERIA = {"lowest_budget_commitment"}


def _decimal(value) -> Decimal:
    return Decimal(str(value))


def _json_number(value: Decimal, unit: str):
    if unit == "months":
        return int(value)
    return float(value.quantize(Decimal("0.01")))


def _criterion_detail(
    results: list[dict], field: str, direction: str, unit: str
) -> dict:
    available = [
        (item["scenario_name"], _decimal(item[field]))
        for item in results
        if item.get(field) is not None
    ]
    if not available:
        return {
            "scenario_names": [],
            "value": None,
            "difference_to_next": None,
            "unit": unit,
            "is_tie": False,
        }

    values = [value for _, value in available]
    winner_value = min(values) if direction == "minimum" else max(values)
    winner_names = [name for name, value in available if value == winner_value]
    distinct_values = sorted(set(values), reverse=direction == "maximum")
    next_value = distinct_values[1] if len(distinct_values) > 1 else None
    difference = abs(next_value - winner_value) if next_value is not None else None
    return {
        "scenario_names": winner_names,
        "value": _json_number(winner_value, unit),
        "difference_to_next": (
            _json_number(difference, unit) if difference is not None else None
        ),
        "unit": unit,
        "is_tie": len(winner_names) > 1,
    }


def _basis_equality(results: list[dict], field: str) -> bool | None:
    values = []
    for item in results:
        value = item.get(field)
        if value is None:
            return None
        values.append(money(_decimal(value)))
    return len(set(values)) == 1


def _financial_context(results: list[dict]) -> dict:
    same_budget = _basis_equality(results, "available_monthly_budget")
    same_vehicle_cost = _basis_equality(results, "estimated_monthly_vehicle_cost")
    all_commitments_available = all(
        item.get("budget_commitment_percentage") is not None for item in results
    )

    if same_budget is None and same_vehicle_cost is None:
        status = "insufficient_financial_context"
    elif same_budget is None:
        status = "insufficient_budget_data"
    elif same_vehicle_cost is None:
        status = "insufficient_vehicle_cost_data"
    elif same_budget is False and same_vehicle_cost is False:
        status = "different_budget_and_vehicle_cost"
    elif same_budget is False:
        status = "different_monthly_budgets"
    elif same_vehicle_cost is False:
        status = "different_vehicle_cost_bases"
    elif not all_commitments_available:
        status = "insufficient_financial_context"
    else:
        status = "comparable"

    return {
        "same_monthly_budget_basis": same_budget,
        "same_vehicle_cost_basis": same_vehicle_cost,
        "financial_context_comparable": status == "comparable",
        "monthly_commitment_comparison_status": status,
    }


def _financial_context_warning(status: str) -> str | None:
    return {
        "different_monthly_budgets": (
            "Os cenários utilizam orçamentos mensais diferentes. O percentual de "
            "comprometimento não representa apenas a condição do financiamento."
        ),
        "different_vehicle_cost_bases": (
            "Os cenários utilizam estimativas diferentes de custo mensal do veículo. "
            "O desembolso total não representa apenas o financiamento."
        ),
        "different_budget_and_vehicle_cost": (
            "Os cenários utilizam orçamentos mensais e custos de uso diferentes. "
            "O comprometimento mensal deve ser analisado individualmente."
        ),
        "insufficient_budget_data": (
            "Pelo menos um cenário não informa orçamento mensal. O comprometimento "
            "mensal não pode ser comparado."
        ),
        "insufficient_vehicle_cost_data": (
            "Pelo menos um cenário não informa o custo mensal estimado do veículo. "
            "O comprometimento mensal não pode ser comparado."
        ),
        "insufficient_financial_context": (
            "Os dados mensais são insuficientes para comparar o comprometimento "
            "entre os cenários."
        ),
    }.get(status)


def _comparison_scope(results: list[dict]) -> dict:
    vehicle_keys = []
    for item in results:
        vehicle = item.get("vehicle") or {}
        vehicle_id = vehicle.get("id")
        vehicle_type = vehicle.get("vehicle_type")
        vehicle_keys.append(
            (vehicle_type, vehicle_id)
            if vehicle_id is not None and vehicle_type is not None
            else None
        )

    known_vehicles = [key for key in vehicle_keys if key is not None]
    same_vehicle = (
        len(known_vehicles) == len(results) and len(set(known_vehicles)) == 1
    )
    price_sources = {item.get("price_source") for item in results}
    price_values = [
        money(_decimal(item["price_used"]))
        for item in results
        if item.get("price_used") is not None
    ]
    same_price_basis = (
        len(price_sources) == 1
        and len(price_values) == len(results)
        and len(set(price_values)) == 1
    )

    if same_vehicle and same_price_basis:
        scope = "same_vehicle_same_price"
    elif same_vehicle:
        scope = "same_vehicle_different_price"
    elif "manual" in price_sources and any(
        source in {"catalog", "negotiated"} for source in price_sources
    ):
        scope = "mixed_manual_and_catalog"
    elif len(known_vehicles) == len(results) and len(set(known_vehicles)) > 1:
        scope = "different_vehicles"
    else:
        scope = "different_acquisition_scenarios"

    return {
        "same_vehicle": same_vehicle,
        "same_price_basis": same_price_basis,
        "comparison_scope": scope,
    }


def compare_results(results: list[dict]) -> dict:
    first = results[0]
    differences = []
    for result in results[1:]:
        installment = result["maximum_installment_in_schedule"]
        first_installment = first["maximum_installment_in_schedule"]
        financing_addition_difference = round(
            result["total_financing_addition"]
            - first["total_financing_addition"],
            2,
        )
        differences.append(
            {
                "from": first["scenario_name"],
                "to": result["scenario_name"],
                "installment_difference": round(installment - first_installment, 2),
                "total_acquisition_outflow_difference": round(
                    result["total_acquisition_outflow"]
                    - first["total_acquisition_outflow"],
                    2,
                ),
                "total_financing_addition_difference": financing_addition_difference,
                "interest_and_costs_difference": financing_addition_difference,
            }
        )

    scope = _comparison_scope(results)
    financial_context = _financial_context(results)
    highlight_details = {}
    suppressed_highlights = []
    for key, field, direction, unit in COMPARISON_CRITERIA:
        if (
            key in FINANCIAL_CONTEXT_CRITERIA
            and not financial_context["financial_context_comparable"]
        ):
            suppressed_highlights.append(
                {
                    "criterion": key,
                    "reason": financial_context[
                        "monthly_commitment_comparison_status"
                    ],
                }
            )
            continue
        highlight_details[key] = _criterion_detail(
            results, field, direction, unit
        )

    highlights = {
        key: detail["scenario_names"]
        for key, detail in highlight_details.items()
    }
    warnings = [
        "Os destaques indicam critérios isolados e não elegem automaticamente uma melhor proposta."
    ]
    if scope["comparison_scope"] != "same_vehicle_same_price":
        warnings.append(
            "Os cenários utilizam veículos ou bases de preço diferentes. "
            "Os destaques refletem a aquisição completa, não apenas as condições financeiras."
        )
    context_warning = _financial_context_warning(
        financial_context["monthly_commitment_comparison_status"]
    )
    if context_warning:
        warnings.append(context_warning)

    comparison_context = {**scope, **financial_context}
    return {
        "module_version": FINANCING_MODULE_VERSION,
        "comparison_type": "criteria_labels",
        "scenario_count": len(results),
        "scenarios": results,
        **scope,
        **financial_context,
        "comparison_context": comparison_context,
        "highlights": highlights,
        "highlight_details": highlight_details,
        "suppressed_highlights": suppressed_highlights,
        "legacy_highlights": {
            "lowest_interest_and_financed_costs": highlights[
                "lowest_total_financing_addition"
            ]
        },
        "deprecated_fields": {
            "legacy_highlights.lowest_interest_and_financed_costs": (
                "Use highlights.lowest_total_financing_addition. Remoção planejada para 2.0.0."
            ),
            "differences_from_first_scenario.interest_and_costs_difference": (
                "Use total_financing_addition_difference. Remoção planejada para 2.0.0."
            ),
        },
        "differences_from_first_scenario": differences,
        "warnings": warnings,
        "disclaimer": DISCLAIMER,
    }
