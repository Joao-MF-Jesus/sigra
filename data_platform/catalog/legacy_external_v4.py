"""Opt-in offline admission of recovered legacy evidence; never operational."""
import copy
import hashlib
import json
from dataclasses import asdict
from pathlib import Path

from data_platform.catalog.legacy_academic_v4 import (
    load_manifest as prior_manifest, _price, _pbev, citation,
)
from data_platform.catalog.legacy_remaining_v4 import DISPOSITIONS
from data_platform.catalog.legacy_technical_v4 import (
    parse_record, identity_blockers, PROFILE, source_citation,
)
from data_platform.catalog.profile_contracts_v3 import ProfileVehicle, observed
from data_platform.contracts.pbev import AUDITED_ASSET_BY_YEAR
from data_platform.ingestion.pbev.parser import PbevPdfParser

VERSION = "legacy-controlled-external-v4-v1"
MANIFEST_PATH = Path(__file__).with_name("legacy_external_v4_evidence_v1.json")
REQUIRED_TECHNICAL = {"seats", "width", "wheelbase", "fuel_type", "transmission"}


def load_manifest(path=MANIFEST_PATH):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    previous = {r["id"]: r for r in prior_manifest()["reviews"]}
    if (data["version"] != VERSION or data["methodology"] != "academic-profile-pilot-v4"
            or data["publication_authorized"] is not False
            or data["database_write_authorized"] is not False
            or data["scope_ids"] != list(DISPOSITIONS) or data["admitted_ids"] != [12]
            or [r["id"] for r in data["dispositions"]] != list(DISPOSITIONS)):
        raise ValueError("External admission scope/version mismatch")
    for row in data["dispositions"]:
        if (row["catalog"] != previous[row["id"]]["catalog"] or not row["reason"]
                or row["status"] != ("admitted" if row["id"] == 12 else "blocked")
                or (row["id"] == 12 and row["human_approval_required"] is not False)):
            raise ValueError("Unreviewed identity or disposition")
    entry = data["admission"]
    old = previous[12]
    if (entry["id"] != 12 or entry["catalog"] != old["catalog"]
            or entry["fipe"] != old["fipe"] or entry["canonical_identity_change"] is not False
            or entry["fipe_source"] != prior_manifest()["sources"][old["fipe"]["source"]]):
        raise ValueError("Canonical FIPE identity/source cannot be substituted")
    binding = entry["pbev"]
    # Individual documented review, not a generic trim-normalization rule.
    if (binding["identity"] != {"brand_name": "TOYOTA", "model_name": "COROLLA CROSS",
            "version_name": "XR 20", "motor_description": "2.0 - 16V",
            "transmission_code": "CVT", "fuel_type": "flex"}
            or binding["row_hash"] != "522ca6e315668a2fe13e6472e77fbe74f7ba4a5af42b858b0adaeb58091614ae"):
        raise ValueError("Only the individually reviewed XR 20 row is admitted")
    tech = entry["technical"]
    identity = old["fipe"]["expected_identity"]
    if (tech["id"] != 12 or tech["catalog"] != old["catalog"]
            or tech["commercial_identity"] != identity["model"]
            or tech["fipe_code"] != identity["codeFipe"] or tech["year_code"] != "2022-5"
            or tech["external_id"] != 22012
            or tech["fiche"]["url"] != "https://www.carpedia.com.br/api/v1/ficha/22012/2022"):
        raise ValueError("Technical exact identity mismatch")
    for source in (entry["fipe_source"], entry["pbev_source"], tech["discovery"], tech["fiche"]):
        source_citation(source, "immutable source")
        if Path(source["cache_file"]).name != source["cache_file"]:
            raise ValueError("Source reference must be a filename")
    return data


def verified_pbev(entry, archive):
    """Reparse the verified official PDF, not an unattached normalized JSON row."""
    source = entry["pbev_source"]
    raw = archive.bytes(source)
    asset = AUDITED_ASSET_BY_YEAR[entry["catalog"]["year"]]
    if hashlib.sha256(raw).hexdigest() != asset.sha256:
        raise ValueError("Official PBEV document hash mismatch")
    path = next(root / source["cache_file"] for root in archive.directories
                if (root / source["cache_file"]).is_file()
                and (root / source["cache_file"]).read_bytes() == raw)
    parsed = PbevPdfParser().parse(path, asset)
    return {"cycle": entry["catalog"]["year"], "status": "parsed",
            "rows": [json.loads(json.dumps(asdict(r), default=str)) for r in parsed.rows]}


def admit_vehicle(vehicle, entry, archive):
    if vehicle.id != 12:
        raise ValueError("Only reviewed ID 12 may use this admission")
    review = copy.deepcopy(next(r for r in prior_manifest()["reviews"] if r["id"] == 12))
    if entry["catalog"] != review["catalog"] or entry["fipe"] != review["fipe"]:
        raise ValueError("Catalog/FIPE substitution prohibited")
    review.update(status="identity_approved", blocker=None, pbev=entry["pbev"])
    price, month, identity = _price(review, json.loads(archive.bytes(entry["fipe_source"])))
    if month != "2026-09":
        raise ValueError("September 2026 FIPE required")
    _, key, consumption = _pbev(review, verified_pbev(entry, archive), entry["pbev_source"])
    _, (technical, missing) = parse_record(entry["technical"], archive)
    if not REQUIRED_TECHNICAL <= set(technical):
        raise ValueError("Required exact technical evidence missing")
    fields = dict(vehicle.fields)
    fref = citation(entry["fipe_source"], "002201-2 / 2022-5 / September 2026")
    for name, value in {"price_brl": price, "reference_month": month,
            "fipe_code": identity["codeFipe"], "year_code": "2022-5",
            "commercial_identity": identity["model"]}.items():
        fields[name] = observed(name, value, (fref,))
    bref = citation(entry["pbev_source"], "row=17; row_hash=" + entry["pbev"]["row_hash"], 2)
    for name, value in {"consumption_city": consumption[0], "consumption_highway": consumption[1],
            "fuel": key[4], "transmission": key[3]}.items():
        fields[name] = observed(name, value, (bref,), "shared_powertrain",
                                ("Laboratory gasoline cycle; not individual road use",))
    candidate = ProfileVehicle.model_validate({**vehicle.model_dump(), "fields": fields,
        "identity_status": "identity_approved", "source_conflicts": (),
        "provenance": {**vehicle.provenance, "legacy_v4_review": review}})
    blockers = identity_blockers(candidate, entry["technical"], technical)
    if blockers:
        raise ValueError("Exact technical identity rejected: " + ", ".join(blockers))
    evidence = {}
    for code, item in technical.items():
        evidence[code] = {"value": str(item.normalized_value), "unit": item.normalized_unit,
            "source_value": item.source_value, "source_label": item.source_label,
            "kind": "observed", "provenance": dict(item.provenance)}
        if code in PROFILE:
            name = PROFILE[code]
            ref = source_citation(entry["technical"]["fiche"], item.provenance["field_locator"])
            value = observed(name, item.normalized_value, (ref,))
            if fields[name].kind != "unavailable" and fields[name] != value:
                raise ValueError("Cannot overwrite an existing technical observation")
            fields[name] = value
    provenance = {**candidate.provenance, "legacy_external_v4": {
        "version": VERSION, "sources": {k: entry[k] for k in ("fipe_source", "pbev_source")},
        "technical": entry["technical"], "fields": evidence, "unavailable": missing,
        "width_semantics": "body only; not mirrors", "source_bytes_verified": True,
        "safety_inventory_admitted": False, "no_publication": True}}
    return ProfileVehicle.model_validate({**candidate.model_dump(), "fields": fields, "provenance": provenance})


def augment_legacy_external_v4(vehicles, archive, *, manifest_path=MANIFEST_PATH):
    """All-or-nothing replay; retain every other legacy unchanged."""
    if [v.id for v in vehicles] != list(range(1, 35)):
        raise ValueError("Exact canonical 34 IDs required")
    manifest = load_manifest(manifest_path)
    admitted = admit_vehicle(vehicles[11], manifest["admission"], archive)
    return tuple(admitted if v.id == 12 else v for v in vehicles)
