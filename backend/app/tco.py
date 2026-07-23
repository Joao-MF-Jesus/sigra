import math
from numbers import Real


IPVA_RATE = 0.04
INSURANCE_RATE = 0.05


class TCOValidationError(ValueError):
    """Indica que o TCO nao pode ser calculado com seguranca."""


def _required_number(name: str, value: float, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(float(value)):
        raise TCOValidationError(f"{name} deve ser um numero finito")
    number = float(value)
    if positive and number <= 0:
        raise TCOValidationError(f"{name} deve ser maior que zero")
    if not positive and number < 0:
        raise TCOValidationError(f"{name} nao pode ser negativo")
    return number


def calculate_tco(
    vehicle_price: float,
    fuel_efficiency_km_l: float,
    monthly_mileage: float,
    fuel_price: float,
    annual_maintenance_cost: float,
    annual_depreciation_rate: float,
    ipva_rate: float = IPVA_RATE,
    insurance_rate: float = INSURANCE_RATE,
) -> dict[str, float]:
    """Calcula o custo total mensal estimado de propriedade do veiculo.

    O TCO e uma estimativa academica: combustivel, manutencao, IPVA, seguro
    e depreciacao rateados por mes. Os percentuais fixos tornam o criterio
    simples de explicar e facil de substituir por dados reais no futuro.
    """
    vehicle_price = _required_number("vehicle_price", vehicle_price, positive=True)
    fuel_efficiency_km_l = _required_number("fuel_efficiency_km_l", fuel_efficiency_km_l, positive=True)
    monthly_mileage = _required_number("monthly_mileage", monthly_mileage)
    fuel_price = _required_number("fuel_price", fuel_price, positive=True)
    annual_maintenance_cost = _required_number("annual_maintenance_cost", annual_maintenance_cost)
    annual_depreciation_rate = _required_number("annual_depreciation_rate", annual_depreciation_rate)
    ipva_rate = _required_number("ipva_rate", ipva_rate)
    insurance_rate = _required_number("insurance_rate", insurance_rate)

    monthly_fuel_cost = (monthly_mileage / fuel_efficiency_km_l) * fuel_price
    monthly_maintenance_cost = annual_maintenance_cost / 12
    monthly_ipva_cost = (vehicle_price * ipva_rate) / 12
    monthly_insurance_cost = (vehicle_price * insurance_rate) / 12
    monthly_depreciation_cost = (vehicle_price * (annual_depreciation_rate / 100)) / 12
    total_monthly_cost = (
        monthly_fuel_cost
        + monthly_maintenance_cost
        + monthly_ipva_cost
        + monthly_insurance_cost
        + monthly_depreciation_cost
    )
    return {
        "monthly_fuel_cost": round(monthly_fuel_cost, 2),
        "monthly_maintenance_cost": round(monthly_maintenance_cost, 2),
        "monthly_ipva_cost": round(monthly_ipva_cost, 2),
        "monthly_insurance_cost": round(monthly_insurance_cost, 2),
        "monthly_depreciation_cost": round(monthly_depreciation_cost, 2),
        "total_monthly_cost": round(total_monthly_cost, 2),
    }
