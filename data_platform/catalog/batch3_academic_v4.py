"""Opt-in Batch 3 replay; no HTTP, publication, production or v3 mutation."""
import hashlib
import json
from decimal import Decimal
from pathlib import Path

from data_platform.catalog.adapter import prepare_batch
from data_platform.catalog.crosswalk import review_batch
from data_platform.catalog.intake import load_selection
from data_platform.catalog.profile_contracts_v3 import Citation, ProfileVehicle, UNITS, observed
from data_platform.catalog.profile_pilot_v4 import evaluate_vehicle

VERSION = "batch3-academic-v4-evidence-v1"
ROOT = Path(__file__).parent
MANIFEST_PATH = ROOT / "batch3_evidence_v1.json"
COLLECTION_PATH = ROOT / "batch3_collection_v1.json"
TECHNICAL = frozenset({"seats", "cargo_l", "length_mm", "width_mm", "wheelbase_mm",
                       "ground_clearance_mm", "weight_kg", "power_gasoline_cv", "airbags", "abs", "esc"})
REQUIRED = frozenset({"seats", "wheelbase_mm", "width_mm"})


def load_manifest(path=MANIFEST_PATH, collection_path=COLLECTION_PATH):
    manifest = json.loads(Path(path).read_text(encoding="utf-8"))
    plan = json.loads(Path(collection_path).read_text(encoding="utf-8"))
    if (manifest["version"] != VERSION or manifest["methodology"] != "academic-profile-pilot-v4"
            or plan["version"] != "batch3-safety-first-collection-v1"
            or plan["mode"] != "offline_academic_preview_only"):
        raise ValueError("Batch 3 version/mode mismatch")
    for key in ("database_write_authorized", "publication_authorized", "operational_activation_authorized"):
        if plan[key] is not False:
            raise ValueError("Operational authorization prohibited")
    selection = load_selection()
    reserved = {v.id for v in selection.candidates}
    previous = set(plan["existing_new_ids"])
    current = set()
    for name in ("carpedia_profile_evidence_v1.json", "carpedia_profile_evidence_batch2_v1.json"):
        current.update(json.loads((ROOT/name).read_text(encoding="utf-8"))["scope"]["candidate_ids"])
    ids = [r["id"] for r in manifest["records"]]
    if (plan["legacy_ids"] != list(range(1, 35)) or previous != current or len(previous) != 19
            or plan["existing_new_ids"] != sorted(previous)
            or plan["available_reserved_ids"] != sorted(reserved - previous)
            or ids != sorted(set(ids)) or ids != plan["admitted_ids"] or not set(ids) <= reserved - previous
            or plan["maximum_total_identities"] != 60 or 34 + len(previous) + len(ids) > 60
            or plan["unfilled_new_slots"] != 7 - len(ids)):
        raise ValueError("Reserved scope/count/duplicate mismatch")
    targets = {v.id: v.model_dump(mode="json") for v in selection.candidates}
    for row in manifest["records"]:
        if row["catalog"] != {k: targets[row["id"]][k] for k in row["catalog"]}:
            raise ValueError("Reserved catalog identity mismatch")
        if set(row["fields"]) - TECHNICAL or not REQUIRED <= set(row["fields"]):
            raise ValueError("Required technical scope mismatch")
        source = row["source"]
        if (source["provider"] != "manufacturer" or Path(source["cache_file"]).name != source["cache_file"]
                or not source["cache_file"].endswith(".pdf")):
            raise ValueError("Official document basename required")
    return manifest


def admit_vehicle(vehicle, row, archive):
    """Only a reviewed base identity; evidence cannot replace FIPE/PBEV fields."""
    decisions = [r for r in review_batch()["decisions"] if r["id"] == row["id"]]
    if len(decisions) != 1 or decisions[0]["status"] != "identity_approved":
        raise ValueError("Exactly one approved crosswalk required")
    decision = decisions[0]
    review = decision["review"]
    binding = row["crosswalk"]
    if (binding["file"] != "batch1_crosswalk_v1.json" or binding["review_id"] != row["id"]
            or binding["alias_id"] != review["alias_id"] or binding["link_type"] != review["link_type"]
            or binding["pbev_row_hash"] != review["pbev"]["raw"]["row_hash"]
            or binding["fipe_response_sha256"] != review["source_references"][0]["sha256"]):
        raise ValueError("Pinned FIPE/PBEV crosswalk mismatch")
    prepare_batch(decisions, archive)
    if vehicle.id != row["id"] or vehicle.identity_status != "identity_approved":
        raise ValueError("Vehicle identity mismatch")
    for key, value in row["identity"].items():
        if vehicle.fields[key].kind != "observed" or vehicle.fields[key].value != value:
            raise ValueError("Exact identity mismatch: " + key)
    if row["identity"]["reference_month"] != "2026-09":
        raise ValueError("September 2026 required")
    for field, key in (("price_brl", "price_brl"), ("consumption_city", "city_km_l"),
                       ("consumption_highway", "highway_km_l")):
        if vehicle.fields[field].value != Decimal(str(decision["observed"][key])):
            raise ValueError("Official price/consumption mismatch")
    expected_official = {"fipe_code": review["fipe"]["CodigoFipe"], "year_code": review["year_code"],
                        "commercial_identity": review["commercial_description"], "fuel": review["powertrain"][4],
                        "transmission": review["powertrain"][3]}
    if any(row["identity"][k] != v for k, v in expected_official.items()):
        raise ValueError("FIPE/PBEV identity cannot be overridden")
    source, scope = row["source"], row["review"]
    if (scope["status"] != "exact_variant_reviewed" or scope["market"] != "BR"
            or scope["source_kind"] != "manufacturer_version_table" or scope["unresolved_restrictions"]
            or scope["model_year"] != row["catalog"]["model_year"] or scope["variant"] != "2.0 SV"
            or scope["engine"] != "2.0 16V" or scope["fuel"] != row["identity"]["fuel"]
            or scope["transmission"] != row["identity"]["transmission"] or not scope["rationale"]):
        raise ValueError("Document exact version/year/engine/fuel/transmission mismatch")
    raw = archive.bytes(source)
    if hashlib.sha256(raw).hexdigest() != source["sha256"] or not raw.startswith(b"%PDF"):
        raise ValueError("Document hash/type mismatch")
    fields = dict(vehicle.fields)
    for name, fact in row["fields"].items():
        if name not in TECHNICAL or fact["unit"] != UNITS[name] or fact["condition"] != "standard":
            raise ValueError("Only explicit standard equipment/valid technical units admitted")
        ref = Citation(provider=source["provider"], url=source["url"], sha256=source["sha256"],
                       document=source["document"], collected_at=source["collected_at"],
                       page=fact["page"], locator=fact["locator"])
        new = observed(name, fact["value"], (ref,), limitations=tuple(row["limitations"]))
        if fields[name].kind != "unavailable" and fields[name] != new:
            raise ValueError("Existing evidence cannot be overwritten")
        fields[name] = new
    if any(fields[k].kind != "observed" or fields[k].value <= 0 for k in REQUIRED):
        raise ValueError("Positive technical inputs required")
    result = ProfileVehicle.model_validate({**vehicle.model_dump(), "fields": fields,
        "provenance": {**vehicle.provenance, "batch3_v4": {"version": VERSION, "review": row,
                       "source_bytes_verified": True, "no_publication": True}}})
    for scenario in ("low", "base", "high"):
        evaluation = evaluate_vehicle(result, "app", scenario, "2026-09")
        if not evaluation["academic_test_ready"] or not evaluation["scenario_tco_complete"]:
            raise ValueError("Academic admission requires complete scenario and a testable profile")
        if evaluation["operationally_active"] or evaluation["recommended"]:
            raise ValueError("Operational activation prohibited")
    return result


def batch3_matrix(vehicles, archive, *, manifest_path=MANIFEST_PATH):
    """Return only newly admitted IDs. Caller explicitly opts into combined preview."""
    vehicles = tuple(vehicles)
    manifest = load_manifest(manifest_path)
    by_id = {}
    for vehicle in vehicles:
        if vehicle.id in by_id:
            raise ValueError("Duplicate input vehicle ID")
        by_id[vehicle.id] = vehicle
    output = []
    for row in manifest["records"]:
        if row["id"] not in by_id:
            raise ValueError("Missing reviewed candidate")
        result = admit_vehicle(by_id[row["id"]], row, archive)
        key = tuple(result.fields[k].value for k in ("fipe_code", "year_code"))
        if any(v.id != result.id and tuple(v.fields[k].value for k in ("fipe_code", "year_code")) == key
               for v in vehicles):
            raise ValueError("Duplicate canonical identity")
        output.append(result)
    return tuple(output)
