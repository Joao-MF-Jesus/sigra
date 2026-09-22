"""Opt-in, offline technical enrichment. Never imported by publication or v3.

The immutable discovery and fiche must agree with the individually reviewed
legacy FIPE/PBEV identity. Inconclusive transmission/trim stays blocked.
"""
import copy
import hashlib
import json
import re
import unicodedata
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from data_platform.catalog.carpedia_profile_evidence import (
    _profile_only_normalization, _source_fuel, _source_transmission,
)
from data_platform.catalog.legacy_academic_v4 import load_manifest as legacy_manifest, _price
from data_platform.catalog.profile_contracts_v3 import Citation, Observation, ProfileVehicle, observed
from data_platform.contracts.carpedia_vehicle_specs import (
    CARPEDIA_NORMALIZER_VERSION, CarpediaRequest, DownloadedCarpediaAsset,
)
from data_platform.ingestion.carpedia.parser import CarpediaJsonParser
from data_platform.transformation.carpedia import normalize_attributes

VERSION = "legacy-technical-v4-evidence-v1"
MANIFEST_PATH = Path(__file__).with_name("legacy_technical_v4_evidence_v1.json")
IDS = (2, 3, 4, 5, 8, 9, 10, 14, 15, 16, 20, 22, 29, 30, 31, 32, 33, 34)
UNITS = {"body_style": None, "seats": "count", "doors": "count", "cargo_capacity": "L",
         "payload_capacity": "kg", "length": "mm", "width": "mm", "wheelbase": "mm",
         "ground_clearance": "mm", "engine_displacement": "cm3", "power": "kW",
         "transmission": None, "fuel_type": None, "fuel_tank_capacity": "L"}
PROFILE = {"seats": "seats", "cargo_capacity": "cargo_l", "payload_capacity": "payload_kg",
           "length": "length_mm", "width": "width_mm", "wheelbase": "wheelbase_mm",
           "ground_clearance": "ground_clearance_mm"}


def exact(value):
    """Whitespace/case normalization only; no token deletion or fuzzy matching."""
    return " ".join(unicodedata.normalize("NFC", str(value)).casefold().split())


def source_citation(source, locator):
    return Citation(provider=source["provider"], url=source["url"], sha256=source["sha256"],
                    document=source["cache_file"], locator=locator, collected_at=source["collected_at"])


def load_manifest(path=MANIFEST_PATH):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if (data["version"] != VERSION or data["normalizer_version"] != CARPEDIA_NORMALIZER_VERSION
            or data["publication_authorized"] is not False or data["database_write_authorized"] is not False
            or [r["id"] for r in data["records"]] != list(IDS)):
        raise ValueError("Technical manifest scope/version mismatch")
    reviews = {r["id"]: r for r in legacy_manifest()["reviews"]}
    for row in data["records"]:
        review = reviews[row["id"]]
        if review["status"] != "identity_approved" or row["catalog"] != review["catalog"]:
            raise ValueError("Technical manifest cannot approve a legacy identity")
        expected = review["fipe"]["expected_identity"]
        if (row["commercial_identity"] != expected["model"] or row["fipe_code"] != expected["codeFipe"]
                or row["year_code"] != review["fipe"]["year_code"]):
            raise ValueError("Technical FIPE binding mismatch")
        for key in ("discovery", "fiche"):
            source = row[key]
            source_citation(source, key)
            if Path(source["cache_file"]).name != source["cache_file"] or source["provider"] != "carpedia":
                raise ValueError("Invalid immutable source reference")
        expected_url = f"https://www.carpedia.com.br/api/v1/ficha/{row['external_id']}/{row['catalog']['year']}"
        if row["fiche"]["url"] != expected_url:
            raise ValueError("Fiche URL identity mismatch")
    price = data["fipe_33"]
    source_citation(price, "FIPE Ka September 2026")
    if price["provider"] != "fipe" or price["url"] != "https://fipe.parallelum.com.br/api/v2/cars/003408-8/years/2019-5":
        raise ValueError("Only the authorized ID 33 FIPE refresh is permitted")
    return data


def parse_record(row, archive):
    discovery = json.loads(archive.bytes(row["discovery"]))
    versions = discovery.get("versoes", discovery.get("data", {}).get("versoes"))
    if not isinstance(versions, list):
        raise ValueError("Discovery contract mismatch")
    matches = [r for r in versions if r.get("id") == row["external_id"]]
    if len(matches) != 1 or {k: matches[0].get(k) for k in row["discovery_identity"]} != row["discovery_identity"]:
        raise ValueError("Discovery identity missing, changed or ambiguous")
    found_discovery = row["discovery_identity"]
    if (exact(found_discovery["nome"]) != exact(row["commercial_identity"])
            or str(row["catalog"]["year"]) not in found_discovery["anos"]
            or found_discovery["combustiveis"] != ["Flex"]):
        raise ValueError("Discovery version/year/fuel mismatch")
    raw = archive.bytes(row["fiche"])
    source = row["fiche"]
    path = next(root / source["cache_file"] for root in archive.directories
                if (root / source["cache_file"]).is_file()
                and hashlib.sha256((root / source["cache_file"]).read_bytes()).hexdigest() == source["sha256"])
    asset = DownloadedCarpediaAsset(
        request=CarpediaRequest("ficha", source["url"], {"ano": row["catalog"]["year"]}, row["external_id"]),
        path=path, collected_at=datetime.fromisoformat(source["collected_at"]), http_status=200,
        content_type="application/json", byte_length=len(raw), sha256=source["sha256"])
    parsed = CarpediaJsonParser().parse(asset)
    found = {"external_id": parsed.raw.external_vehicle_id, "year": parsed.model_year,
             "brand": parsed.brand_name, "model": parsed.model_name, "version": parsed.version_name,
             "source_name": parsed.source_name, "source_at": parsed.source_at}
    if found != row["source_identity"]:
        raise ValueError("Fiche version/year/source identity mismatch")
    if (found["year"] != row["catalog"]["year"] or exact(found["brand"]) != exact(row["catalog"]["brand"])
            or exact(found["version"]) != exact(row["commercial_identity"])):
        raise ValueError("Fiche differs from exact FIPE/version/year")
    items = []
    for item in normalize_attributes(parsed):
        if exact(item.source_label) == exact("Vão livre do solo (mm)"):
            item = _profile_only_normalization(item, {"attribute_code": "ground_clearance"})
        items.append(item)
    return parsed, admit_fields(items)


def admit_fields(items):
    """Return explicit observations and unavailable reasons; never coerce units."""
    fields, missing = {}, {}
    for code, unit in UNITS.items():
        matches = [a for a in items if a.attribute_code == code]
        if not matches:
            missing[code] = "unavailable: field absent"
            continue
        signatures = {(str(a.normalized_value), a.normalized_unit, a.unit_status) for a in matches}
        if len(signatures) != 1:
            missing[code] = "unavailable: conflicting duplicate evidence"
            continue
        a = matches[0]
        if (a.normalized_value is None or a.normalized_unit != unit
                or a.unit_status not in {"recognized", "not_applicable"}):
            missing[code] = "unavailable: invalid/missing unit or value"
            continue
        if unit is not None:
            value = Decimal(a.normalized_value)
            if (not value.is_finite() or value <= 0 or
                    (unit == "count" and value != value.to_integral_value())):
                missing[code] = "unavailable: nonpositive/nonintegral value"
                continue
        elif not str(a.normalized_value).strip():
            missing[code] = "unavailable: empty text"
            continue
        fields[code] = a
    return fields, missing


def identity_blockers(vehicle, row, fields):
    expected = {k: row[k] for k in ("fipe_code", "year_code", "commercial_identity")}
    if (vehicle.id != row["id"] or vehicle.identity_status != "identity_approved"
            or {k: vehicle.fields[k].value for k in expected} != expected):
        raise ValueError("Vehicle differs from approved legacy identity")
    blockers = []
    if "fuel_type" not in fields or _source_fuel(fields["fuel_type"].source_value) != vehicle.fields["fuel"].value:
        blockers.append("CARPEDIA_FUEL_NOT_EXACT")
    if "transmission" not in fields or _source_transmission(fields["transmission"].source_value) != vehicle.fields["transmission"].value:
        blockers.append("CARPEDIA_TRANSMISSION_NOT_EXACT")
    # An aggregated trim title cannot assign trim-specific technical equipment.
    if row["id"] == 33:
        blockers.append("CARPEDIA_SE_SE_PLUS_SCOPE_NOT_INDIVIDUALIZED")
    motor = re.search(r"\b\d\.\d\b", row["source_identity"]["version"])
    if not motor or motor.group() != vehicle.provenance["legacy_v4_review"]["pbev"]["powertrain"][0]:
        blockers.append("CARPEDIA_ENGINE_NOT_EXACT")
    return blockers


def augment_legacy_technical_v4(vehicles, archive, *, manifest_path=MANIFEST_PATH):
    """Pure replay of canonical 34. Missing/ambiguous source never promotes a vehicle."""
    if [v.id for v in vehicles] != list(range(1, 35)):
        raise ValueError("Exact canonical 34 legacy IDs required")
    manifest = load_manifest(manifest_path)
    records = {r["id"]: r for r in manifest["records"]}
    processed = {i: parse_record(row, archive)[1] for i, row in records.items()}
    price_review = copy.deepcopy(next(r for r in legacy_manifest()["reviews"] if r["id"] == 33))
    price_review["fipe"].update(legacy_price_cache=False, reference_month="2026-09")
    price, month, _ = _price(price_review, json.loads(archive.bytes(manifest["fipe_33"])))
    output = []
    for vehicle in vehicles:
        if vehicle.id not in records:
            output.append(vehicle)
            continue
        row = records[vehicle.id]
        admitted, missing = processed[vehicle.id]
        blockers = identity_blockers(vehicle, row, admitted)
        fields = dict(vehicle.fields)
        provenance = dict(vehicle.provenance)
        if vehicle.id == 33:
            ref = source_citation(manifest["fipe_33"], "FIPE=003408-8; year=2019-5; September 2026")
            fields.update(price_brl=observed("price_brl", price, (ref,)),
                          reference_month=observed("reference_month", month, (ref,)))
        evidence = {}
        for code, item in admitted.items():
            evidence[code] = {"value": str(item.normalized_value), "unit": item.normalized_unit,
                              "source_value": item.source_value, "source_unit": item.source_unit,
                              "kind": "observed", "admitted_to_profile": not blockers and code in PROFILE,
                              "source_section": item.source_section, "source_label": item.source_label,
                              "provenance": dict(item.provenance)}
            if blockers:
                continue
            ref = source_citation(row["fiche"], item.provenance["field_locator"])
            if code in PROFILE:
                name = PROFILE[code]
                candidate = observed(name, item.normalized_value, (ref,))
                if fields[name].kind == "unavailable":
                    fields[name] = candidate
                elif fields[name].value != candidate.value or fields[name].unit != candidate.unit:
                    raise ValueError("Technical adapter cannot overwrite existing evidence")
            elif code == "body_style":
                provenance["carpedia_body_type"] = Observation(value=item.normalized_value, unit="text", kind="observed",
                    sources=(ref,), applicability="exact_variant").model_dump(mode="json")
        provenance["legacy_technical_v4"] = {
            "version": VERSION, "manifest_sha256": hashlib.sha256(Path(manifest_path).read_bytes()).hexdigest(),
            "external_id": row["external_id"], "source_identity": row["source_identity"],
            "discovery": row["discovery"], "fiche": row["fiche"], "fields": evidence,
            "unavailable": missing, "blockers": blockers, "source_bytes_verified": True,
            "official_precedence": {"price": "fipe", "fuel": "pbev", "transmission": "pbev", "consumption": "pbev"},
            "power_fuel_basis": "unspecified; never gasoline-specific power",
            "width_semantics": "body only; not mirrors", "no_publication": True}
        output.append(ProfileVehicle.model_validate({**vehicle.model_dump(), "fields": fields, "provenance": provenance}))
    return tuple(output)
