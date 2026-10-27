"""Additive offline academic membership; no database, network or publication API."""
from datetime import datetime
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re

from data_platform.catalog.intake import load_selection
from data_platform.catalog.profile_contracts_v3 import Citation, ProfileVehicle, UNITS, blank_fields, observed
from data_platform.catalog.profile_evidence_v3 import canonical_month
from data_platform.catalog.profile_pilot_v4 import evaluate_vehicle, fingerprint
from data_platform.catalog.profile_scoring_v3 import configuration as profile_configuration
from data_platform.contracts.carpedia_vehicle_specs import CarpediaRequest, DownloadedCarpediaAsset
from data_platform.contracts.pbev import AUDITED_ASSET_BY_YEAR
from data_platform.ingestion.carpedia.parser import CarpediaJsonParser
from data_platform.transformation.carpedia import normalize_attribute
from data_platform.transformation.fipe import parse_brl_price

ROOT = Path(__file__).parent
VERSION = "academic-cohort-v5"
HOLDOUTS = (1, 6, 7, 9, 11, 13, 17, 18, 19, 21, 23, 24, 25, 26, 27, 28, 33)
SCENARIOS = ("low", "base", "high")
TECHNICAL = {"seats": "seats", "length": "length_mm", "width": "width_mm",
             "wheelbase": "wheelbase_mm", "cargo_capacity": "cargo_l", "payload_capacity": "payload_kg"}
GEARS = {"M-5": "manual", "A-4": "automatic", "A-6": "automatic", "A-10": "automatic", "CVT": "cvt"}
FIPE_KEYS = {"Marca", "Modelo", "AnoModelo", "CodigoFipe", "Combustivel", "MesReferencia", "Valor"}
PBEV_KEYS = {"brand_name", "model_name", "version_name", "motor_description", "transmission_code", "fuel_type"}


def configuration(path=ROOT / "academic_cohort_v5.json"):
    config = json.loads(Path(path).read_text(encoding="utf-8"))
    ids, ready, extra = (config[k] for k in ("baseline_inventory_ids", "baseline_ready_ids", "additional_selected_ids"))
    reserved = {v.id for v in load_selection().candidates}
    if (config["version"] != VERSION or config["target_size"] != 60 or config["maximum_additional"] != 17
            or config["target_month"] != "2026-09" or config["methodology"] != "academic-profile-pilot-v4"
            or config["holdout_ids"] != list(HOLDOUTS) or len(ids) != 60 or ids != sorted(set(ids))
            or ready != sorted(set(ids) - set(HOLDOUTS)) or len(ready) != 43
            or extra != sorted(set(extra)) or len(extra) > 17 or set(extra) & set(ids) or not set(extra) <= reserved
            or set(config["baseline_vehicle_fingerprints"]) != {str(i) for i in ids}
            or any(not re.fullmatch(r"[0-9a-f]{64}", h) for h in config["baseline_vehicle_fingerprints"].values())
            or config["transmission_codes"] != GEARS or config["operational_activation_authorized"] is not False
            or config["publication_authorized"] is not False):
        raise ValueError("Invalid v5 academic scope")
    return config


def load_evidence(path=ROOT / "academic_cohort_v5_evidence.json"):
    manifest = json.loads(Path(path).read_text(encoding="utf-8"))
    if (manifest["version"] != "academic-cohort-v5-evidence-v1"
            or [r["id"] for r in manifest["records"]] != configuration()["additional_selected_ids"]):
        raise ValueError("Evidence membership differs from configuration")
    return manifest


def _citation(source, locator, page=None):
    return Citation(**{k: source[k] for k in ("provider", "url", "sha256", "document", "collected_at")}, locator=locator, page=page)


def _items(payload):
    result = {}
    for section in payload["secoes"]:
        for item in section["itens"]:
            key = section["titulo"], item["label"]
            if key in result:
                raise ValueError("Duplicate technical field")
            result[key] = item["valor"]
    return result


def admit_record(record, archive):
    """Revalidate pinned sources and reviewed bindings, never mutate a legacy."""
    config = configuration()
    identifier = record["id"]
    if identifier not in config["additional_selected_ids"]:
        raise ValueError("Unselected identity")
    candidate = next(v for v in load_selection().candidates if v.id == identifier)
    if candidate.model_dump(mode="json") != record["catalog_target"]:
        raise ValueError("Reserved target changed")
    year = candidate.model_year
    review = record["review"]
    if review["status"] != "exact_variant_reviewed" or review["year"] != year or not review["rationale"]:
        raise ValueError("Exact review required")
    sources = record["sources"]
    if set(record["fipe_identity"]) != FIPE_KEYS or set(record["pbev_identity"]) != PBEV_KEYS:
        raise ValueError("Incomplete reviewed identity")
    for provider in ("fipe", "pbev", "carpedia"):
        if sources[provider]["provider"] != provider:
            raise ValueError("Source priority mismatch")
        _citation(sources[provider], "source validation")
    fipe = json.loads(archive.bytes(sources["fipe"]))
    if ({k: fipe[k] for k in record["fipe_identity"]} != record["fipe_identity"] or fipe["TipoVeiculo"] != 1
            or fipe["AnoModelo"] != year or not re.fullmatch(r"\d{6}-\d", fipe["CodigoFipe"])
            or canonical_month(fipe["MesReferencia"]) != config["target_month"]):
        raise ValueError("FIPE observation/type/year/month changed")
    rows = json.loads(archive.bytes(sources["pbev_parse"]))["rows"]
    matches = [r for r in rows if r["raw"]["row_hash"] == record["pbev_row_hash"]]
    if len(matches) != 1:
        raise ValueError("PBEV row missing or ambiguous")
    pbev = matches[0]
    if ({k: pbev[k] for k in record["pbev_identity"]} != record["pbev_identity"]
            or pbev["raw"]["cycle_year"] != year or not pbev["version_name"] or "/" in pbev["version_name"]
            or pbev.get("propulsion_type") not in (None, "combustion")
            or pbev["raw"]["page_number"] != record["pbev_locator"]["page"]
            or pbev["raw"]["row_number"] != record["pbev_locator"]["row"]
            or sum(all(r[k] == pbev[k] for k in record["pbev_identity"]) for r in rows) != 1):
        raise ValueError("Individual PBEV trim/year/locator required")
    if hashlib.sha256(archive.bytes(sources["pbev"])).hexdigest() != AUDITED_ASSET_BY_YEAR[year].sha256:
        raise ValueError("Unaudited PBEV document")
    fuel = {"Gasolina": "gasoline", "Flex": "flex"}.get(fipe["Combustivel"])
    gearbox = pbev["transmission_code"]
    transmission = GEARS.get(gearbox)
    if fuel is None or fuel != pbev["fuel_type"] or transmission is None:
        raise ValueError("Fuel/transmission conflict")
    engine = record["engine_binding"]
    commercial = re.search(r"(?<!\d)\d\.\d(?!\d)", fipe["Modelo"])
    motor = re.search(r"(?<!\d)(\d\.\d)(?!\d).*?(\d+)V", pbev["motor_description"])
    if (not commercial or not motor or commercial.group() != engine["commercial_displacement_l"]
            or motor.group(1) != engine["pbev_displacement_l"] or motor.group(1) != commercial.group()
            or int(motor.group(2)) != engine["pbev_valves"]):
        raise ValueError("Engine displacement/valve binding changed")
    source = sources["carpedia"]
    raw = archive.bytes(source)
    payload = json.loads(raw)
    external = int(fipe["CodigoFipe"].replace("-", ""))
    if (payload["versao"] != record["source_identity"] or payload["versao"]["id"] != external
            or payload["versao"]["nome"] != fipe["Modelo"] or str(payload["ano"]) != str(year)
            or payload["ref"] != "09-2026" or payload["fonte"] != record["upstream_source"]):
        raise ValueError("Technical code/version/year/provenance mismatch")
    items = _items(payload)
    if items.get(("Motor a combustão", "Aspiração")) != engine["aspiration"]:
        raise ValueError("Explicit aspiration evidence changed")
    for fact in record["mechanical_evidence"]:
        if items.get((fact["section"], fact["label"])) != fact["value"]:
            raise ValueError("Mechanical observation changed")
    expected_gear = {"manual": "Manual", "automatic": "Automático", "cvt": "Automático (CVT)"}[transmission]
    if (items.get(("Geral", "Combustível")) != fipe["Combustivel"]
            or items.get(("Transmissão e tração", "Câmbio (tipo)")) != expected_gear
            or (gearbox != "CVT" and items.get(("Transmissão e tração", "Número de marchas")) != gearbox.split("-")[1])):
        raise ValueError("Technical fuel/gearing differs from PBEV")
    wheel = re.search(r"aro (\d+)", pbev["version_name"])
    if wheel and not re.search(r"R" + wheel.group(1) + r"\b", items.get(("Chassi, direção, freios e rodas", "Medida dos pneus"), "")):
        raise ValueError("Wheel configuration conflict")
    path = next((p / source["cache_file"] for p in archive.directories if (p / source["cache_file"]).is_file()
                 and hashlib.sha256((p / source["cache_file"]).read_bytes()).hexdigest() == source["sha256"]), None)
    if path is None:
        raise ValueError("Technical source path missing")
    asset = DownloadedCarpediaAsset(CarpediaRequest("vehicle_specification", f"/api/v1/ficha/{external}/{year}",
        external_vehicle_id=external, source_reference=f"{external}:{year}"), path,
        datetime.fromisoformat(source["collected_at"]), 200, "application/json", len(raw), source["sha256"])
    normalized = {i.provenance["field_locator"]: i for i in (normalize_attribute(r) for r in CarpediaJsonParser().parse(asset).attributes)}
    fields = blank_fields()
    fipe_ref = _citation(sources["fipe"], f"code={fipe['CodigoFipe']};year={year}")
    pbev_ref = _citation(sources["pbev"], f"row={record['pbev_locator']['row']};sha256={record['pbev_row_hash']}", record["pbev_locator"]["page"])
    for name, value in {"fipe_code": fipe["CodigoFipe"], "year_code": f"{year}-" + ("5" if fuel == "flex" else "1"),
                        "commercial_identity": fipe["Modelo"], "reference_month": config["target_month"], "price_brl": parse_brl_price(fipe["Valor"])}.items():
        fields[name] = observed(name, value, (fipe_ref,))
    for name, value in {"fuel": fuel, "transmission": transmission, "consumption_city": str(pbev["fossil_city_km_l"]),
                        "consumption_highway": str(pbev["fossil_highway_km_l"])}.items():
        fields[name] = observed(name, value, (pbev_ref,))
    seen = set()
    for fact in record["fields"]:
        item = normalized.get(fact["locator"])
        if item is None or item.attribute_code not in TECHNICAL or item.unit_status not in {"recognized", "not_applicable"}:
            raise ValueError("Unrecognized technical field/unit")
        name = TECHNICAL[item.attribute_code]
        unit = "l" if item.normalized_unit == "L" else item.normalized_unit
        if (name in seen or fact["name"] != name or unit != fact["unit"] or unit != UNITS[name]
                or fact["attribute_code"] != item.attribute_code or fact["source_value"] != item.source_value
                or fact["source_label"] != item.source_label or fact["source_section"] != item.source_section
                or str(item.normalized_value) != fact["value"] or Decimal(fact["value"]) <= 0):
            raise ValueError("Technical value/unit/locator changed or duplicated")
        seen.add(name)
        fields[name] = observed(name, fact["value"], (_citation(source, fact["locator"]),), limitations=tuple(record["limitations"]))
    if not {"seats", "width_mm", "wheelbase_mm"} <= seen:
        raise ValueError("Habitability observations incomplete")
    return ProfileVehicle(id=identifier, label=fipe["Modelo"], identity_status="identity_approved", fields=fields,
        provenance={"academic_cohort_v5": {"record_fingerprint": fingerprint(record), "source_bytes_verified": True,
                    "no_publication": True, "safety_inventory": "unknown"}})


def build_cohort(inventory, archive, *, excluded_ids=()):
    """Logical exclusion retains all inventory; reinsertion recomputes readiness."""
    config, manifest = configuration(), load_evidence()
    inventory = tuple(ProfileVehicle.model_validate(v.model_dump()) for v in inventory)
    by_id = {v.id: v for v in inventory}
    if len(by_id) != len(inventory) or sorted(by_id) != config["baseline_inventory_ids"]:
        raise ValueError("Baseline inventory changed")
    if any(fingerprint(v) != config["baseline_vehicle_fingerprints"][str(v.id)] for v in inventory):
        raise ValueError("Frozen inventory evidence changed")
    additional = tuple(admit_record(r, archive) for r in manifest["records"])
    excluded = set(excluded_ids)
    if not excluded <= set(by_id) | {v.id for v in additional}:
        raise ValueError("Unknown logical exclusion")
    allowed = set(config["baseline_ready_ids"]) | {v.id for v in additional}
    profiles = tuple(profile_configuration()["profiles"])
    states, keys = [], set()
    for v in sorted(inventory + additional, key=lambda x: x.id):
        holdout = v.id in HOLDOUTS
        evaluations = {} if holdout else {s: {p: evaluate_vehicle(v, p, s, config["target_month"]) for p in profiles} for s in SCENARIOS}
        passing = [] if holdout else [p for p in profiles if all(evaluations[s][p]["academic_test_ready"] for s in SCENARIOS)]
        ready = bool(passing)
        if v.id in allowed and not ready:
            raise ValueError(f"Reviewed membership no longer testable: {v.id}")
        selected = v.id in allowed and ready and v.id not in excluded
        if selected:
            key = (v.fields["fipe_code"].value, v.fields["year_code"].value[:4])
            if key in keys:
                raise ValueError("Duplicate canonical FIPE/year identity")
            keys.add(key)
        states.append({"id": v.id, "identity": v.label, "inventory_registered": True,
            "legacy_holdout": holdout, "academic_cohort_selected": selected, "academic_test_ready": ready,
            "operationally_active": False, "recommended": False, "ready_profiles": passing, "evaluations": evaluations,
            "exclusion_reason": "preserved_legacy_evidence_holdout" if holdout else "logical_exclusion" if v.id in excluded else None})
    selected = [r for r in states if r["academic_cohort_selected"]]
    if len(selected) > config["target_size"]:
        raise ValueError("Academic cohort exceeds authorization")
    return {"version": VERSION, "decision": "ACADEMIC_COHORT_V5_COMPLETE" if len(selected) == 60 else "ACADEMIC_COHORT_V5_PARTIAL",
        "inventory_count": len(states), "cohort_size": len(selected), "target": 60, "unfilled_slots": 60 - len(selected),
        "academic_test_ready_count": sum(r["academic_test_ready"] for r in states), "selected_ids": [r["id"] for r in selected],
        "holdout_ids": list(HOLDOUTS), "profile_counts": {p: sum(p in r["ready_profiles"] for r in selected) for p in profiles},
        "operationally_active": 0, "recommended": 0, "operational_ranking": [], "states": states}
