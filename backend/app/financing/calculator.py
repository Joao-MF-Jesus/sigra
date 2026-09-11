from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP, localcontext

from app.financing.domain import EffectiveCostRatePeriod, FinancingDomainError


CENT = Decimal("0.01")
PERCENT = Decimal("0.01")
HUNDRED = Decimal("100")
TWELVE = Decimal("12")


def money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def percentage(value: Decimal) -> Decimal:
    return value.quantize(PERCENT, rounding=ROUND_HALF_UP)


def effective_monthly_rate_percent(
    *,
    monthly_rate_percent: Decimal | None,
    effective_cost_rate_percent: Decimal | None,
    effective_cost_rate_period: EffectiveCostRatePeriod | None,
) -> Decimal:
    if monthly_rate_percent is not None:
        return monthly_rate_percent
    if effective_cost_rate_percent is None or effective_cost_rate_period is None:
        raise FinancingDomainError("a taxa da simulação não foi informada")
    if effective_cost_rate_period == EffectiveCostRatePeriod.MONTHLY:
        return effective_cost_rate_percent
    with localcontext() as context:
        context.prec = 50
        annual_factor = Decimal("1") + (effective_cost_rate_percent / HUNDRED)
        return (((annual_factor.ln() / TWELVE).exp()) - Decimal("1")) * HUNDRED


def price_installment(principal: Decimal, monthly_rate_percent: Decimal, term_months: int) -> Decimal:
    if principal < 0:
        raise FinancingDomainError("o valor financiado não pode ser negativo")
    if term_months < 1:
        raise FinancingDomainError("o prazo deve ser de pelo menos um mes")
    if principal == 0:
        return Decimal("0")
    monthly_rate = monthly_rate_percent / HUNDRED
    if monthly_rate == 0:
        return principal / Decimal(term_months)
    with localcontext() as context:
        context.prec = 50
        factor = (Decimal("1") + monthly_rate) ** term_months
        return principal * ((monthly_rate * factor) / (factor - Decimal("1")))


def installment_schedule(precise_installment: Decimal, term_months: int) -> dict[str, Decimal | int]:
    """Reconcile displayed installments with the precise aggregate total."""
    if precise_installment < 0:
        raise FinancingDomainError("a parcela não pode ser negativa")
    if term_months < 1:
        raise FinancingDomainError("o prazo deve ser de pelo menos um mes")

    total = money(precise_installment * Decimal(term_months))
    regular = money(precise_installment)
    regular_count = term_months - 1
    final = money(total - (regular * Decimal(regular_count)))

    # Very small principals over long terms can make half-up rounding consume
    # more than the aggregate total. Use a cent floor only for this edge case.
    if final < 0:
        regular = (total / Decimal(term_months)).quantize(CENT, rounding=ROUND_DOWN)
        final = money(total - (regular * Decimal(regular_count)))
    if final < 0:
        raise FinancingDomainError("não foi possível reconciliar as parcelas")

    return {
        "regular_installment": regular,
        "number_of_regular_installments": regular_count,
        "final_installment": final,
        "maximum_installment_in_schedule": max(regular, final),
        "total_installments": total,
        "rounding_adjustment": money(final - regular),
    }


def maximum_price_principal(
    maximum_installment: Decimal,
    monthly_rate_percent: Decimal,
    term_months: int,
) -> Decimal:
    if maximum_installment <= 0:
        return Decimal("0")
    monthly_rate = monthly_rate_percent / HUNDRED
    if monthly_rate == 0:
        return maximum_installment * Decimal(term_months)
    with localcontext() as context:
        context.prec = 50
        factor = (Decimal("1") + monthly_rate) ** term_months
        payment_factor = (monthly_rate * factor) / (factor - Decimal("1"))
        return maximum_installment / payment_factor


def maximum_price_principal_for_schedule(
    maximum_installment: Decimal,
    monthly_rate_percent: Decimal,
    term_months: int,
) -> tuple[Decimal, dict[str, Decimal | int]]:
    """Return the largest cent-valued principal whose displayed schedule fits the limit."""
    limit = money(maximum_installment)
    if limit <= 0:
        return Decimal("0.00"), installment_schedule(Decimal("0"), term_months)

    theoretical = maximum_price_principal(
        maximum_installment, monthly_rate_percent, term_months
    )
    upper_cents = int((theoretical / CENT).to_integral_value(rounding=ROUND_DOWN))
    lower_cents = 0
    best_principal = Decimal("0.00")
    best_schedule = installment_schedule(Decimal("0"), term_months)

    while lower_cents <= upper_cents:
        middle_cents = (lower_cents + upper_cents) // 2
        candidate = Decimal(middle_cents) * CENT
        schedule = installment_schedule(
            price_installment(candidate, monthly_rate_percent, term_months),
            term_months,
        )
        if schedule["maximum_installment_in_schedule"] <= limit:
            best_principal = candidate
            best_schedule = schedule
            lower_cents = middle_cents + 1
        else:
            upper_cents = middle_cents - 1

    return best_principal, best_schedule


def json_decimal(value: Decimal | None) -> float | None:
    if value is None:
        return None
    return float(value)
