import json
import unittest
from pathlib import Path

from app.recommender import RecommendationProfile, Vehicle, recommend


FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "cars_regression_v1.json"


class CarRegressionFixtureTest(unittest.TestCase):
    def test_immutable_car_rankings_and_scores(self):
        fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        self.assertTrue(fixture["immutable"])
        self.assertEqual(fixture["algorithm_version"], "2.1.2")
        self.assertEqual(fixture["weights_version"], "cars-v1")
        tolerance = fixture["score_tolerance"]
        vehicles = [
            Vehicle(
                **{
                    **item,
                    "use_cases": tuple(item["use_cases"]),
                    "chronic_issues": tuple(item["chronic_issues"]),
                }
            )
            for item in fixture["vehicles"]
        ]

        for scenario in fixture["scenarios"]:
            with self.subTest(scenario=scenario["name"]):
                results = recommend(vehicles, RecommendationProfile(**scenario["profile"]))
                self.assertEqual([item["vehicle"].id for item in results], [item[0] for item in scenario["expected"]])
                for result, expected in zip(results, scenario["expected"]):
                    self.assertAlmostEqual(result["score"], expected[1], delta=tolerance)
                    self.assertEqual(result["recommendation_status"], expected[2])
                    self.assertEqual(result["score_components"]["fully_viable"], expected[3])
