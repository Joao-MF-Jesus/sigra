"""Read-only catalog/Gold identity boundary; never joins physical IDs or fuzzy names.

FIPE price references are evidence, not blanket permission to equate trim levels.
An abbreviated catalog description needs a reviewed, versioned binding. The Etios
binding below records the existing app.fipe.FIPE_REFERENCE_PROFILES[10] contract,
confirmed by its complete cached year_code and the published FIPE description.
It is applied only if that exact FIPE key AND full version are present in the
eligible Gold lineage. It does not assert coverage or manufacture a Gold row.
No binding is authorized for Uno Attractive -> UNO DRIVE.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata
from typing import Mapping, Sequence

from data_platform.integrated_vehicle_cost.simulation_contracts import VehicleCostSimulationResult


IDENTITY_POLICY_VERSION = "catalog-gold-identity-v1"


def identity_text(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = " ".join("".join(char.lower() if char.isalnum() else " " for char in text).split())
    return "volkswagen" if text in {"vw", "vw volkswagen"} else text


@dataclass(frozen=True)
class CatalogGoldBinding:
    mapping_id: str
    version: int
    brand: str
    catalog_model: str
    year: int
    fipe_code: str
    year_code: str
    gold_model: str
    gold_version: str | None
    fuel_type: str
    evidence: str


REVIEWED_BINDINGS = (
    CatalogGoldBinding(
        "toyota-etios-xls-2018-fipe", 1, "Toyota", "Etios XLS", 2018,
        "002150-4", "2018-5", "ETIOS XLS 1.5 Flex 5p Aut.", None, "flex",
        "app.fipe.FIPE_REFERENCE_PROFILES[10]; FIPE cache complete year_code; "
        "published FIPE full model identifies XLS 1.5 Flex 5-door automatic",
    ),
)

_GOLD_FIELDS = (
    "vehicle_sk", "dataset_version", "fipe_dataset_version", "gold_record_id",
    "fipe_code", "year_code", "brand_name", "model_name", "version_name",
    "model_year", "fuel_type", "transmission_type", "source_vehicle_key",
)


def _catalog_key(vehicle: Mapping) -> tuple:
    return identity_text(vehicle.get("brand")), identity_text(vehicle.get("model")), vehicle.get("year")


def _gold_key(row: Mapping) -> tuple:
    return identity_text(row.get("brand_name")), identity_text(row.get("model_name")), row.get("model_year")


def _optional_fields_agree(vehicle: Mapping, row: Mapping) -> bool:
    return all(
        not vehicle.get(field) or identity_text(vehicle[field]) == identity_text(row.get(field))
        for field in ("version_name", "fuel_type", "transmission_type")
    )


def resolve_recommendation_identity(
    vehicle: Mapping,
    results: Sequence[VehicleCostSimulationResult],
    *,
    gold_identities: Sequence[Mapping] | None = None,
    reference: Mapping | None = None,
    bindings: Sequence[CatalogGoldBinding] = REVIEWED_BINDINGS,
) -> tuple[VehicleCostSimulationResult | None, dict]:
    """Return a simulation row and an allowlisted, public-safe audit diagnostic.

    None metadata preserves the exact-identity pure caller contract; the API always
    supplies Gold lineage (including an empty collection). A present FIPE key never
    falls back to names. A missing simulation row is not missing catalog coverage.
    """
    reference = reference or {}
    rows = list(gold_identities) if gold_identities is not None else [
        {"vehicle_sk": result.vehicle_sk, "brand_name": result.brand_name,
         "model_name": result.model_name, "version_name": result.version_name,
         "model_year": result.model_year,
         "dataset_version": result.sources.integrated_dataset_version,
         "fipe_dataset_version": result.sources.fipe_dataset_version}
        for result in results
    ]
    code = vehicle.get("fipe_code") or reference.get("code")
    year_code = reference.get("year_code")
    diagnostic = {
        "policy_version": IDENTITY_POLICY_VERSION,
        "match_method": "none", "mapping_id": None, "mapping_version": None,
        "mapping_evidence": None,
        "expected_identity": {
            "catalog_vehicle_id": vehicle.get("id"), "brand": vehicle.get("brand"),
            "model": vehicle.get("model"), "year": vehicle.get("year"),
            "version_name": vehicle.get("version_name"), "fuel_type": vehicle.get("fuel_type"),
            "fipe_code": code, "year_code": year_code, "fipe_model": reference.get("model"),
        },
        "found_identities": [], "rejection_reason": None,
    }

    def reject(reason: str):
        diagnostic["rejection_reason"] = reason
        return None, diagnostic

    def record(candidates):
        diagnostic["found_identities"] = [
            {field: row.get(field) for field in _GOLD_FIELDS} for row in candidates
        ]

    brand, model, year = _catalog_key(vehicle)
    if not brand or not model or not isinstance(year, int) or isinstance(year, bool):
        return reject("required_identity_missing")

    matching_bindings = [binding for binding in bindings if
        (identity_text(binding.brand), identity_text(binding.catalog_model), binding.year)
        == (brand, model, year)]
    if len(matching_bindings) > 1:
        return reject("ambiguous_mapping")
    binding = matching_bindings[0] if matching_bindings else None
    if binding:
        diagnostic["mapping_evidence"] = binding.evidence

    if code:
        diagnostic["match_method"] = "fipe_code"
        if not re.fullmatch(r"[0-9]{6}-[0-9]", str(code)):
            return reject("required_identity_missing")
        # Show existing code candidates, even if the year/fuel or trim is wrong.
        code_rows = [row for row in rows if row.get("fipe_code") == code]
        record(code_rows)
        if not code_rows:
            return reject("coverage_absent")
        if not re.fullmatch(r"[0-9]{4}-[A-Za-z0-9]+", str(year_code or "")):
            return reject("required_identity_missing")
        if int(str(year_code).split("-", 1)[0]) != year:
            return reject("identity_mismatch")
        candidates = [row for row in code_rows if row.get("year_code") == year_code]
        if not candidates:
            return reject("coverage_absent")
        if reference.get("code") != code or not reference.get("model"):
            return reject("identity_mismatch")
        if binding:
            diagnostic.update(match_method="explicit_mapping", mapping_id=binding.mapping_id,
                              mapping_version=binding.version)
            if (code, year_code, identity_text(reference["model"])) != (
                binding.fipe_code, binding.year_code, identity_text(binding.gold_model)
            ):
                return reject("identity_mismatch")
            compatible = lambda row: (
                _gold_key(row) == (brand, identity_text(binding.gold_model), year)
                and identity_text(row.get("version_name")) == identity_text(binding.gold_version)
                and row.get("fuel_type") == binding.fuel_type
            )
        else:
            # A price reference to another trim (e.g. Attractive -> DRIVE) is not
            # identity evidence. Do not bless every ID-based legacy price profile.
            if model != identity_text(reference["model"]):
                return reject("identity_mismatch")
            compatible = lambda row: (
                _gold_key(row) == (brand, model, year)
                and identity_text(row.get("version_name")) == identity_text(vehicle.get("version_name"))
            )
        if not all(compatible(row) and _optional_fields_agree(vehicle, row) for row in candidates):
            return reject("identity_mismatch")
    elif binding:
        # Explicit mapping without a common catalog key still requires its full
        # reviewed target key/version/fuel in the published source.
        diagnostic.update(match_method="explicit_mapping", mapping_id=binding.mapping_id,
                          mapping_version=binding.version)
        candidates = [row for row in rows if row.get("fipe_code") == binding.fipe_code
                      and row.get("year_code") == binding.year_code]
        record(candidates)
        if not candidates:
            return reject("coverage_absent")
        if not all(_gold_key(row) == (brand, identity_text(binding.gold_model), year)
                   and identity_text(row.get("version_name")) == identity_text(binding.gold_version)
                   and row.get("fuel_type") == binding.fuel_type
                   and _optional_fields_agree(vehicle, row) for row in candidates):
            return reject("identity_mismatch")
    else:
        diagnostic["match_method"] = "exact_identity"
        candidates = [row for row in rows if _gold_key(row) == (brand, model, year)]
        record(candidates)
        if not candidates:
            # Without a stable key there is no proof of absence vs a naming gap.
            return reject("identity_unresolved")
        if not all(identity_text(row.get("version_name")) == identity_text(vehicle.get("version_name"))
                   and _optional_fields_agree(vehicle, row) for row in candidates):
            return reject("identity_mismatch")

    record(candidates)
    if len(candidates) != 1:
        return reject("ambiguous_identity")
    row = candidates[0]
    matches = [result for result in results if result.vehicle_sk == row["vehicle_sk"]
               and result.sources.integrated_dataset_version == row.get("dataset_version")
               and result.sources.fipe_dataset_version == row.get("fipe_dataset_version")]
    if not matches:
        return reject("scenario_evidence_unavailable")
    if len(matches) != 1:
        return reject("ambiguous_identity")
    result = matches[0]
    if (_gold_key(row) != (identity_text(result.brand_name), identity_text(result.model_name), result.model_year)
            or identity_text(row.get("version_name")) != identity_text(result.version_name)):
        return reject("identity_mismatch")
    return result, diagnostic
