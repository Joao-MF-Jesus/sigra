"""Additive v6 source verification; blocked evidence never becomes admission."""
from datetime import datetime
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re

from data_platform.catalog.intake import load_selection
from data_platform.catalog.profile_contracts_v3 import Citation, ProfileVehicle, UNITS, blank_fields, observed
from data_platform.catalog.profile_evidence_v3 import canonical_month
from data_platform.catalog.profile_pilot_v4 import fingerprint
from data_platform.catalog.profile_scoring_v3 import configuration as profile_configuration
from data_platform.contracts.carpedia_vehicle_specs import CarpediaRequest, DownloadedCarpediaAsset
from data_platform.contracts.pbev import AUDITED_ASSET_BY_YEAR
from data_platform.ingestion.carpedia.parser import CarpediaJsonParser
from data_platform.transformation.carpedia import normalize_attribute
from data_platform.transformation.fipe import parse_brl_price

from copy import deepcopy
from data_platform.catalog import academic_cohort_v5 as v5
from data_platform.catalog.profile_contracts_v3 import unavailable
from pydantic import Field, StrictInt
from data_platform.catalog import profile_pilot_v4 as v4

ROOT = Path(__file__).parent
VERSION = "academic-cohort-v6"
HOLDOUTS = v5.HOLDOUTS
SCENARIOS = v5.SCENARIOS
TECHNICAL = v5.TECHNICAL
GEARS = {**v5.GEARS, "M5": "manual", "A-8": "automatic"}
FIPE_KEYS = v5.FIPE_KEYS
PBEV_KEYS = v5.PBEV_KEYS
_citation = v5._citation
_items = v5._items


class V6ProfileVehicle(ProfileVehicle):
    """V6-only extension of the identifier domain; all evidence validators inherited."""
    id: StrictInt = Field(ge=1)


def price_reference_month(value):
    """Price-only authorization. Never relabel an October observation as September."""
    if value not in ("2026-09", "2026-10"):
        raise ValueError("V6 price reference month missing or outside authorized window")
    return value


def select_price_snapshot(snapshots, identity):
    """Prefer exact September evidence; October is a separately labelled fallback."""
    candidates = []
    for snapshot in snapshots:
        if any(snapshot.get(key) != identity.get(key) for key in
               ("CodigoFipe", "AnoModelo", "Modelo", "Marca", "Combustivel")):
            raise ValueError("Inexact FIPE snapshot identity")
        month = price_reference_month(canonical_month(snapshot.get("MesReferencia", "")))
        candidates.append((month != "2026-09", snapshot))
    if not candidates:
        raise ValueError("No exact FIPE snapshot")
    return min(candidates, key=lambda row: row[0])[1]


from decimal import ROUND_HALF_UP
from data_platform.catalog.profile_pilot_v4 import (
    baseline_vehicle, habitability_evidence, _inherited_evidence, _positive,
    configuration as v4_configuration, v3_configuration, safety_evidence, utility,
)

def _evaluate_extended_v4(vehicle, profile, scenario, target_month, *, records=(), document_directory=None,
                     scenario_config=None, proxy_reference=None, proxy_weight_multiplier="1",
                     divide_by_places=True):
    # Revalidate even model_copy-constructed input; invalid units never enter scoring.
    vehicle = V6ProfileVehicle.model_validate(vehicle.model_dump())
    method = v3_configuration()
    config = v4_configuration()
    baseline = baseline_vehicle(vehicle, profile, scenario, target_month, config=scenario_config)
    values = dict(baseline["academic_criteria_values"])
    definition = method["profiles"][profile]
    weights = {key: Decimal(value) for key, value in definition["weights"].items()}
    evidence = {key: _inherited_evidence(vehicle, key, value, baseline, method) for key, value in values.items()}
    path = "inherited_academic_v1"
    comparison_group = path
    if profile == "app":
        item = habitability_evidence(vehicle, divide_by_places=divide_by_places)
        evidence["passenger_space"] = item
        values["passenger_space"] = item["value"]
        path = comparison_group = item["path"]
        if path == "academic_habitability_proxy":
            weights["passenger_space"] *= _positive(proxy_weight_multiplier)
    if profile in {"familia", "estrada"}:
        item = safety_evidence(vehicle, records, document_directory)
        evidence["safety"] = item
        values["safety"] = item["value"]
        path = item["path"]
        comparison_group = item.get("comparison_group", "unavailable")
    present = [key for key in weights if values[key] is not None and weights[key] > 0]
    missing = [key for key in definition["required"] if values[key] is None]
    missing_any = [group for group in definition["required_any"] if not any(values[key] is not None for key in group)]
    denominator = sum((weights[key] for key in present), Decimal(0))
    effective = dict.fromkeys(weights, Decimal(0))
    quantum = Decimal(method["precision"]["score"])
    if denominator:
        for key in present[:-1]:
            effective[key] = (weights[key] / denominator).quantize(Decimal(method["precision"]["weight"]), rounding=ROUND_HALF_UP)
        effective[present[-1]] = Decimal(1) - sum(effective.values(), Decimal(0))
    utilities, contributions = dict.fromkeys(weights), dict.fromkeys(weights)
    for key in present:
        if key == "passenger_space" and path == "academic_habitability_proxy":
            default_reference = (config["academic_habitability_proxy"]["reference"] if divide_by_places
                                 else config["sensitivity"]["undivided_reference_m2"])
            reference = _positive(default_reference if proxy_reference is None else proxy_reference)
            raw = Decimal(100) * values[key] / (values[key] + reference)
            evidence[key]["utility_reference"] = reference
            evidence[key]["utility_reference_unit"] = evidence[key]["unit"]
            evidence[key]["utility_formula"] = config["academic_habitability_proxy"]["utility_formula"]
        elif key in {"safety", "transmission"}:
            raw = values[key]
        else:
            raw = utility(values[key], method["scales"][key])
        utilities[key] = raw.quantize(quantum, rounding=ROUND_HALF_UP)
        contributions[key] = (utilities[key] * effective[key]).quantize(quantum, rounding=ROUND_HALF_UP)
    scoreable = not missing and not missing_any
    ready = bool(baseline["identity_resolved"] and baseline["profile_eligible"] and scoreable and baseline["scenario_tco_complete"])
    blockers = [b for b in baseline["blockers"] if b != "PROFILE_REQUIRED_EVIDENCE_MISSING"]
    if missing or missing_any:
        blockers.append("V4_REQUIRED_EVIDENCE_UNAVAILABLE")
    for key in missing:
        if evidence[key].get("reason"):
            blockers.append(evidence[key]["reason"])
    score = sum((x for x in contributions.values() if x is not None), Decimal(0)) if present else None
    by_nature = {nature: [key for key, item in evidence.items() if item["nature"] == nature]
                 for nature in ("observed", "derived_academic", "scenario_estimate", "unavailable")}
    # Methodology/observed TCO come only from the unchanged baseline, never v4 readiness.
    return {
        "version": v4.VERSION, "id": vehicle.id, "vehicle": vehicle.label, "profile": profile, "scenario": scenario,
        "identity_resolved": baseline["identity_resolved"], "profile_eligible": baseline["profile_eligible"],
        "profile_scoreable": scoreable, "academic_test_ready": ready,
        "methodology_ready": baseline["methodology_ready"], "observed_tco_complete": baseline["observed_tco_complete"],
        "scenario_tco_complete": baseline["scenario_tco_complete"], "scenario_monthly_tco_brl": baseline["scenario_monthly_tco_brl"],
        "operationally_active": False, "recommended": False, "operational_ranking": [],
        "academic_path": path, "comparison_group": comparison_group + ":criteria=" + ",".join(sorted(present)),
        "preview_score": score, "criteria": evidence, "utilities": utilities, "contributions": contributions,
        "weights": weights, "effective_weights": effective,
        "coverage": {"weighted": denominator / sum(weights.values(), Decimal(0)),
                     "criteria_by_nature": by_nature,
                     "original_weight_by_nature": {nature: sum((weights[key] for key in keys), Decimal(0))
                                                    / sum(weights.values(), Decimal(0)) for nature, keys in by_nature.items()},
                     "required_missing": missing, "required_any_missing": missing_any,
                     "available": present, "missing": [key for key in weights if values[key] is None]},
        "confidence": {"value": None, "status": "descriptive_traceability_not_statistical_confidence",
                       "proxy_used": path == "academic_habitability_proxy"},
        "blockers": list(dict.fromkeys(blockers)), "scenario_costs": baseline["academic_costs"],
        "field_inventory": {key: field.model_dump(mode="json") for key, field in vehicle.fields.items()},
        "observed_field_names": [key for key, field in vehicle.fields.items() if field.kind == "observed"],
        "derived_criterion_names": by_nature["derived_academic"],
        "baseline_v3_academic_v1": baseline,
    }


def evaluate_vehicle(vehicle, profile, scenario, target_month="2026-09"):
    """Academic price window only; operational eligibility still uses September."""
    if target_month != "2026-09":
        raise ValueError("Frozen operational comparison month must remain September")
    month = price_reference_month(vehicle.fields["reference_month"].value)
    result = _evaluate_extended_v4(vehicle, profile, scenario, month)
    operational = baseline_vehicle(vehicle, profile, scenario, target_month)
    result["methodology_ready"] = operational["methodology_ready"]
    result["baseline_v3_academic_v1"] = operational
    result["price_reference_month"] = month
    result["operational_reference_month"] = target_month
    result["price_reference_policy_version"] = "academic-cohort-v6-price-window-v1"
    result["scenario_costs"]["price_reference_month"] = month
    result["scenario_costs"]["preferred_price_reference_month"] = "2026-09"
    for component in result["scenario_costs"]["components"].values():
        if "price_brl" in component.get("inputs", {}):
            component["inputs"]["price_brl"]["price_reference_month"] = month
    return result

def configuration(path=ROOT / "academic_cohort_v6.json"):
    config = json.loads(Path(path).read_text(encoding="utf-8"))
    base, ready, reviewed, selected = (config[k] for k in (
        "baseline_inventory_ids", "baseline_ready_ids", "reviewed_candidate_ids", "additional_selected_ids"))
    reserved = {v.id for v in load_selection().candidates}
    if (config["version"] != VERSION or config["target_size"] != 60 or config["maximum_additional"] != 10
            or config["target_month"] != "2026-09" or config["methodology"] != "academic-profile-pilot-v4"
            or len(base) != 67 or base != sorted(set(base)) or len(ready) != 50
            or ready != sorted(set(base) - set(HOLDOUTS)) or config["holdout_ids"] != list(HOLDOUTS)
            or reviewed != sorted(set(reviewed)) or set(reviewed) & set(base)
            or any(i not in reserved and i not in config["new_identity_ids"] for i in reviewed)
            or config["new_identity_ids"] != sorted(set(config["new_identity_ids"]))
            or any(type(i) is not int or i <= max(reserved) for i in config["new_identity_ids"])
            or set(config["new_targets"]) != {str(i) for i in config["new_identity_ids"]}
            or config["preferred_reference_month"] != "2026-09"
            or config["accepted_latest_reference_month"] != "2026-10"
            or selected != sorted(set(selected)) or not set(selected) <= set(reviewed) or len(selected) > 10
            or set(config["baseline_vehicle_fingerprints"]) != {str(i) for i in base}
            or any(not re.fullmatch(r"[0-9a-f]{64}", h) for h in config["baseline_vehicle_fingerprints"].values())
            or not re.fullmatch(r"[0-9a-f]{64}", config["baseline_cohort_fingerprint"])
            or config["transmission_codes"] != GEARS or config["operational_activation_authorized"] is not False
            or config["publication_authorized"] is not False):
        raise ValueError("Invalid v6 academic scope")
    return config


def load_evidence(path=ROOT / "academic_cohort_v6_evidence.json"):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if (data["version"] != "academic-cohort-v6-evidence-v1"
            or [r["id"] for r in data["records"]] != configuration()["reviewed_candidate_ids"]):
        raise ValueError("Reviewed evidence membership differs")
    return data


def _existing_conflicts(record, archive):
    path = ROOT / "profile_sources_v3.json"
    if hashlib.sha256(path.read_bytes()).hexdigest() != record["known_conflict_contract_sha256"]:
        raise ValueError("Frozen conflict contract changed")
    contract = json.loads(path.read_text(encoding="utf-8"))
    row = next((r for r in contract["vehicles"] if r["id"] == record["id"]), None)
    if row is None:
        return (), {}
    missing = {}
    for name, spec in row.get("unavailable", {}).items():
        refs = []
        for ref in spec.get("citations", []):
            source = contract["sources"][ref["document_id"]]
            archive.bytes(source)
            refs.append(_citation(source, ref["locator"], ref["page"]))
        missing[name] = unavailable(name, spec["reason"], tuple(refs))
    return tuple(row.get("source_conflicts", [])), missing


def _review_exact_record(record, archive):
    """Revalidate pinned sources and reviewed bindings, never mutate a legacy."""
    config = configuration()
    identifier = record["id"]
    if identifier not in config["reviewed_candidate_ids"]:
        raise ValueError("Unselected identity")
    candidate = next((v for v in load_selection().candidates if v.id == identifier), None)
    target = candidate.model_dump(mode="json") if candidate else config["new_targets"][str(identifier)]
    if target != record["catalog_target"]:
        raise ValueError("Reserved target changed")
    year = target["model_year"]
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
    select_price_snapshot([fipe], record["fipe_identity"])
    if ({k: fipe[k] for k in record["fipe_identity"]} != record["fipe_identity"] or fipe["TipoVeiculo"] != 1
            or fipe["AnoModelo"] != year or not re.fullmatch(r"\d{6}-\d", fipe["CodigoFipe"])):
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
    if identifier > 100 and (target["target_version"].casefold() != pbev["version_name"].casefold()
            or not re.search(r"(?<!\w)" + re.escape(target["target_version"]) + r"(?!\w)", fipe["Modelo"], re.I)):
        raise ValueError("Explicit target trim differs from canonical/PBEV trim")
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
    if items.get(("Motor a combustão", "Cilindrada (cm³)")) != engine["displacement_cm3"]:
        raise ValueError("Explicit displacement evidence changed")
    for fact in record["mechanical_evidence"]:
        if items.get((fact["section"], fact["label"])) != fact["value"]:
            raise ValueError("Mechanical observation changed")
    expected_gear = {"manual": "Manual", "automatic": "Automático", "cvt": "Automático (CVT)"}[transmission]
    if (items.get(("Geral", "Combustível")) != fipe["Combustivel"]
            or items.get(("Transmissão e tração", "Câmbio (tipo)")) != expected_gear
            or (gearbox != "CVT" and items.get(("Transmissão e tração", "Número de marchas")) != re.sub(r"\D", "", gearbox))):
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
                        "commercial_identity": fipe["Modelo"], "reference_month": canonical_month(fipe["MesReferencia"]), "price_brl": parse_brl_price(fipe["Valor"])}.items():
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
    return V6ProfileVehicle(id=identifier, label=fipe["Modelo"], identity_status="identity_approved", fields=fields,
        provenance={"academic_cohort_v6": {"record_fingerprint": fingerprint(record), "source_bytes_verified": True,
                    "no_publication": True, "safety_inventory": "unknown"}})

def review_record(record, archive):
    """Source integrity failures raise; known evidence blockers remain explicit."""
    vehicle = _review_exact_record(record, archive)
    conflicts, missing = _existing_conflicts(record, archive)
    if any(vehicle.fields[name].kind != "unavailable" for name in missing):
        raise ValueError("Known unavailable field cannot be silently replaced")
    blockers = list(conflicts)
    price_reference_month(vehicle.fields["reference_month"].value)
    data = vehicle.model_dump()
    data["fields"].update({k: v.model_dump() for k, v in missing.items()})
    data["source_conflicts"] = conflicts
    data["provenance"]["academic_cohort_v6"]["admission_blockers"] = blockers
    return V6ProfileVehicle.model_validate(data), tuple(blockers)


def build_cohort(inventory, archive, *, baseline_report, excluded_ids=()):
    """Preserve frozen v5; emit source-verified payloads only for academic use."""
    config = configuration()
    inventory = tuple(ProfileVehicle.model_validate(v.model_dump()) for v in inventory)
    by_id = {v.id: v for v in inventory}
    if (len(by_id) != len(inventory) or sorted(by_id) != config["baseline_inventory_ids"]
            or any(fingerprint(v) != config["baseline_vehicle_fingerprints"][str(v.id)] for v in inventory)
            or fingerprint(baseline_report) != config["baseline_cohort_fingerprint"]
            or baseline_report["selected_ids"] != config["baseline_ready_ids"]):
        raise ValueError("Frozen v5 inventory/results changed")
    profiles = tuple(profile_configuration()["profiles"])
    states = deepcopy(baseline_report["states"])
    selected_extra = set(config["additional_selected_ids"])
    frozen_codes = {by_id[i].fields["fipe_code"].value: i for i in config["baseline_ready_ids"]}
    for record in load_evidence()["records"]:
        vehicle, blockers = review_record(record, archive)
        by_id[vehicle.id] = vehicle
        evaluations = {s: {p: evaluate_vehicle(vehicle, p, s, config["target_month"]) for p in profiles} for s in SCENARIOS}
        passing = [] if blockers else [p for p in profiles if all(evaluations[s][p]["academic_test_ready"] for s in SCENARIOS)]
        profile_evidence_ready = bool(passing)
        cohort_blockers = list(blockers)
        duplicate_of = frozen_codes.get(vehicle.fields["fipe_code"].value)
        if duplicate_of is not None:
            cohort_blockers.append("DUPLICATE_FROZEN_FIPE_CODE_DIFFERENT_YEAR_NOT_NEW_ADMISSION")
        ready = profile_evidence_ready and not cohort_blockers
        if vehicle.id in selected_extra and not ready:
            raise ValueError("Blocked candidate cannot be selected")
        states.append({"id": vehicle.id, "identity": vehicle.label, "inventory_registered": True, "legacy_holdout": False,
            "academic_cohort_selected": vehicle.id in selected_extra and ready, "academic_test_ready": ready,
            "profile_evidence_ready": profile_evidence_ready, "duplicate_of_frozen_id": duplicate_of,
            "operationally_active": False, "recommended": False, "ready_profiles": passing, "evaluations": evaluations,
            "rejection_reasons": cohort_blockers, "exclusion_reason": "documented_admission_blocker" if cohort_blockers else None})
    excluded = set(excluded_ids)
    if not excluded <= set(by_id):
        raise ValueError("Unknown logical exclusion")
    keys = set()
    codes = set()
    for row in states:
        if row["id"] in excluded:
            row.update(academic_cohort_selected=False, exclusion_reason="logical_exclusion")
        if row["academic_cohort_selected"]:
            v = by_id[row["id"]]
            key = (v.fields["fipe_code"].value, v.fields["year_code"].value[:4])
            if key in keys or key[0] in codes or row["legacy_holdout"]:
                raise ValueError("Duplicate or holdout selected identity")
            keys.add(key)
            codes.add(key[0])
    states.sort(key=lambda r: r["id"])
    selected = [r for r in states if r["academic_cohort_selected"]]
    if len(selected) > 60:
        raise ValueError("Academic cohort exceeds target")
    payload = [{"vehicle": by_id[r["id"]].model_dump(mode="json"), "evaluations": deepcopy(r["evaluations"]),
                "mode": "academic_only", "operationally_active": False, "recommended": False} for r in selected]
    return {"version": VERSION, "decision": "ACADEMIC_COHORT_V6_COMPLETE" if len(selected) == 60 else "ACADEMIC_COHORT_V6_STILL_PARTIAL",
        "inventory_count": len(states), "cohort_size": len(selected), "academic_test_ready_count": sum(r["academic_test_ready"] for r in states),
        "target": 60, "unfilled_slots": 60 - len(selected), "selected_ids": [r["id"] for r in selected],
        "holdout_ids": list(HOLDOUTS), "profile_counts": {p: sum(p in r["ready_profiles"] for r in selected) for p in profiles},
        "operationally_active": 0, "recommended": 0, "operational_ranking": [], "states": states, "academic_payload": payload}
