"""Offline integration preparation: no API, database, SQLite or source collection."""
from copy import deepcopy
from decimal import Decimal
import json
import os
from pathlib import Path
import tempfile
import unittest

from app.academic_cohort import safety_revision6 as s
from app.academic_cohort.contracts import APPROVED_FINGERPRINT, MaterializationPlan, validate_replay
from data_platform.catalog.profile_pilot_v4 import fingerprint


class InactiveRevision6IntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bundle = Path(os.environ["SIGRA_REVISION6_BUNDLE"]).resolve(strict=True)
        cls.decision_file = Path(os.environ["SIGRA_REVISION6_DECISION"]).resolve(strict=True)
        cls.policy = s._read(s.CONTRACT)
        cls.approved = s._read(cls.bundle / s.APPROVED_PATH)
        cls.candidate = s._read(cls.bundle / "experimental/replay.json")
        cls.decision = s._read(cls.decision_file)
        cls.plan = s.prepare_revision6(cls.bundle, cls.decision_file)

    def test_01_approved_contract_unchanged(self):
        self.assertEqual(validate_replay(self.approved).cohort_fingerprint, APPROVED_FINGERPRINT)
        with self.assertRaises(ValueError):
            validate_replay(self.candidate)

    def test_02_exact_sixty_and_1080(self):
        self.assertEqual(len(self.plan.transport_vehicles), 60)
        self.assertEqual(len(self.plan.transport_evaluations), 1080)
        self.assertEqual(len({r["catalog_id"] for r in self.plan.transport_vehicles}), 60)
        self.assertEqual(len({r["fipe_code"] for r in self.plan.transport_vehicles}), 60)
        self.assertEqual(len({(r["catalog_id"], r["profile"], r["scenario"]) for r in self.plan.transport_evaluations}), 1080)

    def test_03_nine_each_profile_each_scenario(self):
        for scenario in self.policy["scenarios"]:
            for profile, count in self.policy["profile_counts"].items():
                rows = [r for r in self.plan.transport_evaluations if r["profile"] == profile and r["scenario"] == scenario and r["academic_test_ready"]]
                self.assertEqual(len(rows), count)
                if profile in {"familia", "estrada"}:
                    self.assertEqual(sorted(r["catalog_id"] for r in rows), self.policy["safety_ready_ids"])

    def test_04_acceptance_does_not_claim_ten_or_approval(self):
        self.assertFalse(self.plan.coverage_decision["original_target_met"])
        self.assertEqual(self.plan.coverage_decision["original_target"], {"familia": 10, "estrada": 10})
        self.assertTrue(self.plan.coverage_decision["user_accepts_proceeding_with_nine"])
        self.assertFalse(self.plan.coverage_decision["candidate_approved"])

    def test_05_not_a_writer_plan(self):
        self.assertNotIsInstance(self.plan, MaterializationPlan)
        self.assertFalse(hasattr(self.plan, "vehicles"))
        self.assertFalse(hasattr(self.plan, "evaluations"))
        with self.assertRaises(ValueError, msg="No accidental materialization"):
            self.plan.assert_write_allowed()

    def test_06_exact_documentary_sources_preserved(self):
        source_rows = {r["vehicle"]["id"]: r["vehicle"] for r in self.candidate["academic_payload"]}
        for row in self.plan.transport_vehicles:
            self.assertEqual(row["payload"], source_rows[row["catalog_id"]])
            self.assertEqual(row["payload_fingerprint"], fingerprint(row["payload"]))

    def test_07_costs_weights_and_eligibility_preserved(self):
        original = {(r["vehicle"]["id"], scenario, profile): result
                    for r in self.approved["academic_payload"] for scenario, profiles in r["evaluations"].items()
                    for profile, result in profiles.items()}
        for row in self.plan.transport_evaluations:
            old = original[row["catalog_id"], row["scenario"], row["profile"]]
            for key in ("scenario_costs", "weights", "profile_eligible", "observed_tco_complete"):
                self.assertEqual(row["payload"][key], old[key])

    def test_08_tiguan_dealer_not_admitted(self):
        row = next(r for r in self.plan.transport_vehicles if r["catalog_id"] == 70)
        for field in ("airbags", "abs", "esc"):
            self.assertIsNone(row["payload"]["fields"][field]["value"])

    def test_09_fiesta_absence_and_lower_score(self):
        vehicles = {r["catalog_id"]: r for r in self.plan.transport_vehicles}
        self.assertIs(vehicles[44]["payload"]["fields"]["esc"]["value"], False)
        for scenario in self.policy["scenarios"]:
            for profile in ("familia", "estrada"):
                rows = {r["catalog_id"]: r["payload"] for r in self.plan.transport_evaluations if r["scenario"] == scenario and r["profile"] == profile}
                self.assertLess(Decimal(rows[44]["criteria"]["safety"]["value"]), Decimal(rows[62]["criteria"]["safety"]["value"]))

    def test_10_cruze_body_and_mirror_are_distinct(self):
        fields = next(r for r in self.plan.transport_vehicles if r["catalog_id"] == 46)["payload"]["fields"]
        self.assertEqual(Decimal(fields["width_mm"]["value"]), 1807)
        self.assertEqual(Decimal(fields["width_with_mirrors_mm"]["value"]), 2042)
        self.assertEqual(fields["width_with_mirrors_mm"]["applicability"], "model_nominal")
        self.assertEqual(fields["width_with_mirrors_mm"]["sources"][0]["sha256"], "d8b6d5be870780ffa2f80e0f3a26c2218225322b28c20804a1640e81e74f829f")
        for field in ("airbags", "abs", "esc"):
            self.assertIsNone(fields[field]["value"])

    def test_11_kicks_and_rio_airbags_remain_unknown(self):
        for identifier in (102, 123):
            fields = next(r for r in self.plan.transport_vehicles if r["catalog_id"] == identifier)["payload"]["fields"]
            self.assertIsNone(fields["airbags"]["value"])

    def test_12_no_operational_results(self):
        for row in self.plan.transport_evaluations:
            self.assertIs(row["payload"]["operationally_active"], False)
            self.assertIs(row["payload"]["recommended"], False)
            self.assertEqual(row["payload"]["operational_ranking"], [])

    def test_13_diagnostic_groups_use_existing_ranker(self):
        for profile in ("familia", "estrada"):
            preview = self.plan.diagnostic_preview(profile, "base")
            self.assertEqual(preview["eligible_count"], 9)
            self.assertFalse(preview["publication_allowed"])
            self.assertEqual(preview["mode"], "inactive_diagnostic_only")
            self.assertEqual(sum(len(g["ranking"]) for g in preview["groups"].values()), 9)

    def test_14_unknown_profile_rejected(self):
        with self.assertRaises(ValueError):
            self.plan.diagnostic_preview("not-a-profile", "base")

    def test_15_unknown_scenario_rejected(self):
        with self.assertRaises(ValueError):
            self.plan.diagnostic_preview("familia", "not-a-scenario")

    def test_16_preview_repeatability_and_no_mutation(self):
        before = fingerprint(self.candidate)
        self.assertEqual(self.plan.diagnostic_preview("familia", "base"), self.plan.diagnostic_preview("familia", "base"))
        self.assertEqual(fingerprint(self.candidate), before)

    def test_17_local_paths_fail_closed(self):
        for name in ("../outside.json", "/outside.json", "C:/outside.json", "a\\outside.json"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                s._local(self.bundle, name)

    def test_18_untrusted_inventory_rejected(self):
        # A controlled writable test directory avoids the restricted default
        # Windows sandbox TEMP; the tested rejection remains unchanged.
        with tempfile.TemporaryDirectory(prefix="sigra-r6-invalid-", dir=Path(__file__).resolve().parent) as root:
            (Path(root) / "bundle-file-inventory.json").write_text("[]", encoding="utf-8")
            with self.assertRaises(ValueError):
                s.prepare_revision6(root, self.decision_file)

    def test_19_duplicate_json_keys_rejected(self):
        with self.assertRaises(ValueError):
            json.loads('{"status":1,"status":2}', object_pairs_hook=s._unique_object)

    def test_20_missing_acceptance_rejected(self):
        decision = deepcopy(self.decision)
        decision.pop("user_accepts_proceeding_with_nine")
        with self.assertRaises(ValueError):
            s._validate_decision(decision, self.policy)

    def test_21_forged_ten_not_accepted(self):
        decision = deepcopy(self.decision)
        decision["achieved"]["familia"] = 10
        with self.assertRaises(ValueError):
            s._validate_decision(decision, self.policy)

    def test_22_acceptance_cannot_authorize_activation(self):
        for key in ("candidate_approved", "candidate_activation_authorized", "database_write_authorized", "publication_authorized"):
            decision = deepcopy(self.decision)
            decision[key] = True
            with self.subTest(key=key), self.assertRaises(ValueError):
                s._validate_decision(decision, self.policy)

    def test_23_tampered_candidate_rejected(self):
        candidate = deepcopy(self.candidate)
        candidate["profile_counts"]["familia"] = 10
        with self.assertRaises(ValueError):
            s._validate_payloads(self.approved, candidate, self.decision, self.policy)

    def test_24_approved_v6_not_overwritten(self):
        self.assertEqual(fingerprint(self.approved), APPROVED_FINGERPRINT)
        self.assertNotEqual(fingerprint(self.candidate), APPROVED_FINGERPRINT)
        self.assertNotEqual(self.plan.candidate_version, self.approved["version"])

    def test_25_critical_transport_fingerprints(self):
        for row in self.plan.transport_evaluations:
            self.assertEqual(row["payload_fingerprint"], fingerprint(row["payload"]))
            self.assertEqual(row["monthly_tco_brl"], Decimal(row["payload"]["scenario_monthly_tco_brl"]))

    def test_26_unknown_not_false_for_inventory(self):
        fields = next(r for r in self.plan.transport_vehicles if r["catalog_id"] == 70)["payload"]["fields"]
        for field in ("airbags", "abs", "esc"):
            self.assertEqual(fields[field]["kind"], "unavailable")
            self.assertIsNone(fields[field]["value"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
