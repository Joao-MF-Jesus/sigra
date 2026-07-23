import os
from decimal import Decimal, InvalidOperation
from enum import Enum


FINANCING_MODULE_VERSION = "1.0.3"
CALCULATION_METHOD_VERSION = "price-v1.2"
CURRENCY = "BRL"
MAX_TERM_MONTHS = 120
DISCLAIMER = (
    "Simulacao estimada. Nao representa proposta ou aprovacao de credito."
)


class AmortizationMethod(str, Enum):
    PRICE = "price"


class EffectiveCostRatePeriod(str, Enum):
    MONTHLY = "monthly"
    ANNUAL = "annual"


class FinancingCompatibilityStatus(str, Enum):
    COMPATIBLE = "compatible"
    NEAR_LIMIT = "near_limit"
    OVER_INSTALLMENT_LIMIT = "over_installment_limit"
    OVER_MONTHLY_BUDGET = "over_monthly_budget"
    INSUFFICIENT_INPUT = "insufficient_input"
    ZERO_FINANCING_REQUIRED = "zero_financing_required"
    INSUFFICIENT_FOR_FINANCED_COSTS = "insufficient_for_financed_costs"


class FinancingStatus(str, Enum):
    FINANCING_REQUIRED = "financing_required"
    ZERO_FINANCING_REQUIRED = "zero_financing_required"
    OVER_INSTALLMENT_LIMIT = "over_installment_limit"
    WITHIN_INSTALLMENT_LIMIT = "within_installment_limit"
    INSUFFICIENT_FOR_FINANCED_COSTS = "insufficient_for_financed_costs"


class MonthlyBudgetStatus(str, Enum):
    WITHIN_BUDGET = "within_budget"
    NEAR_LIMIT = "near_limit"
    OVER_MONTHLY_BUDGET = "over_monthly_budget"
    INSUFFICIENT_INPUT = "insufficient_input"


class FinancingDomainError(ValueError):
    """Controlled domain validation error exposed as HTTP 422 by the router."""


def near_limit_percentage() -> Decimal:
    raw_value = os.getenv("FINANCING_NEAR_LIMIT_PERCENTAGE", "85")
    try:
        value = Decimal(raw_value)
    except InvalidOperation as error:
        raise RuntimeError("FINANCING_NEAR_LIMIT_PERCENTAGE deve ser numerico") from error
    if not value.is_finite() or value <= 0 or value > 100:
        raise RuntimeError("FINANCING_NEAR_LIMIT_PERCENTAGE deve estar entre 0 e 100")
    return value
