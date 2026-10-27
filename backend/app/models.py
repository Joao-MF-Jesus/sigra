from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, Float, ForeignKey, Index, Integer, JSON, Numeric, String, Text, UniqueConstraint, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from app.database import Base


MONEY_TYPE = Numeric(14, 2)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"
    __table_args__ = (CheckConstraint("role IN ('participant', 'admin')", name="ck_users_role"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    email: Mapped[str] = mapped_column(String(160), unique=True, nullable=False)
    normalized_email: Mapped[str | None] = mapped_column(String(160), unique=True, nullable=True)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    role: Mapped[str] = mapped_column(String(20), default="participant", server_default="participant", nullable=False)

    expenses: Mapped[list["Expense"]] = relationship(back_populates="user")
    maintenances: Mapped[list["Maintenance"]] = relationship(back_populates="user")
    user_vehicles: Mapped[list["UserVehicle"]] = relationship(back_populates="user")


class AuthSession(Base):
    __tablename__ = "auth_sessions"
    token_digest: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ParticipantTestRun(Base):
    __tablename__ = "participant_test_runs"
    __table_args__ = (
        CheckConstraint("feedback_rating IS NULL OR feedback_rating BETWEEN 1 AND 5", name="ck_test_run_rating"),
        Index("ix_test_runs_owner_created", "user_id", "created_at", "id"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    system_version: Mapped[str] = mapped_column(String(80), nullable=False)
    method_version: Mapped[str] = mapped_column(String(160), nullable=False)
    snapshot_version: Mapped[str | None] = mapped_column(String(80), nullable=True)
    snapshot_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    parameters: Mapped[dict] = mapped_column(JSON, nullable=False)
    presented_results: Mapped[dict] = mapped_column(JSON, nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    result_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    feedback_rating: Mapped[int | None] = mapped_column(Integer, nullable=True)
    feedback_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    feedback_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    study_session_id: Mapped[str | None] = mapped_column(ForeignKey("participant_study_sessions.id", ondelete="RESTRICT"), nullable=True)
    technical_record: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class ParticipantStudySession(Base):
    __tablename__ = "participant_study_sessions"
    __table_args__ = (
        CheckConstraint("scenario_id IN ('A','B','C','D','E')", name="ck_study_scenario"),
        CheckConstraint("familiarity IN ('none','low','medium','high')", name="ck_study_familiarity"),
        Index("ix_study_owner_auth_created", "user_id", "auth_session_digest", "created_at"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    auth_session_digest: Mapped[str] = mapped_column(ForeignKey("auth_sessions.token_digest", ondelete="RESTRICT"), nullable=False)
    scenario_id: Mapped[str] = mapped_column(String(1), nullable=False)
    familiarity: Mapped[str] = mapped_column(String(10), nullable=False)
    priorities: Mapped[list] = mapped_column(JSON, nullable=False)
    protocol_version: Mapped[str] = mapped_column(String(80), nullable=False)
    presentation_version: Mapped[str] = mapped_column(String(80), nullable=False)
    environment_tag: Mapped[str] = mapped_column(String(40), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class ParticipantQuestionnaire(Base):
    __tablename__ = "participant_questionnaires"
    __table_args__ = tuple(CheckConstraint(f"{name} BETWEEN 1 AND 5", name=f"ck_questionnaire_{name}")
                           for name in ("interface_clarity", "first_vehicle_explanation", "scenario_coherence", "influential_criteria"))
    run_id: Mapped[str] = mapped_column(ForeignKey("participant_test_runs.id", ondelete="RESTRICT"), primary_key=True)
    version: Mapped[str] = mapped_column(String(80), nullable=False)
    interface_clarity: Mapped[int] = mapped_column(Integer, nullable=False)
    first_vehicle_explanation: Mapped[int] = mapped_column(Integer, nullable=False)
    scenario_coherence: Mapped[int] = mapped_column(Integer, nullable=False)
    influential_criteria: Mapped[int] = mapped_column(Integer, nullable=False)
    comment: Mapped[str] = mapped_column(Text, nullable=False, default="")
    answered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class SigraSchemaMigration(Base):
    __tablename__ = "sigra_schema_migrations"

    version: Mapped[str] = mapped_column(String(40), primary_key=True)
    applied_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Vehicle(Base):
    __tablename__ = "vehicles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    brand: Mapped[str] = mapped_column(String(80), nullable=False)
    model: Mapped[str] = mapped_column(String(120), nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    price: Mapped[Decimal] = mapped_column(MONEY_TYPE, nullable=False)
    fuel_efficiency_km_l: Mapped[float] = mapped_column(Float, nullable=False)
    annual_maintenance_cost: Mapped[Decimal] = mapped_column(MONEY_TYPE, nullable=False)
    reliability_score: Mapped[float] = mapped_column(Float, nullable=False)
    parts_availability_score: Mapped[float] = mapped_column(Float, nullable=False)
    depreciation_rate: Mapped[float] = mapped_column(Float, nullable=False)
    use_cases: Mapped[str] = mapped_column(Text, default="", nullable=False)
    chronic_issues: Mapped[str] = mapped_column(Text, default="", nullable=False)
    image_url: Mapped[str] = mapped_column(String(240), default="", nullable=False)
    category: Mapped[str] = mapped_column(String(60), default="compact", nullable=False)
    segment_level: Mapped[int] = mapped_column(Integer, default=2, nullable=False)
    comfort_score: Mapped[float] = mapped_column(Float, default=60, nullable=False)
    space_score: Mapped[float] = mapped_column(Float, default=60, nullable=False)
    safety_score: Mapped[float] = mapped_column(Float, default=60, nullable=False)
    urban_score: Mapped[float] = mapped_column(Float, default=70, nullable=False)
    road_score: Mapped[float] = mapped_column(Float, default=60, nullable=False)
    family_score: Mapped[float] = mapped_column(Float, default=60, nullable=False)
    app_score: Mapped[float] = mapped_column(Float, default=60, nullable=False)
    vehicle_type: Mapped[str] = mapped_column(String(20), default="car", server_default="car", nullable=False)

    expenses: Mapped[list["Expense"]] = relationship(back_populates="vehicle")
    maintenances: Mapped[list["Maintenance"]] = relationship(back_populates="vehicle")
    user_vehicles: Mapped[list["UserVehicle"]] = relationship(back_populates="vehicle")
    reports: Mapped[list["VehicleReport"]] = relationship(back_populates="vehicle")
    consumption_reports: Mapped[list["FuelConsumptionReport"]] = relationship(back_populates="vehicle")
    part_prices: Mapped[list["PartPrice"]] = relationship(back_populates="vehicle")
    part_compatibilities: Mapped[list["VehiclePartCompatibility"]] = relationship(
        foreign_keys="VehiclePartCompatibility.vehicle_id",
        back_populates="vehicle",
    )

    @validates("vehicle_type")
    def validate_vehicle_type(self, _key: str, value: str) -> str:
        if value != "car":
            raise ValueError("A tabela vehicles aceita apenas automóveis")
        return value


class Motorcycle(Base):
    __tablename__ = "motorcycles"
    __table_args__ = (
        CheckConstraint("price > 0", name="ck_motorcycles_price_positive"),
        CheckConstraint("city_consumption > 0", name="ck_motorcycles_city_consumption_positive"),
        CheckConstraint("road_consumption > 0", name="ck_motorcycles_road_consumption_positive"),
        CheckConstraint("annual_maintenance_cost IS NULL OR annual_maintenance_cost >= 0", name="ck_motorcycles_maintenance_nonnegative"),
        CheckConstraint("reliability_score IS NULL OR reliability_score BETWEEN 0 AND 100", name="ck_motorcycles_reliability_range"),
        CheckConstraint("parts_availability_score IS NULL OR parts_availability_score BETWEEN 0 AND 100", name="ck_motorcycles_parts_range"),
        CheckConstraint("depreciation_rate IS NULL OR depreciation_rate >= 0", name="ck_motorcycles_depreciation_nonnegative"),
        CheckConstraint("data_confidence IS NULL OR data_confidence BETWEEN 0 AND 100", name="ck_motorcycles_confidence_range"),
        CheckConstraint("vehicle_type = 'motorcycle'", name="ck_motorcycles_vehicle_type"),
        Index("ix_motorcycles_brand_model_year", "brand", "model", "year"),
        Index("ix_motorcycles_data_source", "data_source"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    brand: Mapped[str] = mapped_column(String(80), nullable=False)
    model: Mapped[str] = mapped_column(String(120), nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    price: Mapped[Decimal] = mapped_column(MONEY_TYPE, nullable=False)
    city_consumption: Mapped[float] = mapped_column(Float, nullable=False)
    road_consumption: Mapped[float] = mapped_column(Float, nullable=False)
    annual_maintenance_cost: Mapped[Decimal | None] = mapped_column(MONEY_TYPE, nullable=True)
    reliability_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    parts_availability_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    depreciation_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    data_source: Mapped[str | None] = mapped_column(String(30), nullable=True)
    data_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    source_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    source_reference: Mapped[str | None] = mapped_column(String(240), nullable=True)
    source_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    source_collected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source_reference_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    vehicle_type: Mapped[str] = mapped_column(String(20), default="motorcycle", server_default="motorcycle", nullable=False)
    image_url: Mapped[str] = mapped_column(String(240), default="", server_default="", nullable=False)

    version: Mapped[str | None] = mapped_column(String(120), nullable=True)
    market_condition: Mapped[str | None] = mapped_column(String(20), nullable=True)
    fuel_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    price_reference_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_demonstration: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false"), nullable=False
    )

    specifications: Mapped["MotorcycleSpecification | None"] = relationship(
        back_populates="motorcycle",
        cascade="all, delete-orphan",
        uselist=False,
    )
    objective_specifications: Mapped["MotorcycleObjectiveSpecification | None"] = relationship(
        back_populates="motorcycle",
        cascade="all, delete-orphan",
        uselist=False,
    )
    data_sources: Mapped[list["MotorcycleDataSource"]] = relationship(
        back_populates="motorcycle",
        cascade="all, delete-orphan",
    )
    derived_metrics: Mapped[list["MotorcycleDerivedMetric"]] = relationship(
        back_populates="motorcycle",
        cascade="all, delete-orphan",
    )
    economic_estimates: Mapped[list["MotorcycleEconomicEstimate"]] = relationship(
        back_populates="motorcycle",
        cascade="all, delete-orphan",
    )

    @validates("vehicle_type")
    def validate_vehicle_type(self, _key: str, value: str) -> str:
        if value != "motorcycle":
            raise ValueError("A tabela motorcycles aceita apenas motocicletas")
        return value


class MotorcycleSpecification(Base):
    __tablename__ = "motorcycle_specifications"
    __table_args__ = (
        CheckConstraint("engine_displacement_cc > 0 AND engine_displacement_cc <= 3000", name="ck_motorcycle_specs_displacement"),
        CheckConstraint("wet_weight_kg >= 20 AND wet_weight_kg <= 600", name="ck_motorcycle_specs_weight"),
        CheckConstraint("seat_height_mm >= 400 AND seat_height_mm <= 1200", name="ck_motorcycle_specs_seat"),
        CheckConstraint("tank_capacity_l >= 1 AND tank_capacity_l <= 50", name="ck_motorcycle_specs_tank"),
        CheckConstraint("urban_score BETWEEN 0 AND 100", name="ck_motorcycle_specs_urban"),
        CheckConstraint("road_score BETWEEN 0 AND 100", name="ck_motorcycle_specs_road"),
        CheckConstraint("passenger_comfort_score BETWEEN 0 AND 100", name="ck_motorcycle_specs_passenger"),
        CheckConstraint("luggage_score BETWEEN 0 AND 100", name="ck_motorcycle_specs_luggage"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    motorcycle_id: Mapped[int] = mapped_column(ForeignKey("motorcycles.id", ondelete="CASCADE"), unique=True, nullable=False)
    engine_displacement_cc: Mapped[float] = mapped_column(Float, nullable=False)
    motorcycle_category: Mapped[str] = mapped_column(String(30), nullable=False)
    wet_weight_kg: Mapped[float] = mapped_column(Float, nullable=False)
    seat_height_mm: Mapped[float] = mapped_column(Float, nullable=False)
    tank_capacity_l: Mapped[float] = mapped_column(Float, nullable=False)
    has_abs: Mapped[bool] = mapped_column(Boolean, nullable=False)
    recommended_experience: Mapped[str] = mapped_column(String(30), nullable=False)
    urban_score: Mapped[float] = mapped_column(Float, nullable=False)
    road_score: Mapped[float] = mapped_column(Float, nullable=False)
    passenger_comfort_score: Mapped[float] = mapped_column(Float, nullable=False)
    luggage_score: Mapped[float] = mapped_column(Float, nullable=False)

    motorcycle: Mapped[Motorcycle] = relationship(back_populates="specifications")


class MotorcycleObjectiveSpecification(Base):
    __tablename__ = "motorcycle_objective_specifications"
    __table_args__ = (
        CheckConstraint("engine_displacement_cc > 0 AND engine_displacement_cc <= 3000", name="ck_motorcycle_objective_displacement"),
        CheckConstraint("wet_weight_kg >= 20 AND wet_weight_kg <= 600", name="ck_motorcycle_objective_weight"),
        CheckConstraint("seat_height_mm >= 400 AND seat_height_mm <= 1200", name="ck_motorcycle_objective_seat"),
        CheckConstraint("tank_capacity_l >= 1 AND tank_capacity_l <= 50", name="ck_motorcycle_objective_tank"),
        CheckConstraint("power_cv IS NULL OR power_cv > 0", name="ck_motorcycle_objective_power"),
        CheckConstraint("torque_nm IS NULL OR torque_nm > 0", name="ck_motorcycle_objective_torque"),
        CheckConstraint("gear_count IS NULL OR gear_count BETWEEN 1 AND 12", name="ck_motorcycle_objective_gears"),
        CheckConstraint("payload_capacity_kg IS NULL OR payload_capacity_kg > 0", name="ck_motorcycle_objective_payload"),
        CheckConstraint("oil_change_interval_km IS NULL OR oil_change_interval_km > 0", name="ck_motorcycle_objective_oil_interval"),
        CheckConstraint("abs_channels IS NULL OR abs_channels BETWEEN 0 AND 2", name="ck_motorcycle_objective_abs_channels"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    motorcycle_id: Mapped[int] = mapped_column(ForeignKey("motorcycles.id", ondelete="CASCADE"), unique=True, nullable=False)
    engine_displacement_cc: Mapped[float] = mapped_column(Float, nullable=False)
    motorcycle_category: Mapped[str] = mapped_column(String(30), nullable=False)
    wet_weight_kg: Mapped[float] = mapped_column(Float, nullable=False)
    seat_height_mm: Mapped[float] = mapped_column(Float, nullable=False)
    tank_capacity_l: Mapped[float] = mapped_column(Float, nullable=False)
    has_abs: Mapped[bool] = mapped_column(Boolean, nullable=False)
    power_cv: Mapped[float | None] = mapped_column(Float, nullable=True)
    torque_nm: Mapped[float | None] = mapped_column(Float, nullable=True)
    transmission_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    gear_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    final_drive_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    payload_capacity_kg: Mapped[float | None] = mapped_column(Float, nullable=True)
    oil_change_interval_km: Mapped[int | None] = mapped_column(Integer, nullable=True)
    abs_channels: Mapped[int | None] = mapped_column(Integer, nullable=True)
    has_cbs: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    has_traction_control: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    motorcycle: Mapped[Motorcycle] = relationship(back_populates="objective_specifications")


class MotorcycleDataSource(Base):
    __tablename__ = "motorcycle_data_sources"
    __table_args__ = (
        CheckConstraint("confidence IS NULL OR confidence BETWEEN 0 AND 100", name="ck_motorcycle_sources_confidence"),
        Index("ix_motorcycle_sources_group", "motorcycle_id", "data_group"),
        Index(
            "uq_motorcycle_primary_source_per_group",
            "motorcycle_id",
            "data_group",
            unique=True,
            sqlite_where=text("is_primary = 1"),
            postgresql_where=text("is_primary = true"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    motorcycle_id: Mapped[int] = mapped_column(ForeignKey("motorcycles.id", ondelete="CASCADE"), nullable=False)
    data_group: Mapped[str] = mapped_column(String(40), nullable=False)
    source_type: Mapped[str] = mapped_column(String(30), nullable=False)
    source_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    source_reference: Mapped[str | None] = mapped_column(String(240), nullable=True)
    source_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    reference_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    collected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    methodology_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_primary: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    motorcycle: Mapped[Motorcycle] = relationship(back_populates="data_sources")
    derived_metrics: Mapped[list["MotorcycleDerivedMetric"]] = relationship(back_populates="source_group")


class MotorcycleDerivedMetric(Base):
    __tablename__ = "motorcycle_derived_metrics"
    __table_args__ = (
        CheckConstraint("metric_value IS NULL OR metric_value BETWEEN 0 AND 100", name="ck_motorcycle_metrics_value"),
        CheckConstraint("confidence IS NULL OR confidence BETWEEN 0 AND 100", name="ck_motorcycle_metrics_confidence"),
        CheckConstraint(
            "(metric_value IS NOT NULL AND metric_text_value IS NULL) OR "
            "(metric_value IS NULL AND metric_text_value IS NOT NULL)",
            name="ck_motorcycle_metrics_single_value",
        ),
        UniqueConstraint("motorcycle_id", "metric_name", "method_version", name="uq_motorcycle_metric_method"),
        Index("ix_motorcycle_metrics_name", "motorcycle_id", "metric_name"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    motorcycle_id: Mapped[int] = mapped_column(ForeignKey("motorcycles.id", ondelete="CASCADE"), nullable=False)
    metric_name: Mapped[str] = mapped_column(String(60), nullable=False)
    metric_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    metric_text_value: Mapped[str | None] = mapped_column(String(60), nullable=True)
    metric_status: Mapped[str] = mapped_column(String(30), nullable=False)
    method_version: Mapped[str] = mapped_column(String(80), nullable=False)
    calculated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    source_group_id: Mapped[int | None] = mapped_column(ForeignKey("motorcycle_data_sources.id", ondelete="SET NULL"), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    motorcycle: Mapped[Motorcycle] = relationship(back_populates="derived_metrics")
    source_group: Mapped[MotorcycleDataSource | None] = relationship(back_populates="derived_metrics")


class MotorcycleEconomicEstimate(Base):
    __tablename__ = "motorcycle_economic_estimates"
    __table_args__ = (
        CheckConstraint("estimate_value >= 0", name="ck_motorcycle_estimates_value_nonnegative"),
        CheckConstraint("confidence IS NULL OR confidence BETWEEN 0 AND 100", name="ck_motorcycle_estimates_confidence"),
        UniqueConstraint("motorcycle_id", "estimate_name", "method_version", "reference_date", name="uq_motorcycle_estimate_version"),
        Index("ix_motorcycle_estimates_name", "motorcycle_id", "estimate_name"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    motorcycle_id: Mapped[int] = mapped_column(ForeignKey("motorcycles.id", ondelete="CASCADE"), nullable=False)
    estimate_name: Mapped[str] = mapped_column(String(80), nullable=False)
    estimate_value: Mapped[Decimal] = mapped_column(MONEY_TYPE, nullable=False)
    unit: Mapped[str] = mapped_column(String(40), nullable=False)
    method_version: Mapped[str] = mapped_column(String(80), nullable=False)
    reference_date: Mapped[date] = mapped_column(Date, nullable=False)
    calculated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    source_group_id: Mapped[int | None] = mapped_column(ForeignKey("motorcycle_data_sources.id", ondelete="SET NULL"), nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    motorcycle: Mapped[Motorcycle] = relationship(back_populates="economic_estimates")


class Expense(Base):
    __tablename__ = "expenses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicles.id"), nullable=False)
    category: Mapped[str] = mapped_column(String(60), nullable=False)
    amount: Mapped[Decimal] = mapped_column(MONEY_TYPE, nullable=False)
    expense_date: Mapped[date] = mapped_column(Date, nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)

    user: Mapped[User] = relationship(back_populates="expenses")
    vehicle: Mapped[Vehicle] = relationship(back_populates="expenses")


class Maintenance(Base):
    __tablename__ = "maintenances"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicles.id"), nullable=False)
    service_type: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="planned", nullable=False)
    scheduled_date: Mapped[date] = mapped_column(Date, nullable=False)
    completed_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    cost: Mapped[Decimal] = mapped_column(MONEY_TYPE, default=Decimal("0"), nullable=False)
    notes: Mapped[str] = mapped_column(Text, default="", nullable=False)

    user: Mapped[User] = relationship(back_populates="maintenances")
    vehicle: Mapped[Vehicle] = relationship(back_populates="maintenances")


class UserVehicle(Base):
    __tablename__ = "user_vehicles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicles.id"), nullable=False)
    year_model: Mapped[int] = mapped_column(Integer, nullable=False)
    current_km: Mapped[int] = mapped_column(Integer, nullable=False)
    purchase_km: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    purchase_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    main_usage: Mapped[str] = mapped_column(String(40), nullable=False)
    notes: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    user: Mapped[User] = relationship(back_populates="user_vehicles")
    vehicle: Mapped[Vehicle] = relationship(back_populates="user_vehicles")
    reports: Mapped[list["VehicleReport"]] = relationship(back_populates="user_vehicle", cascade="all, delete-orphan")
    consumption_reports: Mapped[list["FuelConsumptionReport"]] = relationship(back_populates="user_vehicle", cascade="all, delete-orphan")


class VehicleReport(Base):
    __tablename__ = "vehicle_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_vehicle_id: Mapped[int] = mapped_column(ForeignKey("user_vehicles.id"), nullable=False)
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicles.id"), nullable=False)
    problem_category: Mapped[str] = mapped_column(String(60), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    occurrence_km: Mapped[int] = mapped_column(Integer, nullable=False)
    repair_cost: Mapped[Decimal] = mapped_column(MONEY_TYPE, default=Decimal("0"), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    occurrence_date: Mapped[date] = mapped_column(Date, nullable=False)
    resolved: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    notes: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    user_vehicle: Mapped[UserVehicle] = relationship(back_populates="reports")
    vehicle: Mapped[Vehicle] = relationship(back_populates="reports")


class FuelConsumptionReport(Base):
    __tablename__ = "fuel_consumption_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_vehicle_id: Mapped[int] = mapped_column(ForeignKey("user_vehicles.id"), nullable=False)
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicles.id"), nullable=False)
    km_per_liter: Mapped[float] = mapped_column(Float, nullable=False)
    usage_type: Mapped[str] = mapped_column(String(40), nullable=False)
    fuel_type: Mapped[str] = mapped_column(String(40), nullable=False)
    notes: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    user_vehicle: Mapped[UserVehicle] = relationship(back_populates="consumption_reports")
    vehicle: Mapped[Vehicle] = relationship(back_populates="consumption_reports")


class Part(Base):
    __tablename__ = "parts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    category: Mapped[str] = mapped_column(String(60), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    original_code: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    alternative_codes: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    prices: Mapped[list["PartPrice"]] = relationship(back_populates="part")
    compatibilities: Mapped[list["VehiclePartCompatibility"]] = relationship(back_populates="part")


class Supplier(Base):
    __tablename__ = "suppliers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(140), nullable=False)
    website: Mapped[str] = mapped_column(String(240), default="", nullable=False)
    city: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    state: Mapped[str] = mapped_column(String(2), default="", nullable=False)
    type: Mapped[str] = mapped_column(String(60), nullable=False)
    reliability_score: Mapped[float] = mapped_column(Float, default=70, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    prices: Mapped[list["PartPrice"]] = relationship(back_populates="supplier")


class PartPrice(Base):
    __tablename__ = "part_prices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    part_id: Mapped[int] = mapped_column(ForeignKey("parts.id"), nullable=False)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"), nullable=False)
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicles.id"), nullable=False)
    price: Mapped[Decimal] = mapped_column(MONEY_TYPE, nullable=False)
    brand: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    condition: Mapped[str] = mapped_column(String(40), nullable=False)
    url: Mapped[str] = mapped_column(String(300), default="", nullable=False)
    source: Mapped[str] = mapped_column(String(40), default="demonstrativo", nullable=False)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    notes: Mapped[str] = mapped_column(Text, default="", nullable=False)

    part: Mapped[Part] = relationship(back_populates="prices")
    supplier: Mapped[Supplier] = relationship(back_populates="prices")
    vehicle: Mapped[Vehicle] = relationship(back_populates="part_prices")


class VehiclePartCompatibility(Base):
    __tablename__ = "vehicle_part_compatibility"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicles.id"), nullable=False)
    part_id: Mapped[int] = mapped_column(ForeignKey("parts.id"), nullable=False)
    compatible_vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicles.id"), nullable=False)
    compatibility_type: Mapped[str] = mapped_column(String(60), nullable=False)
    notes: Mapped[str] = mapped_column(Text, default="", nullable=False)
    confidence_level: Mapped[str] = mapped_column(String(30), default="media", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    vehicle: Mapped[Vehicle] = relationship(foreign_keys=[vehicle_id], back_populates="part_compatibilities")
    compatible_vehicle: Mapped[Vehicle] = relationship(foreign_keys=[compatible_vehicle_id])
    part: Mapped[Part] = relationship(back_populates="compatibilities")
