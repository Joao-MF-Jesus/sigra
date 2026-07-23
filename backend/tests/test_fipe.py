import unittest
from datetime import UTC, datetime

import app.fipe as fipe_module
from app.fipe import (
    FIPE_REFERENCE_PROFILES,
    _fetch_reference,
    effective_price,
    fipe_coverage,
    price_metadata,
)
from app.sample_data import VEHICLES


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class FakeClient:
    def get(self, endpoint):
        if endpoint == "/cars/014059-7/years":
            return FakeResponse(
                [
                    {"code": "2018-1", "name": "2018 Gasolina"},
                    {"code": "2018-5", "name": "2018 Flex"},
                ]
            )
        if endpoint == "/cars/014059-7/years/2018-5":
            return FakeResponse(
                {
                    "price": "R$ 77.123,00",
                    "codeFipe": "014059-7",
                    "modelYear": 2018,
                    "model": "CITY Sedan LX 1.5 Flex 16V 4p Aut.",
                    "referenceMonth": "agosto de 2026",
                }
            )
        raise AssertionError(endpoint)


class FipeReferenceTests(unittest.TestCase):
    def setUp(self):
        fipe_module._references = dict(FIPE_REFERENCE_PROFILES)

    def test_mapped_price_waits_for_a_valid_sync(self):
        self.assertEqual(effective_price(14, 72000), 72000)
        metadata = price_metadata(14)
        self.assertFalse(metadata["is_fipe"])
        self.assertEqual(metadata["code"], "014059-7")
        self.assertEqual(metadata["validation_status"], "mapped_pending_sync")

    def test_mapped_vehicle_keeps_demonstrative_price_before_sync(self):
        self.assertEqual(effective_price(1, 62000), 62000)
        metadata = price_metadata(1)
        self.assertFalse(metadata["is_fipe"])
        self.assertEqual(metadata["validation_status"], "mapped_pending_sync")

    def test_all_sample_vehicles_have_an_exact_fipe_mapping(self):
        self.assertEqual(set(FIPE_REFERENCE_PROFILES), {vehicle.id for vehicle in VEHICLES})
        self.assertTrue(all(len(item.code) == 8 and item.code[6] == "-" for item in FIPE_REFERENCE_PROFILES.values()))

    def test_year_specific_equivalent_versions_use_available_fipe_codes(self):
        expected_codes = {
            6: "015168-8",
            7: "015174-2",
            17: "005490-9",
            23: "001486-9",
        }
        self.assertEqual(
            {vehicle_id: FIPE_REFERENCE_PROFILES[vehicle_id].code for vehicle_id in expected_codes},
            expected_codes,
        )

    def test_mapping_coverage_is_explicit(self):
        coverage = fipe_coverage(34)
        self.assertEqual(coverage["mapped_vehicles"], 34)
        self.assertEqual(coverage["mapping_coverage_percent"], 100)
        self.assertEqual(coverage["total_vehicles"], 34)

    def test_live_response_updates_price_and_reference_month(self):
        now = datetime(2026, 8, 1, 12, tzinfo=UTC)
        updated = _fetch_reference(FakeClient(), FIPE_REFERENCE_PROFILES[14], now)
        self.assertEqual(updated.price, 77123)
        self.assertEqual(updated.year_code, "2018-5")
        self.assertEqual(updated.reference_month, "agosto de 2026")
        self.assertEqual(updated.retrieval_status, "live")


if __name__ == "__main__":
    unittest.main()
