"""Reviewed complementary evidence, exclusively for the explicit alternative.

No replay builder, profile gate, operational repository or reference motor uses
this batch. Resolution returns a copy and never mutates an approved vehicle.
"""
from copy import deepcopy
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path

from data_platform.catalog.profile_contracts_v3 import Citation, observed, unavailable

VERSION = "academic-derived-mass-power-evidence-v1"
POLICY = "academic-derived-seven-v1"
PATH = Path(__file__).with_name("derived_mass_power_v1.json")
EXPECTED_SHA256 = "1ca7b982237d2c7a95cec3ca86cf85f1f18e9e6bcabba11c4893629ff30a91a2"
IDS = (31, 34, 44, 55, 62, 76, 80, 108, 124)
FIELDS = {"weight_kg": ("kg", "curb_order_of_march"),
          "power_gasoline_cv": ("cv", "gasoline_nominal_power")}
IDENTITY_KEYS = ("fipe_code", "year_code", "commercial_identity", "fuel", "transmission")


def validate_batch(batch):
    """Fail closed on contract, scope, definitions, identities and citations."""
    if batch.get("schema_version") != VERSION or batch.get("policy_version") != POLICY:
        raise ValueError("Supplementary mass/power contract version mismatch")
    if batch.get("authorized_ids") != list(IDS) or set(batch.get("authorized_fields", [])) != set(FIELDS):
        raise ValueError("Supplementary evidence scope mismatch")
    records = batch.get("records")
    if not isinstance(records, list) or len(records) != len(IDS):
        raise ValueError("Exactly nine reviewed identities required")
    seen = set()
    for record in records:
        identifier = record.get("catalog_id")
        if type(identifier) is not int or identifier not in IDS or identifier in seen:
            raise ValueError("Duplicate or unauthorized reviewed identity")
        seen.add(identifier)
        identity, target = record.get("identity", {}), record.get("target", {})
        if set(identity) != set(IDENTITY_KEYS) or not all(isinstance(v, str) and v for v in identity.values()):
            raise ValueError("Exact canonical identity required")
        if identity["fuel"] not in {"flex", "gasoline"} or target.get("market") != "BR":
            raise ValueError("Brazilian gasoline-compatible target required")
        if (str(target.get("model_year")) != identity["year_code"].split("-")[0]
                or target.get("transmission") != identity["transmission"]
                or not all(target.get(k) for k in ("manufacturer", "variant", "engine", "body"))):
            raise ValueError("Target year, version, engine, body and transmission required")
        evidence = record.get("evidence", {})
        if set(evidence) != set(FIELDS):
            raise ValueError("Only mass and gasoline nominal power are authorized")
        for field, (unit, definition) in FIELDS.items():
            entry = evidence[field]
            if entry.get("unit") != unit or entry.get("definition") != definition:
                raise ValueError("Incompatible mass/power definition or unit")
            if entry.get("fuel_reference") != "gasoline":
                raise ValueError("Nominal gasoline power reference required")
            if entry.get("status") not in {"ADMISSIBLE", "PRESERVED_EXISTING", "BLOCKED"}:
                raise ValueError("Unknown evidence admissibility")
            if entry["status"] == "BLOCKED":
                if entry.get("value") is not None or not entry.get("reason"):
                    raise ValueError("Blocked evidence must stay unknown with reason")
            else:
                try:
                    number = Decimal(entry["value"])
                    if not isinstance(entry["value"], str) or not number.is_finite() or number <= 0:
                        raise ValueError("Positive exact Decimal input required")
                except (InvalidOperation, TypeError, KeyError):
                    raise ValueError("Invalid reviewed numeric evidence") from None
            citation = Citation.model_validate(entry.get("source", {}))
            if citation.provider != "manufacturer" or not entry.get("justification") or not entry.get("limitations"):
                raise ValueError("Manufacturer evidence and applicability review required")
            representation = entry.get("representation")
            if representation == "original_manufacturer_document":
                if entry.get("original_document_sha256") != citation.sha256:
                    raise ValueError("Original document hash mismatch")
            elif representation == "normalized_public_document_reader_capture":
                if entry.get("original_document_sha256") is not None:
                    raise ValueError("Normalized capture cannot claim original PDF hash")
            else:
                raise ValueError("Unsupported preserved representation")
    if seen != set(IDS):
        raise ValueError("Reviewed identity set mismatch")
    return batch


def configuration():
    raw = PATH.read_bytes()
    if hashlib.sha256(raw).hexdigest() != EXPECTED_SHA256:
        raise ValueError("Supplementary mass/power manifest integrity mismatch")
    return validate_batch(json.loads(raw))


def verify_preserved_sources(directory, batch=None):
    """Explicit offline audit, not a runtime dependency on local source paths."""
    batch = validate_batch(deepcopy(batch)) if batch is not None else configuration()
    root = Path(directory).resolve()
    verified = {}
    for record in batch["records"]:
        for entry in record["evidence"].values():
            citation = entry["source"]
            name = citation["document"]
            path = (root / name).resolve()
            if path.parent != root or not path.is_file():
                raise ValueError("Missing or unsafe preserved source")
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
            if actual != citation["sha256"]:
                raise ValueError("Preserved mass/power source integrity mismatch")
            verified[name] = actual
    return verified


def resolve(vehicle, batch=None):
    """Resolve just the two alternative inputs; preserve existing exact evidence."""
    batch = validate_batch(deepcopy(batch)) if batch is not None else configuration()
    record = next((r for r in batch["records"] if r["catalog_id"] == vehicle.id), None)
    if record is None:
        return vehicle, {}
    result = vehicle.model_copy(deep=True)
    diagnostics = {}
    expected, actual = record["identity"], {key: vehicle.fields[key].value for key in IDENTITY_KEYS}
    identity_matches = (expected == actual and vehicle.identity_status == "identity_approved"
                        and not vehicle.human_approval_required
                        and vehicle.human_approval_status != "pending")
    for field, (unit, definition) in FIELDS.items():
        entry, current = record["evidence"][field], vehicle.fields[field]
        status = entry["status"]
        reason = None
        if not identity_matches:
            status, reason = "BLOCKED_IDENTITY", "Identidade, versão, ano ou combustível não correspondem ao lote revisado."
        elif status == "BLOCKED":
            reason = "Falta massa em ordem de marcha comprovada para o Focus Fastback SE Plus 2018."
        elif current.kind != "unavailable":
            # Equal existing evidence is retained, including original citations.
            if (current.kind != "observed" or current.unit != unit or current.applicability != "exact_variant"
                    or not current.sources or current.value != Decimal(entry["value"])):
                status, reason = "BLOCKED_CONFLICT", "O valor revisado diverge da observação existente; conflito não resolvido."
            else:
                status = "PRESERVED_EXISTING"
        else:
            if status == "PRESERVED_EXISTING":
                status, reason = "BLOCKED_CONFLICT", "A observação a preservar não está presente no snapshot."
            else:
                result.fields[field] = observed(field, Decimal(entry["value"]),
                    (Citation.model_validate(entry["source"]),), limitations=tuple(entry["limitations"]))
        if reason is not None and identity_matches:
            result.fields[field] = unavailable(field, reason, current.sources)
        # A rejected crosswalk is not permission to discard independent,
        # already-validated evidence for another identity. No batch value is
        # attached when identities diverge; existing inputs remain untouched.
        diagnostics[field] = {
            "version": VERSION, "manifest_sha256": EXPECTED_SHA256,
            "status": status, "definition": definition, "fuel_reference": "gasoline",
            "representation": entry["representation"],
            "original_document_sha256": entry["original_document_sha256"],
            "reviewed_source_sha256": entry["source"]["sha256"],
            "reason": reason, "identity_verified": identity_matches,
            "limitations": list(entry["limitations"]),
        }
    return result, diagnostics
