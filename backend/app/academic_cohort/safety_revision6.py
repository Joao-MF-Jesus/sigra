"""Read-only, explicit preparation boundary for the INACTIVE Revision6.

Not imported by routes, repository, materializer or the default snapshot loader.
The approved V6 contract remains unchanged and rejects this documentary candidate.
"""
from copy import deepcopy
from dataclasses import dataclass
from decimal import Decimal
import hashlib
import json
from pathlib import Path, PurePosixPath

from app.academic_cohort.contracts import json_document, method_manifest, validate_replay
from data_platform.catalog import academic_cohort_v6 as v6, profile_pilot_v4 as v4
from data_platform.catalog.profile_pilot_v4 import fingerprint, rankings

CONTRACT = Path(__file__).with_name("safety_revision6_contract.json")
APPROVED_PATH = "input_revision5/input_revision4/input_revision3/input_revision2/approved/canonical-replay-v6.json"


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON property")
        result[key] = value
    return result


def _read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"), object_pairs_hook=_unique_object)


def _sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _local(root, name):
    relative = PurePosixPath(name)
    if (relative.is_absolute() or ".." in relative.parts or "\\" in name or ":" in name
            or not relative.parts):
        raise ValueError("Unsafe bundle member")
    path = root / name
    if path.is_symlink() or not path.resolve(strict=True).is_relative_to(root) or not path.is_file():
        raise ValueError("Out-of-bundle or nonregular source")
    return path


@dataclass(frozen=True)
class InactiveRevision6Proposal:
    """Deliberately NOT a MaterializationPlan: no writer-compatible attributes."""
    candidate_version: str
    candidate_fingerprint: str
    approved_reference_fingerprint: str
    source_inventory_sha256: str
    coverage_decision: dict
    profile_counts: dict
    transport_vehicles: tuple[dict, ...]
    transport_evaluations: tuple[dict, ...]
    limitations: tuple[str, ...]

    def assert_write_allowed(self):
        raise ValueError("Inactive preparation proposal; database writes and activation forbidden")

    def diagnostic_preview(self, profile, scenario):
        policy = _read(CONTRACT)
        if profile not in policy["profiles"] or scenario not in policy["scenarios"]:
            raise ValueError("Unknown profile/scenario")
        results = [deepcopy(row["payload"]) for row in self.transport_evaluations
                   if row["profile"] == profile and row["scenario"] == scenario and row["academic_test_ready"]]
        for row in results:
            row["preview_score"] = Decimal(row["preview_score"])
        return {"mode": "inactive_diagnostic_only", "candidate_fingerprint": self.candidate_fingerprint,
                "profile": profile, "scenario": scenario, "eligible_count": len(results),
                "groups": json_document(rankings(results)), "operationally_active": False,
                "recommended": False, "publication_allowed": False, "limitations": list(self.limitations)}


def _validate_decision(decision, policy):
    # Human acceptance of scope is NOT documentary evidence or snapshot approval.
    expected = {
        "schema": "sigra-documentary-coverage-decision-v1",
        "source": "Current direct user instruction",
        "candidate_reference": "SIGRA_Seguranca_V6_Revision6",
        "candidate_zip_sha256": policy["candidate_zip_sha256"],
        "original_target": {"familia": 10, "estrada": 10},
        "achieved": {"familia": 9, "estrada": 9},
        "original_target_met": False,
        "user_accepts_proceeding_with_nine": True,
        "tenth_inventory_search_closed": True,
        "revision7_requested": False,
        "evidence_policy_changed": False,
        "candidate_approved": False,
        "candidate_activation_authorized": False,
        "database_write_authorized": False,
        "publication_authorized": False,
    }
    if set(decision) != set(expected) | {"recorded_at"} or not isinstance(decision["recorded_at"], str) or not decision["recorded_at"]:
        raise ValueError("Coverage decision missing or inconsistent")
    for key, value in expected.items():
        if fingerprint(decision[key]) != fingerprint(value):
            raise ValueError("Scope acceptance cannot modify evidence or authorize activation")


def _validate_payloads(approved, candidate, decision, policy):
    validate_replay(approved)
    if fingerprint(approved) != policy["approved_v6_fingerprint"]:
        raise ValueError("Wrong approved historical reference")
    if fingerprint(candidate) != policy["candidate_fingerprint"]:
        raise ValueError("Candidate differs from the verified Revision6")
    if fingerprint(method_manifest()) != policy["method_manifest_fingerprint"]:
        raise ValueError("Local methodology changed; review required")
    if candidate["version"] != policy["candidate_version"] or candidate["profile_counts"] != policy["profile_counts"]:
        raise ValueError("Wrong candidate version or coverage")
    if candidate["selected_ids"] != approved["selected_ids"] or candidate["holdout_ids"] != approved["holdout_ids"]:
        raise ValueError("Selected identities or holdouts changed")
    if candidate["operationally_active"] or candidate["recommended"] or candidate["operational_ranking"]:
        raise ValueError("Operational flags prohibited")
    if candidate["snapshot_replacement_authorized"] or candidate["operational_activation_authorized"]:
        raise ValueError("Candidate activation prohibited")
    _validate_decision(decision, policy)
    try:
        validate_replay(candidate)
    except ValueError:
        pass
    else:
        raise ValueError("Approved V6 contract must still reject the candidate")
    old = {row["vehicle"]["id"]: row for row in approved["academic_payload"]}
    rows = {row["vehicle"]["id"]: row for row in candidate["academic_payload"]}
    if len(rows) != 60 or len(candidate["academic_payload"]) != 60 or set(rows) != set(old):
        raise ValueError("Invalid sixty-identity grain")
    states = {row["id"]: row for row in candidate["states"]}
    old_states = {row["id"]: row for row in approved["states"]}
    if len(states) != len(candidate["states"]) or set(states) != set(old_states):
        raise ValueError("Inventory grain changed")
    if any(states[i] != old_states[i] for i in states if i not in rows):
        raise ValueError("Holdout or inactive backlog changed")
    allowed = {int(key): set(value) for key, value in policy["authorized_field_deltas_from_approved_v6"].items()}
    actual = {}
    for identifier, row in rows.items():
        before, after = old[identifier]["vehicle"], row["vehicle"]
        if any(before[key] != after[key] for key in before if key != "fields"):
            raise ValueError("Identity metadata changed")
        changed = {key for key in before["fields"] if before["fields"][key] != after["fields"][key]}
        if changed:
            actual[identifier] = changed
        v6.V6ProfileVehicle.model_validate(after)
        for key in changed - {"width_with_mirrors_mm"}:
            evidence = after["fields"][key]
            if (evidence["kind"] != "observed" or evidence["applicability"] != "exact_variant"
                    or not evidence["sources"] or any(s["provider"] != "manufacturer" for s in evidence["sources"])):
                raise ValueError("Nonmanufacturer or inexact new safety evidence")
    if actual != allowed:
        raise ValueError("Documentary field scope differs")
    if any(rows[70]["vehicle"]["fields"][key]["value"] is not None for key in ("airbags", "abs", "esc")):
        raise ValueError("Tiguan dealership proposal is not admissible")
    if rows[44]["vehicle"]["fields"]["esc"]["value"] is not False:
        raise ValueError("Fiesta explicit absence changed")
    cruze = rows[46]["vehicle"]["fields"]
    if Decimal(cruze["width_mm"]["value"]) != 1807 or Decimal(cruze["width_with_mirrors_mm"]["value"]) != 2042:
        raise ValueError("Cruze body/mirror dimensions confused")
    return old, rows, states


def prepare_revision6(bundle_directory, decision_file):
    """Validate pinned files, re-execute the unchanged engine, return a dry-run plan.

    Explicit paths only. No database/network/subprocess, writes, default selection,
    or imports of arbitrary code supplied by a package.
    """
    root = Path(bundle_directory).resolve(strict=True)
    policy = _read(CONTRACT)
    for key in ("candidate_approved", "activation_allowed", "default_snapshot_replacement_allowed",
                "database_write_allowed", "publication_allowed", "original_target_met"):
        if policy[key] is not False:
            raise ValueError("Inactive policy required")
    inventory_file = _local(root, "bundle-file-inventory.json")
    if _sha(inventory_file) != policy["bundle_inventory_sha256"]:
        raise ValueError("Untrusted bundle inventory")
    inventory = _read(inventory_file)
    listed = {item["path"] for item in inventory}
    actual = {path.relative_to(root).as_posix() for path in root.rglob("*")
              if path.is_file() and path != inventory_file}
    if len(listed) != len(inventory) or listed != actual:
        raise ValueError("Bundle member set differs")
    for item in inventory:
        if _sha(_local(root, item["path"])) != item["sha256"]:
            raise ValueError("Evidence/code hash mismatch")
    approved = _read(_local(root, APPROVED_PATH))
    candidate = _read(_local(root, "experimental/replay.json"))
    decision = _read(decision_file)
    old, rows, states = _validate_payloads(approved, candidate, decision, policy)
    vehicles, evaluations = [], []
    counts = {scenario: {profile: 0 for profile in policy["profiles"]} for scenario in policy["scenarios"]}
    ready = {scenario: {profile: [] for profile in ("familia", "estrada")} for scenario in policy["scenarios"]}
    for identifier in candidate["selected_ids"]:
        row = rows[identifier]
        vehicle = v6.V6ProfileVehicle.model_validate(row["vehicle"])
        fields = vehicle.fields
        vehicles.append({"catalog_id": identifier,
                         "canonical_identity_key": fingerprint({key: fields[key].value for key in
                             ("fipe_code", "year_code", "commercial_identity", "fuel", "transmission")}),
                         "fipe_code": fields["fipe_code"].value, "year_code": fields["year_code"].value,
                         "label": vehicle.label, "purchase_price_brl": fields["price_brl"].value,
                         "reference_month": fields["reference_month"].value,
                         "payload": deepcopy(row["vehicle"]), "payload_fingerprint": fingerprint(row["vehicle"])})
        for scenario in policy["scenarios"]:
            if set(row["evaluations"]) != set(policy["scenarios"]) or set(row["evaluations"][scenario]) != set(policy["profiles"]):
                raise ValueError("Missing scenario/profile")
            for profile in policy["profiles"]:
                expected = row["evaluations"][scenario][profile]
                engine = v6.evaluate_vehicle if "price_reference_policy_version" in expected else v4.evaluate_vehicle
                recalculated = json_document(engine(vehicle, profile, scenario, "2026-09"))
                if fingerprint(recalculated) != fingerprint(expected):
                    raise ValueError("Existing engine does not reproduce the candidate")
                if fingerprint(expected) != fingerprint(states[identifier]["evaluations"][scenario][profile]):
                    raise ValueError("State/payload mismatch")
                for key in ("scenario_costs", "weights", "profile_eligible", "observed_tco_complete"):
                    if fingerprint(expected[key]) != fingerprint(old[identifier]["evaluations"][scenario][profile][key]):
                        raise ValueError("Cost, weight, eliminatory rule or observational status changed")
                if expected["operationally_active"] or expected["recommended"] or expected["operational_ranking"]:
                    raise ValueError("Operational result prohibited")
                if expected["academic_test_ready"]:
                    counts[scenario][profile] += 1
                    if profile in ready[scenario]:
                        ready[scenario][profile].append(identifier)
                evaluations.append({"catalog_id": identifier, "profile": profile, "scenario": scenario,
                                    "academic_test_ready": expected["academic_test_ready"],
                                    "score": None if expected["preview_score"] is None else Decimal(expected["preview_score"]),
                                    "monthly_tco_brl": Decimal(expected["scenario_monthly_tco_brl"]),
                                    "payload": deepcopy(expected), "payload_fingerprint": fingerprint(expected)})
    if len(vehicles) != 60 or len(evaluations) != 1080:
        raise ValueError("Incomplete dry-run transport")
    for scenario in policy["scenarios"]:
        if counts[scenario] != policy["profile_counts"]:
            raise ValueError("Coverage differs")
        if any(sorted(ids) != policy["safety_ready_ids"] for ids in ready[scenario].values()):
            raise ValueError("Wrong admitted safety identities")
    return InactiveRevision6Proposal(policy["candidate_version"], policy["candidate_fingerprint"],
        policy["approved_v6_fingerprint"], policy["bundle_inventory_sha256"], deepcopy(decision),
        deepcopy(policy["profile_counts"]), tuple(vehicles), tuple(evaluations), tuple(policy["limitations"]))
