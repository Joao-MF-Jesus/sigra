"""Opt-in, offline legacy evidence adapter for the existing academic v4.

No discovery, fuzzy matching, publication or replacement of any v3 input.
Each admission is an individually reviewed, immutable source binding.
"""
import hashlib
import json
import re
from decimal import Decimal
from pathlib import Path

from data_platform.catalog.crosswalk import mechanical_key
from data_platform.catalog.experimental_planning import price_crosswalk, replay_price_aliases
from data_platform.catalog.intake import load_selection
from data_platform.catalog.profile_contracts_v3 import Citation, ProfileVehicle, observed
from data_platform.catalog.profile_evidence_v3 import canonical_month, legacy_matrix
from data_platform.catalog.profile_pilot_v4 import evaluate_vehicle
from data_platform.catalog.profile_scoring_v3 import configuration
from data_platform.contracts.pbev import AUDITED_ASSET_BY_YEAR
from data_platform.transformation.fipe import parse_brl_price

VERSION = "legacy-academic-v4-evidence-v1"
MANIFEST_PATH = Path(__file__).with_name("legacy_academic_v4_evidence_v1.json")
BRANDS = {"Chevrolet": "CHEVROLET", "Hyundai": "HYUNDAI", "Toyota": "TOYOTA",
          "Honda": "HONDA", "Volkswagen": "VW", "Fiat": "FIAT", "Renault": "RENAULT",
          "Nissan": "NISSAN", "Jeep": "JEEP", "Ford": "FORD"}
FIPE_BRANDS = {"Chevrolet": "GM - Chevrolet", "Volkswagen": "VW - VolksWagen"}


def load_manifest(path=MANIFEST_PATH):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    canonical = {v.id: v.model_dump(mode="json") for v in load_selection().baseline}
    if data.get("version") != VERSION or data.get("methodology") != "academic-profile-pilot-v4":
        raise ValueError("Legacy academic evidence version mismatch")
    ids = [r["id"] for r in data["reviews"]]
    if ids != list(canonical) or data.get("legacy_ids") != ids:
        raise ValueError("Canonical legacy scope missing, reordered or duplicated")
    for row in data["reviews"]:
        if row["catalog"] != canonical[row["id"]]:
            raise ValueError("Canonical legacy identity changed")
        if row["status"] not in {"identity_approved", "blocked"}:
            raise ValueError("Unknown legacy review status")
        if row["status"] == "identity_approved" and (not row.get("pbev") or not row.get("fipe") or row.get("blocker")):
            raise ValueError("Individual exact review required")
        if row["status"] == "blocked" and (not row.get("blocker") or row.get("pbev")):
            raise ValueError("Blocked review must preserve explicit reason and no admitted PBEV")
    # Validate public citations, timezone, hash shape and provider even before reading bytes.
    for source in data["sources"].values():
        citation(source, "source manifest")
        if Path(source["cache_file"]).name != source["cache_file"]:
            raise ValueError("Source filename must not contain a path")
    return data


def citation(source, locator, page=None):
    return Citation(provider=source["provider"], url=source["url"], sha256=source["sha256"],
                    document=source["document"], locator=locator, page=page,
                    collected_at=source["collected_at"])


def _price(review, payload):
    """Validate source identity independently of the admission status."""
    from app.fipe import FIPE_REFERENCE_PROFILES
    target = review["fipe"]
    expected = target["expected_identity"]
    cat = review["catalog"]
    registry = FIPE_REFERENCE_PROFILES[review["id"]]
    if target["legacy_price_cache"]:
        rows = [r for r in payload if r.get("vehicle_id") == review["id"]]
        if len(rows) != 1:
            raise ValueError("Legacy price cache is missing or duplicated")
        raw = rows[0]
        if raw["retrieval_status"] != "live" or raw["year_code"] != target["year_code"]:
            raise ValueError("Legacy price source status/year mismatch")
        found = {"brand": cat["brand"], "model": raw["model"], "modelYear": int(raw["year_code"].split("-")[0]),
                 "fuel": expected["fuel"], "codeFipe": raw["code"]}
        price, month = Decimal(str(raw["price"])), canonical_month(raw["reference_month"])
    else:
        found = {k: payload[k] for k in expected}
        price, month = parse_brl_price(payload["price"]), canonical_month(payload["referenceMonth"])
        if payload.get("vehicleType") != 1:
            raise ValueError("FIPE response is not an automobile")
    aliases = [r["cached_description"] for r in price_crosswalk()["entries"] if r["id"] == review["id"]]
    if found != expected or found["model"] not in [registry.model, *aliases]:
        raise ValueError("FIPE exact description/version mismatch")
    if found["codeFipe"] != registry.code or str(found["modelYear"]) != registry.year_code or found["modelYear"] != cat["year"]:
        raise ValueError("FIPE code/model year mismatch")
    expected_brand = cat["brand"] if target["legacy_price_cache"] else FIPE_BRANDS.get(cat["brand"], cat["brand"])
    if found["brand"] != expected_brand or target["year_code"].split("-")[0] != str(cat["year"]):
        raise ValueError("FIPE brand/year-code mismatch")
    if month != target["reference_month"] or not price.is_finite() or price <= 0:
        raise ValueError("FIPE price/reference month mismatch")
    return price, month, found


def _pbev(review, parsed, source):
    binding = review["pbev"]
    cat = review["catalog"]
    asset = AUDITED_ASSET_BY_YEAR[cat["year"]]
    if source["sha256"] != asset.sha256 or parsed.get("cycle") != cat["year"] or parsed.get("status") != "parsed":
        raise ValueError("PBEV cycle/document mismatch")
    matches = [r for r in parsed["rows"] if r["raw"]["row_hash"] == binding["row_hash"]]
    if len(matches) != 1:
        raise ValueError("PBEV row missing or ambiguous")
    row = matches[0]
    raw = row["raw"]
    if (raw["cycle_year"], raw["page_number"], raw["row_number"]) != (cat["year"], binding["page"], binding["row_number"]):
        raise ValueError("PBEV year/locator mismatch")
    if {k: row[k] for k in binding["identity"]} != binding["identity"]:
        raise ValueError("PBEV exact version/fuel identity mismatch")
    if row["brand_name"].upper() != BRANDS[cat["brand"]]:
        raise ValueError("PBEV brand mismatch")
    key = mechanical_key(row)
    if list(key) != binding["powertrain"] or not binding.get("rationale") or binding.get("unit") != "km/l":
        raise ValueError("Reviewed mechanical configuration or unit mismatch")
    fipe = review["fipe"]["expected_identity"]
    fuel = {"Flex": "flex", "Gasolina": "gasoline"}.get(fipe["fuel"])
    if fuel != key[4] or {"1": "gasoline", "5": "flex"}.get(review["fipe"]["year_code"].split("-")[-1]) != fuel:
        raise ValueError("Fuel/year-code mismatch")
    motor = re.search(r"\b\d\.\d\b", fipe["model"])
    valves = re.search(r"(\d+)\s*V\b", fipe["model"], re.I)
    if not motor or motor.group() != key[0] or (valves and int(valves.group(1)) != key[1]):
        raise ValueError("FIPE/PBEV engine mismatch")
    if ("Aut." in fipe["model"] and key[3] == "manual") or ("Mec." in fipe["model"] and key[3] != "manual"):
        raise ValueError("FIPE/PBEV transmission mismatch")
    if re.search(r"\bTurbo\b", fipe["model"], re.I) and not key[2]:
        raise ValueError("FIPE/PBEV turbo mismatch")
    if row.get("propulsion_type") not in (None, "combustion"):
        raise ValueError("Unsupported propulsion")
    if {k: row[k] for k in binding["consumption"]} != binding["consumption"]:
        raise ValueError("PBEV consumption differs from reviewed row")
    values = [Decimal(row[k]) for k in ("fossil_city_km_l", "fossil_highway_km_l")]
    if any(not x.is_finite() or x <= 0 for x in values):
        raise ValueError("Positive PBEV consumption required")
    return row, key, values


def legacy_matrix_v4(archive, *, manifest_path=MANIFEST_PATH):
    """Return all 34; approve only exact registered reviews after hash checks.

    SourceArchive receives local roots explicitly. No credentials or DB engine.
    Integrity failures raise before any output is returned; blocked evidence stays null.
    """
    spec = load_manifest(manifest_path)
    content = {name: archive.bytes(source) for name, source in spec["sources"].items()}
    decoded = {name: json.loads(raw, parse_float=Decimal) for name, raw in content.items()
               if spec["sources"][name]["cache_file"].endswith(".json")}
    crosswalk = price_crosswalk()
    july = archive.bytes({"cache_file": "fipe_cache.json", "sha256": crosswalk["source_sha256"]})
    # Reuse immutable v3 baseline; locate the verified file without changing it.
    path = next(p / "fipe_cache.json" for p in archive.directories
                if (p / "fipe_cache.json").is_file() and (p / "fipe_cache.json").read_bytes() == july)
    originals, _ = replay_price_aliases(legacy_matrix(path, crosswalk["source_sha256"]), path)
    originals = {v.id: v for v in originals}
    output = []
    for review in spec["reviews"]:
        v = originals[review["id"]]
        fields = dict(v.fields)
        approved = review["status"] == "identity_approved"
        source = review.get("fipe")
        if source:
            price, month, identity = _price(review, decoded[source["source"]])
            ref = citation(spec["sources"][source["source"]], f"FIPE={identity['codeFipe']}; year={source['year_code']}; legacy_id={v.id}")
            for name, value in {"price_brl": price, "reference_month": month, "fipe_code": identity["codeFipe"],
                                "year_code": source["year_code"], "commercial_identity": identity["model"]}.items():
                fields[name] = observed(name, value, (ref,), "exact_variant" if approved else "legacy_reference",
                                        () if approved else ("Price reference does not approve catalog trim",))
        if approved:
            binding = review["pbev"]
            row, key, values = _pbev(review, decoded[binding["parsed_source"]], spec["sources"][binding["source"]])
            ref = citation(spec["sources"][binding["source"]], f"row={binding['row_number']}; row_hash={binding['row_hash']}", binding["page"])
            for name, value in {"consumption_city": values[0], "consumption_highway": values[1], "fuel": key[4], "transmission": key[3]}.items():
                fields[name] = observed(name, value, (ref,), "shared_powertrain",
                                        ("Exact listed trim membership; laboratory gasoline cycle, not observed individual road use",))
        provenance = {**v.provenance, "legacy_v4_manifest_sha256": hashlib.sha256(Path(manifest_path).read_bytes()).hexdigest(),
                      "legacy_v4_review": review, "source_bytes_verified": True, "no_publication": True,
                      "historical_v3_review_flags_retained_not_overwritten": True}
        output.append(ProfileVehicle(**{**v.model_dump(), "fields": fields,
                                        "identity_status": "identity_approved" if approved else v.identity_status,
                                        "source_conflicts": () if approved else (review["blocker"],), "provenance": provenance}))
    return tuple(output)


def replay_legacy_v4(vehicles, target_month="2026-09"):
    """Per-vehicle replay preserves mixed months; never relabel July as September."""
    expected = [v.id for v in load_selection().baseline]
    if [v.id for v in vehicles] != expected:
        raise ValueError("Replay requires the exact canonical 34 IDs once")
    return {s: {p: [evaluate_vehicle(v, p, s, target_month) for v in vehicles]
                for p in configuration()["profiles"]} for s in ("low", "base", "high")}
