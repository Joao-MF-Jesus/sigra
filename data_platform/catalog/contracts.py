from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator, model_validator


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


def public_source_url(value: str) -> str:
    url = urlsplit(value)
    if (url.scheme != "https" or not url.hostname or url.username or url.password
            or url.query or url.fragment or url.port not in (None, 443)):
        raise ValueError("source URL must be public HTTPS without credentials or query")
    return value


class Candidate(Contract):
    id: int = Field(strict=True, ge=35, le=100)
    candidate_key: str
    collection_group: Literal["Cidade", "Aplicativo", "Trabalho", "Família", "Estrada", "SUV/Espaço"]
    collection_order: int = Field(strict=True, ge=1, le=11)
    batch: int = Field(strict=True, ge=1, le=3)
    brand: str = Field(min_length=1)
    model_family: str = Field(min_length=1)
    target_version: str = Field(min_length=1)
    model_year: int = Field(strict=True, ge=2017, le=2021)
    category: Literal["subcompact", "compact_hatch", "compact_sedan", "midsize_sedan", "compact_minivan", "minivan", "compact_suv", "suv"]
    source_row: int = Field(strict=True, ge=2, le=67)
    status: Literal["selected"]
    identity_note: str
    fipe_family_url: str
    pbev_cycle_url: str

    @model_validator(mode="after")
    def source_identity(self):
        if self.candidate_key != f"sigra-100-2026-09-06:{self.id}" or self.source_row != self.id - 33:
            raise ValueError("candidate selection key or source row differs")
        if self.batch != 1 + (self.id - 35) // 22:
            raise ValueError("candidate batch differs from source selection")
        for field, host in (("fipe_family_url", "parallelum.com.br"), ("pbev_cycle_url", "www.gov.br")):
            url = urlsplit(public_source_url(getattr(self, field)))
            if url.hostname != host:
                raise ValueError("source host differs from the canonical workbook")
        return self


class BaselineVehicle(Contract):
    id: int = Field(strict=True, ge=1, le=34)
    brand: str
    model: str
    year: StrictInt


class SelectionSource(Contract):
    filename: Literal["sigra_66_modelos_candidatos.xlsx"]
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    sheets: tuple[str, ...]
    selection_date: date


class Selection(Contract):
    schema_version: Literal["sigra-catalog-selection-v1"]
    selection_id: Literal["sigra-100-2026-09-06"]
    source: SelectionSource
    baseline: tuple[BaselineVehicle, ...]
    candidates: tuple[Candidate, ...]


class EvidenceReference(Contract):
    source_url: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    locator: str = Field(min_length=1)
    collected_at: datetime

    _safe_url = field_validator("source_url")(public_source_url)

    @field_validator("collected_at")
    @classmethod
    def timezone_required(cls, value):
        if value.tzinfo is None:
            raise ValueError("collection timestamp must include timezone")
        return value


class FieldEvidence(Contract):
    value: Decimal | None = None
    unit: str
    kind: Literal["observed", "derived", "demonstrative", "unavailable"]
    references: tuple[EvidenceReference, ...] = ()
    method_version: str | None = None
    inputs: dict[str, Decimal] = Field(default_factory=dict)

    @field_validator("value", mode="before")
    @classmethod
    def no_implicit_numbers(cls, value):
        if isinstance(value, (bool, float)):
            raise ValueError("use exact decimal strings, not booleans or binary floats")
        return value

    @model_validator(mode="after")
    def provenance(self):
        if self.kind == "unavailable":
            if self.value is not None:
                raise ValueError("unavailable evidence cannot contain a numeric substitute")
        elif self.value is None or not self.references:
            raise ValueError("available evidence requires a value and source references")
        if self.kind == "derived" and (not self.method_version or not self.inputs):
            raise ValueError("derived evidence requires a versioned method and observable inputs")
        return self


class IdentityReview(Contract):
    method: Literal["explicit_review"]
    method_version: str = Field(min_length=1)
    reviewed_by: str = Field(min_length=1)
    reviewed_at: datetime
    candidate_key: str
    target_version: str
    fipe_code: str = Field(pattern=r"^[0-9]{6}-[0-9]$")
    year_code: str = Field(pattern=r"^[0-9]{4}-[0-9]+$")
    fipe_description: str = Field(min_length=1)
    fipe_brand: str = Field(min_length=1)
    fipe_price_brl: Decimal = Field(gt=0)
    fipe_reference_month: date
    fipe_source: EvidenceReference
    pbev_cycle: StrictInt
    pbev_row_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    pbev_source: EvidenceReference
    motor: str = Field(min_length=1)
    transmission: Literal["manual", "automatic", "cvt"]
    fuel: Literal["gasoline", "ethanol", "flex", "diesel", "hybrid", "electric"]
    # Each statement must identify the two exact source configurations. This
    # is a review artifact, never an automatic text-similarity match.
    configuration_evidence: dict[str, str]
    divergences: tuple[str, ...] = ()


class Dossier(Contract):
    candidate_id: int = Field(strict=True, ge=35, le=100)
    identity: IdentityReview | None = None
    fields: dict[str, FieldEvidence] = Field(default_factory=dict)


class Blocker(Contract):
    code: str
    field: str
    reason: str
