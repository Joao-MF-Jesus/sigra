from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from decimal import Decimal
import json
from typing import Iterator, Mapping, Sequence
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

from data_platform.common.logging import sanitize
from data_platform.contracts.integrated_vehicle_cost import (
    DEFAULT_DISTANCE_SCENARIO,
    INTEGRATED_QUALITY_POLICY_VERSION,
    MIXED_1000_V1,
    FuelScenarioCode,
)
from data_platform.integrated_vehicle_cost.pipeline import (
    CALCULATION_POLICY_VERSION,
    GEOGRAPHY_POLICY_VERSION,
    PIPELINE_NAME,
    PIPELINE_VERSION,
    SCENARIO_POLICY_VERSION,
    ActiveGoldSources,
    GoldFuelPriceInput,
    GoldVehicleInput,
    IntegratedMaterializationPlan,
    IntegratedPublicationError,
    IntegratedPublicationRequest,
    canonical_hash,
)


ADVISORY_LOCK_NAME = "gold.integrated_vehicle_cost_publication"


def _json(value: object) -> str:
    def default(item: object) -> str:
        if isinstance(item, (datetime, Decimal)):
            return str(item) if isinstance(item, Decimal) else item.isoformat()
        if hasattr(item, "isoformat"):
            return item.isoformat()  # type: ignore[no-any-return,union-attr]
        if hasattr(item, "value"):
            return str(item.value)  # type: ignore[union-attr]
        raise TypeError(f"unsupported JSON type: {type(item).__name__}")

    return json.dumps(
        value,
        default=default,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )


class IntegratedVehicleCostLoader:
    def __init__(self, engine: Engine):
        self.engine = engine

    @property
    def is_postgresql(self) -> bool:
        return self.engine.dialect.name == "postgresql"

    @contextmanager
    def publication_transaction(self) -> Iterator[Connection]:
        if not self.is_postgresql:
            raise ValueError("integrated persistence requires PostgreSQL")
        connection = self.engine.connect().execution_options(
            isolation_level="REPEATABLE READ"
        )
        transaction = connection.begin()
        try:
            connection.execute(
                text("SELECT pg_advisory_xact_lock(hashtext(:name)::bigint)"),
                {"name": ADVISORY_LOCK_NAME},
            )
            yield connection
            transaction.commit()
        except BaseException:
            transaction.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def transaction_timestamp(connection: Connection) -> datetime:
        return connection.execute(text("SELECT CURRENT_TIMESTAMP")).scalar_one()

    @staticmethod
    def lifecycle_timestamp(
        connection: Connection,
        *,
        dataset_version: str,
        previous_dataset_version: str | None = None,
    ) -> datetime:
        return connection.execute(
            text(
                """SELECT GREATEST(
                    clock_timestamp(),
                    target.created_at,
                    COALESCE(target.last_activated_at,target.created_at),
                    COALESCE(previous.last_activated_at,target.created_at)
                )
                FROM gold.integrated_vehicle_cost_dataset AS target
                LEFT JOIN gold.integrated_vehicle_cost_dataset AS previous
                  ON previous.dataset_version=:previous
                WHERE target.dataset_version=:dataset"""
            ),
            {
                "dataset": dataset_version,
                "previous": previous_dataset_version,
            },
        ).scalar_one()

    @staticmethod
    def load_active_sources(connection: Connection) -> ActiveGoldSources:
        rows = connection.execute(
            text(
                """SELECT
                    fipe.dataset_version AS fipe_dataset_version,
                    fipe.dataset_fingerprint AS fipe_fingerprint,
                    pbev.dataset_version AS pbev_dataset_version,
                    pbev.dataset_fingerprint AS pbev_fingerprint,
                    anp.dataset_version AS anp_dataset_version,
                    anp.dataset_fingerprint AS anp_fingerprint
                FROM gold.vehicle_feature_dataset AS fipe
                CROSS JOIN gold.vehicle_efficiency_dataset AS pbev
                CROSS JOIN gold.anp_fuel_price_dataset AS anp
                WHERE fipe.is_active AND fipe.status='published'
                  AND fipe.base_quality_status='passed'
                  AND pbev.is_active_shadow AND pbev.status='shadow_published'
                  AND pbev.quality_status='passed'
                  AND anp.is_active_shadow AND anp.status='shadow_published'
                  AND anp.quality_status='passed'
                FOR SHARE OF fipe,pbev,anp"""
            )
        ).mappings().all()
        if len(rows) != 1:
            raise IntegratedPublicationError(
                "integrated publication requires exactly one valid active dataset per Gold source"
            )
        return ActiveGoldSources(**dict(rows[0]))

    @staticmethod
    def load_vehicle_inputs(
        connection: Connection,
        sources: ActiveGoldSources,
    ) -> tuple[GoldVehicleInput, ...]:
        rows = connection.execute(
            text(
                """SELECT
                    fipe.vehicle_sk,
                    fipe.gold_record_id AS fipe_gold_record_id,
                    fipe.current_price AS vehicle_price_brl,
                    fipe.price_reference_month,
                    fipe.published_at AS fipe_published_at,
                    fipe.currency AS fipe_currency,
                    pbev.gold_record_id AS pbev_gold_record_id,
                    pbev.cycle_year AS pbev_cycle_year,
                    pbev.fossil_city_km_l,
                    pbev.fossil_highway_km_l,
                    pbev.ethanol_city_km_l,
                    pbev.ethanol_highway_km_l,
                    pbev.published_at AS pbev_published_at
                FROM gold.vehicle_features_snapshot AS fipe
                LEFT JOIN gold.vehicle_efficiency_snapshot AS pbev
                  ON pbev.dataset_version=:pbev_dataset
                 AND pbev.vehicle_sk=fipe.vehicle_sk
                WHERE fipe.dataset_version=:fipe_dataset
                ORDER BY fipe.vehicle_sk"""
            ),
            {
                "fipe_dataset": sources.fipe_dataset_version,
                "pbev_dataset": sources.pbev_dataset_version,
            },
        ).mappings().all()
        return tuple(GoldVehicleInput(**dict(row)) for row in rows)

    @staticmethod
    def load_fuel_prices(
        connection: Connection,
        sources: ActiveGoldSources,
        request: IntegratedPublicationRequest,
    ) -> tuple[GoldFuelPriceInput, ...]:
        product_codes = [
            FuelScenarioCode.GASOLINE_C_COMMON.value,
            FuelScenarioCode.ETHANOL_HYDRATED.value,
        ]
        if request.include_additized:
            product_codes.append(FuelScenarioCode.GASOLINE_C_ADDITIZED.value)
        rows = connection.execute(
            text(
                """SELECT snapshot_id AS anp_gold_snapshot_id,product_code,
                    week_start,week_end,geography_level,geography_key,
                    median_price,currency_code,unit_code
                FROM gold.anp_fuel_price_snapshot
                WHERE dataset_version=:dataset
                  AND week_start=:week_start
                  AND geography_level=:geography_level
                  AND geography_key=:geography_key
                  AND product_code=ANY(:product_codes)
                ORDER BY product_code"""
            ),
            {
                "dataset": sources.anp_dataset_version,
                "week_start": request.week_start,
                "geography_level": request.geography_level,
                "geography_key": request.geography_key,
                "product_codes": product_codes,
            },
        ).mappings().all()
        return tuple(
            GoldFuelPriceInput(
                **{
                    **dict(row),
                    "product_code": FuelScenarioCode(str(row["product_code"])),
                }
            )
            for row in rows
        )

    @staticmethod
    def load_current_baseline(connection: Connection) -> Mapping[str, object] | None:
        return connection.execute(
            text(
                """SELECT baseline_event_id,catalog_coverage_pct,pbev_coverage_pct
                FROM gold.integrated_vehicle_cost_coverage_baseline_current
                ORDER BY baseline_event_id DESC LIMIT 1"""
            )
        ).mappings().one_or_none()

    @staticmethod
    def _dataset_select(where_clause: str) -> str:
        return f"""SELECT dataset.*,
            EXISTS (
                SELECT 1 FROM gold.integrated_vehicle_cost_invalidation AS invalidation
                WHERE invalidation.dataset_version=dataset.dataset_version
            ) AS is_invalidated
        FROM gold.integrated_vehicle_cost_dataset AS dataset
        WHERE {where_clause}"""

    @classmethod
    def find_dataset_by_fingerprint(
        cls,
        connection: Connection,
        fingerprint: str,
    ) -> Mapping[str, object] | None:
        return connection.execute(
            text(cls._dataset_select("dataset.dataset_fingerprint=:fingerprint") + " FOR SHARE"),
            {"fingerprint": fingerprint},
        ).mappings().one_or_none()

    @classmethod
    def find_dataset_by_version(
        cls,
        connection: Connection,
        dataset_version: str,
    ) -> Mapping[str, object] | None:
        return connection.execute(
            text(cls._dataset_select("dataset.dataset_version=:dataset") + " FOR SHARE"),
            {"dataset": dataset_version},
        ).mappings().one_or_none()

    @classmethod
    def find_active_dataset(cls, connection: Connection) -> Mapping[str, object] | None:
        return connection.execute(
            text(cls._dataset_select("dataset.is_active_shadow") + " FOR UPDATE"),
        ).mappings().one_or_none()

    @classmethod
    def get_dataset(
        cls,
        connection: Connection,
        dataset_version: str,
    ) -> Mapping[str, object] | None:
        return connection.execute(
            text(cls._dataset_select("dataset.dataset_version=:dataset") + " FOR UPDATE"),
            {"dataset": dataset_version},
        ).mappings().one_or_none()

    @staticmethod
    def start_run(
        connection: Connection,
        *,
        run_id: UUID,
        dataset_version: str,
        trigger_type: str,
        git_commit: str | None,
        pipeline_name: str = PIPELINE_NAME,
    ) -> None:
        connection.execute(
            text(
                """INSERT INTO meta.pipeline_run
                (pipeline_run_id,pipeline_name,pipeline_version,dataset_version,
                 trigger_type,status,started_at,source_reference,git_commit)
                VALUES (:run,:name,:version,:dataset,:trigger,'running',clock_timestamp(),
                        'gold-fipe+pbev+anp',:git_commit)"""
            ),
            {
                "run": run_id,
                "name": pipeline_name,
                "version": PIPELINE_VERSION,
                "dataset": dataset_version,
                "trigger": trigger_type,
                "git_commit": git_commit,
            },
        )

    @staticmethod
    def finish_run(
        connection: Connection,
        *,
        run_id: UUID,
        status: str,
        received: int,
        inserted: int,
        deduplicated: int,
        rejected: int,
        error: str | None = None,
    ) -> None:
        connection.execute(
            text(
                """UPDATE meta.pipeline_run
                SET status=:status,
                    finished_at=GREATEST(clock_timestamp(),started_at),
                    records_received=:received,
                    records_inserted=:inserted,records_deduplicated=:deduplicated,
                    records_rejected=:rejected,error_summary=:error
                WHERE pipeline_run_id=:run"""
            ),
            {
                "run": run_id,
                "status": status,
                "received": received,
                "inserted": inserted,
                "deduplicated": deduplicated,
                "rejected": rejected,
                "error": sanitize(error) if error else None,
            },
        )

    @staticmethod
    def persist_materialization(
        connection: Connection,
        *,
        run_id: UUID,
        dataset_version: str,
        plan: IntegratedMaterializationPlan,
        activation_type: str | None,
        previous_dataset_version: str | None,
    ) -> None:
        hard_gate_status = "passed" if plan.activation_authorized else "failed"
        quality_status = hard_gate_status
        connection.execute(
            text(
                """INSERT INTO gold.integrated_vehicle_cost_dataset
                (dataset_version,publication_run_id,fipe_source_dataset_version,
                 pbev_source_dataset_version,anp_source_dataset_version,
                 fipe_source_fingerprint,pbev_source_fingerprint,anp_source_fingerprint,
                 analytic_cutoff_at,calculation_policy_version,geography_policy_version,
                 scenario_policy_version,quality_policy_version,request_manifest,
                 catalog_universe_count,pbev_matched_universe_count,eligible_vehicle_count,
                 published_vehicle_count,excluded_vehicle_count,requested_scenario_count,
                 published_scenario_count,excluded_scenario_count,snapshot_row_count,
                 projection_row_count,flex_comparison_count,catalog_coverage_pct,
                 pbev_coverage_pct,coverage_baseline_event_id_used,
                 coverage_regression_status,hard_gate_status,
                 statistical_calibration_status,quality_status,dataset_fingerprint)
                VALUES (:dataset,:run,:fipe_dataset,:pbev_dataset,:anp_dataset,
                        :fipe_fingerprint,:pbev_fingerprint,:anp_fingerprint,
                        :cutoff,:calculation_policy,:geography_policy,:scenario_policy,
                        :quality_policy,CAST(:manifest AS jsonb),:catalog_count,
                        :pbev_count,:eligible_count,:published_vehicle_count,
                        :excluded_vehicle_count,:requested_scenario_count,
                        :published_scenario_count,:excluded_scenario_count,
                        :snapshot_count,:projection_count,:flex_count,:catalog_coverage,
                        :pbev_coverage,:baseline_event,:regression_status,
                        :hard_gate_status,'not_calibrated',:quality_status,:fingerprint)"""
            ),
            {
                "dataset": dataset_version,
                "run": run_id,
                "fipe_dataset": plan.sources.fipe_dataset_version,
                "pbev_dataset": plan.sources.pbev_dataset_version,
                "anp_dataset": plan.sources.anp_dataset_version,
                "fipe_fingerprint": plan.sources.fipe_fingerprint,
                "pbev_fingerprint": plan.sources.pbev_fingerprint,
                "anp_fingerprint": plan.sources.anp_fingerprint,
                "cutoff": plan.analytic_cutoff_at,
                "calculation_policy": CALCULATION_POLICY_VERSION,
                "geography_policy": GEOGRAPHY_POLICY_VERSION,
                "scenario_policy": SCENARIO_POLICY_VERSION,
                "quality_policy": INTEGRATED_QUALITY_POLICY_VERSION,
                "manifest": _json(plan.request.manifest()),
                "catalog_count": plan.catalog_universe_count,
                "pbev_count": plan.pbev_matched_universe_count,
                "eligible_count": plan.eligible_vehicle_count,
                "published_vehicle_count": plan.published_vehicle_count,
                "excluded_vehicle_count": plan.excluded_vehicle_count,
                "requested_scenario_count": plan.requested_scenario_count,
                "published_scenario_count": plan.published_scenario_count,
                "excluded_scenario_count": plan.excluded_scenario_count,
                "snapshot_count": len(plan.snapshots),
                "projection_count": len(plan.snapshots),
                "flex_count": len(plan.flex_comparisons),
                "catalog_coverage": plan.catalog_coverage_pct,
                "pbev_coverage": plan.pbev_coverage_pct,
                "baseline_event": plan.coverage_baseline_event_id_used,
                "regression_status": plan.coverage_regression_status.value,
                "hard_gate_status": hard_gate_status,
                "quality_status": quality_status,
                "fingerprint": plan.dataset_fingerprint,
            },
        )
        request_manifest = plan.request.manifest()
        connection.execute(
            text(
                """INSERT INTO gold.integrated_vehicle_cost_geography_request
                (dataset_version,requested_geography_level,requested_geography_key,
                 resolved_geography_level,resolved_geography_key,reference_week_start,
                 reference_week_end,required_product_codes,optional_product_codes,
                 fallback_used,request_fingerprint)
                VALUES (:dataset,:level,:key,:level,:key,:week_start,:week_end,
                        :required,:optional,FALSE,:fingerprint)"""
            ),
            {
                "dataset": dataset_version,
                "level": plan.request.geography_level,
                "key": plan.request.geography_key,
                "week_start": plan.request.week_start,
                "week_end": plan.request.week_end,
                "required": list(request_manifest["required_product_codes"]),
                "optional": list(request_manifest["optional_product_codes"]),
                "fingerprint": canonical_hash(request_manifest),
            },
        )
        for exclusion in plan.exclusions:
            connection.execute(
                text(
                    """INSERT INTO gold.integrated_vehicle_cost_exclusion
                    (dataset_version,vehicle_sk,fipe_gold_record_id,pbev_gold_record_id,
                     exclusion_scope,reason_code,details,exclusion_fingerprint)
                    VALUES (:dataset,:vehicle,:fipe,:pbev,'vehicle',:reason,
                            CAST(:details AS jsonb),:fingerprint)"""
                ),
                {
                    "dataset": dataset_version,
                    "vehicle": exclusion.vehicle_sk,
                    "fipe": exclusion.fipe_gold_record_id,
                    "pbev": exclusion.pbev_gold_record_id,
                    "reason": exclusion.reason_code,
                    "details": _json(exclusion.details),
                    "fingerprint": exclusion.exclusion_fingerprint,
                },
            )

        projection_ids: dict[tuple[int, str, str, str, object], int] = {}
        for candidate in plan.snapshots:
            snapshot_id = int(
                connection.execute(
                    text(
                        """INSERT INTO gold.integrated_vehicle_cost_snapshot
                        (dataset_version,vehicle_sk,fuel_scenario_code,
                         requested_geography_level,requested_geography_key,
                         anp_week_start,anp_week_end,fipe_gold_record_id,
                         pbev_gold_record_id,anp_gold_snapshot_id,vehicle_price_brl,
                         price_reference_month,pbev_cycle_year,city_consumption_km_l,
                         highway_consumption_km_l,fuel_price_per_liter_brl,
                         city_cost_per_km_brl,highway_cost_per_km_brl,
                         mixed_cost_per_km_brl,city_distance_share,
                         highway_distance_share,currency_code,unit_code,
                         snapshot_fingerprint)
                        VALUES (:dataset,:vehicle,:fuel,:level,:key,:week_start,:week_end,
                                :fipe,:pbev,:anp,:vehicle_price,:reference_month,
                                :cycle,:city_consumption,:highway_consumption,
                                :fuel_price,:city_cost,:highway_cost,:mixed_cost,
                                :city_share,:highway_share,'BRL','liter',:fingerprint)
                        RETURNING snapshot_id"""
                    ),
                    {
                        "dataset": dataset_version,
                        "vehicle": candidate.vehicle_sk,
                        "fuel": candidate.fuel_scenario_code.value,
                        "level": candidate.requested_geography_level,
                        "key": candidate.requested_geography_key,
                        "week_start": candidate.anp_week_start,
                        "week_end": candidate.anp_week_end,
                        "fipe": candidate.fipe_gold_record_id,
                        "pbev": candidate.pbev_gold_record_id,
                        "anp": candidate.anp_gold_snapshot_id,
                        "vehicle_price": candidate.vehicle_price_brl,
                        "reference_month": candidate.price_reference_month,
                        "cycle": candidate.pbev_cycle_year,
                        "city_consumption": candidate.city_consumption_km_l,
                        "highway_consumption": candidate.highway_consumption_km_l,
                        "fuel_price": candidate.fuel_price_per_liter_brl,
                        "city_cost": candidate.city_cost_per_km_brl,
                        "highway_cost": candidate.highway_cost_per_km_brl,
                        "mixed_cost": candidate.mixed_cost_per_km_brl,
                        "city_share": DEFAULT_DISTANCE_SCENARIO.city_distance_share,
                        "highway_share": DEFAULT_DISTANCE_SCENARIO.highway_distance_share,
                        "fingerprint": candidate.snapshot_fingerprint,
                    },
                ).scalar_one()
            )
            projection_id = int(
                connection.execute(
                    text(
                        """INSERT INTO gold.integrated_vehicle_cost_projection_snapshot
                        (dataset_version,snapshot_id,scenario_code,monthly_distance_km,
                         annual_distance_km,projected_monthly_cost_brl,
                         projected_annual_cost_brl,projection_fingerprint)
                        VALUES (:dataset,:snapshot,:scenario,:monthly_distance,
                                :annual_distance,:monthly_cost,:annual_cost,:fingerprint)
                        RETURNING projection_id"""
                    ),
                    {
                        "dataset": dataset_version,
                        "snapshot": snapshot_id,
                        "scenario": MIXED_1000_V1,
                        "monthly_distance": DEFAULT_DISTANCE_SCENARIO.monthly_distance_km,
                        "annual_distance": DEFAULT_DISTANCE_SCENARIO.annual_distance_km,
                        "monthly_cost": candidate.projected_monthly_cost_brl,
                        "annual_cost": candidate.projected_annual_cost_brl,
                        "fingerprint": candidate.projection_fingerprint,
                    },
                ).scalar_one()
            )
            projection_ids[candidate.key] = projection_id

        for comparison in plan.flex_comparisons:
            connection.execute(
                text(
                    """INSERT INTO gold.integrated_vehicle_cost_flex_comparison_snapshot
                    (dataset_version,vehicle_sk,scenario_code,gasoline_projection_id,
                     ethanol_projection_id,requested_geography_level,
                     requested_geography_key,anp_week_start,city_cost_difference_brl,
                     highway_cost_difference_brl,mixed_cost_difference_brl,
                     mixed_cost_difference_pct,lower_cost_product_code,
                     comparison_fingerprint)
                    VALUES (:dataset,:vehicle,:scenario,:gasoline,:ethanol,:level,:key,
                            :week_start,:city_difference,:highway_difference,
                            :mixed_difference,:difference_pct,:lower,:fingerprint)"""
                ),
                {
                    "dataset": dataset_version,
                    "vehicle": comparison.vehicle_sk,
                    "scenario": MIXED_1000_V1,
                    "gasoline": projection_ids[comparison.gasoline_snapshot_key],
                    "ethanol": projection_ids[comparison.ethanol_snapshot_key],
                    "level": comparison.requested_geography_level,
                    "key": comparison.requested_geography_key,
                    "week_start": comparison.anp_week_start,
                    "city_difference": comparison.city_cost_difference_brl,
                    "highway_difference": comparison.highway_cost_difference_brl,
                    "mixed_difference": comparison.mixed_cost_difference_brl,
                    "difference_pct": comparison.mixed_cost_difference_pct,
                    "lower": comparison.lower_cost_product_code,
                    "fingerprint": comparison.comparison_fingerprint,
                },
            )

        for result in plan.quality_results:
            connection.execute(
                text(
                    """INSERT INTO gold.integrated_vehicle_cost_quality_result
                    (dataset_version,quality_policy_version,rule_code,pipeline_run_id,
                     rule_kind,severity,status,observed_value,expected_condition,
                     details,evaluated_at)
                    VALUES (:dataset,:policy,:rule,:run,:kind,:severity,:status,
                            CAST(:observed AS jsonb),:expected,CAST(:details AS jsonb),
                            clock_timestamp())"""
                ),
                {
                    "dataset": dataset_version,
                    "policy": INTEGRATED_QUALITY_POLICY_VERSION,
                    "rule": result.rule_code,
                    "run": run_id,
                    "kind": result.rule_kind,
                    "severity": result.severity,
                    "status": result.status,
                    "observed": _json(result.observed_value),
                    "expected": result.expected_condition,
                    "details": _json(result.details),
                },
            )

        unreconciled = connection.execute(
            text(
                """SELECT dimension,missing_count,unexpected_count,overlap_count
                FROM gold.reconcile_integrated_sets(:dataset)
                WHERE NOT is_reconciled"""
            ),
            {"dataset": dataset_version},
        ).mappings().all()
        if unreconciled:
            raise IntegratedPublicationError("integrated persisted sets are not reconciled")
        if activation_type is not None:
            activated_at = IntegratedVehicleCostLoader.lifecycle_timestamp(
                connection,
                dataset_version=dataset_version,
                previous_dataset_version=previous_dataset_version,
            )
            connection.execute(
                text(
                    """INSERT INTO gold.integrated_vehicle_cost_activation
                    (dataset_version,activation_run_id,previous_dataset_version,
                     activation_type,activated_at,details)
                    VALUES (:dataset,:run,:previous,:activation_type,:activated,
                            CAST(:details AS jsonb))"""
                ),
                {
                    "dataset": dataset_version,
                    "run": run_id,
                    "previous": previous_dataset_version,
                    "activation_type": activation_type,
                    "activated": activated_at,
                    "details": _json(
                        {
                            "quality_policy_version": INTEGRATED_QUALITY_POLICY_VERSION,
                            "dataset_fingerprint": plan.dataset_fingerprint,
                        }
                    ),
                },
            )

    @staticmethod
    def activate_rollback(
        connection: Connection,
        *,
        run_id: UUID,
        dataset_version: str,
        previous_dataset_version: str,
    ) -> None:
        activated_at = IntegratedVehicleCostLoader.lifecycle_timestamp(
            connection,
            dataset_version=dataset_version,
            previous_dataset_version=previous_dataset_version,
        )
        connection.execute(
            text(
                """INSERT INTO gold.integrated_vehicle_cost_activation
                (dataset_version,activation_run_id,previous_dataset_version,
                 activation_type,activated_at,details)
                VALUES (:dataset,:run,:previous,'rollback',:activated,
                        CAST(:details AS jsonb))"""
            ),
            {
                "dataset": dataset_version,
                "run": run_id,
                "previous": previous_dataset_version,
                "activated": activated_at,
                "details": _json({"operation": "explicit_rollback"}),
            },
        )
