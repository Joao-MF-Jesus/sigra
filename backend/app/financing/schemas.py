from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator

from app.financing.domain import AmortizationMethod, EffectiveCostRatePeriod, MAX_TERM_MONTHS
from app.vehicle_domain import VehicleType


Money = Annotated[Decimal, Field(max_digits=18, decimal_places=6)]


class FinancingRequestBase(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    vehicle_type: VehicleType
    down_payment: Money = Field(ge=0)
    term_months: int = Field(ge=1, le=MAX_TERM_MONTHS)
    monthly_interest_rate_percent: Money | None = Field(default=None, ge=0, le=100)
    effective_cost_rate_percent: Money | None = Field(default=None, ge=0, le=1000)
    effective_cost_rate_period: EffectiveCostRatePeriod | None = None
    effective_rate_includes_additional_costs: StrictBool | None = None
    upfront_fees: Money = Field(ge=0)
    financed_fees: Money = Field(ge=0)
    financed_insurance: Money = Field(ge=0)
    financed_services: Money = Field(ge=0)
    available_monthly_budget: Money | None = Field(default=None, ge=0)
    estimated_monthly_vehicle_cost: Money | None = Field(default=None, ge=0)
    amortization_method: AmortizationMethod = AmortizationMethod.PRICE
    notes: str | None = Field(default=None, max_length=1000)

    @field_validator(
        "down_payment",
        "monthly_interest_rate_percent",
        "effective_cost_rate_percent",
        "upfront_fees",
        "financed_fees",
        "financed_insurance",
        "financed_services",
        "available_monthly_budget",
        "estimated_monthly_vehicle_cost",
        mode="before",
    )
    @classmethod
    def validate_decimal_input(cls, value):
        if value is None:
            return None
        if isinstance(value, bool):
            raise ValueError("valores booleanos nao sao aceitos em campos numericos")
        try:
            decimal_value = Decimal(str(value))
        except (InvalidOperation, ValueError, TypeError) as error:
            raise ValueError("informe um valor numerico valido") from error
        if not decimal_value.is_finite():
            raise ValueError("o valor deve ser finito")
        return decimal_value

    @field_validator("term_months", mode="before")
    @classmethod
    def validate_term_is_integer(cls, value):
        if isinstance(value, bool):
            raise ValueError("o prazo deve ser um numero inteiro")
        if isinstance(value, float) and not value.is_integer():
            raise ValueError("o prazo deve ser um numero inteiro")
        return value

    @model_validator(mode="after")
    def validate_rate_contract(self):
        has_monthly_rate = self.monthly_interest_rate_percent is not None
        has_effective_rate = self.effective_cost_rate_percent is not None
        if has_monthly_rate == has_effective_rate:
            raise ValueError("informe exatamente uma taxa: mensal ou CET")
        if has_effective_rate:
            if self.effective_cost_rate_period is None:
                raise ValueError("effective_cost_rate_period e obrigatorio no modo CET")
            if self.effective_rate_includes_additional_costs is None:
                raise ValueError(
                    "effective_rate_includes_additional_costs e obrigatorio no modo CET"
                )
        elif self.effective_cost_rate_period is not None or self.effective_rate_includes_additional_costs is not None:
            raise ValueError("campos de CET nao podem ser enviados junto com a taxa mensal")
        if has_effective_rate and self.effective_rate_includes_additional_costs is True:
            financed_costs = self.financed_fees + self.financed_insurance + self.financed_services
            if financed_costs > 0:
                raise ValueError(
                    "os custos adicionais ja estao representados pelo CET informado; "
                    "nao envie tarifas, seguro ou servicos financiados separadamente"
                )
        return self


class DirectFinancingRequest(FinancingRequestBase):
    vehicle_id: int | None = Field(default=None, ge=1)
    vehicle_price: Money | None = Field(default=None, gt=0)
    negotiated_price: Money | None = Field(default=None, gt=0)
    desired_max_installment: Money | None = Field(default=None, ge=0)
    offer_name: str | None = Field(default=None, min_length=1, max_length=120)
    institution_name: str | None = Field(default=None, min_length=1, max_length=160)
    offer_reference: str | None = Field(default=None, min_length=1, max_length=240)
    offer_date: date | None = None

    @field_validator("vehicle_price", "negotiated_price", "desired_max_installment", mode="before")
    @classmethod
    def validate_direct_decimal_input(cls, value):
        return FinancingRequestBase.validate_decimal_input(value)

    @model_validator(mode="after")
    def validate_price_contract(self):
        if self.vehicle_id is None:
            if self.vehicle_price is None:
                raise ValueError("informe vehicle_id ou vehicle_price no modo manual")
            if self.negotiated_price is not None:
                raise ValueError(
                    "negotiated_price exige vehicle_id; no modo manual envie apenas vehicle_price"
                )
        elif self.vehicle_price is not None:
            raise ValueError(
                "vehicle_price e exclusivo do modo manual; use negotiated_price para substituir o catalogo"
            )
        known_price = self.negotiated_price or self.vehicle_price
        if known_price is not None and self.down_payment > known_price:
            raise ValueError("a entrada nao pode ser maior que o preco utilizado")
        return self


class ReverseFinancingRequest(FinancingRequestBase):
    maximum_installment: Money = Field(ge=0)

    @field_validator("maximum_installment", mode="before")
    @classmethod
    def validate_maximum_installment(cls, value):
        return FinancingRequestBase.validate_decimal_input(value)


class FinancingComparisonRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    scenarios: list[DirectFinancingRequest] = Field(min_length=2, max_length=10)
