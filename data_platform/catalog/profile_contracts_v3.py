"""Offline pilot contracts. No publication, persistence or production DTO."""
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import Field, StrictInt, model_validator, field_validator

from data_platform.catalog.contracts import Contract, public_source_url

VERSION = "catalog-profile-evidence-v3"
UNITS = {
    "fipe_code": "text", "year_code": "text", "commercial_identity": "text",
    "reference_month": "YYYY-MM", "price_brl": "BRL",
    "consumption_city": "km/l", "consumption_highway": "km/l",
    "fuel": "text", "transmission": "text",
    "seats": "count", "cargo_l": "l", "length_mm": "mm", "width_mm": "mm",
    "width_with_mirrors_mm": "mm", "wheelbase_mm": "mm",
    "ground_clearance_mm": "mm", "weight_kg": "kg", "power_gasoline_cv": "cv",
    "payload_kg": "kg", "airbags": "count", "abs": "bool", "esc": "bool",
    "rear_legroom_mm": "mm", "interior_width_mm": "mm",
    "gasoline_brl_per_l": "BRL/l", "maintenance_annual_brl": "BRL/year",
    "ipva_annual_brl": "BRL/year", "insurance_annual_brl": "BRL/year",
    "depreciation_annual_brl": "BRL/year",
}
TEXT_UNITS = {"text", "YYYY-MM"}


class Citation(Contract):
    provider: Literal["fipe", "pbev", "anp", "manufacturer", "carpedia", "latinncap"]
    url: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    document: str = Field(min_length=1)
    locator: str = Field(min_length=1)
    page: StrictInt | None = Field(default=None, ge=1)
    collected_at: datetime

    _safe_url = field_validator("url")(public_source_url)

    @field_validator("collected_at")
    @classmethod
    def timezone_required(cls, value):
        if value.tzinfo is None:
            raise ValueError("Timezone is required")
        return value


class Observation(Contract):
    value: object = None
    unit: str
    kind: Literal["observed", "derived", "unavailable"] = "unavailable"
    sources: tuple[Citation, ...] = ()
    applicability: Literal["exact_variant", "shared_powertrain", "model_nominal", "legacy_reference", "none"] = "none"
    method_version: str | None = None
    formula: str | None = None
    inputs: dict[str, Decimal] = Field(default_factory=dict)
    reason: str | None = None
    limitations: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_observation(self):
        if self.kind == "unavailable":
            if self.value is not None:
                raise ValueError("Unavailable is null, not an imputed number")
            if not self.reason:
                raise ValueError("Missing evidence requires a reason")
            return self
        if self.value is None or not self.sources or self.applicability == "none":
            raise ValueError("Available evidence requires sources and applicability")
        if self.unit == "bool":
            if not isinstance(self.value, bool):
                raise ValueError("Boolean evidence must be explicit true/false")
        elif self.unit in TEXT_UNITS:
            if not isinstance(self.value, str) or not self.value.strip():
                raise ValueError("Text evidence requires a nonempty string")
        else:
            if isinstance(self.value, (bool, float)):
                raise ValueError("Financial and technical numeric evidence uses Decimal")
            value = Decimal(self.value)
            if not value.is_finite() or value < 0:
                raise ValueError("Nonnegative finite evidence required")
            if self.unit == "count" and value != value.to_integral_value():
                raise ValueError("Count must be integral")
            object.__setattr__(self, "value", value)
        if self.kind == "derived" and (not self.formula or not self.inputs or self.method_version != VERSION):
            raise ValueError("Derivation requires version, formula and exact inputs")
        return self


class ProfileVehicle(Contract):
    schema_version: Literal["catalog-profile-evidence-v3"] = VERSION
    id: StrictInt = Field(ge=1, le=100)
    label: str
    identity_status: Literal["identity_approved", "legacy_binding_not_reaudited"]
    fields: dict[str, Observation]
    provenance: dict = Field(default_factory=dict)
    source_conflicts: tuple[str, ...] = ()
    human_approval_required: bool = False
    human_approval_status: Literal["pending", "human_approved", "not_applicable"] = "not_applicable"

    @model_validator(mode="after")
    def evidence_units_and_priority(self):
        if set(self.fields) != set(UNITS):
            raise ValueError("Every versioned field must exist, even when unavailable")
        for name, observation in self.fields.items():
            if observation.unit != UNITS[name]:
                raise ValueError("Evidence unit mismatch: " + name)
            if observation.kind == "unavailable":
                continue
            providers = {source.provider for source in observation.sources}
            official = (
                "fipe" if name in {"fipe_code", "year_code", "commercial_identity", "reference_month", "price_brl"} else
                "pbev" if name in {"consumption_city", "consumption_highway", "fuel", "transmission"} else
                "anp" if name == "gasoline_brl_per_l" else None
            )
            if official and providers != {official}:
                raise ValueError("Official-source precedence violation: " + name)
            if name in {"price_brl", "consumption_city", "consumption_highway", "power_gasoline_cv", "weight_kg", "gasoline_brl_per_l"} and observation.value <= 0:
                raise ValueError("Positive evidence required: " + name)
            if name == "reference_month":
                from datetime import date
                if date.fromisoformat(observation.value + "-01").strftime("%Y-%m") != observation.value:
                    raise ValueError("Canonical reference month required")
            if name == "fuel" and observation.value not in {"flex", "gasoline", "ethanol", "diesel", "electric", "hybrid"}:
                raise ValueError("Unknown fuel")
            if name == "transmission" and observation.value not in {"manual", "automatic", "cvt"}:
                raise ValueError("Unknown transmission")
        return self


def unavailable(name, reason="No individually applicable source evidence", sources=()):
    return Observation(unit=UNITS[name], reason=reason, sources=sources)


def blank_fields():
    return {name: unavailable(name) for name in UNITS}


def observed(name, value, sources, applicability="exact_variant", limitations=()):
    return Observation(value=value, unit=UNITS[name], kind="observed", sources=sources,
                       applicability=applicability, limitations=limitations)


def available(vehicle, name):
    observation = vehicle.fields[name]
    return observation.kind != "unavailable" and observation.value is not None
