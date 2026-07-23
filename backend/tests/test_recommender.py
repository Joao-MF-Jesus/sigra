import unittest

from app.sample_data import VEHICLES as SAMPLE_VEHICLES
from app.recommender import RecommendationProfile, Vehicle, estimate_monthly_cost, recommend
from app.tco import calculate_tco


class RecommenderTest(unittest.TestCase):
    def setUp(self):
        self.vehicles = [
            Vehicle(1, "A", "Economico", 2020, 50000, 14, 2400, 85, 90, 8, ("cidade",), ()),
            Vehicle(2, "B", "Caro", 2020, 90000, 9, 5000, 70, 70, 14, ("estrada",), ()),
        ]

    def test_recommendation_prioritizes_profile_fit_and_costs(self):
        profile = RecommendationProfile(budget=60000, monthly_limit=900, use_case="cidade")
        results = recommend(self.vehicles, profile)

        self.assertEqual(results[0]["vehicle"].model, "Economico")
        self.assertGreater(results[0]["score"], results[1]["score"])

    def test_monthly_cost_includes_fuel_and_maintenance(self):
        profile = RecommendationProfile(budget=60000, monthly_limit=900, use_case="cidade", monthly_mileage=1400, fuel_price=6)

        self.assertEqual(estimate_monthly_cost(self.vehicles[0], profile), 1508.33)

    def test_tco_breakdown(self):
        tco = calculate_tco(
            vehicle_price=60000,
            fuel_efficiency_km_l=12,
            monthly_mileage=1200,
            fuel_price=6,
            annual_maintenance_cost=2400,
            annual_depreciation_rate=10,
        )

        self.assertEqual(tco["monthly_fuel_cost"], 600)
        self.assertEqual(tco["monthly_maintenance_cost"], 200)
        self.assertEqual(tco["monthly_ipva_cost"], 200)
        self.assertEqual(tco["monthly_insurance_cost"], 250)
        self.assertEqual(tco["monthly_depreciation_cost"], 500)
        self.assertEqual(tco["total_monthly_cost"], 1750)

    def test_high_mileage_changes_recommendation_score(self):
        low_mileage = RecommendationProfile(budget=60000, monthly_limit=1200, use_case="cidade", monthly_mileage=500, fuel_price=6)
        high_mileage = RecommendationProfile(budget=60000, monthly_limit=1200, use_case="cidade", monthly_mileage=2500, fuel_price=6)

        low_results = recommend(self.vehicles, low_mileage)
        high_results = recommend(self.vehicles, high_mileage)

        self.assertGreater(low_results[0]["score"], high_results[0]["score"])

    def test_recommendation_returns_v2_components(self):
        profile = RecommendationProfile(budget=100000, monthly_limit=2500, use_case="cidade")
        result = recommend(self.vehicles, profile)[0]

        self.assertIn("tco", result)
        self.assertIn("score_components", result)
        self.assertIn("financial_score", result["score_components"])
        self.assertIn("usage_score", result["score_components"])
        self.assertIn("maintenance_score", result["score_components"])
        self.assertIn("reliability_score", result["score_components"])
        self.assertIn("parts_score", result["score_components"])
        self.assertIn("resale_score", result["score_components"])
        self.assertIn("risk_score", result["score_components"])
        self.assertIn("tco_score", result["score_components"])
        self.assertIn("segment_score", result["score_components"])
        self.assertIn("purchase_intent_score", result["score_components"])
        self.assertIn("purchase_viable", result["score_components"])
        self.assertIn("monthly_viable", result["score_components"])
        self.assertIn("fully_viable", result["score_components"])
        self.assertIn("monthly_capacity_score", result["score_components"])
        self.assertIn("financial_capacity_profile", result["score_components"])
        self.assertIn("monthly_limit_gap", result["score_components"])
        self.assertIn("total_monthly_cost", result["score_components"])
        self.assertIn("final_score", result["score_components"])
        self.assertEqual(result["recommendation_strategy"], "cost_benefit")
        self.assertIn("recommendation_summary", result)
        self.assertIn("score_breakdown", result)
        self.assertIn("confidence", result)
        self.assertAlmostEqual(
            sum(item["weight"] for item in result["score_breakdown"]["criteria"]),
            100.0,
            places=2,
        )
        self.assertLessEqual(result["score_breakdown"]["context_adjustment"], 8.0)
        self.assertIn(result["confidence"]["level"], {"baixa", "moderada"})

    def test_monthly_limit_penalizes_expensive_tco(self):
        profile = RecommendationProfile(budget=100000, monthly_limit=900, use_case="cidade", monthly_mileage=1400, fuel_price=6)
        results = recommend(self.vehicles, profile)

        expensive = next(item for item in results if item["vehicle"].model == "Caro")
        self.assertIn(expensive["recommendation_status"], {"attention", "not_recommended"})
        self.assertGreater(expensive["tco"]["total_monthly_cost"], profile.monthly_limit)

    def test_cheap_purchase_expensive_maintenance_is_penalized(self):
        vehicles = [
            Vehicle(1, "A", "Barato caro de manter", 2020, 42000, 8, 9000, 60, 55, 16, ("cidade",), ()),
            Vehicle(2, "B", "Equilibrado", 2020, 62000, 14, 2600, 86, 88, 8, ("cidade",), ()),
        ]
        profile = RecommendationProfile(budget=70000, monthly_limit=1800, use_case="cidade", monthly_mileage=1000, fuel_price=6)
        results = recommend(vehicles, profile)

        self.assertEqual(results[0]["vehicle"].model, "Equilibrado")
        self.assertLess(results[1]["score_components"]["maintenance_score"], results[0]["score_components"]["maintenance_score"])

    def test_more_expensive_but_efficient_can_rank_higher(self):
        vehicles = [
            Vehicle(1, "A", "Entrada gastador", 2020, 45000, 7.5, 5200, 65, 62, 15, ("app",), ()),
            Vehicle(2, "B", "Eficiente", 2020, 65000, 16, 2600, 86, 88, 8, ("app",), ()),
        ]
        profile = RecommendationProfile(budget=70000, monthly_limit=1900, use_case="app", monthly_mileage=2800, fuel_price=6)
        results = recommend(vehicles, profile)

        self.assertEqual(results[0]["vehicle"].model, "Eficiente")
        self.assertLess(results[0]["tco"]["total_monthly_cost"], results[1]["tco"]["total_monthly_cost"])

    def test_use_case_can_change_top_recommendation(self):
        vehicles = [
            Vehicle(1, "A", "Urbano", 2020, 65000, 13, 3000, 84, 85, 9, ("cidade",), ()),
            Vehicle(2, "B", "Estradeiro", 2020, 65000, 13, 3000, 84, 85, 9, ("estrada",), ()),
        ]
        profile = RecommendationProfile(budget=95000, monthly_limit=1600, use_case="estrada", monthly_mileage=1200, fuel_price=6)
        results = recommend(vehicles, profile)

        self.assertEqual(results[0]["vehicle"].model, "Estradeiro")

    def test_suv_profile_can_recommend_suv_model(self):
        vehicles = [
            Vehicle(1, "A", "Sedan", 2020, 70000, 13, 3000, 86, 88, 9, ("familia", "estrada"), ()),
            Vehicle(2, "B", "SUV", 2020, 78000, 10.1, 3700, 78, 78, 11.5, ("familia", "estrada", "suv"), ()),
        ]
        profile = RecommendationProfile(budget=90000, monthly_limit=2500, use_case="suv", monthly_mileage=1000, fuel_price=6)
        results = recommend(vehicles, profile)

        self.assertEqual(results[0]["vehicle"].model, "SUV")
        self.assertTrue(results[0]["score_components"]["fully_viable"])

    def test_default_strategy_is_cost_benefit(self):
        profile = RecommendationProfile(budget=200000, monthly_limit=5000, use_case="cidade")
        results = recommend(SAMPLE_VEHICLES, profile)

        self.assertEqual(profile.recommendation_strategy, "cost_benefit")
        self.assertEqual(results[0]["recommendation_strategy"], "cost_benefit")

    def test_lowest_cost_can_prioritize_cheap_cars_with_high_budget(self):
        profile = RecommendationProfile(
            budget=200000,
            monthly_limit=5000,
            use_case="cidade",
            recommendation_strategy="lowest_cost",
        )
        top_models = [item["vehicle"].model for item in recommend(SAMPLE_VEHICLES, profile)[:6]]

        self.assertTrue({"Mobi Like", "Uno Attractive", "March SV"} & set(top_models))

    def test_budget_economy_differs_from_lowest_cost_with_high_budget(self):
        base = {
            "budget": 200000,
            "monthly_limit": 5000,
            "use_case": "cidade",
        }
        lowest = [item["vehicle"].model for item in recommend(SAMPLE_VEHICLES, RecommendationProfile(**base, recommendation_strategy="lowest_cost"))[:6]]
        economy = [item["vehicle"].model for item in recommend(SAMPLE_VEHICLES, RecommendationProfile(**base, recommendation_strategy="budget_economy"))[:6]]

        self.assertNotEqual(lowest, economy)

    def test_best_within_budget_promotes_superior_segments(self):
        profile = RecommendationProfile(
            budget=200000,
            monthly_limit=5000,
            use_case="familia",
            recommendation_strategy="best_within_budget",
        )
        top_results = recommend(SAMPLE_VEHICLES, profile)[:6]

        self.assertTrue(any(item["vehicle"].segment_level >= 4 for item in top_results))

    def test_best_within_budget_city_high_budget_promotes_two_superior_segments(self):
        profile = RecommendationProfile(
            budget=200000,
            monthly_limit=3500,
            use_case="cidade",
            recommendation_strategy="best_within_budget",
        )
        top_results = recommend(SAMPLE_VEHICLES, profile)[:6]
        superior_count = sum(
            1
            for item in top_results
            if item["vehicle"].segment_level >= 4
            or item["vehicle"].category in {"midsize_sedan", "compact_suv", "suv"}
        )

        self.assertGreaterEqual(superior_count, 2)

    def test_lowest_cost_and_best_within_budget_are_not_too_similar(self):
        base = {
            "budget": 200000,
            "monthly_limit": 3500,
            "use_case": "cidade",
        }
        lowest = {item["vehicle"].model for item in recommend(SAMPLE_VEHICLES, RecommendationProfile(**base, recommendation_strategy="lowest_cost"))[:6]}
        best = {item["vehicle"].model for item in recommend(SAMPLE_VEHICLES, RecommendationProfile(**base, recommendation_strategy="best_within_budget"))[:6]}

        self.assertLess(len(lowest & best), 4)

    def test_budget_economy_stays_between_entry_and_upper_segment(self):
        profile = RecommendationProfile(
            budget=200000,
            monthly_limit=3500,
            use_case="cidade",
            recommendation_strategy="budget_economy",
        )
        top_results = recommend(SAMPLE_VEHICLES, profile)[:6]
        entry_models = {"Mobi Like", "Uno Attractive", "Gol Trendline", "March SV"}
        entry_count = sum(1 for item in top_results if item["vehicle"].model in entry_models)
        has_intermediate_or_better = any(item["vehicle"].segment_level >= 3 for item in top_results)

        self.assertLessEqual(entry_count, 1)
        self.assertTrue(has_intermediate_or_better)

    def test_comfort_space_values_roomier_vehicles(self):
        profile = RecommendationProfile(
            budget=200000,
            monthly_limit=5000,
            use_case="familia",
            recommendation_strategy="comfort_space",
        )
        top_models = [item["vehicle"].model for item in recommend(SAMPLE_VEHICLES, profile)[:6]]

        self.assertTrue({"Corolla Cross XR", "Spin LT", "HR-V LX", "Creta Attitude", "Corolla GLi"} & set(top_models))

    def test_low_budget_still_penalizes_expensive_cars(self):
        profile = RecommendationProfile(
            budget=55000,
            monthly_limit=1200,
            use_case="cidade",
            recommendation_strategy="best_within_budget",
        )
        corolla_cross = next(item for item in recommend(SAMPLE_VEHICLES, profile) if item["vehicle"].model == "Corolla Cross XR")

        self.assertEqual(corolla_cross["recommendation_status"], "not_recommended")
        self.assertLess(corolla_cross["final_score"], 60)

    def test_final_score_stays_between_zero_and_one_hundred(self):
        profile = RecommendationProfile(
            budget=200000,
            monthly_limit=5000,
            use_case="familia",
            recommendation_strategy="comfort_space",
        )
        scores = [item["final_score"] for item in recommend(SAMPLE_VEHICLES, profile)]

        self.assertTrue(all(0 <= score <= 100 for score in scores))

    def test_tco_components_are_still_returned(self):
        profile = RecommendationProfile(budget=200000, monthly_limit=5000, use_case="cidade")
        result = recommend(SAMPLE_VEHICLES, profile)[0]

        for key in [
            "monthly_fuel_cost",
            "monthly_maintenance_cost",
            "monthly_ipva_cost",
            "monthly_insurance_cost",
            "monthly_depreciation_cost",
            "total_monthly_cost",
        ]:
            self.assertIn(key, result["tco"])

    def test_high_budget_and_high_monthly_limit_promotes_upper_segment(self):
        profile = RecommendationProfile(
            budget=200000,
            monthly_limit=4000,
            use_case="cidade",
            recommendation_strategy="best_within_budget",
        )
        top_results = recommend(SAMPLE_VEHICLES, profile)[:6]
        superior_count = sum(1 for item in top_results if item["vehicle"].segment_level >= 4)

        self.assertGreaterEqual(superior_count, 4)
        self.assertGreaterEqual(top_results[0]["vehicle"].segment_level, 4)

    def test_high_budget_and_low_monthly_limit_restricts_expensive_tco(self):
        profile = RecommendationProfile(
            budget=200000,
            monthly_limit=800,
            use_case="cidade",
            recommendation_strategy="best_within_budget",
        )
        results = recommend(SAMPLE_VEHICLES, profile)
        top_results = results[:6]
        superior_count = sum(1 for item in top_results if item["vehicle"].segment_level >= 4)

        self.assertLessEqual(superior_count, 1)
        self.assertTrue(all(not item["score_components"]["monthly_viable"] for item in results))
        self.assertTrue(all(item["recommendation_status"] == "not_recommended" for item in top_results))

    def test_no_viable_options_returns_clear_summary_and_suggestion(self):
        profile = RecommendationProfile(
            budget=200000,
            monthly_limit=800,
            use_case="cidade",
            recommendation_strategy="best_within_budget",
        )
        results = recommend(SAMPLE_VEHICLES, profile)
        summary = results[0]["recommendation_summary"]

        self.assertGreater(len(results), 0)
        self.assertFalse(summary["has_viable_options"])
        self.assertEqual(summary["viable_count"], 0)
        self.assertEqual(summary["total_count"], len(results))
        self.assertGreater(summary["suggested_monthly_limit"], profile.monthly_limit)
        self.assertEqual(summary["suggested_strategy"], "lowest_cost")
        self.assertIn("limite mensal", summary["message"])
        self.assertIn("custo mensal estimado", summary["message"])

    def test_viable_options_return_positive_summary_without_warning_message(self):
        profile = RecommendationProfile(
            budget=200000,
            monthly_limit=4000,
            use_case="cidade",
            recommendation_strategy="best_within_budget",
        )
        results = recommend(SAMPLE_VEHICLES, profile)
        summary = results[0]["recommendation_summary"]

        self.assertTrue(summary["has_viable_options"])
        self.assertGreater(summary["viable_count"], 0)
        self.assertEqual(summary["message"], "")
        self.assertIsNone(summary["suggested_monthly_limit"])

    def test_high_budget_and_high_monthly_limit_capacity_profile(self):
        profile = RecommendationProfile(
            budget=200000,
            monthly_limit=4000,
            use_case="cidade",
            recommendation_strategy="best_within_budget",
        )
        result = recommend(SAMPLE_VEHICLES, profile)[0]

        self.assertIn(result["score_components"]["financial_capacity_profile"], {"comfortable", "high_capacity"})
        self.assertGreaterEqual(result["score_components"]["monthly_capacity_score"], 80)

    def test_high_budget_and_low_monthly_limit_capacity_profile(self):
        profile = RecommendationProfile(
            budget=200000,
            monthly_limit=800,
            use_case="cidade",
            recommendation_strategy="best_within_budget",
        )
        result = recommend(SAMPLE_VEHICLES, profile)[0]

        self.assertEqual(result["score_components"]["financial_capacity_profile"], "purchase_high_monthly_low")
        self.assertEqual(result["score_components"]["monthly_capacity_score"], 0)

    def test_lowest_cost_still_prioritizes_low_cost_with_high_monthly_limit(self):
        profile = RecommendationProfile(
            budget=200000,
            monthly_limit=4000,
            use_case="cidade",
            recommendation_strategy="lowest_cost",
        )
        top_models = [item["vehicle"].model for item in recommend(SAMPLE_VEHICLES, profile)[:6]]

        self.assertTrue({"Mobi Like", "Uno Attractive", "Gol Trendline", "March SV"} & set(top_models))

    def test_best_within_budget_high_capacity_not_dominated_by_entry_models(self):
        profile = RecommendationProfile(
            budget=200000,
            monthly_limit=4000,
            use_case="cidade",
            recommendation_strategy="best_within_budget",
        )
        top_results = recommend(SAMPLE_VEHICLES, profile)[:6]
        entry_models = {"Mobi Like", "Uno Attractive", "Gol Trendline", "March SV"}

        self.assertFalse(any(item["vehicle"].model in entry_models for item in top_results))

    def test_cost_benefit_high_budget_avoids_entry_level_recommendation(self):
        profile = RecommendationProfile(
            budget=300000,
            monthly_limit=4000,
            use_case="cidade",
            monthly_mileage=1000,
            fuel_price=6,
            recommendation_strategy="cost_benefit",
        )
        top_results = recommend(SAMPLE_VEHICLES, profile)[:6]
        entry_models = {"Mobi Like", "Uno Attractive", "Gol Trendline", "March SV", "Ka SE"}

        self.assertTrue(top_results[0]["vehicle"].segment_level >= 4)
        self.assertFalse(any(item["vehicle"].model in entry_models for item in top_results))
        self.assertGreaterEqual(sum(1 for item in top_results if item["vehicle"].segment_level >= 4), 4)

    def test_cost_benefit_very_high_budget_does_not_pick_cheapest_intermediate_car(self):
        profile = RecommendationProfile(
            budget=400000,
            monthly_limit=4000,
            use_case="cidade",
            monthly_mileage=1000,
            fuel_price=6,
            recommendation_strategy="cost_benefit",
        )
        top_results = recommend(SAMPLE_VEHICLES, profile)[:6]
        top_models = [item["vehicle"].model for item in top_results]

        self.assertNotEqual(top_models[0], "Fit EX")
        self.assertTrue(top_results[0]["vehicle"].segment_level >= 4)
        self.assertGreaterEqual(sum(1 for item in top_results if item["vehicle"].segment_level >= 4), 4)

    def test_best_within_budget_high_budget_prioritizes_best_available_category(self):
        profile = RecommendationProfile(
            budget=300000,
            monthly_limit=4000,
            use_case="cidade",
            monthly_mileage=1000,
            fuel_price=6,
            recommendation_strategy="best_within_budget",
        )
        top_results = recommend(SAMPLE_VEHICLES, profile)[:6]
        top_models = {item["vehicle"].model for item in top_results[:3]}

        self.assertIn("Corolla GLi", top_models)
        self.assertTrue(any(item["vehicle"].segment_level >= 4 for item in top_results[:3]))
        self.assertTrue(all(item["vehicle"].segment_level >= 4 for item in top_results))

    def test_app_lowest_cost_high_capacity_can_show_economy_models(self):
        profile = RecommendationProfile(
            budget=300000,
            monthly_limit=4000,
            use_case="app",
            monthly_mileage=1000,
            fuel_price=6,
            recommendation_strategy="lowest_cost",
        )
        top_models = {item["vehicle"].model for item in recommend(SAMPLE_VEHICLES, profile)[:6]}

        self.assertTrue({"Mobi Like", "Uno Attractive", "March SV", "Etios XLS"} & top_models)

    def test_app_budget_economy_high_capacity_not_dominated_by_entry_models(self):
        profile = RecommendationProfile(
            budget=300000,
            monthly_limit=4000,
            use_case="app",
            monthly_mileage=1000,
            fuel_price=6,
            recommendation_strategy="budget_economy",
        )
        top_results = recommend(SAMPLE_VEHICLES, profile)[:6]
        top_models = {item["vehicle"].model for item in top_results}
        entry_models = {"Mobi Like", "Uno Attractive", "March SV", "Gol Trendline"}
        expected_models = {"Fit EX", "Yaris XL", "Versa SV", "Prisma LT", "HB20S Comfort", "Corolla GLi", "City LX", "Etios XLS"}

        self.assertLessEqual(len(top_models & entry_models), 1)
        self.assertTrue(top_models & expected_models)

    def test_app_best_within_budget_high_capacity_promotes_professional_fit(self):
        profile = RecommendationProfile(
            budget=300000,
            monthly_limit=4000,
            use_case="app",
            monthly_mileage=1000,
            fuel_price=6,
            recommendation_strategy="best_within_budget",
        )
        top_results = recommend(SAMPLE_VEHICLES, profile)[:6]
        top_models = [item["vehicle"].model for item in top_results]
        superior_count = sum(1 for item in top_results if item["vehicle"].segment_level >= 3)

        self.assertGreaterEqual(superior_count, 3)
        self.assertNotIn("Mobi Like", top_models[:3])
        self.assertNotIn("Uno Attractive", top_models[:3])

    def test_app_low_budget_low_monthly_lowest_cost_can_show_entry_models(self):
        profile = RecommendationProfile(
            budget=55000,
            monthly_limit=1600,
            use_case="app",
            monthly_mileage=1000,
            fuel_price=6,
            recommendation_strategy="lowest_cost",
        )
        top_models = {item["vehicle"].model for item in recommend(SAMPLE_VEHICLES, profile)[:6]}

        self.assertTrue({"Mobi Like", "Uno Attractive"} & top_models)

    def test_suv_best_within_budget_high_capacity_does_not_saturate_top_six(self):
        profile = RecommendationProfile(
            budget=300000,
            monthly_limit=4000,
            use_case="suv",
            monthly_mileage=1000,
            fuel_price=6,
            recommendation_strategy="best_within_budget",
        )
        top_scores = [item["final_score"] for item in recommend(SAMPLE_VEHICLES, profile)[:6]]

        self.assertFalse(all(score == 100 for score in top_scores))
        self.assertLess(sum(1 for score in top_scores if score >= 99), 2)

    def test_suv_best_within_budget_high_capacity_has_granular_scores(self):
        profile = RecommendationProfile(
            budget=300000,
            monthly_limit=4000,
            use_case="suv",
            monthly_mileage=1000,
            fuel_price=6,
            recommendation_strategy="best_within_budget",
        )
        top_scores = [item["final_score"] for item in recommend(SAMPLE_VEHICLES, profile)[:6]]

        self.assertGreaterEqual(len(set(top_scores)), 4)

    def test_suv_best_within_budget_high_capacity_keeps_superior_vehicles(self):
        profile = RecommendationProfile(
            budget=300000,
            monthly_limit=4000,
            use_case="suv",
            monthly_mileage=1000,
            fuel_price=6,
            recommendation_strategy="best_within_budget",
        )
        top_results = recommend(SAMPLE_VEHICLES, profile)[:6]

        self.assertGreaterEqual(sum(1 for item in top_results if item["vehicle"].segment_level >= 4), 4)
        self.assertTrue(all("suv" in item["vehicle"].use_cases for item in top_results))

    def test_budget_economy_remains_distinct_from_lowest_and_best_within_budget(self):
        base = {
            "budget": 300000,
            "monthly_limit": 4000,
            "use_case": "cidade",
            "monthly_mileage": 1000,
            "fuel_price": 6,
        }
        lowest = [item["vehicle"].model for item in recommend(SAMPLE_VEHICLES, RecommendationProfile(**base, recommendation_strategy="lowest_cost"))[:6]]
        economy = [item["vehicle"].model for item in recommend(SAMPLE_VEHICLES, RecommendationProfile(**base, recommendation_strategy="budget_economy"))[:6]]
        best = [item["vehicle"].model for item in recommend(SAMPLE_VEHICLES, RecommendationProfile(**base, recommendation_strategy="best_within_budget"))[:6]]

        self.assertNotEqual(economy, lowest)
        self.assertNotEqual(economy, best)

    def test_high_capacity_use_profiles_do_not_repeat_the_same_top_three(self):
        top_threes = []
        for use_case in ("cidade", "familia", "trabalho", "estrada", "app", "suv"):
            profile = RecommendationProfile(
                budget=500000,
                monthly_limit=3000,
                use_case=use_case,
                monthly_mileage=1000,
                fuel_price=6,
                recommendation_strategy="cost_benefit",
            )
            top_threes.append(tuple(item["vehicle"].model for item in recommend(SAMPLE_VEHICLES, profile)[:3]))

        self.assertGreaterEqual(len(set(top_threes)), 4)

    def test_high_capacity_work_profile_does_not_promote_unmatched_suvs(self):
        profile = RecommendationProfile(
            budget=500000,
            monthly_limit=3000,
            use_case="trabalho",
            monthly_mileage=1000,
            fuel_price=6,
            recommendation_strategy="cost_benefit",
        )
        top_models = {item["vehicle"].model for item in recommend(SAMPLE_VEHICLES, profile)[:3]}

        self.assertFalse(top_models & {"Kicks S", "HR-V LX", "Creta Attitude"})

    def test_high_capacity_app_profile_promotes_professional_sedan(self):
        profile = RecommendationProfile(
            budget=500000,
            monthly_limit=3000,
            use_case="app",
            monthly_mileage=1000,
            fuel_price=6,
            recommendation_strategy="cost_benefit",
        )
        top_models = {item["vehicle"].model for item in recommend(SAMPLE_VEHICLES, profile)[:3]}

        self.assertTrue(top_models & {"Versa SV", "Cronos Drive", "Cobalt LTZ", "Corolla GLi"})

    def test_evidence_penalty_limits_excellence_score(self):
        profile = RecommendationProfile(
            budget=300000,
            monthly_limit=4000,
            use_case="familia",
            recommendation_strategy="cost_benefit",
        )
        feedback = {
            9: {
                "net_adjustment": -5,
                "stats": {"report_count": 3, "consumption_gap_percent": -15},
            }
        }
        result = next(item for item in recommend(SAMPLE_VEHICLES, profile, feedback) if item["vehicle"].id == 9)

        self.assertLessEqual(result["final_score"], 84)
        self.assertTrue(result["score_breakdown"]["guardrails"])
        self.assertEqual(result["confidence"]["level"], "moderada")

    def test_tco_over_fifty_percent_above_limit_caps_score(self):
        profile = RecommendationProfile(
            budget=300000,
            monthly_limit=1000,
            use_case="familia",
            recommendation_strategy="cost_benefit",
        )
        corolla = next(item for item in recommend(SAMPLE_VEHICLES, profile) if item["vehicle"].model == "Corolla GLi")

        self.assertGreater(corolla["tco"]["total_monthly_cost"], profile.monthly_limit * 1.5)
        self.assertLessEqual(corolla["final_score"], 49)


if __name__ == "__main__":
    unittest.main()
