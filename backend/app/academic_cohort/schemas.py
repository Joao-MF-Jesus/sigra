from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

Profile = Literal["cidade", "app", "trabalho", "suv", "familia", "estrada"]
Scenario = Literal["low", "base", "high"]


class AcademicResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    mode: Literal["academic_only"] = "academic_only"
    operationally_active: Literal[False] = False
    recommended: Literal[False] = False


class AcademicMetadata(AcademicResponse):
    snapshot_id: UUID
    cohort_version: str
    cohort_fingerprint: str
    method_fingerprint: str
    inventory_count: int
    selected_count: int
    holdout_ids: list[int]
    outside_selection_ids: list[int]
    profile_counts: dict[str, int]
    limitations: list[str]


class AcademicVehicleItem(AcademicResponse):
    catalog_id: int
    label: str
    fipe_code: str
    year_code: str
    purchase_price_brl: Decimal
    price_reference_month: Literal["2026-09", "2026-10"]


class AcademicVehiclePage(AcademicResponse):
    snapshot_id: UUID
    cohort_fingerprint: str
    items: list[AcademicVehicleItem]
    total: int
    limit: int
    offset: int


class AcademicVehicleDetail(AcademicResponse):
    snapshot_id: UUID
    cohort_version: str
    cohort_fingerprint: str
    vehicle: AcademicVehicleItem
    evidence: dict[str, Any]
    evaluations: dict[str, dict[str, Any]]
    limitations: list[str]


class AcademicEvaluationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    profile: Profile
    scenario: Scenario = "base"
    snapshot_id: UUID | None = None
    max_purchase_price_brl: Decimal | None = Field(default=None, gt=0)
    max_monthly_tco_brl: Decimal | None = Field(default=None, gt=0)
    limit: int = Field(default=10, ge=1, le=60, strict=True)


class AcademicEvaluationResponse(AcademicResponse):
    snapshot_id: UUID
    cohort_version: str
    cohort_fingerprint: str
    profile: Profile
    scenario: Scenario
    eligible_ids: list[int]
    eligible_count: int
    returned_ids: list[int]
    groups: dict[str, Any]
    evaluations: dict[str, Any]
    limitations: list[str]
    empty_reason: str | None
