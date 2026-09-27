"""Opt-in, offline Batch 4. No production, network or publication entry point."""
from datetime import datetime
from decimal import Decimal
import hashlib
import json
from pathlib import Path

from data_platform.catalog.adapter import prepare_batch
from data_platform.catalog.crosswalk import review_batch, fingerprint
from data_platform.catalog.intake import load_selection
from data_platform.catalog.profile_contracts_v3 import Citation, ProfileVehicle, UNITS, observed
from data_platform.catalog.profile_pilot_v4 import evaluate_vehicle
from data_platform.contracts.carpedia_vehicle_specs import CarpediaRequest, DownloadedCarpediaAsset
from data_platform.ingestion.carpedia.parser import CarpediaJsonParser
from data_platform.transformation.carpedia import normalize_attribute

ROOT = Path(__file__).parent
VERSION = "batch4-academic-v4-evidence-v1"
IDS = (44, 45, 51, 52, 54, 56)
FIELDS = {"seats": "seats", "length": "length_mm", "width": "width_mm",
          "wheelbase": "wheelbase_mm", "cargo_capacity": "cargo_l", "payload_capacity": "payload_kg"}
REQUIRED = {"seats", "width_mm", "wheelbase_mm"}


def load_manifest(path=ROOT / "batch4_evidence_v1.json", collection_path=ROOT / "batch4_collection_v1.json"):
    manifest = json.loads(Path(path).read_text(encoding="utf-8"))
    plan = json.loads(Path(collection_path).read_text(encoding="utf-8"))
    existing = set()
    for name in ("carpedia_profile_evidence_v1.json", "carpedia_profile_evidence_batch2_v1.json"):
        existing.update(json.loads((ROOT / name).read_text(encoding="utf-8"))["scope"]["candidate_ids"])
    existing.update(json.loads((ROOT / "batch3_collection_v1.json").read_text(encoding="utf-8"))["admitted_ids"])
    reserved = {v.id for v in load_selection().candidates}
    ids = [r["id"] for r in manifest["records"]]
    if (manifest["version"] != VERSION or plan["version"] != "batch4-collection-v1"
            or ids != list(IDS) or plan["admitted_ids"] != ids
            or plan["existing_new_ids"] != sorted(existing) or len(existing) != 20
            or plan["legacy_ids"] != list(range(1, 35)) or set(ids) & existing
            or not set(ids) <= reserved or plan["maximum_total_identities"] != 60
            or 34 + len(existing) + len(ids) != 60
            or any(plan[k] is not False for k in ("publication_authorized", "database_write_authorized", "operational_activation_authorized"))):
        raise ValueError("Batch 4 scope/authorization mismatch")
    for row in manifest["records"]:
        source = row["source"]
        if source["provider"] != "carpedia" or Path(source["cache_file"]).name != source["cache_file"]:
            raise ValueError("Invalid source path/provider")
        codes = [f["attribute_code"] for f in row["fields"]]
        locators = [f["locator"] for f in row["fields"]]
        if (len(set(codes)) != len(codes) or len(set(locators)) != len(locators)
                or set(codes) - set(FIELDS) or not REQUIRED <= {FIELDS[c] for c in codes}):
            raise ValueError("Missing/duplicate/forbidden technical fields")
    return manifest


def _items(payload):
    result = {}
    for section in payload["secoes"]:
        for item in section["itens"]:
            key = (section["titulo"], item["label"])
            if key in result:
                raise ValueError("Duplicate raw field label")
            result[key] = item["valor"]
    return result


def admit_vehicle(vehicle, row, archive):
    decisions = [r for r in review_batch()["decisions"] if r["id"] == row["id"]]
    if len(decisions) != 1 or decisions[0]["status"] != "identity_approved":
        raise ValueError("One approved FIPE/PBEV crosswalk required")
    decision = decisions[0]
    review = decision["review"]
    if fingerprint(review) != row["crosswalk_fingerprint"]:
        raise ValueError("Pinned crosswalk changed")
    prepare_batch(decisions, archive)
    if vehicle.id != row["id"] or vehicle.identity_status != "identity_approved" or vehicle.source_conflicts:
        raise ValueError("Identity/source conflict")
    if vehicle.human_approval_required and vehicle.human_approval_status != "human_approved":
        raise ValueError("Human approval still pending")
    expected = {"fipe_code": review["fipe"]["CodigoFipe"], "year_code": review["year_code"],
                "commercial_identity": review["fipe"]["Modelo"], "reference_month": "2026-09",
                "fuel": review["powertrain"][4], "transmission": review["powertrain"][3]}
    if row["identity"] != expected or any(vehicle.fields[k].value != v for k, v in expected.items()):
        raise ValueError("Exact official identity mismatch")
    for field, key in (("price_brl", "price_brl"), ("consumption_city", "city_km_l"), ("consumption_highway", "highway_km_l")):
        if vehicle.fields[field].value != Decimal(str(decision["observed"][key])):
            raise ValueError("Official financial/consumption observation changed")
    source = row["source"]
    raw = archive.bytes(source)
    if hashlib.sha256(raw).hexdigest() != source["sha256"]:
        raise ValueError("Cache hash mismatch")
    payload = json.loads(raw)
    identity = payload["versao"]
    if (identity != row["source_identity"] or identity["id"] != int(expected["fipe_code"].replace("-", ""))
            or identity["nome"] != expected["commercial_identity"]
            or str(payload["ano"]) != expected["year_code"][:4] or payload["ref"] != "09-2026"
            or payload["fonte"] != row["upstream_source"]):
        raise ValueError("CarPedia exact version/year/source mismatch")
    items = _items(payload)
    for field in row["mechanical_evidence"]:
        if items.get((field["section"], field["label"])) != field["value"]:
            raise ValueError("Mechanical field missing or changed")
    transmission = items.get(("Transmissão e tração", "Câmbio (tipo)"))
    gears = items.get(("Transmissão e tração", "Número de marchas"))
    raw_pbev = review["pbev"]["transmission_code"]
    if expected["transmission"] == "cvt":
        valid_transmission = transmission == "Automático (CVT)" and raw_pbev == "CVT"
    else:
        prefix, label = ("M", "Manual") if expected["transmission"] == "manual" else ("A", "Automático")
        valid_transmission = transmission == label and raw_pbev.replace("-", "") == prefix + str(gears)
    if not valid_transmission or items.get(("Geral", "Combustível")) != "Flex" or expected["fuel"] != "flex":
        raise ValueError("Fuel/transmission is not explicitly compatible")
    path = next((d / source["cache_file"] for d in archive.directories
                 if (d / source["cache_file"]).is_file() and hashlib.sha256((d / source["cache_file"]).read_bytes()).hexdigest() == source["sha256"]), None)
    asset = DownloadedCarpediaAsset(request=CarpediaRequest("vehicle_specification",
        f"/api/v1/ficha/{identity['id']}/{payload['ano']}", external_vehicle_id=identity["id"],
        source_reference=f"{identity['id']}:{payload['ano']}"), path=path,
        collected_at=datetime.fromisoformat(source["collected_at"]), http_status=200,
        content_type="application/json", byte_length=len(raw), sha256=source["sha256"])
    parsed = CarpediaJsonParser().parse(asset)
    normalized = {a.provenance["field_locator"]: normalize_attribute(a) for a in parsed.attributes}
    fields = dict(vehicle.fields)
    for fact in row["fields"]:
        item = normalized.get(fact["locator"])
        if item is None or item.attribute_code not in FIELDS:
            raise ValueError("Unrecognized field")
        actual = {k: getattr(item, k) for k in ("attribute_code", "source_section", "source_label", "source_value", "source_unit", "normalized_unit")}
        actual["normalized_value"] = str(item.normalized_value)
        if actual != {k: fact[k] for k in actual} or item.unit_status not in {"recognized", "not_applicable"}:
            raise ValueError("Field value/unit differs from reviewed evidence")
        name = FIELDS[item.attribute_code]
        # The existing CarPedia contract spells litres "L"; profile v3 uses "l".
        unit = "l" if item.normalized_unit == "L" else item.normalized_unit
        if unit != UNITS[name] or Decimal(item.normalized_value) <= 0:
            raise ValueError("Invalid positive technical unit/value")
        citation = Citation(provider="carpedia", url=source["url"], sha256=source["sha256"],
            document=source["document"], locator=fact["locator"], collected_at=source["collected_at"])
        value = observed(name, item.normalized_value, (citation,), limitations=tuple(row["limitations"]))
        if fields[name].kind != "unavailable" and fields[name] != value:
            raise ValueError("Existing evidence cannot be overwritten")
        fields[name] = value
    result = ProfileVehicle.model_validate({**vehicle.model_dump(), "fields": fields,
        "provenance": {**vehicle.provenance, "batch4_v4": {"version": VERSION, "review": row, "source_bytes_verified": True, "no_publication": True}}})
    for scenario in ("low", "base", "high"):
        evaluation = evaluate_vehicle(result, "app", scenario, "2026-09")
        if not evaluation["academic_test_ready"] or not evaluation["scenario_tco_complete"]:
            raise ValueError("Academic readiness not satisfied")
        if evaluation["operationally_active"] or evaluation["recommended"]:
            raise ValueError("Operational admission prohibited")
    return result


def batch4_matrix(vehicles, archive, *, manifest_path=ROOT / "batch4_evidence_v1.json"):
    vehicles = tuple(vehicles)
    by_id = {v.id: v for v in vehicles}
    if len(by_id) != len(vehicles):
        raise ValueError("Duplicate input ID")
    output = []
    for row in load_manifest(manifest_path)["records"]:
        if row["id"] not in by_id:
            raise ValueError("Missing candidate")
        result = admit_vehicle(by_id[row["id"]], row, archive)
        key = tuple(result.fields[k].value for k in ("fipe_code", "year_code"))
        if any(v.id != result.id and tuple(v.fields[k].value for k in ("fipe_code", "year_code")) == key for v in vehicles):
            raise ValueError("Duplicate canonical identity")
        output.append(result)
    return tuple(output)
