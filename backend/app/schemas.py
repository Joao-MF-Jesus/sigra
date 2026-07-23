from datetime import date, datetime
import re
from typing import Literal

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, StrictBool, TypeAdapter, field_validator, model_validator

from app.vehicle_domain import (
    CarCategory,
    CarUseCase,
    DataSource,
    MotorcycleCategory,
    RiderExperience,
    VehicleType,
)
from app.motorcycle_domain import (
    MotorcycleDataGroup,
    MotorcycleDerivedMetricName,
    MotorcycleEconomicEstimateName,
    MotorcycleEconomicEstimateStatus,
    MotorcycleEligibilityStatus,
    MotorcycleFinalDriveType,
    MotorcycleFuelType,
    MotorcycleMarketCondition,
    MotorcycleMetricStatus,
    MotorcycleTransmissionType,
)


class VehicleBase(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    brand: str = Field(min_length=2, max_length=80)
    model: str = Field(min_length=1, max_length=120)
    year: int = Field(ge=1990, le=2035)
    price: float = Field(gt=0)
    fuel_efficiency_km_l: float = Field(gt=0)
    annual_maintenance_cost: float | None = Field(default=None, ge=0)
    reliability_score: float = Field(ge=0, le=100)
    parts_availability_score: float = Field(ge=0, le=100)
    depreciation_rate: float = Field(ge=0)
    use_cases: list[CarUseCase] = Field(default_factory=list)
    chronic_issues: list[str] = Field(default_factory=list)
    image_url: str = Field(default="", max_length=240)
    category: CarCategory = CarCategory.COMPACT
    segment_level: int = Field(default=2, ge=1, le=5)
    comfort_score: float = Field(default=60, ge=0, le=100)
    space_score: float = Field(default=60, ge=0, le=100)
    safety_score: float = Field(default=60, ge=0, le=100)
    urban_score: float = Field(default=70, ge=0, le=100)
    road_score: float = Field(default=60, ge=0, le=100)
    family_score: float = Field(default=60, ge=0, le=100)
    app_score: float = Field(default=60, ge=0, le=100)


class VehicleCreate(VehicleBase):
    pass


class VehicleRead(VehicleBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    vehicle_type: VehicleType = VehicleType.CAR


class MotorcycleSpecifications(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False, extra="forbid")

    engine_displacement_cc: float = Field(gt=0, le=3000)
    motorcycle_category: MotorcycleCategory
    wet_weight_kg: float = Field(ge=20, le=600)
    seat_height_mm: float = Field(ge=400, le=1200)
    tank_capacity_l: float = Field(ge=1, le=50)
    has_abs: StrictBool
    power_cv: float | None = Field(default=None, gt=0)
    torque_nm: float | None = Field(default=None, gt=0)
    transmission_type: MotorcycleTransmissionType | None = None
    gear_count: int | None = Field(default=None, ge=1, le=12)
    final_drive_type: MotorcycleFinalDriveType | None = None
    payload_capacity_kg: float | None = Field(default=None, gt=0)
    oil_change_interval_km: int | None = Field(default=None, gt=0)
    abs_channels: int | None = Field(default=None, ge=0, le=2)
    has_cbs: StrictBool | None = None
    has_traction_control: StrictBool | None = None

    # Compatibilidade de entrada 0.1.x. A fonte de verdade passa a ser
    # motorcycle_derived_metrics e estes campos nunca definem completude.
    recommended_experience: RiderExperience | None = None
    urban_score: float | None = Field(default=None, ge=0, le=100)
    road_score: float | None = Field(default=None, ge=0, le=100)
    passenger_comfort_score: float | None = Field(default=None, ge=0, le=100)
    luggage_score: float | None = Field(default=None, ge=0, le=100)


class MotorcycleBase(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False, extra="forbid")

    brand: str = Field(min_length=2, max_length=80)
    model: str = Field(min_length=1, max_length=120)
    year: int = Field(ge=1990, le=2035)
    price: float = Field(gt=0)
    city_consumption: float = Field(gt=0)
    road_consumption: float = Field(gt=0)
    annual_maintenance_cost: float | None = Field(default=None, ge=0)
    reliability_score: float | None = Field(default=None, ge=0, le=100)
    parts_availability_score: float | None = Field(default=None, ge=0, le=100)
    depreciation_rate: float | None = Field(default=None, ge=0)
    data_source: DataSource | None = None
    data_confidence: float | None = Field(default=None, ge=0, le=100)
    source_name: str | None = Field(default=None, min_length=2, max_length=160)
    source_reference: str | None = Field(default=None, min_length=2, max_length=240)
    source_url: str | None = Field(default=None, max_length=500)
    source_collected_at: datetime | None = None
    source_reference_date: date | None = None
    last_verified_at: datetime | None = None
    image_url: str = Field(default="", max_length=240)
    version: str | None = Field(default=None, min_length=1, max_length=120)
    market_condition: MotorcycleMarketCondition | None = None
    fuel_type: MotorcycleFuelType | None = None
    price_reference_date: date | None = None
    is_demonstration: StrictBool = False


class MotorcycleDataSourceBase(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False, extra="forbid")

    data_group: MotorcycleDataGroup
    source_type: DataSource
    source_name: str | None = Field(default=None, min_length=2, max_length=160)
    source_reference: str | None = Field(default=None, min_length=2, max_length=240)
    source_url: str | None = Field(default=None, max_length=500)
    reference_date: date | None = None
    collected_at: datetime | None = None
    last_verified_at: datetime | None = None
    confidence: float | None = Field(default=None, ge=0, le=100)
    methodology_notes: str | None = Field(default=None, max_length=2000)
    is_primary: StrictBool = False

    @field_validator("source_url")
    @classmethod
    def validate_group_source_url(cls, value: str | None) -> str | None:
        if value is not None:
            TypeAdapter(AnyHttpUrl).validate_python(value)
        return value

    @field_validator("collected_at", "last_verified_at")
    @classmethod
    def validate_group_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.utcoffset() is None:
            raise ValueError("a data e hora deve incluir fuso horário")
        return value

    @model_validator(mode="after")
    def validate_group_source_requirements(self):
        if self.source_type == DataSource.OFFICIAL and not self.source_name:
            raise ValueError("source_name é obrigatório para fontes oficiais")
        if self.source_type == DataSource.ESTIMATED and not (self.methodology_notes or self.source_reference):
            raise ValueError("fontes estimadas exigem metodologia ou referência")
        if self.source_type == DataSource.USER_REPORTED:
            for value in (self.source_name, self.source_reference, self.methodology_notes):
                if isinstance(value, str) and re.search(r"\b[^\s@]+@[^\s@]+\.[^\s@]+\b", value):
                    raise ValueError("fontes relatadas não podem expor endereço de e-mail")
        if self.collected_at and self.last_verified_at and self.last_verified_at < self.collected_at:
            raise ValueError("last_verified_at não pode ser anterior a collected_at")
        return self


class MotorcycleDataSourceCreate(MotorcycleDataSourceBase):
    pass


class MotorcycleDataSourceUpdate(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False, extra="forbid")

    data_group: MotorcycleDataGroup | None = None
    source_type: DataSource | None = None
    source_name: str | None = Field(default=None, min_length=2, max_length=160)
    source_reference: str | None = Field(default=None, min_length=2, max_length=240)
    source_url: str | None = Field(default=None, max_length=500)
    reference_date: date | None = None
    collected_at: datetime | None = None
    last_verified_at: datetime | None = None
    confidence: float | None = Field(default=None, ge=0, le=100)
    methodology_notes: str | None = Field(default=None, max_length=2000)
    is_primary: StrictBool | None = None

    @field_validator("source_url")
    @classmethod
    def validate_group_source_url(cls, value: str | None) -> str | None:
        if value is not None:
            TypeAdapter(AnyHttpUrl).validate_python(value)
        return value

    @field_validator("collected_at", "last_verified_at")
    @classmethod
    def validate_group_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.utcoffset() is None:
            raise ValueError("a data e hora deve incluir fuso horário")
        return value


class MotorcycleDataSourceRead(MotorcycleDataSourceBase):
    model_config = ConfigDict(from_attributes=True, allow_inf_nan=False)

    id: int
    motorcycle_id: int
    created_at: datetime
    updated_at: datetime


class MotorcycleDerivedMetricBase(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False, extra="forbid")

    metric_name: MotorcycleDerivedMetricName
    metric_value: float | None = Field(default=None, ge=0, le=100)
    metric_text_value: str | None = Field(default=None, min_length=1, max_length=60)
    metric_status: MotorcycleMetricStatus
    method_version: str = Field(min_length=2, max_length=80)
    calculated_at: datetime | None = None
    confidence: float | None = Field(default=None, ge=0, le=100)
    source_group_id: int | None = Field(default=None, gt=0)
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator("calculated_at")
    @classmethod
    def validate_metric_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.utcoffset() is None:
            raise ValueError("calculated_at deve incluir fuso horário")
        return value

    @model_validator(mode="after")
    def validate_metric_value_kind(self):
        is_experience = self.metric_name == MotorcycleDerivedMetricName.RECOMMENDED_EXPERIENCE
        if is_experience:
            if self.metric_value is not None or self.metric_text_value not in {item.value for item in RiderExperience}:
                raise ValueError("recommended_experience exige metric_text_value controlado")
        elif self.metric_value is None or self.metric_text_value is not None:
            raise ValueError("métricas numéricas exigem somente metric_value")
        return self


class MotorcycleDerivedMetricCreate(MotorcycleDerivedMetricBase):
    @model_validator(mode="after")
    def validate_public_creation_status(self):
        if self.metric_status not in {
            MotorcycleMetricStatus.DEMONSTRATION,
            MotorcycleMetricStatus.UNVALIDATED,
        }:
            raise ValueError("a criação pública aceita apenas métricas demonstration ou unvalidated")
        if self.metric_status == MotorcycleMetricStatus.DEMONSTRATION:
            if not self.method_version.startswith("demonstration-"):
                raise ValueError("métricas demonstrativas exigem method_version demonstration-*")
            if self.confidence is not None and self.confidence > 50:
                raise ValueError("métricas demonstrativas não podem declarar confiança acima de 50")
        if (
            self.metric_status == MotorcycleMetricStatus.UNVALIDATED
            and self.notes is None
            and self.source_group_id is None
        ):
            raise ValueError("métricas não validadas exigem notas metodológicas ou uma fonte vinculada")
        return self


class MotorcycleDerivedMetricRead(MotorcycleDerivedMetricBase):
    model_config = ConfigDict(from_attributes=True, allow_inf_nan=False)

    id: int
    motorcycle_id: int


class MotorcycleEconomicEstimateBase(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False, extra="forbid")

    estimate_name: MotorcycleEconomicEstimateName
    estimate_value: float = Field(ge=0, le=100)
    unit: Literal["percent_per_year"]
    method_version: str = Field(min_length=2, max_length=80)
    reference_date: date
    calculated_at: datetime | None = None
    confidence: float | None = Field(default=None, ge=0, le=100)
    source_group_id: int | None = Field(default=None, gt=0)
    status: MotorcycleEconomicEstimateStatus
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator("calculated_at")
    @classmethod
    def validate_estimate_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.utcoffset() is None:
            raise ValueError("calculated_at deve incluir fuso horário")
        return value


class MotorcycleEconomicEstimateCreate(MotorcycleEconomicEstimateBase):
    @model_validator(mode="after")
    def validate_public_creation_status(self):
        if self.status not in {
            MotorcycleEconomicEstimateStatus.DEMONSTRATION,
            MotorcycleEconomicEstimateStatus.UNVALIDATED,
        }:
            raise ValueError("a criação pública aceita apenas estimativas demonstration ou unvalidated")
        if self.status == MotorcycleEconomicEstimateStatus.DEMONSTRATION:
            if not self.method_version.startswith("demonstration-"):
                raise ValueError("estimativas demonstrativas exigem method_version demonstration-*")
            if self.confidence is not None and self.confidence > 50:
                raise ValueError("estimativas demonstrativas não podem declarar confiança acima de 50")
        if (
            self.status == MotorcycleEconomicEstimateStatus.UNVALIDATED
            and self.notes is None
            and self.source_group_id is None
        ):
            raise ValueError("estimativas não validadas exigem notas metodológicas ou uma fonte vinculada")
        return self


class MotorcycleEconomicEstimateRead(MotorcycleEconomicEstimateBase):
    model_config = ConfigDict(from_attributes=True, allow_inf_nan=False)

    id: int
    motorcycle_id: int


class MotorcycleCreate(MotorcycleBase):
    specifications: MotorcycleSpecifications
    data_sources: list[MotorcycleDataSourceCreate] = Field(default_factory=list)
    derived_metrics: list[MotorcycleDerivedMetricCreate] = Field(default_factory=list)
    economic_estimates: list[MotorcycleEconomicEstimateCreate] = Field(default_factory=list)

    @field_validator("source_url")
    @classmethod
    def validate_source_url(cls, value: str | None) -> str | None:
        if value is not None:
            TypeAdapter(AnyHttpUrl).validate_python(value)
        return value

    @field_validator("source_collected_at", "last_verified_at")
    @classmethod
    def validate_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.utcoffset() is None:
            raise ValueError("a data e hora deve incluir fuso horário")
        return value

    @model_validator(mode="after")
    def validate_source_requirements(self):
        validate_motorcycle_source_metadata(self.model_dump(mode="python"))
        if self.data_source is None:
            primary_identity = any(
                source.data_group == MotorcycleDataGroup.IDENTITY and source.is_primary
                for source in self.data_sources
            )
            if not primary_identity:
                raise ValueError("novos registros sem origem legada exigem uma fonte principal de identity")
        return self


class MotorcycleSpecificationsUpdate(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False, extra="forbid")

    engine_displacement_cc: float | None = Field(default=None, gt=0, le=3000)
    motorcycle_category: MotorcycleCategory | None = None
    wet_weight_kg: float | None = Field(default=None, ge=20, le=600)
    seat_height_mm: float | None = Field(default=None, ge=400, le=1200)
    tank_capacity_l: float | None = Field(default=None, ge=1, le=50)
    has_abs: StrictBool | None = None
    power_cv: float | None = Field(default=None, gt=0)
    torque_nm: float | None = Field(default=None, gt=0)
    transmission_type: MotorcycleTransmissionType | None = None
    gear_count: int | None = Field(default=None, ge=1, le=12)
    final_drive_type: MotorcycleFinalDriveType | None = None
    payload_capacity_kg: float | None = Field(default=None, gt=0)
    oil_change_interval_km: int | None = Field(default=None, gt=0)
    abs_channels: int | None = Field(default=None, ge=0, le=2)
    has_cbs: StrictBool | None = None
    has_traction_control: StrictBool | None = None
    recommended_experience: RiderExperience | None = None
    urban_score: float | None = Field(default=None, ge=0, le=100)
    road_score: float | None = Field(default=None, ge=0, le=100)
    passenger_comfort_score: float | None = Field(default=None, ge=0, le=100)
    luggage_score: float | None = Field(default=None, ge=0, le=100)


class MotorcycleUpdate(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False, extra="forbid")

    brand: str | None = Field(default=None, min_length=2, max_length=80)
    model: str | None = Field(default=None, min_length=1, max_length=120)
    year: int | None = Field(default=None, ge=1990, le=2035)
    price: float | None = Field(default=None, gt=0)
    city_consumption: float | None = Field(default=None, gt=0)
    road_consumption: float | None = Field(default=None, gt=0)
    annual_maintenance_cost: float | None = Field(default=None, ge=0)
    reliability_score: float | None = Field(default=None, ge=0, le=100)
    parts_availability_score: float | None = Field(default=None, ge=0, le=100)
    depreciation_rate: float | None = Field(default=None, ge=0)
    data_source: DataSource | None = None
    data_confidence: float | None = Field(default=None, ge=0, le=100)
    source_name: str | None = Field(default=None, min_length=2, max_length=160)
    source_reference: str | None = Field(default=None, min_length=2, max_length=240)
    source_url: str | None = Field(default=None, max_length=500)
    source_collected_at: datetime | None = None
    source_reference_date: date | None = None
    last_verified_at: datetime | None = None
    image_url: str | None = Field(default=None, max_length=240)
    version: str | None = Field(default=None, min_length=1, max_length=120)
    market_condition: MotorcycleMarketCondition | None = None
    fuel_type: MotorcycleFuelType | None = None
    price_reference_date: date | None = None
    specifications: MotorcycleSpecificationsUpdate | None = None

    @field_validator("source_url")
    @classmethod
    def validate_source_url(cls, value: str | None) -> str | None:
        if value is not None:
            TypeAdapter(AnyHttpUrl).validate_python(value)
        return value

    @field_validator("source_collected_at", "last_verified_at")
    @classmethod
    def validate_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.utcoffset() is None:
            raise ValueError("a data e hora deve incluir fuso horário")
        return value


class MotorcycleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, allow_inf_nan=False)

    id: int
    brand: str
    model: str
    year: int
    price: float
    city_consumption: float
    road_consumption: float
    annual_maintenance_cost: float | None = None
    vehicle_type: VehicleType = VehicleType.MOTORCYCLE
    image_url: str = ""
    version: str | None = None
    market_condition: MotorcycleMarketCondition | None = None
    fuel_type: MotorcycleFuelType | None = None
    price_reference_date: date | None = None
    is_demonstration: StrictBool = False
    specifications: MotorcycleSpecifications | None
    record_status: Literal["complete", "incomplete"] = "complete"
    incomplete_reasons: list[str] = Field(default_factory=list)
    eligibility_status: MotorcycleEligibilityStatus
    eligibility_reasons: list[dict[str, str]] = Field(default_factory=list)
    blocking_issues: list[dict[str, str]] = Field(default_factory=list)
    informational_issues: list[dict[str, str]] = Field(default_factory=list)
    data_sources: list[MotorcycleDataSourceRead] = Field(default_factory=list)
    derived_metrics: list[MotorcycleDerivedMetricRead] = Field(default_factory=list)
    economic_estimates: list[MotorcycleEconomicEstimateRead] = Field(default_factory=list)
    coverage: dict = Field(default_factory=dict)
    source_contract: dict = Field(default_factory=dict)
    legacy_data: dict | None = None


class MotorcycleInvalidRecordSummary(BaseModel):
    id: int | None = None
    brand: str | None = None
    model: str | None = None
    issue_count: int = Field(ge=1)


class MotorcycleListEnvelope(BaseModel):
    module_version: str
    algorithm_version: None = None
    weights_version: None = None
    derived_metrics_method_version: None = None
    total_found: int
    returned: int
    valid_records: int
    invalid_records: int
    motorcycles: list[MotorcycleRead]
    invalid_record_summary: list[MotorcycleInvalidRecordSummary] = Field(default_factory=list)


def validate_motorcycle_source_metadata(values: dict) -> None:
    source = values.get("data_source")
    if isinstance(source, DataSource):
        source = source.value
    source_name = values.get("source_name")
    source_reference = values.get("source_reference")
    source_url = values.get("source_url")
    collected_at = values.get("source_collected_at")

    if source == DataSource.OFFICIAL.value:
        if not source_name:
            raise ValueError("source_name é obrigatório para dados oficiais")
        if not (source_reference or source_url):
            raise ValueError("source_reference ou source_url é obrigatório para dados oficiais")
        if collected_at is None:
            raise ValueError("source_collected_at é obrigatório para dados oficiais")
    elif source == DataSource.ESTIMATED.value and not source_reference:
        raise ValueError("source_reference deve documentar o método usado em dados estimados")
    elif source == DataSource.USER_REPORTED.value and collected_at is None:
        raise ValueError("source_collected_at é obrigatório para dados relatados por usuário")


class UserCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    email: str = Field(min_length=5, max_length=160, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class UserRead(UserCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int


class LoginRequest(BaseModel):
    email: str = Field(min_length=5, max_length=160)
    password: str = Field(min_length=4, max_length=80)
    role: Literal["user", "admin"]


class LoginResponse(BaseModel):
    id: int
    name: str
    email: str
    role: str


class ExpenseCreate(BaseModel):
    user_id: int
    vehicle_id: int
    category: Literal["combustivel", "seguro", "documentacao", "manutencao", "outros"]
    amount: float = Field(gt=0)
    expense_date: date
    description: str = Field(default="", max_length=300)


class ExpenseRead(ExpenseCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int


class MaintenanceCreate(BaseModel):
    user_id: int
    vehicle_id: int
    service_type: str = Field(min_length=2, max_length=120)
    status: Literal["planned", "pending", "completed", "cancelled"] = "planned"
    scheduled_date: date
    completed_date: date | None = None
    cost: float = Field(default=0, ge=0)
    notes: str = Field(default="", max_length=500)


class MaintenanceRead(MaintenanceCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int


UsageType = Literal["cidade", "urbano", "estrada", "misto", "app", "familia", "trabalho", "suv"]
ProblemCategory = Literal[
    "motor",
    "cambio",
    "suspensao",
    "freio",
    "eletrica",
    "arrefecimento",
    "acabamento",
    "consumo",
    "pecas",
    "seguro",
    "outros",
]
Severity = Literal["baixa", "media", "alta"]
FuelType = Literal["gasolina", "etanol", "diesel", "flex"]


class UserVehicleCreate(BaseModel):
    user_id: int = Field(gt=0)
    vehicle_id: int = Field(gt=0)
    year_model: int = Field(ge=1990, le=2035)
    current_km: int = Field(ge=0)
    purchase_km: int = Field(default=0, ge=0)
    purchase_date: date | None = None
    main_usage: UsageType
    notes: str = Field(default="", max_length=600)


class UserVehicleUpdate(BaseModel):
    year_model: int | None = Field(default=None, ge=1990, le=2035)
    current_km: int | None = Field(default=None, ge=0)
    purchase_km: int | None = Field(default=None, ge=0)
    purchase_date: date | None = None
    main_usage: UsageType | None = None
    notes: str | None = Field(default=None, max_length=600)


class UserVehicleRead(UserVehicleCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int


class VehicleReportCreate(BaseModel):
    user_vehicle_id: int = Field(gt=0)
    problem_category: ProblemCategory
    description: str = Field(min_length=3, max_length=800)
    occurrence_km: int = Field(ge=0)
    repair_cost: float = Field(default=0, ge=0)
    severity: Severity
    occurrence_date: date
    resolved: bool = False
    notes: str = Field(default="", max_length=600)


class VehicleReportRead(VehicleReportCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    vehicle_id: int


class FuelConsumptionReportCreate(BaseModel):
    user_vehicle_id: int = Field(gt=0)
    km_per_liter: float = Field(gt=0, le=40)
    usage_type: Literal["urbano", "cidade", "estrada", "misto"]
    fuel_type: FuelType
    notes: str = Field(default="", max_length=500)


class FuelConsumptionReportRead(FuelConsumptionReportCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    vehicle_id: int


PartCategory = Literal[
    "suspensao",
    "freio",
    "motor",
    "cambio",
    "arrefecimento",
    "eletrica",
    "direcao",
    "filtros",
    "correias",
    "embreagem",
    "acabamento",
    "pneus",
    "outros",
]
SupplierType = Literal["loja online", "autopecas local", "marketplace", "concessionaria", "distribuidor", "oficina parceira"]
PartCondition = Literal["novo", "usado", "recondicionado", "original", "paralelo"]
PartSource = Literal["manual", "demonstrativo", "API futura", "scraping futuro"]


class PartRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    category: str
    description: str = ""
    original_code: str = ""
    alternative_codes: str = ""


class SupplierRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    website: str = ""
    city: str = ""
    state: str = ""
    type: str
    reliability_score: float


class PartPriceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    part_id: int
    supplier_id: int
    vehicle_id: int
    price: float
    brand: str = ""
    condition: str
    url: str = ""
    source: str
    notes: str = ""
