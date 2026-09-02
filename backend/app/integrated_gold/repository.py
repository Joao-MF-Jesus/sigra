from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session


class IntegratedGoldStorageError(RuntimeError):
    """Falha sanitizada ao consultar a Gold integrada."""


@dataclass(frozen=True)
class IntegratedGoldFilters:
    brand_name: str | None = None
    model_name: str | None = None
    model_year: int | None = None
    fuel_scenario_code: str | None = None
    vehicle_sk: int | None = None


_ORDER_COLUMNS = {
    "brand_name": "consumption.brand_name",
    "model_name": "consumption.model_name",
    "model_year": "consumption.model_year",
    "vehicle_sk": "consumption.vehicle_sk",
    "mixed_cost_per_km_brl": "consumption.mixed_cost_per_km_brl",
}


class IntegratedGoldRepository:
    """Isola o consumidor dos nomes fisicos e aceita apenas SELECT."""

    def __init__(self, session: Session):
        self._session = session

    def eligible_dataset(self) -> Mapping[str, Any] | None:
        try:
            return self._session.execute(
                text(
                    """SELECT DISTINCT consumption.dataset_version,
                              consumption.fipe_source_dataset_version,
                              consumption.pbev_source_dataset_version,
                              consumption.anp_source_dataset_version,
                              consumption.analytic_cutoff_at,
                              consumption.calculation_policy_version,
                              consumption.geography_policy_version,
                              consumption.scenario_policy_version,
                              consumption.quality_policy_version,
                              consumption.published_vehicle_count,
                              consumption.published_scenario_count,
                              consumption.catalog_coverage_pct,
                              consumption.pbev_coverage_pct,
                              consumption.first_published_at,
                              consumption.last_activated_at
                       FROM gold.integrated_vehicle_cost_consumption_v1 AS consumption
                       ORDER BY consumption.last_activated_at DESC,
                                consumption.dataset_version ASC
                       LIMIT 1"""
                )
            ).mappings().one_or_none()
        except SQLAlchemyError as exc:
            raise IntegratedGoldStorageError(
                "integrated Gold storage is unavailable"
            ) from exc

    def list_costs(
        self,
        dataset_version: str,
        filters: IntegratedGoldFilters,
        *,
        limit: int,
        offset: int,
        sort_by: str,
        sort_direction: str,
    ) -> tuple[list[Mapping[str, Any]], int]:
        order_column = _ORDER_COLUMNS[sort_by]
        direction = "DESC" if sort_direction == "desc" else "ASC"
        clauses = ["consumption.dataset_version=:dataset_version"]
        parameters: dict[str, Any] = {
            "dataset_version": dataset_version,
        }
        for field_name, column in (
            ("brand_name", "consumption.brand_name"),
            ("model_name", "consumption.model_name"),
            ("model_year", "consumption.model_year"),
            ("fuel_scenario_code", "consumption.fuel_scenario_code"),
            ("vehicle_sk", "consumption.vehicle_sk"),
        ):
            value = getattr(filters, field_name)
            if value is not None:
                clauses.append(f"{column}=:{field_name}")
                parameters[field_name] = value
        where_sql = " AND ".join(clauses)
        page_parameters = {
            **parameters,
            "limit": limit,
            "offset": offset,
        }
        statement = text(
            f"""SELECT consumption.dataset_version,
                       consumption.vehicle_sk,
                       consumption.brand_name,
                       consumption.model_name,
                       consumption.version_name,
                       consumption.model_year,
                       consumption.fuel_scenario_code,
                       consumption.requested_geography_level,
                       consumption.requested_geography_key,
                       consumption.anp_week_start,
                       consumption.anp_week_end,
                       consumption.vehicle_price_brl,
                       consumption.city_consumption_km_l,
                       consumption.highway_consumption_km_l,
                       consumption.fuel_price_per_liter_brl,
                       consumption.city_cost_per_km_brl,
                       consumption.highway_cost_per_km_brl,
                       consumption.mixed_cost_per_km_brl,
                       consumption.city_distance_share,
                       consumption.highway_distance_share,
                       consumption.analytical_scenario_code,
                       consumption.analytical_monthly_distance_km,
                       consumption.analytical_annual_distance_km,
                       consumption.analytical_projected_monthly_cost_brl,
                       consumption.analytical_projected_annual_cost_brl,
                       COUNT(*) OVER() AS total_count
                FROM gold.integrated_vehicle_cost_consumption_v1 AS consumption
                WHERE {where_sql}
                ORDER BY {order_column} {direction} NULLS LAST,
                         consumption.brand_name ASC,
                         consumption.model_name ASC,
                         consumption.model_year ASC NULLS LAST,
                         consumption.vehicle_sk ASC,
                         consumption.fuel_scenario_code ASC
                LIMIT :limit OFFSET :offset"""
        )
        count_statement = text(
            f"""SELECT COUNT(*)
                FROM gold.integrated_vehicle_cost_consumption_v1 AS consumption
                WHERE {where_sql}"""
        )
        try:
            rows = list(self._session.execute(statement, page_parameters).mappings())
            total = (
                int(rows[0]["total_count"])
                if rows
                else int(self._session.execute(count_statement, parameters).scalar_one())
            )
        except SQLAlchemyError as exc:
            raise IntegratedGoldStorageError(
                "integrated Gold storage is unavailable"
            ) from exc
        items = []
        for row in rows:
            item = dict(row)
            item.pop("total_count", None)
            items.append(item)
        return items, total
