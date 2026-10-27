"""Optional recommendation linkage, always anchored in the eligible Gold view."""
from typing import Any, Mapping

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.integrated_gold.repository import IntegratedGoldStorageError


class GoldRecommendationIdentityReader:
    def __init__(self, session: Session):
        self._session = session

    def recommendation_identities(self) -> list[Mapping[str, Any]]:
        """Canonical FIPE keys through the exact lineage of eligible publications.

        DISTINCT collapses fuel/geography scenarios, not different FIPE records.
        No catalog ID is equated with a warehouse surrogate key.
        """
        try:
            return list(self._session.execute(text(
                """SELECT DISTINCT consumption.dataset_version,
                          feature.dataset_version AS fipe_dataset_version,
                          feature.gold_record_id, feature.vehicle_sk,
                          feature.fipe_code, feature.year_code,
                          feature.brand_name, feature.model_name, feature.version_name,
                          feature.model_year, feature.fuel_type,
                          feature.transmission_type, feature.source_vehicle_key
                   FROM gold.integrated_vehicle_cost_consumption_v1 AS consumption
                   JOIN gold.integrated_vehicle_cost_snapshot AS snapshot
                     ON snapshot.dataset_version=consumption.dataset_version
                    AND snapshot.vehicle_sk=consumption.vehicle_sk
                    AND snapshot.fuel_scenario_code=consumption.fuel_scenario_code
                    AND snapshot.requested_geography_level=consumption.requested_geography_level
                    AND snapshot.requested_geography_key=consumption.requested_geography_key
                    AND snapshot.anp_week_start=consumption.anp_week_start
                   JOIN gold.vehicle_features_snapshot AS feature
                     ON feature.gold_record_id=snapshot.fipe_gold_record_id
                    AND feature.dataset_version=consumption.fipe_source_dataset_version
                    AND feature.vehicle_sk=consumption.vehicle_sk
                   ORDER BY consumption.dataset_version, feature.vehicle_sk,
                            feature.gold_record_id"""
            )).mappings())
        except SQLAlchemyError as exc:
            raise IntegratedGoldStorageError("integrated Gold identity storage is unavailable") from exc
