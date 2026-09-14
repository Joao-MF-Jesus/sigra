"""Hash-verified, read-only FIPE/PBEV and explicitly reviewed OEM evidence."""
from datetime import date
import hashlib
import json
from pathlib import Path

from data_platform.catalog.crosswalk import review_batch, review_batch2, fingerprint
from data_platform.catalog.evidence_v2 import candidate_evidence, legacy_evidence
from data_platform.catalog.profile_contracts_v3 import (
    VERSION, Citation, ProfileVehicle, blank_fields, observed, unavailable,
)

TECHNICAL_PATH = Path(__file__).with_name("profile_sources_v3.json")
MONTHS = dict(zip(
    ("janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"),
    range(1, 13),
))


def canonical_month(value):
    if not isinstance(value, str):
        raise ValueError("Missing reference month")
    if " de " in value:
        month, year = value.casefold().split(" de ")
        result = date(int(year), MONTHS[month], 1)
    else:
        result = date.fromisoformat(value if len(value) == 10 else value + "-01")
    return result.strftime("%Y-%m")


def _citation(source, provider, document, locator, page=None):
    return Citation(provider=provider, url=source["url"], sha256=source["sha256"],
                    document=document, locator=locator, page=page, collected_at=source["collected_at"])


def candidate_matrix(archive, technical_directory, *, carpedia_cache_directory=None, include_batch2=False):
    """Only revalidated identities; blocked IDs never enter the pilot.

    CarPedia enrichment is opt-in and accepts only hash-bound cached fichas
    registered in the versioned evidence manifest.
    """
    approved = [row for row in review_batch()["decisions"] if row["status"] == "identity_approved"]
    if include_batch2:
        approved.extend(row for row in review_batch2()["decisions"] if row["status"] == "identity_approved")
    inputs = {row.identifier: row for row in candidate_evidence(archive, approved)}
    decisions = {row["id"]: row for row in approved}
    result = []
    for identifier, row in decisions.items():
        review = row["review"]
        fields = blank_fields()
        fipe = _citation(review["source_references"][0], "fipe", "FIPE complete cached response",
                         f"code={review['fipe']['CodigoFipe']} year={review['year_code']}")
        raw = review["pbev"]["raw"]
        pbev = _citation(review["source_references"][1], "pbev", f"PBEV {raw['cycle_year']} official table",
                         f"row={raw['row_number']}; row_hash={raw['row_hash']}", raw["page_number"])
        identity = {
            "fipe_code": review["fipe"]["CodigoFipe"], "year_code": review["year_code"],
            "commercial_identity": review["fipe"]["Modelo"],
            "reference_month": canonical_month(row["observed"]["reference_month"]),
            "price_brl": inputs[identifier].fields["price_brl"].value,
        }
        for name, value in identity.items():
            fields[name] = observed(name, value, (fipe,))
        for name in ("consumption_city", "consumption_highway"):
            fields[name] = observed(name, inputs[identifier].fields[name].value, (pbev,), "shared_powertrain",
                                   ("PBEV gasoline laboratory cycle; not an individual real-world measurement",))
        fields["fuel"] = observed("fuel", review["pbev"]["fuel_type"], (pbev,), "shared_powertrain")
        fields["transmission"] = observed("transmission", review["powertrain"][3], (pbev,), "shared_powertrain")
        # QQ's textual Flex contradiction is retained as an unresolved source
        # issue for methodology; identity_approved is not silently revoked.
        conflicts = ("QQ_FIPE_TEXT_FLEX_VS_STRUCTURED_GASOLINE",) if identifier == 41 else ()
        result.append(ProfileVehicle(
            id=identifier, label=review["commercial_description"], identity_status="identity_approved",
            fields=fields, source_conflicts=conflicts,
            provenance={"identity_review_fingerprint": fingerprint(review), "link_type": review["link_type"],
                        "raw_snapshots_hash_verified": True, "no_source_publication": True},
            human_approval_required=row["human_approval_required"], human_approval_status=row["human_approval_status"],
        ))
    result = augment_technical(tuple(result), technical_directory)
    if carpedia_cache_directory is not None:
        from data_platform.catalog.carpedia_profile_evidence import (
            BATCH2_MANIFEST_PATH,
            augment_carpedia_profile_evidence,
        )
        result = augment_carpedia_profile_evidence(result, carpedia_cache_directory)
        if include_batch2:
            result = augment_carpedia_profile_evidence(
                result, carpedia_cache_directory, manifest_path=BATCH2_MANIFEST_PATH,
            )
    return result


def legacy_matrix(cache_path, expected_sha256):
    """Preserve v2 strict replay. No sample score/consumption/price fallback."""
    result = []
    for old in legacy_evidence(cache_path, expected_sha256):
        fields = blank_fields()
        price = old.fields["price_brl"]
        if price.kind == "observed":
            refs = tuple(Citation(provider="fipe", url=ref.source_url, sha256=ref.sha256,
                                 document="Legacy FIPE cache replay", locator=ref.locator,
                                 collected_at=ref.collected_at) for ref in price.references)
            entries = {
                "price_brl": price.value, "fipe_code": old.provenance["fipe_code"],
                "year_code": old.provenance["year_code"],
                "reference_month": canonical_month(old.provenance["price_reference_month"]),
                "commercial_identity": old.provenance["found_price_reference"]["model"],
            }
            for name, value in entries.items():
                fields[name] = observed(name, value, refs, "legacy_reference",
                                        ("Existing price reference binding has not been reaudited as catalog trim identity",))
        else:
            for name in ("price_brl", "fipe_code", "year_code", "reference_month", "commercial_identity"):
                fields[name] = unavailable(name, "; ".join(old.provenance["price_rejection_reasons"]))
        result.append(ProfileVehicle(id=old.identifier, label=old.label,
                                     identity_status="legacy_binding_not_reaudited", fields=fields,
                                     provenance=old.provenance))
    return tuple(result)


def augment_technical(vehicles, directory):
    """Exact registered ID/code/year/description review, never fuzzy matching.

    Full bytes are hash checked before any numeric fact is admitted. Existing
    official FIPE/PBEV fields cannot be overwritten by this enrichment.
    """
    directory = Path(directory).resolve(strict=True)
    spec = json.loads(TECHNICAL_PATH.read_text(encoding="utf-8"))
    if spec["version"] != VERSION:
        raise ValueError("Technical review version mismatch")
    for source in spec["sources"].values():
        name = source["cache_file"]
        if Path(name).name != name:
            raise ValueError("Invalid cache filename")
        if hashlib.sha256((directory/name).read_bytes()).hexdigest() != source["sha256"]:
            raise ValueError("Manufacturer snapshot changed")
    if {row["id"] for row in spec["vehicles"]} != {35, 36, 37}:
        raise ValueError("Unexpected technical pilot scope")
    reviews = {row["id"]: row for row in spec["vehicles"]}

    def citation(fact):
        source = spec["sources"][fact["document_id"]]
        return _citation(source, "manufacturer", source["document"], fact["locator"], fact["page"])

    output = []
    for vehicle in vehicles:
        entry = reviews.get(vehicle.id)
        if entry is None:
            output.append(vehicle)
            continue
        for key, expected in (("fipe_code", entry["fipe_code"]), ("year_code", entry["year_code"]),
                              ("commercial_identity", entry["expected_fipe_description"])):
            if vehicle.fields[key].value != expected:
                raise ValueError("Technical review identity mismatch")
        fields = dict(vehicle.fields)
        for name, fact in entry["fields"].items():
            if fields[name].kind != "unavailable":
                raise ValueError("Technical enrichment cannot overwrite existing evidence")
            fields[name] = observed(name, fact["value"], (citation(fact),),
                                    fact["applicability"], tuple(fact["limitations"]))
        for name, rejected in entry["unavailable"].items():
            if fields[name].kind != "unavailable":
                raise ValueError("Technical review cannot discard an observation")
            fields[name] = unavailable(name, rejected["reason"], tuple(citation(ref) for ref in rejected.get("citations", [])))
        output.append(ProfileVehicle(
            **{**vehicle.model_dump(), "fields": fields,
               "source_conflicts": vehicle.source_conflicts + tuple(entry["source_conflicts"]),
               "provenance": {**vehicle.provenance, "technical_review_sha256": hashlib.sha256(TECHNICAL_PATH.read_bytes()).hexdigest(),
                              "binding_rationale": entry["binding_rationale"], "technical_limitations": entry["limitations"]}},
        ))
    return tuple(output)
