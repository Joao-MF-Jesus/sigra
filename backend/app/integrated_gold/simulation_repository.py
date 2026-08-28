from __future__ import annotations

from typing import Any, Mapping

from sqlalchemy import bindparam, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from data_platform.contracts.integrated_vehicle_cost import FuelScenarioCode
from data_platform.integrated_vehicle_cost.simulation_contracts import (
    PublishedVehicleExclusion,
    SimulationSourceVersions,
    VehicleCostEvidence,
)


class VehicleCostSimulationStorageError(RuntimeError):
    """Falha sanitizada ao ler evidencias Gold da simulacao."""


class VehicleCostSimulationRepository:
    """Le somente a Gold publicada; nao executa mutacoes ou pipelines."""

    def __init__(self, session: Session):
        self._session = session

    def eligible_dataset(self) -> Mapping[str, Any] | None:
        try:
            return self._session.execute(
                text(
                    """SELECT DISTINCT consumption.dataset_version,
                              consumption.fipe_source_dataset_version,
                              consumption.pbev_source_dataset_version,
                              consumption.anp_source_dataset_version
                       FROM gold.integrated_vehicle_cost_consumption_v1 AS consumption
                       ORDER BY consumption.dataset_version ASC
                       LIMIT 1"""
                )
            ).mappings().one_or_none()
        except SQLAlchemyError as exc:
            raise VehicleCostSimulationStorageError(
                "vehicle cost simulation storage is unavailable"
            ) from exc

    def evidence_rows(
        self,
        dataset_version: str,
        vehicle_sks: tuple[int, ...] | None,
    ) -> tuple[VehicleCostEvidence, ...]:
        clauses = ["consumption.dataset_version=:dataset_version"]
        parameters: dict[str, object] = {"dataset_version": dataset_version}
        statement = """SELECT consumption.dataset_version,
                              consumption.fipe_source_dataset_version,
                              consumption.pbev_source_dataset_version,
                              consumption.anp_source_dataset_version,
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
                              consumption.city_consumption_km_l,
                              consumption.highway_consumption_km_l,
                              consumption.fuel_price_per_liter_brl,
                              consumption.analytical_scenario_code,
                              consumption.analytical_monthly_distance_km,
                              consumption.analytical_annual_distance_km,
                              consumption.analytical_projected_monthly_cost_brl,
                              consumption.analytical_projected_annual_cost_brl
                       FROM gold.integrated_vehicle_cost_consumption_v1 AS consumption"""
        if vehicle_sks is not None:
            clauses.append("consumption.vehicle_sk IN :vehicle_sks")
            parameters["vehicle_sks"] = vehicle_sks
        query = text(
            f"{statement} WHERE {' AND '.join(clauses)} "
            "ORDER BY consumption.vehicle_sk,consumption.fuel_scenario_code,"
            "consumption.requested_geography_level,"
            "consumption.requested_geography_key,consumption.anp_week_start"
        )
        if vehicle_sks is not None:
            query = query.bindparams(bindparam("vehicle_sks", expanding=True))
        try:
            rows = self._session.execute(query, parameters).mappings().all()
            return tuple(self._evidence(row) for row in rows)
        except (SQLAlchemyError, TypeError, ValueError) as exc:
            raise VehicleCostSimulationStorageError(
                "vehicle cost simulation storage is unavailable"
            ) from exc

    def published_exclusions(
        self,
        dataset_version: str,
        vehicle_sks: tuple[int, ...] | None,
    ) -> tuple[PublishedVehicleExclusion, ...]:
        clauses = [
            "exclusion.dataset_version=:dataset_version",
            "exclusion.exclusion_scope='vehicle'",
        ]
        parameters: dict[str, object] = {"dataset_version": dataset_version}
        statement = """SELECT exclusion.vehicle_sk,exclusion.reason_code
                       FROM gold.integrated_vehicle_cost_exclusion AS exclusion"""
        if vehicle_sks is not None:
            clauses.append("exclusion.vehicle_sk IN :vehicle_sks")
            parameters["vehicle_sks"] = vehicle_sks
        query = text(
            f"{statement} WHERE {' AND '.join(clauses)} "
            "ORDER BY exclusion.vehicle_sk,exclusion.reason_code"
        )
        if vehicle_sks is not None:
            query = query.bindparams(bindparam("vehicle_sks", expanding=True))
        try:
            rows = self._session.execute(query, parameters).mappings().all()
            return tuple(
                PublishedVehicleExclusion(
                    vehicle_sk=int(row["vehicle_sk"]),
                    reason_code=str(row["reason_code"]),
                )
                for row in rows
            )
        except (SQLAlchemyError, TypeError, ValueError) as exc:
            raise VehicleCostSimulationStorageError(
                "vehicle cost simulation storage is unavailable"
            ) from exc

    @staticmethod
    def _evidence(row: Mapping[str, Any]) -> VehicleCostEvidence:
        return VehicleCostEvidence(
            sources=SimulationSourceVersions(
                integrated_dataset_version=str(row["dataset_version"]),
                fipe_dataset_version=str(row["fipe_source_dataset_version"]),
                pbev_dataset_version=str(row["pbev_source_dataset_version"]),
                anp_dataset_version=str(row["anp_source_dataset_version"]),
            ),
            vehicle_sk=int(row["vehicle_sk"]),
            brand_name=str(row["brand_name"]),
            model_name=str(row["model_name"]),
            version_name=(
                str(row["version_name"])
                if row["version_name"] is not None
                else None
            ),
            model_year=(int(row["model_year"]) if row["model_year"] is not None else None),
            fuel_code=FuelScenarioCode(str(row["fuel_scenario_code"])),
            requested_geography_level=str(row["requested_geography_level"]),
            requested_geography_key=str(row["requested_geography_key"]),
            anp_week_start=row["anp_week_start"],
            anp_week_end=row["anp_week_end"],
            city_consumption_km_l=row["city_consumption_km_l"],
            highway_consumption_km_l=row["highway_consumption_km_l"],
            fuel_price_per_liter_brl=row["fuel_price_per_liter_brl"],
            analytical_scenario_code=str(row["analytical_scenario_code"]),
            analytical_monthly_distance_km=row[
                "analytical_monthly_distance_km"
            ],
            analytical_annual_distance_km=row[
                "analytical_annual_distance_km"
            ],
            analytical_projected_monthly_cost_brl=row[
                "analytical_projected_monthly_cost_brl"
            ],
            analytical_projected_annual_cost_brl=row[
                "analytical_projected_annual_cost_brl"
            ],
        )
