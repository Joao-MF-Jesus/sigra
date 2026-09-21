"""Offline applicability contract. Never infer equipment from a crash-test rating."""
from datetime import date
from decimal import Decimal
import hashlib
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, StrictInt, field_validator, model_validator

from data_platform.catalog.contracts import Contract
from data_platform.catalog.profile_contracts_v3 import Citation

IDENTITY_FIELDS = ("fipe_code", "year_code", "commercial_identity", "fuel")


class TestedScope(Contract):
    generation: str = Field(min_length=1)
    body: str = Field(min_length=1)
    configuration: str = Field(min_length=1)
    model_year: StrictInt = Field(ge=1900, le=2100)


class LatinNCAPRecord(Contract):
    """Human-reviewed dossier, not automatic text matching.

    The applicability citation must bind canonical trim/year to the tested
    configuration and period. Unresolved VIN/date/trim restrictions fail closed.
    A hostname/hash alone cannot prove the semantic applicability of a document.
    """

    candidate_id: StrictInt = Field(ge=1, le=100)
    identity: dict[str, str]
    target_scope: TestedScope
    tested_scope: TestedScope
    covered_model_years: tuple[StrictInt, ...]
    test_year: StrictInt = Field(ge=1900, le=2100)
    protocol_id: str = Field(min_length=1)
    protocol_period_start: date
    protocol_period_end: date
    metric: Literal["adult_occupant_points", "child_occupant_points", "overall_stars"]
    result: Decimal = Field(ge=0)
    maximum: Decimal = Field(gt=0)
    review_status: Literal["exact_configuration_reviewed"]
    review_note: str = Field(min_length=20)
    unresolved_restrictions: tuple[str, ...] = ()
    result_source: Citation
    applicability_source: Citation
    protocol_source: Citation
    result_file: str
    applicability_file: str
    protocol_file: str

    @field_validator("result", "maximum", mode="before")
    @classmethod
    def exact_number(cls, value):
        if isinstance(value, (bool, float)):
            raise ValueError("Use exact Decimal/text numbers")
        return value

    @model_validator(mode="after")
    def exact_scope(self):
        if set(self.identity) != set(IDENTITY_FIELDS) or not all(self.identity.values()):
            raise ValueError("Complete canonical identity required")
        if self.target_scope != self.tested_scope:
            raise ValueError("Generation/body/configuration/model year mismatch")
        if self.unresolved_restrictions:
            raise ValueError("Unresolved VIN, production-date or trim restriction")
        if self.target_scope.model_year not in self.covered_model_years:
            raise ValueError("Target year not explicitly covered")
        if self.identity["year_code"].split("-")[0] != str(self.target_scope.model_year):
            raise ValueError("Canonical year mismatch")
        if self.result > self.maximum:
            raise ValueError("Result exceeds protocol maximum")
        if (self.protocol_period_end < self.protocol_period_start
                or not self.protocol_period_start.year <= self.test_year <= self.protocol_period_end.year):
            raise ValueError("Test year outside protocol period")
        for source in (self.result_source, self.protocol_source):
            host = (urlsplit(source.url).hostname or "").lower()
            if source.provider != "latinncap" or host not in {"latinncap.com", "www.latinncap.com"}:
                raise ValueError("Official Latin NCAP result and protocol required")
        if self.applicability_source.provider not in {"manufacturer", "latinncap"}:
            raise ValueError("Official applicability evidence required")
        for filename in (self.result_file, self.applicability_file, self.protocol_file):
            if not filename or "/" in filename or "\\" in filename or ":" in filename or filename in {".", ".."}:
                raise ValueError("Document must be a local cache basename")
        return self


def validate_record(record, vehicle, document_directory):
    record = LatinNCAPRecord.model_validate(record)
    if vehicle.id != record.candidate_id or vehicle.identity_status != "identity_approved":
        raise ValueError("Candidate identity not approved or mismatched")
    for key in IDENTITY_FIELDS:
        observation = vehicle.fields[key]
        if observation.kind != "observed" or observation.value != record.identity[key]:
            raise ValueError("Canonical identity mismatch: " + key)
    if document_directory is None:
        raise ValueError("Offline document directory required")
    root = Path(document_directory).resolve(strict=True)
    for prefix in ("result", "applicability", "protocol"):
        path = (root / getattr(record, prefix + "_file")).resolve(strict=True)
        if path.parent != root or not path.is_file():
            raise ValueError("Document outside authorized cache")
        if hashlib.sha256(path.read_bytes()).hexdigest() != getattr(record, prefix + "_source").sha256:
            raise ValueError("Document hash mismatch: " + prefix)
    return record


def safety_evidence(vehicle, records=(), document_directory=None):
    inputs = {name: vehicle.fields[name].model_dump(mode="json") for name in ("airbags", "abs", "esc")}
    complete = all(vehicle.fields[name].kind == "observed"
                   and vehicle.fields[name].applicability == "exact_variant"
                   and all(s.provider in {"manufacturer", "latinncap"} for s in vehicle.fields[name].sources)
                   for name in inputs)
    if complete:
        value = Decimal(100) * (
            min(vehicle.fields["airbags"].value, Decimal(6)) / Decimal(6)
            + Decimal(int(vehicle.fields["abs"].value)) + Decimal(int(vehicle.fields["esc"].value))
        ) / Decimal(3)
        return {"value": value, "unit": "equipment_index", "nature": "derived_academic",
                "path": "exact_inventory", "comparison_group": "exact_inventory",
                "formula": "100*(min(airbags,6)/6 + ABS + ESC)/3",
                "method_version": "catalog-profile-evidence-v3", "inputs": inputs,
                "reason": None, "equipment_inferred": False}
    candidates = [row for row in records if row.get("candidate_id") == vehicle.id]
    if len(candidates) > 1:
        return {"value": None, "nature": "unavailable", "path": "unavailable", "inputs": inputs,
                "reason": "AMBIGUOUS_LATIN_NCAP_RECORDS", "equipment_inferred": False}
    if candidates:
        try:
            record = validate_record(candidates[0], vehicle, document_directory)
        except (ValueError, OSError) as exc:
            # Do not serialize raw exception/input; dossier input is not trusted.
            return {"value": None, "nature": "unavailable", "path": "unavailable", "inputs": inputs,
                    "reason": "LATIN_NCAP_APPLICABILITY_OR_DOCUMENT_REJECTED",
                    "error_type": type(exc).__name__, "equipment_inferred": False}
        group = (record.protocol_id, str(record.protocol_period_start), str(record.protocol_period_end),
                 record.metric, str(record.maximum), record.protocol_source.sha256)
        return {"value": Decimal(100) * record.result / record.maximum, "unit": "protocol_relative_percent",
                "nature": "derived_academic", "path": "latin_ncap_configuration_test",
                "comparison_group": "latin_ncap:" + "|".join(group),
                "formula": "100 * official_result / official_maximum",
                "method_version": "academic-profile-pilot-v4", "inputs": record.model_dump(mode="json"),
                "equipment_observations": inputs, "equipment_inferred": False, "reason": None}
    return {"value": None, "nature": "unavailable", "path": "unavailable", "inputs": inputs,
            "reason": "NO_COMPLETE_EXACT_INVENTORY_OR_APPLICABLE_LATIN_NCAP_RESULT",
            "equipment_inferred": False}
