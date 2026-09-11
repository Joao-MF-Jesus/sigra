from decimal import Decimal

from app.financing.calculator import (
    effective_monthly_rate_percent,
    installment_schedule,
    json_decimal,
    maximum_price_principal_for_schedule,
    money,
    percentage,
    price_installment,
)
from app.financing.domain import (
    CALCULATION_METHOD_VERSION,
    CURRENCY,
    DISCLAIMER,
    FINANCING_MODULE_VERSION,
    FinancingCompatibilityStatus,
    FinancingDomainError,
    FinancingStatus,
    MonthlyBudgetStatus,
    near_limit_percentage,
)
from app.financing.schemas import DirectFinancingRequest, ReverseFinancingRequest


def _rate_details(payload) -> tuple[Decimal, dict]:
    monthly_rate = effective_monthly_rate_percent(
        monthly_rate_percent=payload.monthly_interest_rate_percent,
        effective_cost_rate_percent=payload.effective_cost_rate_percent,
        effective_cost_rate_period=payload.effective_cost_rate_period,
    )
    input_mode = "monthly_interest_rate" if payload.monthly_interest_rate_percent is not None else "informed_effective_cost_rate"
    additional_costs_separate = not (
        payload.effective_cost_rate_percent is not None
        and payload.effective_rate_includes_additional_costs is True
    )
    return monthly_rate, {
        "input_mode": input_mode,
        "monthly_interest_rate_percent": json_decimal(percentage(payload.monthly_interest_rate_percent)) if payload.monthly_interest_rate_percent is not None else None,
        "informed_effective_cost_rate_percent": json_decimal(percentage(payload.effective_cost_rate_percent)) if payload.effective_cost_rate_percent is not None else None,
        "informed_effective_cost_rate_period": payload.effective_cost_rate_period.value if payload.effective_cost_rate_period else None,
        "effective_rate_includes_additional_costs": payload.effective_rate_includes_additional_costs,
        "effective_monthly_rate_percent": json_decimal(percentage(monthly_rate)),
        "additional_costs_considered_separately": additional_costs_separate,
        "note": (
            "O CET informado foi usado como taxa efetiva e não foi decomposto em juros, tarifas ou seguros."
            if payload.effective_cost_rate_percent is not None
            else "Taxa mensal informada pelo usuário."
        ),
    }


def _financial_statuses(
    *,
    installment: Decimal,
    total_monthly_outflow: Decimal | None,
    desired_max_installment: Decimal | None,
    available_monthly_budget: Decimal | None,
    zero_financing: bool,
    insufficient_for_financed_costs: bool = False,
) -> dict:
    warnings: list[str] = []
    installment_within_limit = (
        None if desired_max_installment is None else installment <= desired_max_installment
    )
    if insufficient_for_financed_costs:
        installment_within_limit = False
    monthly_outflow_within_budget = (
        None
        if available_monthly_budget is None or total_monthly_outflow is None
        else total_monthly_outflow <= available_monthly_budget
    )
    budget_commitment = (
        None
        if available_monthly_budget in (None, Decimal("0")) or total_monthly_outflow is None
        else (total_monthly_outflow / available_monthly_budget) * Decimal("100")
    )

    if insufficient_for_financed_costs:
        financing_status = FinancingStatus.INSUFFICIENT_FOR_FINANCED_COSTS
    elif zero_financing:
        financing_status = FinancingStatus.ZERO_FINANCING_REQUIRED
    elif installment_within_limit is False:
        financing_status = FinancingStatus.OVER_INSTALLMENT_LIMIT
    elif installment_within_limit is True:
        financing_status = FinancingStatus.WITHIN_INSTALLMENT_LIMIT
    else:
        financing_status = FinancingStatus.FINANCING_REQUIRED

    if monthly_outflow_within_budget is None:
        monthly_budget_status = MonthlyBudgetStatus.INSUFFICIENT_INPUT
    elif monthly_outflow_within_budget is False:
        monthly_budget_status = MonthlyBudgetStatus.OVER_MONTHLY_BUDGET
    elif budget_commitment is not None and budget_commitment >= near_limit_percentage():
        monthly_budget_status = MonthlyBudgetStatus.NEAR_LIMIT
    else:
        monthly_budget_status = MonthlyBudgetStatus.WITHIN_BUDGET

    installment_commitment = (
        None
        if desired_max_installment in (None, Decimal("0"))
        else (installment / desired_max_installment) * Decimal("100")
    )
    installment_near_limit = (
        installment_within_limit is True
        and installment_commitment is not None
        and installment_commitment >= near_limit_percentage()
    )

    if financing_status == FinancingStatus.INSUFFICIENT_FOR_FINANCED_COSTS:
        overall_status = FinancingCompatibilityStatus.INSUFFICIENT_FOR_FINANCED_COSTS
    elif monthly_budget_status == MonthlyBudgetStatus.OVER_MONTHLY_BUDGET:
        overall_status = FinancingCompatibilityStatus.OVER_MONTHLY_BUDGET
    elif financing_status == FinancingStatus.OVER_INSTALLMENT_LIMIT:
        overall_status = FinancingCompatibilityStatus.OVER_INSTALLMENT_LIMIT
    elif monthly_budget_status == MonthlyBudgetStatus.NEAR_LIMIT or installment_near_limit:
        overall_status = FinancingCompatibilityStatus.NEAR_LIMIT
    elif monthly_budget_status == MonthlyBudgetStatus.WITHIN_BUDGET and financing_status in (
        FinancingStatus.WITHIN_INSTALLMENT_LIMIT,
        FinancingStatus.ZERO_FINANCING_REQUIRED,
    ):
        overall_status = FinancingCompatibilityStatus.COMPATIBLE
    elif financing_status == FinancingStatus.ZERO_FINANCING_REQUIRED:
        overall_status = FinancingCompatibilityStatus.ZERO_FINANCING_REQUIRED
    else:
        overall_status = FinancingCompatibilityStatus.INSUFFICIENT_INPUT

    if total_monthly_outflow is None:
        warnings.append(
            "O custo mensal do veículo não foi informado; o desembolso mensal total não foi calculado."
        )
    if desired_max_installment is None:
        warnings.append("A parcela máxima não foi informada.")
    if available_monthly_budget is None:
        warnings.append("O orçamento mensal disponível não foi informado.")
    if installment_within_limit is False and not insufficient_for_financed_costs:
        warnings.append("A maior parcela do cronograma excede o limite informado.")
    if insufficient_for_financed_costs:
        warnings.append(
            "A parcela máxima informada não é suficiente para financiar os custos adicionais desta proposta."
        )
    return {
        "financing_status": financing_status.value,
        "monthly_budget_status": monthly_budget_status.value,
        "overall_status": overall_status.value,
        "installment_within_user_limit": installment_within_limit,
        "monthly_outflow_within_budget": monthly_outflow_within_budget,
        "budget_commitment": budget_commitment,
        "installment_commitment": installment_commitment,
        "warnings": warnings,
    }


def _base_metadata(payload, rate_details: dict) -> dict:
    return {
        "module_version": FINANCING_MODULE_VERSION,
        "calculation_method": payload.amortization_method.value,
        "calculation_method_version": CALCULATION_METHOD_VERSION,
        "currency": CURRENCY,
        "rate": rate_details,
        "disclaimer": DISCLAIMER,
    }


def simulate_direct(payload: DirectFinancingRequest, price_context: dict) -> dict:
    vehicle_price: Decimal = price_context["used_price"]
    if payload.down_payment > vehicle_price:
        raise FinancingDomainError("a entrada não pode ser maior que o preço utilizado")

    monthly_rate, rate_details = _rate_details(payload)
    financed_principal = vehicle_price - payload.down_payment
    financed_additional_costs = (
        payload.financed_fees + payload.financed_insurance + payload.financed_services
    )
    total_financed_amount = financed_principal + financed_additional_costs
    precise_installment = price_installment(total_financed_amount, monthly_rate, payload.term_months)
    schedule = installment_schedule(precise_installment, payload.term_months)
    regular_installment = schedule["regular_installment"]
    maximum_installment_in_schedule = schedule["maximum_installment_in_schedule"]
    total_installments = schedule["total_installments"]
    total_upfront_outflow = payload.down_payment + payload.upfront_fees
    total_acquisition_outflow = total_upfront_outflow + total_installments
    total_financing_addition = total_installments - financed_principal
    interest_estimate = (
        total_installments - total_financed_amount
        if payload.monthly_interest_rate_percent is not None
        else None
    )
    difference_from_cash_price = total_acquisition_outflow - vehicle_price
    total_monthly_outflow = (
        None
        if payload.estimated_monthly_vehicle_cost is None
        else maximum_installment_in_schedule + payload.estimated_monthly_vehicle_cost
    )
    monthly_budget_remaining = (
        None
        if payload.available_monthly_budget is None or total_monthly_outflow is None
        else payload.available_monthly_budget - total_monthly_outflow
    )
    statuses = _financial_statuses(
        installment=maximum_installment_in_schedule,
        total_monthly_outflow=total_monthly_outflow,
        desired_max_installment=payload.desired_max_installment,
        available_monthly_budget=payload.available_monthly_budget,
        zero_financing=total_financed_amount == 0,
    )
    warnings = [*statuses["warnings"], *price_context.get("warnings", [])]

    result = _base_metadata(payload, rate_details)
    result.update(
        {
            "vehicle": price_context.get("vehicle"),
            "price_source": price_context["price_source"],
            "catalog_price": json_decimal(money(price_context.get("catalog_price"))) if price_context.get("catalog_price") is not None else None,
            "manual_price": json_decimal(money(price_context.get("manual_price"))) if price_context.get("manual_price") is not None else None,
            "negotiated_price": json_decimal(money(price_context.get("negotiated_price"))) if price_context.get("negotiated_price") is not None else None,
            "price_used": json_decimal(money(vehicle_price)),
            "catalog_vehicle_price": json_decimal(money(price_context.get("catalog_price"))) if price_context.get("catalog_price") is not None else None,
            "vehicle_price": json_decimal(money(vehicle_price)),
            "down_payment": json_decimal(money(payload.down_payment)),
            "down_payment_percentage": json_decimal(percentage((payload.down_payment / vehicle_price) * Decimal("100"))),
            "financed_principal": json_decimal(money(financed_principal)),
            "financed_vehicle_principal": json_decimal(money(financed_principal)),
            "financed_additional_costs": json_decimal(money(financed_additional_costs)),
            "required_financed_additional_costs": json_decimal(money(financed_additional_costs)),
            "available_vehicle_principal": json_decimal(money(financed_principal)),
            "financed_fees": json_decimal(money(payload.financed_fees)),
            "financed_insurance": json_decimal(money(payload.financed_insurance)),
            "financed_services": json_decimal(money(payload.financed_services)),
            "total_financed_amount": json_decimal(money(total_financed_amount)),
            "term_months": payload.term_months,
            "regular_installment": json_decimal(schedule["regular_installment"]),
            "number_of_regular_installments": schedule["number_of_regular_installments"],
            "final_installment": json_decimal(schedule["final_installment"]),
            "maximum_installment_in_schedule": json_decimal(maximum_installment_in_schedule),
            "rounding_adjustment": json_decimal(schedule["rounding_adjustment"]),
            "estimated_installment": json_decimal(schedule["regular_installment"]),
            "total_installments": json_decimal(total_installments),
            "upfront_fees": json_decimal(money(payload.upfront_fees)),
            "total_upfront_outflow": json_decimal(money(total_upfront_outflow)),
            "upfront_cost": json_decimal(money(total_upfront_outflow)),
            "total_acquisition_outflow": json_decimal(money(total_acquisition_outflow)),
            "interest_estimate": json_decimal(money(interest_estimate)) if interest_estimate is not None else None,
            "total_financing_addition": json_decimal(money(total_financing_addition)),
            "total_interest_and_financed_costs": json_decimal(money(total_financing_addition)),
            "difference_from_cash_price": json_decimal(money(difference_from_cash_price)),
            "additional_costs_considered_separately": rate_details["additional_costs_considered_separately"],
            "has_financed_additional_costs": financed_additional_costs > 0,
            "estimated_monthly_vehicle_cost": json_decimal(money(payload.estimated_monthly_vehicle_cost)) if payload.estimated_monthly_vehicle_cost is not None else None,
            "total_monthly_outflow": json_decimal(money(total_monthly_outflow)) if total_monthly_outflow is not None else None,
            "available_monthly_budget": json_decimal(money(payload.available_monthly_budget)) if payload.available_monthly_budget is not None else None,
            "monthly_budget_remaining": json_decimal(money(monthly_budget_remaining)) if monthly_budget_remaining is not None else None,
            "budget_commitment_percentage": json_decimal(percentage(statuses["budget_commitment"])) if statuses["budget_commitment"] is not None else None,
            "installment_commitment_percentage": json_decimal(percentage(statuses["installment_commitment"])) if statuses["installment_commitment"] is not None else None,
            "desired_max_installment": json_decimal(money(payload.desired_max_installment)) if payload.desired_max_installment is not None else None,
            "financing_status": statuses["financing_status"],
            "monthly_budget_status": statuses["monthly_budget_status"],
            "overall_status": statuses["overall_status"],
            "installment_within_user_limit": statuses["installment_within_user_limit"],
            "monthly_outflow_within_budget": statuses["monthly_outflow_within_budget"],
            "compatibility_status": statuses["overall_status"],
            "offer": {
                "name": payload.offer_name,
                "institution_name": payload.institution_name,
                "reference": payload.offer_reference,
                "date": payload.offer_date.isoformat() if payload.offer_date else None,
                "notes": payload.notes,
            },
            "is_demonstration_data": bool(price_context.get("is_demonstration_data")),
            "deprecated_fields": {
                "vehicle_price": "Use price_used.",
                "catalog_vehicle_price": "Use catalog_price.",
                "financed_principal": "Use financed_vehicle_principal.",
                "estimated_installment": "Use regular_installment.",
                "upfront_cost": "Use total_upfront_outflow.",
                "total_interest_and_financed_costs": "Use total_financing_addition.",
                "compatibility_status": "Use overall_status.",
            },
            "warnings": warnings,
        }
    )
    return result


def simulate_reverse(payload: ReverseFinancingRequest) -> dict:
    monthly_rate, rate_details = _rate_details(payload)
    maximum_financed_amount, capacity_schedule = maximum_price_principal_for_schedule(
        payload.maximum_installment, monthly_rate, payload.term_months
    )
    required_financed_additional_costs = (
        payload.financed_fees + payload.financed_insurance + payload.financed_services
    )
    insufficient_for_financed_costs = (
        required_financed_additional_costs > maximum_financed_amount
    )
    available_vehicle_principal = max(
        maximum_financed_amount - required_financed_additional_costs,
        Decimal("0"),
    )
    maximum_vehicle_price = payload.down_payment + available_vehicle_principal

    if insufficient_for_financed_costs:
        actual_financed_amount = Decimal("0")
        financed_additional_costs = Decimal("0")
        schedule = installment_schedule(Decimal("0"), payload.term_months)
    else:
        actual_financed_amount = maximum_financed_amount
        financed_additional_costs = required_financed_additional_costs
        schedule = capacity_schedule

    maximum_installment_in_schedule = schedule["maximum_installment_in_schedule"]
    total_installments = schedule["total_installments"]
    total_upfront_outflow = payload.down_payment + payload.upfront_fees
    total_acquisition_outflow = total_upfront_outflow + total_installments
    total_financing_addition = total_installments - available_vehicle_principal
    interest_estimate = (
        total_installments - actual_financed_amount
        if payload.monthly_interest_rate_percent is not None
        else None
    )
    total_monthly_outflow = (
        None
        if payload.estimated_monthly_vehicle_cost is None
        else maximum_installment_in_schedule + payload.estimated_monthly_vehicle_cost
    )
    monthly_budget_remaining = (
        None
        if payload.available_monthly_budget is None or total_monthly_outflow is None
        else payload.available_monthly_budget - total_monthly_outflow
    )
    statuses = _financial_statuses(
        installment=maximum_installment_in_schedule,
        total_monthly_outflow=total_monthly_outflow,
        desired_max_installment=money(payload.maximum_installment),
        available_monthly_budget=payload.available_monthly_budget,
        zero_financing=actual_financed_amount == 0,
        insufficient_for_financed_costs=insufficient_for_financed_costs,
    )
    warnings = statuses["warnings"]

    result = _base_metadata(payload, rate_details)
    result.update(
        {
            "vehicle_type": payload.vehicle_type.value,
            "down_payment": json_decimal(money(payload.down_payment)),
            "maximum_financed_amount": json_decimal(money(maximum_financed_amount)),
            "required_financed_additional_costs": json_decimal(money(required_financed_additional_costs)),
            "available_vehicle_principal": json_decimal(money(available_vehicle_principal)),
            "financed_vehicle_principal": json_decimal(money(available_vehicle_principal)),
            "financed_additional_costs": json_decimal(money(financed_additional_costs)),
            "total_financed_amount": json_decimal(money(actual_financed_amount)),
            "maximum_vehicle_price": json_decimal(money(maximum_vehicle_price)),
            "regular_installment": json_decimal(schedule["regular_installment"]),
            "number_of_regular_installments": schedule["number_of_regular_installments"],
            "final_installment": json_decimal(schedule["final_installment"]),
            "maximum_installment_in_schedule": json_decimal(maximum_installment_in_schedule),
            "rounding_adjustment": json_decimal(schedule["rounding_adjustment"]),
            "estimated_installment": json_decimal(schedule["regular_installment"]),
            "term_months": payload.term_months,
            "total_installments": json_decimal(total_installments),
            "estimated_total_installments": json_decimal(total_installments),
            "upfront_fees": json_decimal(money(payload.upfront_fees)),
            "total_upfront_outflow": json_decimal(money(total_upfront_outflow)),
            "estimated_total_acquisition_outflow": json_decimal(money(total_acquisition_outflow)),
            "total_acquisition_outflow": json_decimal(money(total_acquisition_outflow)),
            "interest_estimate": json_decimal(money(interest_estimate)) if interest_estimate is not None else None,
            "total_financing_addition": json_decimal(money(total_financing_addition)),
            "additional_costs_considered_separately": rate_details["additional_costs_considered_separately"],
            "has_financed_additional_costs": financed_additional_costs > 0,
            "estimated_monthly_vehicle_cost": json_decimal(money(payload.estimated_monthly_vehicle_cost)) if payload.estimated_monthly_vehicle_cost is not None else None,
            "total_monthly_outflow": json_decimal(money(total_monthly_outflow)) if total_monthly_outflow is not None else None,
            "available_monthly_budget": json_decimal(money(payload.available_monthly_budget)) if payload.available_monthly_budget is not None else None,
            "monthly_budget_remaining": json_decimal(money(monthly_budget_remaining)) if monthly_budget_remaining is not None else None,
            "budget_commitment_percentage": json_decimal(percentage(statuses["budget_commitment"])) if statuses["budget_commitment"] is not None else None,
            "installment_commitment_percentage": json_decimal(percentage(statuses["installment_commitment"])) if statuses["installment_commitment"] is not None else None,
            "financing_status": statuses["financing_status"],
            "monthly_budget_status": statuses["monthly_budget_status"],
            "overall_status": statuses["overall_status"],
            "installment_within_user_limit": statuses["installment_within_user_limit"],
            "monthly_outflow_within_budget": statuses["monthly_outflow_within_budget"],
            "compatibility_status": statuses["overall_status"],
            "deprecated_fields": {
                "estimated_installment": "Use regular_installment.",
                "estimated_total_installments": "Use total_installments.",
                "compatibility_status": "Use overall_status.",
            },
            "warnings": warnings,
        }
    )
    return result
