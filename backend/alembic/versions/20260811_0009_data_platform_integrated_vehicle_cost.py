"""Adiciona os contratos estruturais da Gold analitica integrada.

Revision ID: 20260811_0009
Revises: 20260811_0008
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260811_0009"
down_revision: Union[str, None] = "20260811_0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


QUALITY_POLICY_VERSION = "integrated-vehicle-cost-quality-v1"
SCENARIO_CODE = "mixed_1000_v1"

HARD_GATE_RULES = (
    "INTEGRATED_FIPE_SOURCE_AVAILABLE",
    "INTEGRATED_PBEV_SOURCE_AVAILABLE",
    "INTEGRATED_ANP_SOURCE_AVAILABLE",
    "INTEGRATED_SOURCE_FINGERPRINTS_MATCH",
    "INTEGRATED_SOURCE_DATASETS_IMMUTABLE",
    "INTEGRATED_POINT_IN_TIME_VALID",
    "INTEGRATED_NO_FUTURE_DATA",
    "INTEGRATED_EXACT_GEOGRAPHY_ONLY",
    "INTEGRATED_NATIONAL_GEOGRAPHY_BLOCKED",
    "INTEGRATED_ANP_COMMON_WEEK",
    "INTEGRATED_REQUIRED_PRODUCTS_PRESENT",
    "INTEGRATED_PBEV_MATCHED_ONLY",
    "INTEGRATED_CONSUMPTION_POSITIVE",
    "INTEGRATED_FUEL_PRICE_POSITIVE",
    "INTEGRATED_CURRENCY_BRL",
    "INTEGRATED_UNIT_LITER",
    "INTEGRATED_SCENARIO_POLICY",
    "INTEGRATED_DISTANCE_RECONCILED",
    "INTEGRATED_DECIMAL_ARITHMETIC",
    "INTEGRATED_GOLD_LINEAGE_COMPLETE",
    "INTEGRATED_SNAPSHOT_GRAIN_UNIQUE",
    "INTEGRATED_PROJECTION_GRAIN_UNIQUE",
    "INTEGRATED_FLEX_COMPARISON_RECONCILED",
    "INTEGRATED_COUNTS_RECONCILED",
    "INTEGRATED_VEHICLE_COVERAGE_RECONCILED",
    "INTEGRATED_SCENARIO_COVERAGE_RECONCILED",
    "INTEGRATED_COVERAGE_NON_REGRESSION",
    "INTEGRATED_SHADOW_ONLY",
    "INTEGRATED_NO_PARTIAL_PUBLICATION",
)

STATISTICAL_RULES = (
    "ANP_MINIMUM_SAMPLE",
    "ANP_MINIMUM_ESTABLISHMENTS",
    "ANP_MUNICIPAL_COVERAGE",
    "ANP_MAXIMUM_FRESHNESS",
    "ANP_EXTREME_PRICE",
    "ANP_PRICE_DISPERSION",
    "ANP_WEEKLY_VOLUME_VARIATION",
)


def _is_postgresql() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _execute(statement: str) -> None:
    op.execute(sa.text(statement))


def _create_tables() -> None:
    _execute(
        """CREATE TABLE gold.integrated_vehicle_cost_dataset (
            dataset_version VARCHAR(96) PRIMARY KEY,
            publication_run_id UUID NOT NULL UNIQUE
                REFERENCES meta.pipeline_run(pipeline_run_id) ON DELETE RESTRICT,
            fipe_source_dataset_version VARCHAR(80) NOT NULL
                REFERENCES gold.vehicle_feature_dataset(dataset_version) ON DELETE RESTRICT,
            pbev_source_dataset_version VARCHAR(80) NOT NULL
                REFERENCES gold.vehicle_efficiency_dataset(dataset_version) ON DELETE RESTRICT,
            anp_source_dataset_version VARCHAR(80) NOT NULL
                REFERENCES gold.anp_fuel_price_dataset(dataset_version) ON DELETE RESTRICT,
            fipe_source_fingerprint CHAR(64) NOT NULL,
            pbev_source_fingerprint CHAR(64) NOT NULL,
            anp_source_fingerprint CHAR(64) NOT NULL,
            analytic_cutoff_at TIMESTAMPTZ NOT NULL,
            calculation_policy_version VARCHAR(40) NOT NULL,
            geography_policy_version VARCHAR(40) NOT NULL,
            scenario_policy_version VARCHAR(40) NOT NULL,
            quality_policy_version VARCHAR(80) NOT NULL,
            request_manifest JSONB NOT NULL DEFAULT '{}'::jsonb,
            status VARCHAR(20) NOT NULL DEFAULT 'building',
            is_active_shadow BOOLEAN NOT NULL DEFAULT FALSE,
            catalog_universe_count INTEGER NOT NULL DEFAULT 0,
            pbev_matched_universe_count INTEGER NOT NULL DEFAULT 0,
            eligible_vehicle_count INTEGER NOT NULL DEFAULT 0,
            published_vehicle_count INTEGER NOT NULL DEFAULT 0,
            excluded_vehicle_count INTEGER NOT NULL DEFAULT 0,
            requested_scenario_count INTEGER NOT NULL DEFAULT 0,
            published_scenario_count INTEGER NOT NULL DEFAULT 0,
            excluded_scenario_count INTEGER NOT NULL DEFAULT 0,
            snapshot_row_count INTEGER NOT NULL DEFAULT 0,
            projection_row_count INTEGER NOT NULL DEFAULT 0,
            flex_comparison_count INTEGER NOT NULL DEFAULT 0,
            catalog_coverage_pct NUMERIC(5,2) NOT NULL DEFAULT 0,
            pbev_coverage_pct NUMERIC(5,2) NOT NULL DEFAULT 0,
            coverage_baseline_event_id_used BIGINT,
            coverage_regression_status VARCHAR(30) NOT NULL DEFAULT 'not_applicable',
            hard_gate_status VARCHAR(20) NOT NULL DEFAULT 'pending',
            statistical_calibration_status VARCHAR(20) NOT NULL DEFAULT 'not_calibrated',
            quality_status VARCHAR(20) NOT NULL DEFAULT 'pending',
            dataset_fingerprint CHAR(64) NOT NULL UNIQUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            first_published_at TIMESTAMPTZ,
            last_activated_at TIMESTAMPTZ,
            retired_at TIMESTAMPTZ,
            last_activation_event_id BIGINT,
            activation_run_id UUID REFERENCES meta.pipeline_run(pipeline_run_id) ON DELETE RESTRICT,
            CONSTRAINT ck_integrated_dataset_hashes CHECK (
                fipe_source_fingerprint ~ '^[0-9a-f]{64}$' AND
                pbev_source_fingerprint ~ '^[0-9a-f]{64}$' AND
                anp_source_fingerprint ~ '^[0-9a-f]{64}$' AND
                dataset_fingerprint ~ '^[0-9a-f]{64}$'
            ),
            CONSTRAINT ck_integrated_dataset_manifest CHECK (jsonb_typeof(request_manifest)='object'),
            CONSTRAINT ck_integrated_dataset_status CHECK (status IN ('building','shadow_published','retired')),
            CONSTRAINT ck_integrated_dataset_counts CHECK (
                catalog_universe_count>=0 AND
                pbev_matched_universe_count>=0 AND
                eligible_vehicle_count>=0 AND
                published_vehicle_count>=0 AND
                excluded_vehicle_count>=0 AND
                requested_scenario_count>=0 AND
                published_scenario_count>=0 AND
                excluded_scenario_count>=0 AND
                snapshot_row_count>=0 AND
                projection_row_count>=0 AND
                flex_comparison_count>=0 AND
                catalog_universe_count>=eligible_vehicle_count AND
                pbev_matched_universe_count>=eligible_vehicle_count AND
                eligible_vehicle_count>=published_vehicle_count AND
                requested_scenario_count>=published_scenario_count
            ),
            CONSTRAINT ck_integrated_dataset_coverage CHECK (
                catalog_coverage_pct BETWEEN 0 AND 100 AND
                pbev_coverage_pct BETWEEN 0 AND 100 AND
                ((catalog_universe_count=0 AND catalog_coverage_pct=0) OR
                 (catalog_universe_count>0 AND catalog_coverage_pct=
                    ROUND(published_vehicle_count::numeric*100/catalog_universe_count,2))) AND
                ((pbev_matched_universe_count=0 AND pbev_coverage_pct=0) OR
                 (pbev_matched_universe_count>0 AND pbev_coverage_pct=
                    ROUND(published_vehicle_count::numeric*100/pbev_matched_universe_count,2)))
            ),
            CONSTRAINT ck_integrated_dataset_regression CHECK (
                coverage_regression_status IN ('not_applicable','passed','manual_review_required')
            ),
            CONSTRAINT ck_integrated_dataset_quality CHECK (
                hard_gate_status IN ('pending','passed','failed') AND
                statistical_calibration_status='not_calibrated' AND
                quality_status IN ('pending','passed','failed')
            ),
            CONSTRAINT ck_integrated_dataset_lifecycle CHECK (
                (status='building' AND NOT is_active_shadow AND first_published_at IS NULL
                    AND last_activated_at IS NULL AND retired_at IS NULL
                    AND last_activation_event_id IS NULL AND activation_run_id IS NULL) OR
                (status='shadow_published' AND is_active_shadow AND first_published_at IS NOT NULL
                    AND last_activated_at IS NOT NULL AND retired_at IS NULL
                    AND last_activation_event_id IS NOT NULL AND activation_run_id IS NOT NULL) OR
                (status='retired' AND NOT is_active_shadow AND first_published_at IS NOT NULL
                    AND last_activated_at IS NOT NULL AND retired_at IS NOT NULL
                    AND last_activation_event_id IS NOT NULL AND activation_run_id IS NOT NULL)
            ),
            CONSTRAINT ck_integrated_dataset_times CHECK (
                analytic_cutoff_at<=created_at AND
                (first_published_at IS NULL OR first_published_at>=created_at) AND
                (last_activated_at IS NULL OR last_activated_at>=first_published_at) AND
                (retired_at IS NULL OR retired_at>=last_activated_at)
            )
        )"""
    )
    _execute(
        """CREATE UNIQUE INDEX uq_integrated_dataset_active_shadow
        ON gold.integrated_vehicle_cost_dataset(is_active_shadow)
        WHERE is_active_shadow"""
    )
    _execute(
        """CREATE TABLE gold.integrated_vehicle_cost_geography_request (
            geography_request_id BIGSERIAL PRIMARY KEY,
            dataset_version VARCHAR(96) NOT NULL
                REFERENCES gold.integrated_vehicle_cost_dataset(dataset_version) ON DELETE RESTRICT,
            requested_geography_level VARCHAR(20) NOT NULL,
            requested_geography_key VARCHAR(200) NOT NULL,
            resolved_geography_level VARCHAR(20) NOT NULL,
            resolved_geography_key VARCHAR(200) NOT NULL,
            reference_week_start DATE NOT NULL,
            reference_week_end DATE NOT NULL,
            required_product_codes VARCHAR(40)[] NOT NULL,
            optional_product_codes VARCHAR(40)[] NOT NULL DEFAULT ARRAY[]::VARCHAR(40)[],
            fallback_used BOOLEAN NOT NULL DEFAULT FALSE,
            request_fingerprint CHAR(64) NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_integrated_geography_level CHECK (
                requested_geography_level IN ('municipality','state') AND
                resolved_geography_level IN ('municipality','state')
            ),
            CONSTRAINT ck_integrated_geography_exact CHECK (
                NOT fallback_used AND
                requested_geography_level=resolved_geography_level AND
                requested_geography_key=resolved_geography_key
            ),
            CONSTRAINT ck_integrated_geography_week CHECK (reference_week_end=reference_week_start+6),
            CONSTRAINT ck_integrated_geography_products CHECK (
                required_product_codes @> ARRAY['gasoline_c_common','ethanol_hydrated']::VARCHAR(40)[] AND
                required_product_codes <@ ARRAY['gasoline_c_common','ethanol_hydrated']::VARCHAR(40)[] AND
                optional_product_codes <@ ARRAY['gasoline_c_additized']::VARCHAR(40)[] AND
                cardinality(required_product_codes)=2 AND cardinality(optional_product_codes)<=1 AND
                array_position(required_product_codes,NULL) IS NULL AND
                array_position(optional_product_codes,NULL) IS NULL
            ),
            CONSTRAINT ck_integrated_geography_hash CHECK (request_fingerprint ~ '^[0-9a-f]{64}$'),
            CONSTRAINT uq_integrated_geography_request UNIQUE (
                dataset_version,requested_geography_level,requested_geography_key,reference_week_start
            )
        )"""
    )
    _execute(
        """CREATE TABLE gold.integrated_vehicle_cost_snapshot (
            snapshot_id BIGSERIAL PRIMARY KEY,
            dataset_version VARCHAR(96) NOT NULL
                REFERENCES gold.integrated_vehicle_cost_dataset(dataset_version) ON DELETE RESTRICT,
            vehicle_sk BIGINT NOT NULL,
            fuel_scenario_code VARCHAR(40) NOT NULL,
            requested_geography_level VARCHAR(20) NOT NULL,
            requested_geography_key VARCHAR(200) NOT NULL,
            anp_week_start DATE NOT NULL,
            anp_week_end DATE NOT NULL,
            fipe_gold_record_id BIGINT NOT NULL
                REFERENCES gold.vehicle_features_snapshot(gold_record_id) ON DELETE RESTRICT,
            pbev_gold_record_id BIGINT NOT NULL
                REFERENCES gold.vehicle_efficiency_snapshot(gold_record_id) ON DELETE RESTRICT,
            anp_gold_snapshot_id BIGINT NOT NULL
                REFERENCES gold.anp_fuel_price_snapshot(snapshot_id) ON DELETE RESTRICT,
            vehicle_price_brl NUMERIC(14,2) NOT NULL,
            price_reference_month DATE NOT NULL,
            pbev_cycle_year SMALLINT NOT NULL,
            city_consumption_km_l NUMERIC(10,4) NOT NULL,
            highway_consumption_km_l NUMERIC(10,4) NOT NULL,
            fuel_price_per_liter_brl NUMERIC(12,4) NOT NULL,
            city_cost_per_km_brl NUMERIC(18,8) NOT NULL,
            highway_cost_per_km_brl NUMERIC(18,8) NOT NULL,
            mixed_cost_per_km_brl NUMERIC(18,8) NOT NULL,
            city_distance_share NUMERIC(5,4) NOT NULL,
            highway_distance_share NUMERIC(5,4) NOT NULL,
            currency_code CHAR(3) NOT NULL DEFAULT 'BRL',
            unit_code VARCHAR(20) NOT NULL DEFAULT 'liter',
            snapshot_fingerprint CHAR(64) NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_integrated_snapshot_fuel CHECK (
                fuel_scenario_code IN ('gasoline_c_common','gasoline_c_additized','ethanol_hydrated')
            ),
            CONSTRAINT ck_integrated_snapshot_geography CHECK (
                requested_geography_level IN ('municipality','state')
            ),
            CONSTRAINT ck_integrated_snapshot_week CHECK (anp_week_end=anp_week_start+6),
            CONSTRAINT ck_integrated_snapshot_metrics CHECK (
                vehicle_price_brl>0 AND city_consumption_km_l>0 AND highway_consumption_km_l>0 AND
                fuel_price_per_liter_brl>0 AND city_cost_per_km_brl>0 AND
                highway_cost_per_km_brl>0 AND mixed_cost_per_km_brl>0 AND
                city_cost_per_km_brl=ROUND(fuel_price_per_liter_brl/city_consumption_km_l,8) AND
                highway_cost_per_km_brl=ROUND(fuel_price_per_liter_brl/highway_consumption_km_l,8) AND
                mixed_cost_per_km_brl=ROUND(
                    city_cost_per_km_brl*city_distance_share+
                    highway_cost_per_km_brl*highway_distance_share,8)
            ),
            CONSTRAINT ck_integrated_snapshot_shares CHECK (
                city_distance_share>=0 AND highway_distance_share>=0 AND
                city_distance_share+highway_distance_share=1.0000
            ),
            CONSTRAINT ck_integrated_snapshot_units CHECK (currency_code='BRL' AND unit_code='liter'),
            CONSTRAINT ck_integrated_snapshot_hash CHECK (snapshot_fingerprint ~ '^[0-9a-f]{64}$'),
            CONSTRAINT uq_integrated_snapshot_identity UNIQUE (dataset_version,snapshot_id),
            CONSTRAINT uq_integrated_snapshot_grain UNIQUE (
                dataset_version,vehicle_sk,fuel_scenario_code,requested_geography_level,
                requested_geography_key,anp_week_start
            )
        )"""
    )
    _execute(
        """CREATE TABLE gold.integrated_vehicle_cost_projection_snapshot (
            projection_id BIGSERIAL PRIMARY KEY,
            dataset_version VARCHAR(96) NOT NULL,
            snapshot_id BIGINT NOT NULL,
            scenario_code VARCHAR(40) NOT NULL,
            monthly_distance_km NUMERIC(12,2) NOT NULL,
            annual_distance_km NUMERIC(12,2) NOT NULL,
            projected_monthly_cost_brl NUMERIC(18,4) NOT NULL,
            projected_annual_cost_brl NUMERIC(18,4) NOT NULL,
            projection_fingerprint CHAR(64) NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT fk_integrated_projection_snapshot FOREIGN KEY (dataset_version,snapshot_id)
                REFERENCES gold.integrated_vehicle_cost_snapshot(dataset_version,snapshot_id)
                ON DELETE RESTRICT,
            CONSTRAINT ck_integrated_projection_scenario CHECK (scenario_code='mixed_1000_v1'),
            CONSTRAINT ck_integrated_projection_distance CHECK (
                monthly_distance_km=1000.00 AND annual_distance_km=12000.00
            ),
            CONSTRAINT ck_integrated_projection_cost CHECK (
                projected_monthly_cost_brl>=0 AND projected_annual_cost_brl>=0 AND
                projected_annual_cost_brl=ROUND(projected_monthly_cost_brl*12,4)
            ),
            CONSTRAINT ck_integrated_projection_hash CHECK (projection_fingerprint ~ '^[0-9a-f]{64}$'),
            CONSTRAINT uq_integrated_projection_identity UNIQUE (dataset_version,projection_id),
            CONSTRAINT uq_integrated_projection_grain UNIQUE (dataset_version,snapshot_id,scenario_code)
        )"""
    )
    _execute(
        """CREATE TABLE gold.integrated_vehicle_cost_flex_comparison_snapshot (
            flex_comparison_id BIGSERIAL PRIMARY KEY,
            dataset_version VARCHAR(96) NOT NULL,
            vehicle_sk BIGINT NOT NULL,
            scenario_code VARCHAR(40) NOT NULL,
            gasoline_projection_id BIGINT NOT NULL,
            ethanol_projection_id BIGINT NOT NULL,
            requested_geography_level VARCHAR(20) NOT NULL,
            requested_geography_key VARCHAR(200) NOT NULL,
            anp_week_start DATE NOT NULL,
            city_cost_difference_brl NUMERIC(18,8) NOT NULL,
            highway_cost_difference_brl NUMERIC(18,8) NOT NULL,
            mixed_cost_difference_brl NUMERIC(18,8) NOT NULL,
            mixed_cost_difference_pct NUMERIC(9,4) NOT NULL,
            lower_cost_product_code VARCHAR(40) NOT NULL,
            comparison_fingerprint CHAR(64) NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT fk_integrated_flex_gas_projection FOREIGN KEY (dataset_version,gasoline_projection_id)
                REFERENCES gold.integrated_vehicle_cost_projection_snapshot(dataset_version,projection_id)
                ON DELETE RESTRICT,
            CONSTRAINT fk_integrated_flex_ethanol_projection FOREIGN KEY (dataset_version,ethanol_projection_id)
                REFERENCES gold.integrated_vehicle_cost_projection_snapshot(dataset_version,projection_id)
                ON DELETE RESTRICT,
            CONSTRAINT ck_integrated_flex_scenario CHECK (scenario_code='mixed_1000_v1'),
            CONSTRAINT ck_integrated_flex_geography CHECK (requested_geography_level IN ('municipality','state')),
            CONSTRAINT ck_integrated_flex_lower CHECK (
                lower_cost_product_code IN ('gasoline_c_common','gasoline_c_additized','ethanol_hydrated','tie')
            ),
            CONSTRAINT ck_integrated_flex_hash CHECK (comparison_fingerprint ~ '^[0-9a-f]{64}$'),
            CONSTRAINT uq_integrated_flex_grain UNIQUE (
                dataset_version,vehicle_sk,scenario_code,requested_geography_level,
                requested_geography_key,anp_week_start
            )
        )"""
    )
    _execute(
        """CREATE TABLE gold.integrated_vehicle_cost_exclusion (
            exclusion_id BIGSERIAL PRIMARY KEY,
            dataset_version VARCHAR(96) NOT NULL
                REFERENCES gold.integrated_vehicle_cost_dataset(dataset_version) ON DELETE RESTRICT,
            vehicle_sk BIGINT NOT NULL,
            fipe_gold_record_id BIGINT NOT NULL
                REFERENCES gold.vehicle_features_snapshot(gold_record_id) ON DELETE RESTRICT,
            pbev_gold_record_id BIGINT
                REFERENCES gold.vehicle_efficiency_snapshot(gold_record_id) ON DELETE RESTRICT,
            exclusion_scope VARCHAR(20) NOT NULL,
            scenario_code VARCHAR(40),
            fuel_scenario_code VARCHAR(40),
            requested_geography_level VARCHAR(20),
            requested_geography_key VARCHAR(200),
            anp_week_start DATE,
            reason_code VARCHAR(80) NOT NULL,
            details JSONB NOT NULL DEFAULT '{}'::jsonb,
            exclusion_fingerprint CHAR(64) NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_integrated_exclusion_scope CHECK (
                (exclusion_scope='vehicle' AND scenario_code IS NULL AND fuel_scenario_code IS NULL
                    AND requested_geography_level IS NULL AND requested_geography_key IS NULL
                    AND anp_week_start IS NULL) OR
                (exclusion_scope='scenario' AND scenario_code='mixed_1000_v1'
                    AND fuel_scenario_code IS NOT NULL AND requested_geography_level IS NOT NULL
                    AND requested_geography_key IS NOT NULL AND anp_week_start IS NOT NULL
                    AND pbev_gold_record_id IS NOT NULL)
            ),
            CONSTRAINT ck_integrated_exclusion_fuel CHECK (
                fuel_scenario_code IS NULL OR
                fuel_scenario_code IN ('gasoline_c_common','gasoline_c_additized','ethanol_hydrated')
            ),
            CONSTRAINT ck_integrated_exclusion_geography CHECK (
                requested_geography_level IS NULL OR requested_geography_level IN ('municipality','state')
            ),
            CONSTRAINT ck_integrated_exclusion_details CHECK (jsonb_typeof(details)='object'),
            CONSTRAINT ck_integrated_exclusion_hash CHECK (exclusion_fingerprint ~ '^[0-9a-f]{64}$')
        )"""
    )
    _execute(
        """CREATE UNIQUE INDEX uq_integrated_vehicle_exclusion
        ON gold.integrated_vehicle_cost_exclusion(dataset_version,vehicle_sk)
        WHERE exclusion_scope='vehicle'"""
    )
    _execute(
        """CREATE UNIQUE INDEX uq_integrated_scenario_exclusion
        ON gold.integrated_vehicle_cost_exclusion(
            dataset_version,vehicle_sk,scenario_code,fuel_scenario_code,
            requested_geography_level,requested_geography_key,anp_week_start
        ) WHERE exclusion_scope='scenario'"""
    )
    _execute(
        """CREATE TABLE gold.integrated_vehicle_cost_quality_rule_catalog (
            quality_policy_version VARCHAR(80) NOT NULL,
            rule_code VARCHAR(80) NOT NULL,
            rule_kind VARCHAR(30) NOT NULL,
            severity VARCHAR(20) NOT NULL,
            required_for_activation BOOLEAN NOT NULL,
            expected_status VARCHAR(30) NOT NULL,
            description TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT pk_integrated_quality_catalog PRIMARY KEY (quality_policy_version,rule_code),
            CONSTRAINT ck_integrated_quality_rule_kind CHECK (rule_kind IN ('hard_gate','statistical_control')),
            CONSTRAINT ck_integrated_quality_severity CHECK (severity IN ('critical','warning','info')),
            CONSTRAINT ck_integrated_quality_expected CHECK (expected_status IN ('passed','not_calibrated')),
            CONSTRAINT ck_integrated_quality_contract CHECK (
                (rule_kind='hard_gate' AND severity='critical' AND expected_status='passed') OR
                (rule_kind='statistical_control' AND expected_status='not_calibrated')
            )
        )"""
    )
    _execute(
        """CREATE TABLE gold.integrated_vehicle_cost_quality_result (
            quality_result_id BIGSERIAL PRIMARY KEY,
            dataset_version VARCHAR(96) NOT NULL
                REFERENCES gold.integrated_vehicle_cost_dataset(dataset_version) ON DELETE RESTRICT,
            quality_policy_version VARCHAR(80) NOT NULL,
            rule_code VARCHAR(80) NOT NULL,
            pipeline_run_id UUID NOT NULL
                REFERENCES meta.pipeline_run(pipeline_run_id) ON DELETE RESTRICT,
            rule_kind VARCHAR(30) NOT NULL,
            severity VARCHAR(20) NOT NULL,
            status VARCHAR(30) NOT NULL,
            observed_value JSONB NOT NULL DEFAULT '{}'::jsonb,
            expected_condition TEXT NOT NULL,
            details JSONB NOT NULL DEFAULT '{}'::jsonb,
            evaluated_at TIMESTAMPTZ NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT fk_integrated_quality_catalog FOREIGN KEY (quality_policy_version,rule_code)
                REFERENCES gold.integrated_vehicle_cost_quality_rule_catalog(quality_policy_version,rule_code)
                ON DELETE RESTRICT,
            CONSTRAINT ck_integrated_quality_result_kind CHECK (rule_kind IN ('hard_gate','statistical_control')),
            CONSTRAINT ck_integrated_quality_result_severity CHECK (severity IN ('critical','warning','info')),
            CONSTRAINT ck_integrated_quality_result_status CHECK (status IN ('passed','failed','not_calibrated')),
            CONSTRAINT ck_integrated_quality_result_json CHECK (
                jsonb_typeof(observed_value)='object' AND jsonb_typeof(details)='object'
            ),
            CONSTRAINT uq_integrated_quality_result_identity UNIQUE (
                dataset_version,quality_policy_version,rule_code
            )
        )"""
    )
    _execute(
        """CREATE TABLE gold.integrated_vehicle_cost_activation (
            activation_event_id BIGSERIAL PRIMARY KEY,
            dataset_version VARCHAR(96) NOT NULL
                REFERENCES gold.integrated_vehicle_cost_dataset(dataset_version) ON DELETE RESTRICT,
            activation_run_id UUID NOT NULL UNIQUE
                REFERENCES meta.pipeline_run(pipeline_run_id) ON DELETE RESTRICT,
            previous_dataset_version VARCHAR(96)
                REFERENCES gold.integrated_vehicle_cost_dataset(dataset_version) ON DELETE RESTRICT,
            activation_type VARCHAR(20) NOT NULL,
            activated_at TIMESTAMPTZ NOT NULL,
            details JSONB NOT NULL DEFAULT '{}'::jsonb,
            CONSTRAINT ck_integrated_activation_type CHECK (activation_type IN ('publish','replace','rollback')),
            CONSTRAINT ck_integrated_activation_previous CHECK (
                (activation_type='publish' AND previous_dataset_version IS NULL) OR
                (activation_type IN ('replace','rollback') AND previous_dataset_version IS NOT NULL
                    AND previous_dataset_version<>dataset_version)
            ),
            CONSTRAINT ck_integrated_activation_details CHECK (jsonb_typeof(details)='object'),
            CONSTRAINT uq_integrated_activation_dataset_event_run UNIQUE (
                dataset_version,activation_event_id,activation_run_id
            )
        )"""
    )
    _execute(
        """CREATE TABLE gold.integrated_vehicle_cost_invalidation (
            invalidation_event_id BIGSERIAL PRIMARY KEY,
            dataset_version VARCHAR(96) NOT NULL
                REFERENCES gold.integrated_vehicle_cost_dataset(dataset_version) ON DELETE RESTRICT,
            invalidation_run_id UUID NOT NULL
                REFERENCES meta.pipeline_run(pipeline_run_id) ON DELETE RESTRICT,
            reason_code VARCHAR(80) NOT NULL,
            details JSONB NOT NULL DEFAULT '{}'::jsonb,
            invalidation_fingerprint CHAR(64) NOT NULL UNIQUE,
            invalidated_at TIMESTAMPTZ NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_integrated_invalidation_details CHECK (jsonb_typeof(details)='object'),
            CONSTRAINT ck_integrated_invalidation_hash CHECK (invalidation_fingerprint ~ '^[0-9a-f]{64}$')
        )"""
    )
    _execute(
        """CREATE TABLE gold.integrated_vehicle_cost_coverage_baseline (
            baseline_event_id BIGSERIAL PRIMARY KEY,
            dataset_version VARCHAR(96) NOT NULL
                REFERENCES gold.integrated_vehicle_cost_dataset(dataset_version) ON DELETE RESTRICT,
            approval_run_id UUID NOT NULL
                REFERENCES meta.pipeline_run(pipeline_run_id) ON DELETE RESTRICT,
            quality_policy_version VARCHAR(80) NOT NULL,
            status VARCHAR(20) NOT NULL,
            candidate_event_id BIGINT
                REFERENCES gold.integrated_vehicle_cost_coverage_baseline(baseline_event_id) ON DELETE RESTRICT,
            supersedes_baseline_event_id BIGINT
                REFERENCES gold.integrated_vehicle_cost_coverage_baseline(baseline_event_id) ON DELETE RESTRICT,
            catalog_coverage_pct NUMERIC(5,2) NOT NULL,
            pbev_coverage_pct NUMERIC(5,2) NOT NULL,
            approved_at TIMESTAMPTZ,
            reason_code VARCHAR(80) NOT NULL,
            details JSONB NOT NULL DEFAULT '{}'::jsonb,
            baseline_fingerprint CHAR(64) NOT NULL UNIQUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_integrated_baseline_status CHECK (status IN ('candidate','active','revoked')),
            CONSTRAINT ck_integrated_baseline_coverage CHECK (
                catalog_coverage_pct BETWEEN 0 AND 100 AND pbev_coverage_pct BETWEEN 0 AND 100
            ),
            CONSTRAINT ck_integrated_baseline_lifecycle CHECK (
                (status='candidate' AND candidate_event_id IS NULL AND approved_at IS NULL) OR
                (status='active' AND candidate_event_id IS NOT NULL AND approved_at IS NOT NULL) OR
                (status='revoked' AND supersedes_baseline_event_id IS NOT NULL)
            ),
            CONSTRAINT ck_integrated_baseline_details CHECK (jsonb_typeof(details)='object'),
            CONSTRAINT ck_integrated_baseline_hash CHECK (baseline_fingerprint ~ '^[0-9a-f]{64}$')
        )"""
    )
    _execute(
        """ALTER TABLE gold.integrated_vehicle_cost_dataset
        ADD CONSTRAINT fk_integrated_dataset_last_activation
        FOREIGN KEY (dataset_version,last_activation_event_id,activation_run_id)
        REFERENCES gold.integrated_vehicle_cost_activation(
            dataset_version,activation_event_id,activation_run_id
        ) ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED"""
    )
    _execute(
        """ALTER TABLE gold.integrated_vehicle_cost_dataset
        ADD CONSTRAINT fk_integrated_dataset_coverage_baseline
        FOREIGN KEY (coverage_baseline_event_id_used)
        REFERENCES gold.integrated_vehicle_cost_coverage_baseline(baseline_event_id)
        ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED"""
    )
    _execute(
        """CREATE VIEW gold.integrated_vehicle_cost_coverage_baseline_current AS
        SELECT baseline.*
        FROM gold.integrated_vehicle_cost_coverage_baseline AS baseline
        WHERE baseline.status='active'
          AND NOT EXISTS (
              SELECT 1 FROM gold.integrated_vehicle_cost_coverage_baseline AS successor
              WHERE successor.supersedes_baseline_event_id=baseline.baseline_event_id
          )"""
    )
    for index_statement in (
        "CREATE INDEX ix_integrated_geography_lookup ON gold.integrated_vehicle_cost_geography_request(dataset_version,reference_week_start)",
        "CREATE INDEX ix_integrated_snapshot_vehicle ON gold.integrated_vehicle_cost_snapshot(dataset_version,vehicle_sk)",
        "CREATE INDEX ix_integrated_snapshot_anp_lineage ON gold.integrated_vehicle_cost_snapshot(anp_gold_snapshot_id)",
        "CREATE INDEX ix_integrated_projection_scenario ON gold.integrated_vehicle_cost_projection_snapshot(dataset_version,scenario_code)",
        "CREATE INDEX ix_integrated_flex_vehicle ON gold.integrated_vehicle_cost_flex_comparison_snapshot(dataset_version,vehicle_sk)",
        "CREATE INDEX ix_integrated_exclusion_scope ON gold.integrated_vehicle_cost_exclusion(dataset_version,exclusion_scope)",
        "CREATE INDEX ix_integrated_quality_status ON gold.integrated_vehicle_cost_quality_result(dataset_version,quality_policy_version,status)",
        "CREATE INDEX ix_integrated_activation_timeline ON gold.integrated_vehicle_cost_activation(activated_at,activation_event_id)",
        "CREATE INDEX ix_integrated_invalidation_dataset ON gold.integrated_vehicle_cost_invalidation(dataset_version,invalidated_at)",
        "CREATE INDEX ix_integrated_baseline_timeline ON gold.integrated_vehicle_cost_coverage_baseline(status,baseline_event_id)",
    ):
        _execute(index_statement)


def _create_set_functions() -> None:
    _execute(
        """CREATE FUNCTION gold.integrated_expected_vehicle_set(p_dataset_version VARCHAR)
        RETURNS TABLE(vehicle_sk BIGINT)
        LANGUAGE sql STABLE AS $$
            SELECT DISTINCT fipe.vehicle_sk
            FROM gold.integrated_vehicle_cost_dataset AS dataset
            JOIN gold.vehicle_features_snapshot AS fipe
              ON fipe.dataset_version=dataset.fipe_source_dataset_version
            WHERE dataset.dataset_version=p_dataset_version
        $$"""
    )
    _execute(
        """CREATE FUNCTION gold.integrated_pbev_eligible_vehicle_set(p_dataset_version VARCHAR)
        RETURNS TABLE(vehicle_sk BIGINT)
        LANGUAGE sql STABLE AS $$
            SELECT DISTINCT fipe.vehicle_sk
            FROM gold.integrated_vehicle_cost_dataset AS dataset
            JOIN gold.vehicle_features_snapshot AS fipe
              ON fipe.dataset_version=dataset.fipe_source_dataset_version
            JOIN gold.vehicle_efficiency_snapshot AS pbev
              ON pbev.dataset_version=dataset.pbev_source_dataset_version
             AND pbev.vehicle_sk=fipe.vehicle_sk
            WHERE dataset.dataset_version=p_dataset_version
        $$"""
    )
    _execute(
        """CREATE FUNCTION gold.integrated_expected_scenario_set(p_dataset_version VARCHAR)
        RETURNS TABLE(
            vehicle_sk BIGINT,
            scenario_code VARCHAR,
            fuel_scenario_code VARCHAR,
            requested_geography_level VARCHAR,
            requested_geography_key VARCHAR,
            anp_week_start DATE
        )
        LANGUAGE sql STABLE AS $$
            SELECT DISTINCT
                pbev.vehicle_sk,
                'mixed_1000_v1'::VARCHAR,
                anp.product_code::VARCHAR,
                request.requested_geography_level::VARCHAR,
                request.requested_geography_key::VARCHAR,
                request.reference_week_start
            FROM gold.integrated_vehicle_cost_dataset AS dataset
            JOIN gold.vehicle_efficiency_snapshot AS pbev
              ON pbev.dataset_version=dataset.pbev_source_dataset_version
            JOIN gold.vehicle_features_snapshot AS fipe
              ON fipe.dataset_version=dataset.fipe_source_dataset_version
             AND fipe.vehicle_sk=pbev.vehicle_sk
            JOIN gold.integrated_vehicle_cost_geography_request AS request
              ON request.dataset_version=dataset.dataset_version
            JOIN gold.anp_fuel_price_snapshot AS anp
              ON anp.dataset_version=dataset.anp_source_dataset_version
             AND anp.week_start=request.reference_week_start
             AND anp.geography_level=request.requested_geography_level
             AND anp.geography_key=request.requested_geography_key
             AND anp.product_code=ANY(request.required_product_codes||request.optional_product_codes)
            WHERE dataset.dataset_version=p_dataset_version
              AND (
                  (anp.product_code IN ('gasoline_c_common','gasoline_c_additized')
                    AND pbev.fossil_city_km_l IS NOT NULL AND pbev.fossil_highway_km_l IS NOT NULL) OR
                  (anp.product_code='ethanol_hydrated'
                    AND pbev.ethanol_city_km_l IS NOT NULL AND pbev.ethanol_highway_km_l IS NOT NULL)
              )
        $$"""
    )
    _execute(
        """CREATE FUNCTION gold.reconcile_integrated_sets(p_dataset_version VARCHAR)
        RETURNS TABLE(
            dimension VARCHAR,
            missing_count BIGINT,
            unexpected_count BIGINT,
            overlap_count BIGINT,
            missing_keys JSONB,
            unexpected_keys JSONB,
            is_reconciled BOOLEAN
        )
        LANGUAGE sql STABLE AS $$
            WITH expected_vehicle AS (
                SELECT vehicle_sk FROM gold.integrated_expected_vehicle_set(p_dataset_version)
            ), actual_vehicle AS (
                SELECT DISTINCT snapshot.vehicle_sk
                FROM gold.integrated_vehicle_cost_projection_snapshot AS projection
                JOIN gold.integrated_vehicle_cost_snapshot AS snapshot
                  ON snapshot.dataset_version=projection.dataset_version
                 AND snapshot.snapshot_id=projection.snapshot_id
                WHERE projection.dataset_version=p_dataset_version
            ), excluded_vehicle AS (
                SELECT vehicle_sk FROM gold.integrated_vehicle_cost_exclusion
                WHERE dataset_version=p_dataset_version AND exclusion_scope='vehicle'
            ), accounted_vehicle AS (
                SELECT vehicle_sk FROM actual_vehicle
                UNION
                SELECT vehicle_sk FROM excluded_vehicle
            ), missing_vehicle AS (
                SELECT vehicle_sk FROM expected_vehicle
                EXCEPT
                SELECT vehicle_sk FROM accounted_vehicle
            ), unexpected_vehicle AS (
                SELECT vehicle_sk FROM accounted_vehicle
                EXCEPT
                SELECT vehicle_sk FROM expected_vehicle
            ), overlap_vehicle AS (
                SELECT vehicle_sk FROM actual_vehicle
                INTERSECT
                SELECT vehicle_sk FROM excluded_vehicle
            ), expected_scenario AS (
                SELECT * FROM gold.integrated_expected_scenario_set(p_dataset_version)
            ), actual_scenario AS (
                SELECT snapshot.vehicle_sk,projection.scenario_code,snapshot.fuel_scenario_code,
                       snapshot.requested_geography_level,snapshot.requested_geography_key,
                       snapshot.anp_week_start
                FROM gold.integrated_vehicle_cost_projection_snapshot AS projection
                JOIN gold.integrated_vehicle_cost_snapshot AS snapshot
                  ON snapshot.dataset_version=projection.dataset_version
                 AND snapshot.snapshot_id=projection.snapshot_id
                WHERE projection.dataset_version=p_dataset_version
            ), excluded_scenario AS (
                SELECT vehicle_sk,scenario_code,fuel_scenario_code,requested_geography_level,
                       requested_geography_key,anp_week_start
                FROM gold.integrated_vehicle_cost_exclusion
                WHERE dataset_version=p_dataset_version AND exclusion_scope='scenario'
                UNION
                SELECT expected.*
                FROM expected_scenario AS expected
                JOIN gold.integrated_vehicle_cost_exclusion AS exclusion
                  ON exclusion.dataset_version=p_dataset_version
                 AND exclusion.exclusion_scope='vehicle'
                 AND exclusion.vehicle_sk=expected.vehicle_sk
            ), accounted_scenario AS (
                SELECT * FROM actual_scenario
                UNION
                SELECT * FROM excluded_scenario
            ), missing_scenario AS (
                SELECT * FROM expected_scenario
                EXCEPT
                SELECT * FROM accounted_scenario
            ), unexpected_scenario AS (
                SELECT * FROM accounted_scenario
                EXCEPT
                SELECT * FROM expected_scenario
            ), overlap_scenario AS (
                SELECT * FROM actual_scenario
                INTERSECT
                SELECT * FROM excluded_scenario
            )
            SELECT 'vehicle'::VARCHAR,
                   (SELECT count(*) FROM missing_vehicle),
                   (SELECT count(*) FROM unexpected_vehicle),
                   (SELECT count(*) FROM overlap_vehicle),
                   COALESCE((SELECT jsonb_agg(to_jsonb(row_value)) FROM missing_vehicle AS row_value),'[]'::jsonb),
                   COALESCE((SELECT jsonb_agg(to_jsonb(row_value)) FROM unexpected_vehicle AS row_value),'[]'::jsonb),
                   NOT EXISTS(SELECT 1 FROM missing_vehicle)
                       AND NOT EXISTS(SELECT 1 FROM unexpected_vehicle)
                       AND NOT EXISTS(SELECT 1 FROM overlap_vehicle)
            UNION ALL
            SELECT 'scenario'::VARCHAR,
                   (SELECT count(*) FROM missing_scenario),
                   (SELECT count(*) FROM unexpected_scenario),
                   (SELECT count(*) FROM overlap_scenario),
                   COALESCE((SELECT jsonb_agg(to_jsonb(row_value)) FROM missing_scenario AS row_value),'[]'::jsonb),
                   COALESCE((SELECT jsonb_agg(to_jsonb(row_value)) FROM unexpected_scenario AS row_value),'[]'::jsonb),
                   NOT EXISTS(SELECT 1 FROM missing_scenario)
                       AND NOT EXISTS(SELECT 1 FROM unexpected_scenario)
                       AND NOT EXISTS(SELECT 1 FROM overlap_scenario)
        $$"""
    )
    _execute(
        """CREATE FUNCTION gold.calculate_integrated_coverage_regression(p_dataset_version VARCHAR)
        RETURNS VARCHAR
        LANGUAGE plpgsql STABLE AS $$
        DECLARE
            candidate gold.integrated_vehicle_cost_dataset%ROWTYPE;
            baseline gold.integrated_vehicle_cost_coverage_baseline_current%ROWTYPE;
        BEGIN
            SELECT * INTO candidate FROM gold.integrated_vehicle_cost_dataset
            WHERE dataset_version=p_dataset_version;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Integrated dataset does not exist';
            END IF;
            SELECT * INTO baseline FROM gold.integrated_vehicle_cost_coverage_baseline_current
            ORDER BY baseline_event_id DESC LIMIT 1;
            IF NOT FOUND THEN
                RETURN 'not_applicable';
            END IF;
            IF candidate.catalog_coverage_pct<baseline.catalog_coverage_pct
               OR candidate.pbev_coverage_pct<baseline.pbev_coverage_pct THEN
                RETURN 'manual_review_required';
            END IF;
            RETURN 'passed';
        END $$"""
    )
    _execute(
        """CREATE FUNCTION gold.assert_integrated_downgrade_safe()
        RETURNS void LANGUAGE plpgsql AS $$
        BEGIN
            IF EXISTS (SELECT 1 FROM gold.integrated_vehicle_cost_dataset)
               OR EXISTS (SELECT 1 FROM gold.integrated_vehicle_cost_snapshot)
               OR EXISTS (SELECT 1 FROM gold.integrated_vehicle_cost_projection_snapshot)
               OR EXISTS (SELECT 1 FROM gold.integrated_vehicle_cost_flex_comparison_snapshot)
               OR EXISTS (SELECT 1 FROM gold.integrated_vehicle_cost_exclusion)
               OR EXISTS (SELECT 1 FROM gold.integrated_vehicle_cost_quality_result)
               OR EXISTS (SELECT 1 FROM gold.integrated_vehicle_cost_activation)
               OR EXISTS (SELECT 1 FROM gold.integrated_vehicle_cost_invalidation)
               OR EXISTS (SELECT 1 FROM gold.integrated_vehicle_cost_coverage_baseline) THEN
                RAISE EXCEPTION 'Integrated vehicle cost downgrade blocked: datasets or evidence exist';
            END IF;
        END $$"""
    )


def _create_guards() -> None:
    _execute(
        """CREATE FUNCTION gold.prevent_integrated_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'Integrated analytical evidence is immutable';
        END $$"""
    )
    for table in (
        "integrated_vehicle_cost_geography_request",
        "integrated_vehicle_cost_snapshot",
        "integrated_vehicle_cost_projection_snapshot",
        "integrated_vehicle_cost_flex_comparison_snapshot",
        "integrated_vehicle_cost_exclusion",
        "integrated_vehicle_cost_quality_rule_catalog",
        "integrated_vehicle_cost_quality_result",
        "integrated_vehicle_cost_activation",
        "integrated_vehicle_cost_invalidation",
        "integrated_vehicle_cost_coverage_baseline",
    ):
        _execute(
            f"""CREATE TRIGGER trg_{table}_immutable
            BEFORE UPDATE OR DELETE ON gold.{table}
            FOR EACH ROW EXECUTE FUNCTION gold.prevent_integrated_mutation()"""
        )
    _execute(
        """CREATE FUNCTION gold.guard_integrated_dataset_source()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE
            fipe_fingerprint CHAR(64);
            pbev_fingerprint CHAR(64);
            anp_fingerprint CHAR(64);
        BEGIN
            SELECT dataset_fingerprint INTO fipe_fingerprint
            FROM gold.vehicle_feature_dataset
            WHERE dataset_version=NEW.fipe_source_dataset_version;
            SELECT dataset_fingerprint INTO pbev_fingerprint
            FROM gold.vehicle_efficiency_dataset
            WHERE dataset_version=NEW.pbev_source_dataset_version;
            SELECT dataset_fingerprint INTO anp_fingerprint
            FROM gold.anp_fuel_price_dataset
            WHERE dataset_version=NEW.anp_source_dataset_version;
            IF fipe_fingerprint IS DISTINCT FROM NEW.fipe_source_fingerprint
               OR pbev_fingerprint IS DISTINCT FROM NEW.pbev_source_fingerprint
               OR anp_fingerprint IS DISTINCT FROM NEW.anp_source_fingerprint THEN
                RAISE EXCEPTION 'Integrated dataset fingerprints do not match pinned Gold sources';
            END IF;
            RETURN NEW;
        END $$"""
    )
    _execute(
        """CREATE TRIGGER trg_integrated_dataset_source
        BEFORE INSERT ON gold.integrated_vehicle_cost_dataset
        FOR EACH ROW EXECUTE FUNCTION gold.guard_integrated_dataset_source()"""
    )
    _execute(
        """CREATE FUNCTION gold.guard_integrated_building_insert()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE parent_status VARCHAR(20);
        BEGIN
            SELECT status INTO parent_status
            FROM gold.integrated_vehicle_cost_dataset
            WHERE dataset_version=NEW.dataset_version;
            IF parent_status IS DISTINCT FROM 'building' THEN
                RAISE EXCEPTION 'Integrated child inserts require a building dataset';
            END IF;
            RETURN NEW;
        END $$"""
    )
    for table in (
        "integrated_vehicle_cost_geography_request",
        "integrated_vehicle_cost_snapshot",
        "integrated_vehicle_cost_projection_snapshot",
        "integrated_vehicle_cost_flex_comparison_snapshot",
        "integrated_vehicle_cost_exclusion",
        "integrated_vehicle_cost_quality_result",
    ):
        _execute(
            f"""CREATE TRIGGER trg_{table}_building
            BEFORE INSERT ON gold.{table}
            FOR EACH ROW EXECUTE FUNCTION gold.guard_integrated_building_insert()"""
        )
    _execute(
        """CREATE FUNCTION gold.guard_integrated_snapshot_lineage()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE
            dataset_row gold.integrated_vehicle_cost_dataset%ROWTYPE;
            fipe_row gold.vehicle_features_snapshot%ROWTYPE;
            pbev_row gold.vehicle_efficiency_snapshot%ROWTYPE;
            anp_row gold.anp_fuel_price_snapshot%ROWTYPE;
            expected_city NUMERIC(10,4);
            expected_highway NUMERIC(10,4);
        BEGIN
            SELECT * INTO dataset_row FROM gold.integrated_vehicle_cost_dataset
            WHERE dataset_version=NEW.dataset_version;
            SELECT * INTO fipe_row FROM gold.vehicle_features_snapshot
            WHERE gold_record_id=NEW.fipe_gold_record_id;
            SELECT * INTO pbev_row FROM gold.vehicle_efficiency_snapshot
            WHERE gold_record_id=NEW.pbev_gold_record_id;
            SELECT * INTO anp_row FROM gold.anp_fuel_price_snapshot
            WHERE snapshot_id=NEW.anp_gold_snapshot_id;
            IF fipe_row.dataset_version IS DISTINCT FROM dataset_row.fipe_source_dataset_version
               OR pbev_row.dataset_version IS DISTINCT FROM dataset_row.pbev_source_dataset_version
               OR anp_row.dataset_version IS DISTINCT FROM dataset_row.anp_source_dataset_version
               OR fipe_row.vehicle_sk IS DISTINCT FROM NEW.vehicle_sk
               OR pbev_row.vehicle_sk IS DISTINCT FROM NEW.vehicle_sk THEN
                RAISE EXCEPTION 'Integrated snapshot Gold lineage does not match pinned sources';
            END IF;
            IF anp_row.product_code IS DISTINCT FROM NEW.fuel_scenario_code
               OR anp_row.week_start IS DISTINCT FROM NEW.anp_week_start
               OR anp_row.week_end IS DISTINCT FROM NEW.anp_week_end
               OR anp_row.geography_level IS DISTINCT FROM NEW.requested_geography_level
               OR anp_row.geography_key IS DISTINCT FROM NEW.requested_geography_key
               OR anp_row.currency_code IS DISTINCT FROM NEW.currency_code
               OR anp_row.unit_code IS DISTINCT FROM NEW.unit_code
               OR anp_row.median_price IS DISTINCT FROM NEW.fuel_price_per_liter_brl THEN
                RAISE EXCEPTION 'Integrated snapshot ANP lineage does not match requested scenario';
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM gold.integrated_vehicle_cost_geography_request AS request
                WHERE request.dataset_version=NEW.dataset_version
                  AND request.requested_geography_level=NEW.requested_geography_level
                  AND request.requested_geography_key=NEW.requested_geography_key
                  AND request.reference_week_start=NEW.anp_week_start
                  AND NEW.fuel_scenario_code=ANY(
                      request.required_product_codes||request.optional_product_codes
                  )
            ) THEN
                RAISE EXCEPTION 'Integrated snapshot does not belong to a declared geography request';
            END IF;
            IF NEW.fuel_scenario_code='ethanol_hydrated' THEN
                expected_city:=pbev_row.ethanol_city_km_l;
                expected_highway:=pbev_row.ethanol_highway_km_l;
            ELSE
                expected_city:=pbev_row.fossil_city_km_l;
                expected_highway:=pbev_row.fossil_highway_km_l;
            END IF;
            IF expected_city IS NULL OR expected_highway IS NULL
               OR expected_city IS DISTINCT FROM NEW.city_consumption_km_l
               OR expected_highway IS DISTINCT FROM NEW.highway_consumption_km_l
               OR fipe_row.current_price IS DISTINCT FROM NEW.vehicle_price_brl
               OR fipe_row.price_reference_month IS DISTINCT FROM NEW.price_reference_month
               OR pbev_row.cycle_year IS DISTINCT FROM NEW.pbev_cycle_year THEN
                RAISE EXCEPTION 'Integrated snapshot material metrics do not match Gold sources';
            END IF;
            IF fipe_row.published_at>dataset_row.analytic_cutoff_at
               OR pbev_row.published_at>dataset_row.analytic_cutoff_at
               OR anp_row.week_end>dataset_row.analytic_cutoff_at::date THEN
                RAISE EXCEPTION 'Integrated snapshot cannot use future source evidence';
            END IF;
            RETURN NEW;
        END $$"""
    )
    _execute(
        """CREATE TRIGGER trg_integrated_snapshot_lineage
        BEFORE INSERT ON gold.integrated_vehicle_cost_snapshot
        FOR EACH ROW EXECUTE FUNCTION gold.guard_integrated_snapshot_lineage()"""
    )
    _execute(
        """CREATE FUNCTION gold.guard_integrated_projection_conflict()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE snapshot_row gold.integrated_vehicle_cost_snapshot%ROWTYPE;
        BEGIN
            SELECT * INTO snapshot_row FROM gold.integrated_vehicle_cost_snapshot
            WHERE dataset_version=NEW.dataset_version AND snapshot_id=NEW.snapshot_id;
            IF EXISTS (
                SELECT 1 FROM gold.integrated_vehicle_cost_exclusion AS exclusion
                WHERE exclusion.dataset_version=NEW.dataset_version
                  AND exclusion.vehicle_sk=snapshot_row.vehicle_sk
                  AND (exclusion.exclusion_scope='vehicle' OR (
                      exclusion.exclusion_scope='scenario'
                      AND exclusion.scenario_code=NEW.scenario_code
                      AND exclusion.fuel_scenario_code=snapshot_row.fuel_scenario_code
                      AND exclusion.requested_geography_level=snapshot_row.requested_geography_level
                      AND exclusion.requested_geography_key=snapshot_row.requested_geography_key
                      AND exclusion.anp_week_start=snapshot_row.anp_week_start
                  ))
            ) THEN
                RAISE EXCEPTION 'Integrated projection conflicts with an exclusion';
            END IF;
            IF NEW.projected_monthly_cost_brl IS DISTINCT FROM
               ROUND(snapshot_row.mixed_cost_per_km_brl*NEW.monthly_distance_km,4) THEN
                RAISE EXCEPTION 'Integrated projection cost is inconsistent with its snapshot';
            END IF;
            RETURN NEW;
        END $$"""
    )
    _execute(
        """CREATE TRIGGER trg_integrated_projection_conflict
        BEFORE INSERT ON gold.integrated_vehicle_cost_projection_snapshot
        FOR EACH ROW EXECUTE FUNCTION gold.guard_integrated_projection_conflict()"""
    )
    _execute(
        """CREATE FUNCTION gold.guard_integrated_exclusion()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE dataset_row gold.integrated_vehicle_cost_dataset%ROWTYPE;
        BEGIN
            SELECT * INTO dataset_row FROM gold.integrated_vehicle_cost_dataset
            WHERE dataset_version=NEW.dataset_version;
            IF NOT EXISTS (
                SELECT 1 FROM gold.vehicle_features_snapshot
                WHERE gold_record_id=NEW.fipe_gold_record_id
                  AND dataset_version=dataset_row.fipe_source_dataset_version
                  AND vehicle_sk=NEW.vehicle_sk
            ) THEN
                RAISE EXCEPTION 'Integrated exclusion FIPE lineage is invalid';
            END IF;
            IF NEW.pbev_gold_record_id IS NOT NULL AND NOT EXISTS (
                SELECT 1 FROM gold.vehicle_efficiency_snapshot
                WHERE gold_record_id=NEW.pbev_gold_record_id
                  AND dataset_version=dataset_row.pbev_source_dataset_version
                  AND vehicle_sk=NEW.vehicle_sk
            ) THEN
                RAISE EXCEPTION 'Integrated exclusion PBEV lineage is invalid';
            END IF;
            IF NEW.exclusion_scope='scenario' AND NOT EXISTS (
                SELECT 1 FROM gold.integrated_expected_scenario_set(NEW.dataset_version) AS expected
                WHERE expected.vehicle_sk=NEW.vehicle_sk
                  AND expected.scenario_code=NEW.scenario_code
                  AND expected.fuel_scenario_code=NEW.fuel_scenario_code
                  AND expected.requested_geography_level=NEW.requested_geography_level
                  AND expected.requested_geography_key=NEW.requested_geography_key
                  AND expected.anp_week_start=NEW.anp_week_start
            ) THEN
                RAISE EXCEPTION 'Integrated scenario exclusion is outside the expected set';
            END IF;
            IF EXISTS (
                SELECT 1
                FROM gold.integrated_vehicle_cost_projection_snapshot AS projection
                JOIN gold.integrated_vehicle_cost_snapshot AS snapshot
                  ON snapshot.dataset_version=projection.dataset_version
                 AND snapshot.snapshot_id=projection.snapshot_id
                WHERE projection.dataset_version=NEW.dataset_version
                  AND snapshot.vehicle_sk=NEW.vehicle_sk
                  AND (NEW.exclusion_scope='vehicle' OR (
                      projection.scenario_code=NEW.scenario_code
                      AND snapshot.fuel_scenario_code=NEW.fuel_scenario_code
                      AND snapshot.requested_geography_level=NEW.requested_geography_level
                      AND snapshot.requested_geography_key=NEW.requested_geography_key
                      AND snapshot.anp_week_start=NEW.anp_week_start
                  ))
            ) THEN
                RAISE EXCEPTION 'Integrated exclusion conflicts with a projection';
            END IF;
            RETURN NEW;
        END $$"""
    )
    _execute(
        """CREATE TRIGGER trg_integrated_exclusion_lineage
        BEFORE INSERT ON gold.integrated_vehicle_cost_exclusion
        FOR EACH ROW EXECUTE FUNCTION gold.guard_integrated_exclusion()"""
    )
    _execute(
        """CREATE FUNCTION gold.guard_integrated_flex_comparison()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE
            gas_snapshot gold.integrated_vehicle_cost_snapshot%ROWTYPE;
            ethanol_snapshot gold.integrated_vehicle_cost_snapshot%ROWTYPE;
            gas_projection gold.integrated_vehicle_cost_projection_snapshot%ROWTYPE;
            ethanol_projection gold.integrated_vehicle_cost_projection_snapshot%ROWTYPE;
            expected_lower VARCHAR(40);
        BEGIN
            SELECT * INTO gas_projection FROM gold.integrated_vehicle_cost_projection_snapshot
            WHERE dataset_version=NEW.dataset_version AND projection_id=NEW.gasoline_projection_id;
            SELECT * INTO ethanol_projection FROM gold.integrated_vehicle_cost_projection_snapshot
            WHERE dataset_version=NEW.dataset_version AND projection_id=NEW.ethanol_projection_id;
            SELECT * INTO gas_snapshot FROM gold.integrated_vehicle_cost_snapshot
            WHERE dataset_version=NEW.dataset_version AND snapshot_id=gas_projection.snapshot_id;
            SELECT * INTO ethanol_snapshot FROM gold.integrated_vehicle_cost_snapshot
            WHERE dataset_version=NEW.dataset_version AND snapshot_id=ethanol_projection.snapshot_id;
            IF gas_snapshot.fuel_scenario_code NOT IN ('gasoline_c_common','gasoline_c_additized')
               OR ethanol_snapshot.fuel_scenario_code<>'ethanol_hydrated'
               OR gas_snapshot.vehicle_sk IS DISTINCT FROM ethanol_snapshot.vehicle_sk
               OR gas_snapshot.vehicle_sk IS DISTINCT FROM NEW.vehicle_sk
               OR gas_projection.scenario_code IS DISTINCT FROM NEW.scenario_code
               OR ethanol_projection.scenario_code IS DISTINCT FROM NEW.scenario_code
               OR gas_snapshot.requested_geography_level IS DISTINCT FROM ethanol_snapshot.requested_geography_level
               OR gas_snapshot.requested_geography_key IS DISTINCT FROM ethanol_snapshot.requested_geography_key
               OR gas_snapshot.anp_week_start IS DISTINCT FROM ethanol_snapshot.anp_week_start
               OR gas_snapshot.requested_geography_level IS DISTINCT FROM NEW.requested_geography_level
               OR gas_snapshot.requested_geography_key IS DISTINCT FROM NEW.requested_geography_key
               OR gas_snapshot.anp_week_start IS DISTINCT FROM NEW.anp_week_start THEN
                RAISE EXCEPTION 'Integrated flex comparison projections are not materially comparable';
            END IF;
            IF NEW.city_cost_difference_brl IS DISTINCT FROM
                    gas_snapshot.city_cost_per_km_brl-ethanol_snapshot.city_cost_per_km_brl
               OR NEW.highway_cost_difference_brl IS DISTINCT FROM
                    gas_snapshot.highway_cost_per_km_brl-ethanol_snapshot.highway_cost_per_km_brl
               OR NEW.mixed_cost_difference_brl IS DISTINCT FROM
                    gas_snapshot.mixed_cost_per_km_brl-ethanol_snapshot.mixed_cost_per_km_brl
               OR NEW.mixed_cost_difference_pct IS DISTINCT FROM
                    ROUND((gas_snapshot.mixed_cost_per_km_brl-ethanol_snapshot.mixed_cost_per_km_brl)
                          *100/gas_snapshot.mixed_cost_per_km_brl,4) THEN
                RAISE EXCEPTION 'Integrated flex comparison metrics are inconsistent';
            END IF;
            expected_lower:=CASE
                WHEN gas_snapshot.mixed_cost_per_km_brl<ethanol_snapshot.mixed_cost_per_km_brl
                    THEN gas_snapshot.fuel_scenario_code
                WHEN ethanol_snapshot.mixed_cost_per_km_brl<gas_snapshot.mixed_cost_per_km_brl
                    THEN 'ethanol_hydrated'
                ELSE 'tie' END;
            IF NEW.lower_cost_product_code IS DISTINCT FROM expected_lower THEN
                RAISE EXCEPTION 'Integrated flex comparison winner is inconsistent';
            END IF;
            RETURN NEW;
        END $$"""
    )
    _execute(
        """CREATE TRIGGER trg_integrated_flex_comparison
        BEFORE INSERT ON gold.integrated_vehicle_cost_flex_comparison_snapshot
        FOR EACH ROW EXECUTE FUNCTION gold.guard_integrated_flex_comparison()"""
    )
    _execute(
        """CREATE FUNCTION gold.guard_integrated_quality_result()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE catalog_row gold.integrated_vehicle_cost_quality_rule_catalog%ROWTYPE;
        BEGIN
            SELECT * INTO catalog_row FROM gold.integrated_vehicle_cost_quality_rule_catalog
            WHERE quality_policy_version=NEW.quality_policy_version AND rule_code=NEW.rule_code;
            IF catalog_row.rule_code IS NULL
               OR catalog_row.rule_kind IS DISTINCT FROM NEW.rule_kind
               OR catalog_row.severity IS DISTINCT FROM NEW.severity THEN
                RAISE EXCEPTION 'Integrated quality evidence does not match its policy catalog';
            END IF;
            RETURN NEW;
        END $$"""
    )
    _execute(
        """CREATE TRIGGER trg_integrated_quality_result_catalog
        BEFORE INSERT ON gold.integrated_vehicle_cost_quality_result
        FOR EACH ROW EXECUTE FUNCTION gold.guard_integrated_quality_result()"""
    )
    _execute(
        """CREATE FUNCTION gold.guard_integrated_dataset_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP='DELETE' THEN
                RAISE EXCEPTION 'Integrated datasets cannot be deleted';
            END IF;
            IF ROW(NEW.dataset_version,NEW.publication_run_id,NEW.fipe_source_dataset_version,
                   NEW.pbev_source_dataset_version,NEW.anp_source_dataset_version,
                   NEW.fipe_source_fingerprint,NEW.pbev_source_fingerprint,
                   NEW.anp_source_fingerprint,NEW.analytic_cutoff_at,
                   NEW.calculation_policy_version,NEW.geography_policy_version,
                   NEW.scenario_policy_version,NEW.quality_policy_version,
                   NEW.request_manifest,NEW.dataset_fingerprint,NEW.created_at)
               IS DISTINCT FROM
               ROW(OLD.dataset_version,OLD.publication_run_id,OLD.fipe_source_dataset_version,
                   OLD.pbev_source_dataset_version,OLD.anp_source_dataset_version,
                   OLD.fipe_source_fingerprint,OLD.pbev_source_fingerprint,
                   OLD.anp_source_fingerprint,OLD.analytic_cutoff_at,
                   OLD.calculation_policy_version,OLD.geography_policy_version,
                   OLD.scenario_policy_version,OLD.quality_policy_version,
                   OLD.request_manifest,OLD.dataset_fingerprint,OLD.created_at) THEN
                RAISE EXCEPTION 'Integrated dataset identity and source content are immutable';
            END IF;
            IF NEW.first_published_at IS DISTINCT FROM OLD.first_published_at
               AND NOT (OLD.status='building' AND NEW.status='shadow_published'
                       AND OLD.first_published_at IS NULL AND NEW.first_published_at IS NOT NULL) THEN
                RAISE EXCEPTION 'Integrated first publication timestamp is immutable';
            END IF;
            IF OLD.status<>'building' AND ROW(
                   NEW.catalog_universe_count,NEW.pbev_matched_universe_count,
                   NEW.eligible_vehicle_count,NEW.published_vehicle_count,
                   NEW.excluded_vehicle_count,NEW.requested_scenario_count,
                   NEW.published_scenario_count,NEW.excluded_scenario_count,
                   NEW.snapshot_row_count,NEW.projection_row_count,NEW.flex_comparison_count,
                   NEW.catalog_coverage_pct,NEW.pbev_coverage_pct,
                   NEW.coverage_baseline_event_id_used,NEW.coverage_regression_status,
                   NEW.hard_gate_status,NEW.statistical_calibration_status,NEW.quality_status)
               IS DISTINCT FROM ROW(
                   OLD.catalog_universe_count,OLD.pbev_matched_universe_count,
                   OLD.eligible_vehicle_count,OLD.published_vehicle_count,
                   OLD.excluded_vehicle_count,OLD.requested_scenario_count,
                   OLD.published_scenario_count,OLD.excluded_scenario_count,
                   OLD.snapshot_row_count,OLD.projection_row_count,OLD.flex_comparison_count,
                   OLD.catalog_coverage_pct,OLD.pbev_coverage_pct,
                   OLD.coverage_baseline_event_id_used,OLD.coverage_regression_status,
                   OLD.hard_gate_status,OLD.statistical_calibration_status,OLD.quality_status) THEN
                RAISE EXCEPTION 'Published integrated dataset evidence is immutable';
            END IF;
            IF NOT (
                OLD.status=NEW.status OR
                (OLD.status='building' AND NEW.status='shadow_published') OR
                (OLD.status='shadow_published' AND NEW.status='retired') OR
                (OLD.status='retired' AND NEW.status='shadow_published')
            ) THEN
                RAISE EXCEPTION 'Invalid integrated dataset lifecycle transition';
            END IF;
            RETURN NEW;
        END $$"""
    )
    _execute(
        """CREATE TRIGGER trg_integrated_dataset_guard
        BEFORE UPDATE OR DELETE ON gold.integrated_vehicle_cost_dataset
        FOR EACH ROW EXECUTE FUNCTION gold.guard_integrated_dataset_mutation()"""
    )
    _execute(
        """CREATE FUNCTION gold.validate_integrated_activation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE
            target gold.integrated_vehicle_cost_dataset%ROWTYPE;
            active_version VARCHAR(96);
            current_baseline_id BIGINT;
            computed_regression VARCHAR(30);
        BEGIN
            PERFORM pg_advisory_xact_lock(hashtext('gold.integrated_vehicle_cost_activation'));
            SELECT * INTO target FROM gold.integrated_vehicle_cost_dataset
            WHERE dataset_version=NEW.dataset_version FOR UPDATE;
            SELECT dataset_version INTO active_version
            FROM gold.integrated_vehicle_cost_dataset WHERE is_active_shadow FOR UPDATE;
            IF NEW.activation_type='publish' THEN
                IF active_version IS NOT NULL OR target.status<>'building' THEN
                    RAISE EXCEPTION 'Initial integrated publication requires no active dataset and a building target';
                END IF;
            ELSE
                IF active_version IS DISTINCT FROM NEW.previous_dataset_version THEN
                    RAISE EXCEPTION 'Integrated replacement or rollback must name the active dataset';
                END IF;
                IF NEW.activation_type='replace' AND target.status<>'building' THEN
                    RAISE EXCEPTION 'Integrated replacement requires a building target';
                END IF;
                IF NEW.activation_type='rollback' AND target.status<>'retired' THEN
                    RAISE EXCEPTION 'Integrated rollback requires a retired target';
                END IF;
            END IF;
            IF EXISTS (
                SELECT 1 FROM gold.integrated_vehicle_cost_invalidation
                WHERE dataset_version=NEW.dataset_version
            ) THEN
                RAISE EXCEPTION 'Invalidated integrated datasets cannot be activated';
            END IF;
            IF target.quality_status<>'passed' OR target.hard_gate_status<>'passed'
               OR target.statistical_calibration_status<>'not_calibrated'
               OR target.coverage_regression_status='manual_review_required' THEN
                RAISE EXCEPTION 'Integrated dataset quality does not authorize activation';
            END IF;
            SELECT baseline_event_id INTO current_baseline_id
            FROM gold.integrated_vehicle_cost_coverage_baseline_current
            ORDER BY baseline_event_id DESC LIMIT 1;
            computed_regression:=gold.calculate_integrated_coverage_regression(
                NEW.dataset_version
            );
            IF target.coverage_regression_status IS DISTINCT FROM computed_regression
               OR (computed_regression='not_applicable'
                   AND target.coverage_baseline_event_id_used IS NOT NULL)
               OR (computed_regression<>'not_applicable'
                   AND target.coverage_baseline_event_id_used IS DISTINCT FROM current_baseline_id) THEN
                RAISE EXCEPTION 'Integrated coverage regression evidence is stale or inconsistent';
            END IF;
            IF EXISTS (
                SELECT 1
                FROM gold.integrated_vehicle_cost_quality_rule_catalog AS catalog
                WHERE catalog.quality_policy_version=target.quality_policy_version
                  AND catalog.required_for_activation
                  AND NOT EXISTS (
                      SELECT 1 FROM gold.integrated_vehicle_cost_quality_result AS result
                      WHERE result.dataset_version=target.dataset_version
                        AND result.quality_policy_version=catalog.quality_policy_version
                        AND result.rule_code=catalog.rule_code
                        AND result.rule_kind=catalog.rule_kind
                        AND result.severity=catalog.severity
                        AND result.status=catalog.expected_status
                  )
            ) THEN
                RAISE EXCEPTION 'Integrated activation lacks policy-scoped quality evidence';
            END IF;
            IF EXISTS (
                SELECT 1 FROM gold.reconcile_integrated_sets(NEW.dataset_version)
                WHERE NOT is_reconciled
            ) THEN
                RAISE EXCEPTION 'Integrated activation failed set reconciliation';
            END IF;
            RETURN NEW;
        END $$"""
    )
    _execute(
        """CREATE TRIGGER trg_integrated_activation_validate
        BEFORE INSERT ON gold.integrated_vehicle_cost_activation
        FOR EACH ROW EXECUTE FUNCTION gold.validate_integrated_activation()"""
    )
    _execute(
        """CREATE FUNCTION gold.apply_integrated_activation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.previous_dataset_version IS NOT NULL THEN
                UPDATE gold.integrated_vehicle_cost_dataset
                SET status='retired',is_active_shadow=FALSE,retired_at=NEW.activated_at
                WHERE dataset_version=NEW.previous_dataset_version;
            END IF;
            UPDATE gold.integrated_vehicle_cost_dataset
            SET status='shadow_published',is_active_shadow=TRUE,
                first_published_at=COALESCE(first_published_at,NEW.activated_at),
                last_activated_at=NEW.activated_at,retired_at=NULL,
                last_activation_event_id=NEW.activation_event_id,
                activation_run_id=NEW.activation_run_id
            WHERE dataset_version=NEW.dataset_version;
            RETURN NEW;
        END $$"""
    )
    _execute(
        """CREATE TRIGGER trg_integrated_activation_apply
        AFTER INSERT ON gold.integrated_vehicle_cost_activation
        FOR EACH ROW EXECUTE FUNCTION gold.apply_integrated_activation()"""
    )
    _execute(
        """CREATE FUNCTION gold.apply_integrated_invalidation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            UPDATE gold.integrated_vehicle_cost_dataset
            SET status='retired',is_active_shadow=FALSE,retired_at=NEW.invalidated_at
            WHERE dataset_version=NEW.dataset_version AND status='shadow_published';
            RETURN NEW;
        END $$"""
    )
    _execute(
        """CREATE TRIGGER trg_integrated_invalidation_apply
        AFTER INSERT ON gold.integrated_vehicle_cost_invalidation
        FOR EACH ROW EXECUTE FUNCTION gold.apply_integrated_invalidation()"""
    )
    _execute(
        """CREATE FUNCTION gold.guard_integrated_baseline_insert()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE
            candidate gold.integrated_vehicle_cost_coverage_baseline%ROWTYPE;
            dataset_row gold.integrated_vehicle_cost_dataset%ROWTYPE;
            current_baseline_id BIGINT;
        BEGIN
            PERFORM pg_advisory_xact_lock(hashtext('gold.integrated_vehicle_cost_coverage_baseline'));
            SELECT * INTO dataset_row FROM gold.integrated_vehicle_cost_dataset
            WHERE dataset_version=NEW.dataset_version;
            IF dataset_row.status NOT IN ('shadow_published','retired')
               OR dataset_row.quality_policy_version IS DISTINCT FROM NEW.quality_policy_version
               OR dataset_row.catalog_coverage_pct IS DISTINCT FROM NEW.catalog_coverage_pct
               OR dataset_row.pbev_coverage_pct IS DISTINCT FROM NEW.pbev_coverage_pct THEN
                RAISE EXCEPTION 'Integrated baseline must preserve published dataset evidence';
            END IF;
            SELECT baseline_event_id INTO current_baseline_id
            FROM gold.integrated_vehicle_cost_coverage_baseline_current
            ORDER BY baseline_event_id DESC LIMIT 1;
            IF NEW.status='active' THEN
                SELECT * INTO candidate FROM gold.integrated_vehicle_cost_coverage_baseline
                WHERE baseline_event_id=NEW.candidate_event_id;
                IF candidate.status IS DISTINCT FROM 'candidate'
                   OR candidate.dataset_version IS DISTINCT FROM NEW.dataset_version
                   OR candidate.catalog_coverage_pct IS DISTINCT FROM NEW.catalog_coverage_pct
                   OR candidate.pbev_coverage_pct IS DISTINCT FROM NEW.pbev_coverage_pct THEN
                    RAISE EXCEPTION 'Integrated baseline activation must preserve its candidate evidence';
                END IF;
                IF (current_baseline_id IS NULL AND NEW.supersedes_baseline_event_id IS NOT NULL)
                   OR (current_baseline_id IS NOT NULL
                       AND NEW.supersedes_baseline_event_id IS DISTINCT FROM current_baseline_id) THEN
                    RAISE EXCEPTION 'Integrated baseline activation must supersede the current baseline';
                END IF;
            ELSIF NEW.status='revoked'
                  AND NEW.supersedes_baseline_event_id IS DISTINCT FROM current_baseline_id THEN
                RAISE EXCEPTION 'Integrated baseline revocation must supersede the current baseline';
            END IF;
            RETURN NEW;
        END $$"""
    )
    _execute(
        """CREATE TRIGGER trg_integrated_baseline_insert
        BEFORE INSERT ON gold.integrated_vehicle_cost_coverage_baseline
        FOR EACH ROW EXECUTE FUNCTION gold.guard_integrated_baseline_insert()"""
    )


def _seed_quality_catalog() -> None:
    values = []
    for rule_code in HARD_GATE_RULES:
        values.append(
            f"('{QUALITY_POLICY_VERSION}','{rule_code}','hard_gate','critical',TRUE,'passed',"
            f"'Hard gate {rule_code} for integrated vehicle cost publication')"
        )
    for rule_code in STATISTICAL_RULES:
        values.append(
            f"('{QUALITY_POLICY_VERSION}','{rule_code}','statistical_control','info',TRUE,"
            f"'not_calibrated','ANP statistical control retained as explicitly not calibrated')"
        )
    _execute(
        "INSERT INTO gold.integrated_vehicle_cost_quality_rule_catalog "
        "(quality_policy_version,rule_code,rule_kind,severity,required_for_activation,"
        "expected_status,description) VALUES " + ",".join(values)
    )


def upgrade() -> None:
    # A Gold analitica integrada permanece PostgreSQL-only; SQLite e no-op.
    if not _is_postgresql():
        return
    _create_tables()
    _create_set_functions()
    _create_guards()
    _seed_quality_catalog()


def downgrade() -> None:
    if not _is_postgresql():
        return
    _execute("SELECT gold.assert_integrated_downgrade_safe()")
    _execute("DROP TRIGGER trg_integrated_baseline_insert ON gold.integrated_vehicle_cost_coverage_baseline")
    _execute("DROP FUNCTION gold.guard_integrated_baseline_insert()")
    _execute("DROP TRIGGER trg_integrated_invalidation_apply ON gold.integrated_vehicle_cost_invalidation")
    _execute("DROP FUNCTION gold.apply_integrated_invalidation()")
    _execute("DROP TRIGGER trg_integrated_activation_apply ON gold.integrated_vehicle_cost_activation")
    _execute("DROP FUNCTION gold.apply_integrated_activation()")
    _execute("DROP TRIGGER trg_integrated_activation_validate ON gold.integrated_vehicle_cost_activation")
    _execute("DROP FUNCTION gold.validate_integrated_activation()")
    _execute("DROP TRIGGER trg_integrated_dataset_guard ON gold.integrated_vehicle_cost_dataset")
    _execute("DROP FUNCTION gold.guard_integrated_dataset_mutation()")
    _execute("DROP TRIGGER trg_integrated_dataset_source ON gold.integrated_vehicle_cost_dataset")
    _execute("DROP FUNCTION gold.guard_integrated_dataset_source()")
    _execute("DROP TRIGGER trg_integrated_quality_result_catalog ON gold.integrated_vehicle_cost_quality_result")
    _execute("DROP FUNCTION gold.guard_integrated_quality_result()")
    _execute("DROP TRIGGER trg_integrated_flex_comparison ON gold.integrated_vehicle_cost_flex_comparison_snapshot")
    _execute("DROP FUNCTION gold.guard_integrated_flex_comparison()")
    _execute("DROP TRIGGER trg_integrated_exclusion_lineage ON gold.integrated_vehicle_cost_exclusion")
    _execute("DROP FUNCTION gold.guard_integrated_exclusion()")
    _execute("DROP TRIGGER trg_integrated_projection_conflict ON gold.integrated_vehicle_cost_projection_snapshot")
    _execute("DROP FUNCTION gold.guard_integrated_projection_conflict()")
    _execute("DROP TRIGGER trg_integrated_snapshot_lineage ON gold.integrated_vehicle_cost_snapshot")
    _execute("DROP FUNCTION gold.guard_integrated_snapshot_lineage()")
    for table in reversed(
        (
            "integrated_vehicle_cost_geography_request",
            "integrated_vehicle_cost_snapshot",
            "integrated_vehicle_cost_projection_snapshot",
            "integrated_vehicle_cost_flex_comparison_snapshot",
            "integrated_vehicle_cost_exclusion",
            "integrated_vehicle_cost_quality_result",
        )
    ):
        _execute(f"DROP TRIGGER trg_{table}_building ON gold.{table}")
    _execute("DROP FUNCTION gold.guard_integrated_building_insert()")
    for table in reversed(
        (
            "integrated_vehicle_cost_geography_request",
            "integrated_vehicle_cost_snapshot",
            "integrated_vehicle_cost_projection_snapshot",
            "integrated_vehicle_cost_flex_comparison_snapshot",
            "integrated_vehicle_cost_exclusion",
            "integrated_vehicle_cost_quality_rule_catalog",
            "integrated_vehicle_cost_quality_result",
            "integrated_vehicle_cost_activation",
            "integrated_vehicle_cost_invalidation",
            "integrated_vehicle_cost_coverage_baseline",
        )
    ):
        _execute(f"DROP TRIGGER trg_{table}_immutable ON gold.{table}")
    _execute("DROP FUNCTION gold.prevent_integrated_mutation()")
    _execute("DROP FUNCTION gold.assert_integrated_downgrade_safe()")
    _execute("DROP FUNCTION gold.calculate_integrated_coverage_regression(VARCHAR)")
    _execute("DROP FUNCTION gold.reconcile_integrated_sets(VARCHAR)")
    _execute("DROP FUNCTION gold.integrated_expected_scenario_set(VARCHAR)")
    _execute("DROP FUNCTION gold.integrated_pbev_eligible_vehicle_set(VARCHAR)")
    _execute("DROP FUNCTION gold.integrated_expected_vehicle_set(VARCHAR)")
    _execute("DROP VIEW gold.integrated_vehicle_cost_coverage_baseline_current")
    _execute("ALTER TABLE gold.integrated_vehicle_cost_dataset DROP CONSTRAINT fk_integrated_dataset_coverage_baseline")
    _execute("ALTER TABLE gold.integrated_vehicle_cost_dataset DROP CONSTRAINT fk_integrated_dataset_last_activation")
    for table in (
        "integrated_vehicle_cost_coverage_baseline",
        "integrated_vehicle_cost_invalidation",
        "integrated_vehicle_cost_activation",
        "integrated_vehicle_cost_quality_result",
        "integrated_vehicle_cost_quality_rule_catalog",
        "integrated_vehicle_cost_exclusion",
        "integrated_vehicle_cost_flex_comparison_snapshot",
        "integrated_vehicle_cost_projection_snapshot",
        "integrated_vehicle_cost_snapshot",
        "integrated_vehicle_cost_geography_request",
        "integrated_vehicle_cost_dataset",
    ):
        _execute(f"DROP TABLE gold.{table}")
