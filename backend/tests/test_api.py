import copy
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient


class ApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.TemporaryDirectory()
        cls.previous_database_url = os.environ.get("DATABASE_URL")
        cls.previous_fipe_auto_refresh = os.environ.get("FIPE_AUTO_REFRESH")
        os.environ["DATABASE_URL"] = f"sqlite:///{cls.tmpdir.name}/test.db"
        os.environ["FIPE_AUTO_REFRESH"] = "false"

        from app.database import create_database
        from app.main import app

        create_database()
        cls.app = app

    @classmethod
    def tearDownClass(cls):
        from app.database import engine

        engine.dispose()
        if cls.previous_database_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = cls.previous_database_url
        if cls.previous_fipe_auto_refresh is None:
            os.environ.pop("FIPE_AUTO_REFRESH", None)
        else:
            os.environ["FIPE_AUTO_REFRESH"] = cls.previous_fipe_auto_refresh
        cls.tmpdir.cleanup()

    def client(self):
        return TestClient(self.app)

    def test_health_and_docs(self):
        with self.client() as client:
            health = client.get("/health")
            self.assertEqual(health.status_code, 200)
            self.assertEqual(health.json()["status"], "ok")
            self.assertIn("docs_url", health.json())
            self.assertEqual(health.json()["database"]["engine"], "sqlite")
            self.assertTrue(health.json()["database"]["reachable"])
            self.assertFalse(
                health.json()["database"]["migration_up_to_date"]
            )
            self.assertNotIn("url", health.json()["database"])
            self.assertGreaterEqual(health.json()["vehicles"], 30)
            self.assertEqual(health.json()["fipe"]["mapped_vehicles"], 34)
            self.assertEqual(health.json()["fipe"]["mapping_coverage_percent"], 100)
            database_health = client.get("/health/database")
            self.assertEqual(database_health.status_code, 200)
            self.assertTrue(database_health.json()["database"]["reachable"])
            self.assertFalse(
                database_health.json()["database"]["migration_up_to_date"]
            )
            self.assertNotIn("url", database_health.json()["database"])
            self.assertEqual(client.get("/docs").status_code, 200)

    def test_fipe_price_reference_is_exposed(self):
        with self.client() as client:
            city = client.get("/vehicles/14/price-reference")
            self.assertEqual(city.status_code, 200)
            self.assertEqual(city.json()["price_reference"]["code"], "014059-7")
            self.assertIn(city.json()["price_reference"]["validation_status"], {"mapped_pending_sync", "verified"})

            onix = client.get("/vehicles/1/price-reference")
            self.assertEqual(onix.status_code, 200)
            self.assertEqual(onix.json()["price_reference"]["code"], "004517-9")

            status = client.get("/prices/fipe/status")
            self.assertEqual(status.status_code, 200)
            self.assertEqual(status.json()["provider"], "API Parallelum")

    def test_login_user_admin_and_invalid(self):
        with self.client() as client:
            user_login = client.post(
                "/auth/login",
                json={"email": "usuario@sigra.local", "password": "usuario123", "role": "user"},
            )
            self.assertEqual(user_login.status_code, 200)
            self.assertEqual(user_login.json()["role"], "user")

            admin_login = client.post(
                "/auth/login",
                json={"email": "admin@sigra.local", "password": "admin123", "role": "admin"},
            )
            self.assertEqual(admin_login.status_code, 200)
            self.assertEqual(admin_login.json()["role"], "admin")

            denied_login = client.post(
                "/auth/login",
                json={"email": "admin@sigra.local", "password": "errada", "role": "admin"},
            )
            self.assertEqual(denied_login.status_code, 401)

    def test_public_demo_is_read_only_without_affecting_stateless_flows(self):
        recommendation_payload = {
            "budget": 70000,
            "monthly_limit": 2000,
            "use_case": "cidade",
        }
        financing_payload = {
            "vehicle_type": "car",
            "vehicle_price": 30000,
            "down_payment": 10000,
            "term_months": 36,
            "monthly_interest_rate_percent": 1.5,
            "upfront_fees": 0,
            "financed_fees": 0,
            "financed_insurance": 0,
            "financed_services": 0,
            "available_monthly_budget": 3000,
            "estimated_monthly_vehicle_cost": 600,
        }
        with patch.dict(os.environ, {"PUBLIC_DEMO_MODE": "true"}, clear=False):
            with self.client() as client:
                self.assertEqual(client.get("/health").status_code, 200)
                self.assertEqual(client.get("/vehicles").status_code, 200)
                recommendation = client.post(
                    "/recommendations",
                    json=recommendation_payload,
                )
                self.assertEqual(recommendation.status_code, 200)
                self.assertTrue(recommendation.json())
                financing = client.post(
                    "/financing/simulate",
                    json=financing_payload,
                )
                self.assertEqual(financing.status_code, 200, financing.text)
                self.assertEqual(
                    client.post("/motorcycles/recommendations").status_code,
                    501,
                )

                for method, path, payload in (
                    ("post", "/auth/login", {
                        "email": "usuario@sigra.local",
                        "password": "usuario123",
                        "role": "user",
                    }),
                    ("post", "/users", {
                        "name": "Publico",
                        "email": "publico@example.com",
                    }),
                    ("post", "/vehicles", {}),
                    ("post", "/expenses", {}),
                    ("patch", "/motorcycles/1", {"price": 10000}),
                    ("delete", "/motorcycles/1", None),
                ):
                    response = (
                        getattr(client, method)(path, json=payload)
                        if payload is not None
                        else getattr(client, method)(path)
                    )
                    self.assertEqual(response.status_code, 403, path)
                    self.assertEqual(
                        response.json()["detail"]["code"],
                        "demo_read_only",
                    )
                self.assertEqual(client.get("/expenses").status_code, 403)

    def test_motorcycle_crud_and_reserved_recommendation(self):
        payload = {
            "brand": "Honda",
            "model": "CB 300F Teste",
            "year": 2025,
            "price": 25000,
            "city_consumption": 30,
            "road_consumption": 34,
            "annual_maintenance_cost": 2200,
            "reliability_score": 80,
            "parts_availability_score": 85,
            "depreciation_rate": 10,
            "data_source": "demonstration",
            "data_confidence": 35,
            "specifications": {
                "engine_displacement_cc": 293.5,
                "motorcycle_category": "naked",
                "wet_weight_kg": 153,
                "seat_height_mm": 789,
                "tank_capacity_l": 13.8,
                "has_abs": True,
                "recommended_experience": "intermediate",
                "urban_score": 80,
                "road_score": 72,
                "passenger_comfort_score": 60,
                "luggage_score": 40,
            },
        }
        with self.client() as client:
            created = client.post("/motorcycles", json=payload)
            self.assertEqual(created.status_code, 201)
            motorcycle_id = created.json()["id"]
            self.assertEqual(created.json()["vehicle_type"], "motorcycle")
            self.assertNotIn("data_source", created.json())

            read = client.get(f"/motorcycles/{motorcycle_id}")
            self.assertEqual(read.status_code, 200)
            self.assertEqual(read.json()["specifications"]["motorcycle_category"], "naked")

            updated = client.patch(
                f"/motorcycles/{motorcycle_id}",
                json={"price": 25500, "specifications": {"has_abs": False}},
            )
            self.assertEqual(updated.status_code, 200)
            self.assertEqual(updated.json()["price"], 25500)
            self.assertFalse(updated.json()["specifications"]["has_abs"])

            legacy = client.post(
                "/recommendations",
                json={"budget": 70000, "monthly_limit": 2000, "use_case": "cidade"},
            )
            self.assertIsInstance(legacy.json(), list)
            self.assertTrue(all(item["vehicle"]["vehicle_type"] == "car" for item in legacy.json()))
            envelope = client.post(
                "/recommendations?envelope=true",
                json={"budget": 70000, "monthly_limit": 2000, "use_case": "cidade"},
            ).json()
            self.assertEqual(envelope["vehicle_type"], "car")
            self.assertTrue(all(item["vehicle"]["vehicle_type"] == "car" for item in envelope["recommendations"]))

            reserved = client.post("/motorcycles/recommendations")
            self.assertEqual(reserved.status_code, 501)
            self.assertIn("ainda não foi implementado", reserved.json()["detail"])

            deleted = client.delete(f"/motorcycles/{motorcycle_id}")
            self.assertEqual(deleted.status_code, 204)
            self.assertEqual(client.get(f"/motorcycles/{motorcycle_id}").status_code, 404)
            self.assertEqual(client.patch("/motorcycles/999999", json={"price": 20000}).status_code, 404)
            self.assertEqual(client.delete("/motorcycles/999999").status_code, 404)

    def test_invalid_motorcycle_payloads(self):
        base = {
            "brand": "Honda", "model": "Teste", "year": 2025, "price": 25000,
            "city_consumption": 30, "road_consumption": 34, "annual_maintenance_cost": 2200,
            "reliability_score": 80, "parts_availability_score": 85, "depreciation_rate": 10,
            "data_source": "demonstration", "data_confidence": 35,
            "specifications": {
                "engine_displacement_cc": 300, "motorcycle_category": "naked", "wet_weight_kg": 150,
                "seat_height_mm": 790, "tank_capacity_l": 14, "has_abs": True,
                "recommended_experience": "intermediate", "urban_score": 80, "road_score": 70,
                "passenger_comfort_score": 60, "luggage_score": 40,
            },
        }
        cases = [
            {"specifications": {**base["specifications"], "motorcycle_category": "invalida"}},
            {"specifications": {**base["specifications"], "recommended_experience": "invalida"}},
            {"specifications": {**base["specifications"], "engine_displacement_cc": 0}},
            {"specifications": {**base["specifications"], "wet_weight_kg": -1}},
            {"specifications": {**base["specifications"], "seat_height_mm": 100}},
            {"specifications": {**base["specifications"], "tank_capacity_l": 0}},
            {"reliability_score": 101},
        ]
        with self.client() as client:
            for payload_update in cases:
                with self.subTest(payload_update=payload_update):
                    response = client.post("/motorcycles", json={**base, **payload_update})
                    self.assertEqual(response.status_code, 422)

    def test_invalid_recommendation_strategy_and_use_case_return_422(self):
        with self.client() as client:
            invalid_strategy = client.post(
                "/recommendations",
                json={
                    "budget": 70000,
                    "monthly_limit": 1200,
                    "use_case": "cidade",
                    "recommendation_strategy": "qualquer_coisa",
                },
            )
            self.assertEqual(invalid_strategy.status_code, 422)
            self.assertEqual(invalid_strategy.json()["detail"][0]["loc"][-1], "recommendation_strategy")
            self.assertEqual(invalid_strategy.json()["detail"][0]["input"], "qualquer_coisa")

            invalid_use = client.post(
                "/recommendations",
                json={"budget": 70000, "monthly_limit": 1200, "use_case": "qualquer_uso"},
            )
            self.assertEqual(invalid_use.status_code, 422)
            self.assertEqual(invalid_use.json()["detail"][0]["loc"][-1], "use_case")

            invalid_type = client.post(
                "/recommendations",
                json={
                    "vehicle_type": "motorcycle",
                    "budget": 70000,
                    "monthly_limit": 1200,
                    "use_case": "cidade",
                },
            )
            self.assertEqual(invalid_type.status_code, 422)
            self.assertEqual(invalid_type.json()["detail"][0]["loc"][-1], "vehicle_type")

            invalid_vehicle_category = client.post(
                "/vehicles",
                json={
                    "brand": "Marca", "model": "Modelo", "year": 2025, "price": 50000,
                    "fuel_efficiency_km_l": 12, "annual_maintenance_cost": 2000,
                    "reliability_score": 80, "parts_availability_score": 80,
                    "depreciation_rate": 10, "category": "categoria_livre",
                    "use_cases": ["cidade"],
                },
            )
            self.assertEqual(invalid_vehicle_category.status_code, 422)

            invalid_vehicle_use = client.post(
                "/vehicles",
                json={
                    "brand": "Marca", "model": "Modelo", "year": 2025, "price": 50000,
                    "fuel_efficiency_km_l": 12, "annual_maintenance_cost": 2000,
                    "reliability_score": 80, "parts_availability_score": 80,
                    "depreciation_rate": 10, "category": "compact",
                    "use_cases": ["qualquer_uso"],
                },
            )
            self.assertEqual(invalid_vehicle_use.status_code, 422)

            valid = client.post(
                "/recommendations",
                json={
                    "budget": 70000,
                    "monthly_limit": 1200,
                    "use_case": "cidade",
                    "recommendation_strategy": "cost_benefit",
                },
            )
            self.assertEqual(valid.status_code, 200)
            self.assertTrue(valid.json())

    def test_automotive_queries_explicitly_exclude_non_car_rows(self):
        from sqlalchemy import text

        from app.database import SessionLocal

        with SessionLocal() as db:
            for vehicle_id, vehicle_type in ((9001, "motorcycle"), (9002, "unknown")):
                db.execute(
                    text(
                        """
                        INSERT INTO vehicles (
                            id, brand, model, year, price, fuel_efficiency_km_l,
                            annual_maintenance_cost, reliability_score,
                            parts_availability_score, depreciation_rate, use_cases,
                            chronic_issues, image_url, category, segment_level,
                            comfort_score, space_score, safety_score, urban_score,
                            road_score, family_score, app_score, vehicle_type
                        ) VALUES (
                            :id, 'Registro', 'Invalido', 2025, 10000, 30,
                            100, 100, 100, 1, 'cidade', '', '', 'compact', 1,
                            100, 100, 100, 100, 100, 100, 100, :vehicle_type
                        )
                        """
                    ),
                    {"id": vehicle_id, "vehicle_type": vehicle_type},
                )
            db.commit()

        try:
            with self.client() as client:
                catalog_ids = {item["id"] for item in client.get("/vehicles").json()}
                ranking_ids = {
                    item["vehicle"]["id"]
                    for item in client.post(
                        "/recommendations",
                        json={"budget": 70000, "monthly_limit": 1200, "use_case": "cidade"},
                    ).json()
                }
                self.assertFalse({9001, 9002} & catalog_ids)
                self.assertFalse({9001, 9002} & ranking_ids)
        finally:
            with SessionLocal() as db:
                db.execute(text("DELETE FROM vehicles WHERE id IN (9001, 9002)"))
                db.commit()

    def test_motorcycle_traceability_and_incomplete_record_repair(self):
        from app import models
        from app.database import SessionLocal

        with self.client() as client:
            official_payload = {
                "brand": "Honda", "model": "Fonte Oficial", "year": 2025, "price": 25000,
                "city_consumption": 30, "road_consumption": 34, "annual_maintenance_cost": 2200,
                "reliability_score": 80, "parts_availability_score": 85, "depreciation_rate": 10,
                "data_source": "official", "data_confidence": 90,
                "source_name": "Fabricante Exemplo", "source_reference": "Ficha 2025",
                "source_url": "https://example.com/ficha", "source_collected_at": "2026-07-21T10:00:00-03:00",
                "source_reference_date": "2026-07-01", "last_verified_at": "2026-07-21T11:00:00-03:00",
                "specifications": {
                    "engine_displacement_cc": 300, "motorcycle_category": "naked", "wet_weight_kg": 150,
                    "seat_height_mm": 790, "tank_capacity_l": 14, "has_abs": True,
                    "recommended_experience": "intermediate", "urban_score": 80, "road_score": 70,
                    "passenger_comfort_score": 60, "luggage_score": 40,
                },
            }
            created = client.post("/motorcycles", json=official_payload)
            self.assertEqual(created.status_code, 201)
            self.assertNotIn("source_name", created.json())
            legacy_created = client.get(
                f"/motorcycles/{created.json()['id']}?include_legacy=true"
            )
            self.assertEqual(
                legacy_created.json()["legacy_data"]["fields"]["source_name"],
                "Fabricante Exemplo",
            )
            self.assertEqual(
                legacy_created.json()["legacy_data"]["fields"]["source_reference_date"],
                "2026-07-01",
            )
            client.delete(f"/motorcycles/{created.json()['id']}")

            missing_source = client.post(
                "/motorcycles",
                json={**official_payload, "source_name": None, "source_reference": None, "source_url": None},
            )
            self.assertEqual(missing_source.status_code, 422)
            invalid_url = client.post("/motorcycles", json={**official_payload, "source_url": "nao-e-url"})
            self.assertEqual(invalid_url.status_code, 422)
            invalid_date = client.post("/motorcycles", json={**official_payload, "source_collected_at": "ontem"})
            self.assertEqual(invalid_date.status_code, 422)

        with SessionLocal() as db:
            incomplete = models.Motorcycle(
                brand="Moto", model="Incompleta", year=2024, price=18000,
                city_consumption=30, road_consumption=33, annual_maintenance_cost=1800,
                reliability_score=70, parts_availability_score=75, depreciation_rate=10,
                data_source="demonstration", data_confidence=20, vehicle_type="motorcycle",
            )
            db.add(incomplete)
            db.commit()
            db.refresh(incomplete)
            incomplete_id = incomplete.id

        with self.client() as client:
            catalog = client.get("/motorcycles?envelope=true")
            self.assertEqual(catalog.status_code, 200)
            self.assertGreaterEqual(catalog.json()["invalid_records"], 1)
            read = client.get(f"/motorcycles/{incomplete_id}")
            self.assertEqual(read.status_code, 409)
            self.assertEqual(read.json()["detail"]["code"], "motorcycle_record_invalid")
            self.assertIn(
                "specifications",
                {issue["field"] for issue in read.json()["detail"]["issues"]},
            )

            repair = client.patch(
                f"/motorcycles/{incomplete_id}",
                json={
                    "specifications": {
                        "engine_displacement_cc": 160, "motorcycle_category": "street", "wet_weight_kg": 130,
                        "seat_height_mm": 780, "tank_capacity_l": 12, "has_abs": True,
                        "recommended_experience": "beginner", "urban_score": 80, "road_score": 60,
                        "passenger_comfort_score": 50, "luggage_score": 30,
                    }
                },
            )
            self.assertEqual(repair.status_code, 200)
            self.assertEqual(repair.json()["record_status"], "complete")
            self.assertEqual(client.delete(f"/motorcycles/{incomplete_id}").status_code, 204)

    def test_motorcycle_resilient_listing_pagination_repair_and_invalid_delete(self):
        from sqlalchemy import text

        from app.database import SessionLocal
        from backend.tests.test_motorcycles import VALID_MOTORCYCLE

        created_ids = []
        with self.client() as client:
            for model in ("A Auditoria", "B Auditoria", "C Auditoria"):
                payload = copy.deepcopy(VALID_MOTORCYCLE)
                payload["model"] = model
                created = client.post("/motorcycles", json=payload)
                self.assertEqual(created.status_code, 201)
                created_ids.append(created.json()["id"])

        with SessionLocal() as db:
            db.execute(text("PRAGMA ignore_check_constraints = ON"))
            db.execute(
                text(
                    "UPDATE motorcycles SET data_confidence = 150, source_url = 'fonte-invalida', "
                    "source_collected_at = 'ontem' WHERE id = :id"
                ),
                {"id": created_ids[1]},
            )
            db.execute(
                text(
                    "UPDATE motorcycle_objective_specifications SET motorcycle_category = 'livre' "
                    "WHERE motorcycle_id = :id"
                ),
                {"id": created_ids[1]},
            )
            db.execute(
                text("UPDATE motorcycles SET data_source = 'desconhecida' WHERE id = :id"),
                {"id": created_ids[2]},
            )
            db.execute(text("PRAGMA ignore_check_constraints = OFF"))
            db.commit()

        try:
            with self.client() as client:
                envelope = client.get("/motorcycles?envelope=true")
                self.assertEqual(envelope.status_code, 200)
                data = envelope.json()
                self.assertEqual(data["total_found"], 3)
                self.assertEqual(data["returned"], 3)
                self.assertEqual(data["valid_records"], 1)
                self.assertEqual(data["invalid_records"], 2)
                self.assertEqual(len(data["motorcycles"]), 1)
                self.assertEqual(len(data["invalid_record_summary"]), 2)

                first_page = client.get("/motorcycles?envelope=true&limit=1")
                self.assertEqual(first_page.json()["total_found"], 3)
                self.assertEqual(first_page.json()["returned"], 1)
                self.assertEqual(first_page.json()["valid_records"], 1)

                invalid_page = client.get("/motorcycles?envelope=true&limit=1&offset=1")
                self.assertEqual(invalid_page.json()["total_found"], 3)
                self.assertEqual(invalid_page.json()["returned"], 1)
                self.assertEqual(invalid_page.json()["valid_records"], 0)
                self.assertEqual(invalid_page.json()["invalid_records"], 1)
                self.assertEqual(invalid_page.json()["motorcycles"], [])

                legacy = client.get("/motorcycles")
                self.assertEqual(legacy.status_code, 200)
                self.assertEqual([item["id"] for item in legacy.json()], [created_ids[0]])

                invalid_read = client.get(f"/motorcycles/{created_ids[1]}")
                self.assertEqual(invalid_read.status_code, 409)
                self.assertEqual(invalid_read.json()["detail"]["code"], "motorcycle_record_invalid")

                repaired = client.patch(
                    f"/motorcycles/{created_ids[1]}?include_legacy=true",
                    json={
                        "data_confidence": 50,
                        "source_url": None,
                        "source_collected_at": None,
                        "specifications": {"motorcycle_category": "naked", "urban_score": 80},
                    },
                )
                self.assertEqual(repaired.status_code, 200)
                self.assertEqual(
                    repaired.json()["legacy_data"]["fields"]["data_confidence"],
                    50,
                )

                self.assertEqual(client.delete(f"/motorcycles/{created_ids[2]}").status_code, 204)
                created_ids.remove(created_ids[2])
        finally:
            with self.client() as client:
                for motorcycle_id in created_ids:
                    client.delete(f"/motorcycles/{motorcycle_id}")
                empty = client.get("/motorcycles?envelope=true")
                self.assertEqual(empty.status_code, 200)
                self.assertEqual(empty.json()["total_found"], 0)
                self.assertEqual(empty.json()["returned"], 0)

    def test_vehicle_base_and_recommendations(self):
        with self.client() as client:
            vehicles = client.get("/vehicles").json()
            self.assertGreaterEqual(len(vehicles), 30)

            city_response = client.post(
                "/recommendations",
                json={"budget": 70000, "monthly_limit": 1200, "use_case": "cidade"},
            )
            city_response_text = city_response.text
            city = city_response.json()
            self.assertGreaterEqual(len(city), 30)
            self.assertIn("recommendation_status", city[0])
            self.assertIn("score", city[0])
            self.assertIn("explanations", city[0])
            self.assertIn("parts_catalog", city[0])
            self.assertIn("parts_feedback", city[0])
            self.assertIn("category_awards", city[0])
            self.assertIn("tco", city[0])
            self.assertIn("total_monthly_cost", city[0]["tco"])
            self.assertIn("score_components", city[0])
            self.assertIn("financial_score", city[0]["score_components"])
            self.assertIn("purchase_intent_score", city[0]["score_components"])
            self.assertIn("segment_score", city[0]["score_components"])
            self.assertEqual(city[0]["recommendation_strategy"], "cost_benefit")
            self.assertIn("recommendation_summary", city[0])
            self.assertIn("score_breakdown", city[0])
            self.assertIn("confidence", city[0])
            self.assertEqual(city[0]["score_breakdown"]["method"], "MCDA ponderada com ajustes limitados e travas de coerencia")
            mojibake_markers = (chr(0x00C3), chr(0x00C2), chr(0xFFFD))
            self.assertFalse(any(marker in city_response_text for marker in mojibake_markers))

            road = client.post(
                "/recommendations",
                json={
                    "budget": 90000,
                    "monthly_limit": 1600,
                    "use_case": "estrada",
                    "monthly_mileage": 2500,
                    "fuel_price": 6,
                },
            ).json()
            best_choices = [item for item in road if item["is_best_choice"]]
            if any(item["score_components"]["fully_viable"] for item in road):
                self.assertEqual(len(best_choices), 1)
                self.assertTrue(best_choices[0]["score_components"]["fully_viable"])
            else:
                self.assertEqual(best_choices, [])
                self.assertTrue(road[0]["is_best_available_reference"])
            self.assertNotEqual(city[0]["vehicle"]["id"], road[0]["vehicle"]["id"])

    def test_multifactor_recommendation_is_explicit_stateless_and_sanitized(self):
        from app.integrated_gold.simulation_service import (
            VehicleCostSimulationUnavailableError,
        )

        payload = {
            "budget": 250000,
            "monthly_limit": 3500,
            "use_case": "cidade",
            "multifactor_profile": {
                "enabled": True,
                "scenario": {
                    "monthly_distance_km": "1250.00",
                    "city_percentage": "60.00",
                    "highway_percentage": "40.00",
                    "state_code": "SP",
                    "municipality": "Sao Paulo",
                    "reference_week_start": "2026-08-17",
                    "fuel_strategy": "gasoline_c_common",
                    "horizon_months": 18,
                },
                "weights": {
                    "total_cost": "25",
                    "usage_fit": "20",
                    "comfort": "10",
                    "safety": "15",
                    "performance": "10",
                    "efficiency": "10",
                    "legacy_quality": "10",
                },
            },
        }
        service = MagicMock()
        service.simulate.return_value = SimpleNamespace(fingerprint="f" * 64)

        def fake_ranking(items, simulation, weights, *, gold_identities, catalog_references):
            self.assertEqual(simulation.fingerprint, "f" * 64)
            self.assertEqual(sum(weights.values()), 100)
            self.assertEqual(gold_identities, [])
            self.assertEqual(set(catalog_references), {item["vehicle"]["id"] for item in items})
            output = copy.deepcopy(items)
            output[0]["multifactor"] = {"status": "ranked", "position": 1}
            return output

        with self.client() as client, patch(
            "app.main.simulation_service_for_session",
            return_value=service,
        ), patch("app.main.GoldRecommendationIdentityReader.recommendation_identities", return_value=[]), patch(
            "app.main.apply_multifactor_ranking", side_effect=fake_ranking
        ):
            response = client.post("/recommendations?envelope=true", json=payload)
            self.assertEqual(response.status_code, 200, response.text)
            data = response.json()
            self.assertTrue(data["multifactor_profile"]["enabled"])
            self.assertTrue(data["multifactor_profile"]["stateless"])
            self.assertTrue(data["multifactor_profile"]["active_gold_unchanged"])
            self.assertEqual(
                data["multifactor_profile"]["simulation_fingerprint"],
                "f" * 64,
            )
            service.simulate.assert_called_once()
            self.assertNotIn("allow_budget_above_200k", payload["multifactor_profile"])

        unavailable_service = MagicMock()
        unavailable_service.simulate.side_effect = VehicleCostSimulationUnavailableError(
            "internal storage detail"
        )
        with self.client() as client, patch(
            "app.main.simulation_service_for_session",
            return_value=unavailable_service,
        ):
            unavailable = client.post("/recommendations?envelope=true", json=payload)
            self.assertEqual(unavailable.status_code, 503)
            self.assertNotIn("internal storage detail", unavailable.text)

    def test_multifactor_identity_boundary_returns_real_ranking_and_reconciled_counts(self):
        from tests.test_multifactor_recommendation import (
            _batch, _etios_identity, _etios_reference, _etios_result,
        )
        from app.integrated_gold.repository import IntegratedGoldStorageError

        body = {
            "budget": 100000, "monthly_limit": 1750, "use_case": "cidade",
            "multifactor_profile": {"enabled": True,
                "scenario": {"monthly_distance_km": "1250.00", "city_percentage": "60.00",
                    "highway_percentage": "40.00", "state_code": "SP", "municipality": "Sao Paulo",
                    "reference_week_start": "2026-08-17", "fuel_strategy": "gasoline_c_common", "horizon_months": 18},
                "weights": {"total_cost": "25", "usage_fit": "20", "comfort": "10", "safety": "15",
                    "performance": "10", "efficiency": "10", "legacy_quality": "10"}},
        }
        service = MagicMock()
        service.simulate.return_value = _batch(_etios_result())
        references = {10: _etios_reference(), 23: {"code": "001486-9", "year_code": "2018-5",
                                               "model": "UNO DRIVE 1.0 Flex 6V 5p"}}
        with self.client() as client, patch("app.main.simulation_service_for_session", return_value=service), patch(
            "app.main.GoldRecommendationIdentityReader.recommendation_identities", return_value=[_etios_identity()]
        ) as reader, patch("app.main.price_metadata", side_effect=lambda key: references.get(key, {})):
            legacy_body = {key: value for key, value in body.items() if key != "multifactor_profile"}
            baseline = client.post("/recommendations?envelope=true", json=legacy_body).json()
            reader.assert_not_called()
            response = client.post("/recommendations?envelope=true", json=body)
            self.assertEqual(response.status_code, 200, response.text)
            data = response.json()
            items = {item["vehicle"]["id"]: item for item in data["recommendations"]}
            originals = {item["vehicle"]["id"]: item for item in baseline["recommendations"]}
            self.assertEqual(items[10]["multifactor"]["status"], "ranked")
            self.assertEqual(items[10]["multifactor"]["identity_diagnostic"]["match_method"], "explicit_mapping")
            self.assertEqual(items[23]["multifactor"]["reason_code"], "GOLD_IDENTITY_NOT_FOUND")
            self.assertEqual(items[23]["multifactor"]["identity_diagnostic"]["rejection_reason"], "coverage_absent")
            self.assertIsNone(items[23]["multifactor"]["final_score"])
            self.assertEqual(data["multifactor_profile"]["ranked_count"], 1)
            self.assertEqual(data["multifactor_profile"]["unavailable_count"], len(items) - 1)
            for key, item in items.items():
                self.assertEqual(item["vehicle"], originals[key]["vehicle"])
                self.assertEqual(item["tco"], originals[key]["tco"])
            # An empty eligible lineage cannot silently fall back to names or IDs.
            reader.return_value = []
            no_coverage = client.post("/recommendations?envelope=true", json=body).json()
            self.assertEqual(no_coverage["multifactor_profile"]["ranked_count"], 0)
            self.assertEqual(no_coverage["multifactor_profile"]["unavailable_count"], len(items))
            self.assertEqual([item["vehicle"]["id"] for item in no_coverage["recommendations"]],
                             [item["vehicle"]["id"] for item in baseline["recommendations"]])
            reader.side_effect = IntegratedGoldStorageError("internal identity storage detail")
            unavailable = client.post("/recommendations?envelope=true", json=body)
            self.assertEqual(unavailable.status_code, 503)
            self.assertNotIn("internal identity storage detail", unavailable.text)

    def test_recommendations_without_viable_options_still_return_comparative_list(self):
        with self.client() as client:
            response = client.post(
                "/recommendations",
                json={
                    "budget": 200000,
                    "monthly_limit": 800,
                    "use_case": "cidade",
                    "recommendation_strategy": "best_within_budget",
                },
            )
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertGreaterEqual(len(data), 30)
            summary = data[0]["recommendation_summary"]
            self.assertFalse(summary["has_viable_options"])
            self.assertEqual(summary["viable_count"], 0)
            self.assertGreater(summary["suggested_monthly_limit"], 800)
            self.assertIn("limite mensal", summary["message"])

    def test_recommendation_envelope_exposes_processing_and_versions(self):
        with self.client() as client:
            response = client.post(
                "/recommendations?envelope=true",
                json={
                    "budget": 200000,
                    "monthly_limit": 3500,
                    "use_case": "cidade",
                    "monthly_mileage": 1000,
                    "fuel_price": 6,
                    "recommendation_strategy": "cost_benefit",
                },
            )
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(data["algorithm_version"], "2.1.2")
            self.assertEqual(data["weights_version"], "cars-v1")
            self.assertEqual(data["vehicle_type"], "car")
            self.assertIsNone(data["data_reference"])
            self.assertIn("generated_at", data)
            self.assertEqual(data["vehicle_processing"]["total_found"], 34)
            self.assertEqual(data["vehicle_processing"]["evaluated"], 34)
            self.assertEqual(data["vehicle_processing"]["ignored"], 0)
            self.assertTrue(data["has_viable_options"])
            self.assertEqual(sum(item["is_best_choice"] for item in data["recommendations"]), 1)

    def test_no_viable_option_has_only_comparative_reference(self):
        with self.client() as client:
            response = client.post(
                "/recommendations?envelope=true",
                json={
                    "budget": 1000,
                    "monthly_limit": 100,
                    "use_case": "cidade",
                    "monthly_mileage": 1000,
                    "fuel_price": 6,
                    "recommendation_strategy": "cost_benefit",
                },
            )
            data = response.json()
            items = data["recommendations"]
            self.assertFalse(data["has_viable_options"])
            self.assertFalse(any(item["is_best_choice"] for item in items))
            self.assertTrue(items[0]["is_best_available_reference"])
            self.assertEqual(sum(item["is_best_available_reference"] for item in items), 1)

    def test_online_search_and_parts_analysis(self):
        with self.client() as client:
            self.assertGreater(len(client.get("/online-car-search?query=corolla").json()), 0)

            parts = client.get("/parts")
            self.assertEqual(parts.status_code, 200)
            self.assertGreaterEqual(len(parts.json()), 10)

            suppliers = client.get("/suppliers")
            self.assertEqual(suppliers.status_code, 200)
            self.assertGreaterEqual(len(suppliers.json()), 4)

            analysis = client.get("/vehicles/1/parts-analysis")
            self.assertEqual(analysis.status_code, 200)
            self.assertIn("maintenance_index", analysis.json())
            self.assertIn("parts", analysis.json())

            maintenance_index = client.get("/vehicles/1/maintenance-index")
            self.assertEqual(maintenance_index.status_code, 200)
            self.assertGreater(maintenance_index.json()["maintenance_index"], 0)

            price_stats = client.get("/parts/1/prices?vehicle_id=1")
            self.assertEqual(price_stats.status_code, 200)
            self.assertIn("average_price", price_stats.json())
            self.assertIn("variation_percent", price_stats.json())

            high_variation = client.get("/parts/3/prices?vehicle_id=1")
            self.assertEqual(high_variation.status_code, 200)
            self.assertGreater(high_variation.json()["variation_percent"], 100)
            self.assertGreater(len(high_variation.json()["alerts"]), 0)

            fallback = client.get("/vehicles/12/parts-analysis")
            self.assertEqual(fallback.status_code, 200)
            self.assertEqual(fallback.json()["parts"], [])

    def test_user_vehicle_history_problem_and_consumption(self):
        with self.client() as client:
            user_vehicles = client.get("/user-vehicles?user_id=1")
            self.assertEqual(user_vehicles.status_code, 200)
            self.assertGreaterEqual(len(user_vehicles.json()), 1)
            user_vehicle_id = user_vehicles.json()[0]["id"]

            history = client.get(f"/user-vehicles/{user_vehicle_id}/history")
            self.assertEqual(history.status_code, 200)
            self.assertIn("alerts", history.json())
            self.assertIn("model_statistics", history.json())

            report = client.post(
                "/vehicle-reports",
                json={
                    "user_vehicle_id": user_vehicle_id,
                    "problem_category": "suspensao",
                    "description": "Ruido na suspensao em teste automatizado.",
                    "occurrence_km": 99000,
                    "repair_cost": 1000,
                    "severity": "media",
                    "occurrence_date": "2026-06-08",
                    "resolved": True,
                    "notes": "Registro de teste",
                },
            )
            self.assertEqual(report.status_code, 201)

            consumption = client.post(
                "/fuel-consumption-reports",
                json={
                    "user_vehicle_id": user_vehicle_id,
                    "km_per_liter": 11.2,
                    "usage_type": "urbano",
                    "fuel_type": "flex",
                    "notes": "Registro de teste",
                },
            )
            self.assertEqual(consumption.status_code, 201)
            self.assertGreaterEqual(len(client.get("/vehicle-statistics").json()), 30)

    def test_expense_valid_and_invalid_cases(self):
        with self.client() as client:
            vehicle_id = client.get("/vehicles").json()[0]["id"]
            expense = client.post(
                "/expenses",
                json={
                    "user_id": 1,
                    "vehicle_id": vehicle_id,
                    "category": "combustivel",
                    "amount": 250,
                    "expense_date": "2026-06-08",
                    "description": "Abastecimento",
                },
            )
            self.assertEqual(expense.status_code, 201)
            self.assertEqual(client.get("/reports/financial-summary").json()["total_expenses"], 250)

            invalid_vehicle = client.post(
                "/expenses",
                json={
                    "user_id": 1,
                    "vehicle_id": 9999,
                    "category": "combustivel",
                    "amount": 100,
                    "expense_date": "2026-06-08",
                    "description": "Veiculo inexistente",
                },
            )
            self.assertEqual(invalid_vehicle.status_code, 404)

            invalid_user = client.post(
                "/expenses",
                json={
                    "user_id": 9999,
                    "vehicle_id": vehicle_id,
                    "category": "combustivel",
                    "amount": 100,
                    "expense_date": "2026-06-08",
                    "description": "Usuario inexistente",
                },
            )
            self.assertEqual(invalid_user.status_code, 404)

    def test_motorcycle_v020_sources_metrics_eligibility_and_reserved_endpoint(self):
        from backend.tests.test_motorcycle_spec_v1 import objective_payload

        with self.client() as client:
            payload = objective_payload(source="demonstration")
            payload.pop("source_reference", None)
            created = client.post("/motorcycles", json=payload)
            self.assertEqual(created.status_code, 201, created.text)
            motorcycle_id = created.json()["id"]
            self.assertEqual(created.json()["derived_metrics"], [])
            self.assertEqual(created.json()["eligibility_status"], "demonstration_only")
            self.assertNotIn("score", created.json())
            self.assertNotIn("ranking", created.json())

            source_payload = {
                "data_group": "identity",
                "source_type": "official",
                "source_name": "Fabricante Exemplo",
                "source_reference": "Ficha do modelo",
                "confidence": 80,
                "is_primary": True,
            }
            source = client.post(f"/motorcycles/{motorcycle_id}/sources", json=source_payload)
            self.assertEqual(source.status_code, 201, source.text)
            duplicate_primary = client.post(f"/motorcycles/{motorcycle_id}/sources", json=source_payload)
            self.assertEqual(duplicate_primary.status_code, 409)
            second_group = client.post(
                f"/motorcycles/{motorcycle_id}/sources",
                json={
                    "data_group": "technical_specs",
                    "source_type": "estimated",
                    "source_reference": "Coleta técnica documentada",
                    "confidence": 65,
                    "is_primary": True,
                },
            )
            self.assertEqual(second_group.status_code, 201, second_group.text)
            self.assertEqual(len(client.get(f"/motorcycles/{motorcycle_id}/sources").json()), 2)

            updated_source = client.patch(
                f"/motorcycles/{motorcycle_id}/sources/{source.json()['id']}",
                json={"confidence": 85},
            )
            self.assertEqual(updated_source.status_code, 200, updated_source.text)
            self.assertEqual(updated_source.json()["confidence"], 85)

            metric_payload = {
                "metric_name": "urban_score",
                "metric_value": 75,
                "metric_status": "demonstration",
                "method_version": "demonstration-v0",
            }
            metric = client.post(f"/motorcycles/{motorcycle_id}/derived-metrics", json=metric_payload)
            self.assertEqual(metric.status_code, 201, metric.text)
            self.assertEqual(
                client.post(f"/motorcycles/{motorcycle_id}/derived-metrics", json=metric_payload).status_code,
                409,
            )
            self.assertEqual(len(client.get(f"/motorcycles/{motorcycle_id}/derived-metrics").json()), 1)

            reserved = client.post("/motorcycles/recommendations")
            self.assertEqual(reserved.status_code, 501)
            self.assertEqual(reserved.json()["module_version"], "0.3.1")
            self.assertIsNone(reserved.json()["algorithm_version"])
            self.assertIsNone(reserved.json()["weights_version"])

            self.assertEqual(
                client.delete(f"/motorcycles/{motorcycle_id}/sources/{source.json()['id']}").status_code,
                204,
            )
            self.assertEqual(client.delete(f"/motorcycles/{motorcycle_id}").status_code, 204)

    def test_financing_metadata_and_manual_simulation(self):
        payload = {
            "vehicle_type": "car",
            "vehicle_price": 30000,
            "down_payment": 10000,
            "term_months": 36,
            "monthly_interest_rate_percent": 1.8,
            "upfront_fees": 300,
            "financed_fees": 500,
            "financed_insurance": 100,
            "financed_services": 50,
            "desired_max_installment": 1000,
            "available_monthly_budget": 1800,
            "estimated_monthly_vehicle_cost": 620,
        }
        with self.client() as client:
            metadata = client.get("/financing/metadata")
            self.assertEqual(metadata.status_code, 200)
            self.assertEqual(metadata.json()["module_version"], "1.0.3")
            self.assertEqual(metadata.json()["calculation_method_version"], "price-v1.2")
            self.assertFalse(metadata.json()["bank_integration"])
            self.assertFalse(metadata.json()["credit_approval_guarantee"])

            response = client.post("/financing/simulate", json=payload)
            self.assertEqual(response.status_code, 200, response.text)
            result = response.json()
            self.assertEqual(result["price_source"], "manual")
            self.assertEqual(result["vehicle_price"], 30000)
            self.assertEqual(result["price_used"], 30000)
            self.assertEqual(result["manual_price"], 30000)
            self.assertIsNone(result["catalog_price"])
            self.assertIsNone(result["negotiated_price"])
            self.assertEqual(result["financed_additional_costs"], 650)
            self.assertGreaterEqual(
                result["maximum_installment_in_schedule"], result["regular_installment"]
            )
            self.assertIn("aprovação de crédito", result["disclaimer"])

    def test_financing_integrates_car_motorcycle_and_negotiated_price(self):
        from backend.tests.test_motorcycle_spec_v1 import objective_payload

        base = {
            "down_payment": 10000,
            "term_months": 24,
            "monthly_interest_rate_percent": 1.5,
            "upfront_fees": 0,
            "financed_fees": 0,
            "financed_insurance": 0,
            "financed_services": 0,
            "desired_max_installment": 5000,
            "available_monthly_budget": 6000,
            "estimated_monthly_vehicle_cost": 500,
        }
        with self.client() as client:
            car = client.post(
                "/financing/simulate",
                json={**base, "vehicle_type": "car", "vehicle_id": 1, "negotiated_price": 60000},
            )
            self.assertEqual(car.status_code, 200, car.text)
            self.assertEqual(car.json()["vehicle"]["vehicle_type"], "car")
            self.assertEqual(car.json()["vehicle_price"], 60000)
            self.assertEqual(car.json()["price_source"], "negotiated")
            self.assertIsNotNone(car.json()["catalog_price"])
            self.assertEqual(car.json()["negotiated_price"], 60000)
            self.assertEqual(car.json()["price_used"], 60000)

            catalog = client.post(
                "/financing/simulate",
                json={**base, "vehicle_type": "car", "vehicle_id": 1},
            )
            self.assertEqual(catalog.status_code, 200, catalog.text)
            self.assertEqual(catalog.json()["price_source"], "catalog")
            self.assertEqual(catalog.json()["price_used"], catalog.json()["catalog_price"])
            self.assertIsNone(catalog.json()["manual_price"])

            created_motorcycle = client.post(
                "/motorcycles", json=objective_payload(source="demonstration")
            )
            self.assertEqual(created_motorcycle.status_code, 201, created_motorcycle.text)
            motorcycle_id = created_motorcycle.json()["id"]
            motorcycle = client.post(
                "/financing/simulate",
                json={
                    **base,
                    "vehicle_type": "motorcycle",
                    "vehicle_id": motorcycle_id,
                    "down_payment": 5000,
                },
            )
            self.assertEqual(motorcycle.status_code, 200, motorcycle.text)
            self.assertEqual(motorcycle.json()["vehicle"]["vehicle_type"], "motorcycle")
            self.assertTrue(motorcycle.json()["is_demonstration_data"])

            mismatch = client.post(
                "/financing/simulate",
                json={**base, "vehicle_type": "motorcycle", "vehicle_id": 34},
            )
            self.assertEqual(mismatch.status_code, 422)
            self.assertNotIn("Traceback", mismatch.text)
            self.assertEqual(client.delete(f"/motorcycles/{motorcycle_id}").status_code, 204)

    def test_financing_reverse_compare_validation_and_motorcycle_501(self):
        reverse_payload = {
            "vehicle_type": "car",
            "down_payment": 8000,
            "maximum_installment": 900,
            "term_months": 36,
            "monthly_interest_rate_percent": 1.8,
            "upfront_fees": 0,
            "financed_fees": 500,
            "financed_insurance": 0,
            "financed_services": 0,
            "available_monthly_budget": 1600,
            "estimated_monthly_vehicle_cost": 600,
        }
        scenario = {
            "vehicle_type": "car",
            "vehicle_price": 30000,
            "down_payment": 10000,
            "term_months": 36,
            "monthly_interest_rate_percent": 1.8,
            "upfront_fees": 0,
            "financed_fees": 500,
            "financed_insurance": 0,
            "financed_services": 0,
            "desired_max_installment": 900,
            "available_monthly_budget": 1600,
            "estimated_monthly_vehicle_cost": 620,
            "offer_name": "A",
        }
        with self.client() as client:
            reverse = client.post("/financing/reverse-simulate", json=reverse_payload)
            self.assertEqual(reverse.status_code, 200, reverse.text)
            self.assertLessEqual(reverse.json()["maximum_installment_in_schedule"], 900)

            insufficient = client.post(
                "/financing/reverse-simulate",
                json={**reverse_payload, "maximum_installment": 10, "financed_fees": 1000},
            )
            self.assertEqual(insufficient.status_code, 200, insufficient.text)
            insufficient_result = insufficient.json()
            self.assertEqual(
                insufficient_result["financing_status"],
                "insufficient_for_financed_costs",
            )
            self.assertEqual(insufficient_result["available_vehicle_principal"], 0)
            self.assertEqual(insufficient_result["total_financed_amount"], 0)
            self.assertGreater(
                insufficient_result["required_financed_additional_costs"],
                insufficient_result["maximum_financed_amount"],
            )

            comparison = client.post(
                "/financing/compare",
                json={"scenarios": [scenario, {**scenario, "offer_name": "B", "term_months": 48}]},
            )
            self.assertEqual(comparison.status_code, 200, comparison.text)
            self.assertEqual(comparison.json()["scenario_count"], 2)
            self.assertIn("A", comparison.json()["highlights"]["shortest_term"])
            self.assertEqual(
                comparison.json()["comparison_scope"],
                "different_acquisition_scenarios",
            )
            self.assertEqual(len(comparison.json()["highlight_details"]), 7)
            self.assertTrue(comparison.json()["financial_context_comparable"])
            self.assertEqual(
                comparison.json()["monthly_commitment_comparison_status"],
                "comparable",
            )
            self.assertNotIn(
                "lowest_interest_and_financed_costs",
                comparison.json()["highlights"],
            )
            self.assertIn(
                "lowest_interest_and_financed_costs",
                comparison.json()["legacy_highlights"],
            )

            different_budget = client.post(
                "/financing/compare",
                json={
                    "scenarios": [
                        scenario,
                        {
                            **scenario,
                            "offer_name": "B",
                            "available_monthly_budget": 3200,
                        },
                    ]
                },
            )
            self.assertEqual(different_budget.status_code, 200, different_budget.text)
            budget_data = different_budget.json()
            self.assertFalse(budget_data["financial_context_comparable"])
            self.assertNotIn("lowest_budget_commitment", budget_data["highlights"])
            self.assertEqual(
                budget_data["suppressed_highlights"][0]["reason"],
                "different_monthly_budgets",
            )

            ten_scenarios = client.post(
                "/financing/compare",
                json={"scenarios": [{**scenario, "offer_name": f"Cenario {index}"} for index in range(10)]},
            )
            self.assertEqual(ten_scenarios.status_code, 200, ten_scenarios.text)
            self.assertEqual(ten_scenarios.json()["scenario_count"], 10)

            invalid = client.post(
                "/financing/simulate",
                json={**scenario, "monthly_interest_rate_percent": "NaN"},
            )
            self.assertEqual(invalid.status_code, 422)
            self.assertNotIn("Traceback", invalid.text)

            ambiguous_price = client.post(
                "/financing/simulate",
                json={**scenario, "negotiated_price": 25000},
            )
            self.assertEqual(ambiguous_price.status_code, 422)
            self.assertNotIn("Traceback", ambiguous_price.text)

            eleven = client.post(
                "/financing/compare",
                json={"scenarios": [{**scenario, "offer_name": f"Cenario {index}"} for index in range(11)]},
            )
            self.assertEqual(eleven.status_code, 422)
            self.assertNotIn("Traceback", eleven.text)
            self.assertEqual(client.post("/motorcycles/recommendations").status_code, 501)

    def test_motorcycle_v030_canonical_and_legacy_contracts(self):
        from backend.tests.test_motorcycle_schema_v03 import canonical_payload

        with self.client() as client:
            created = client.post("/motorcycles", json=canonical_payload())
            self.assertEqual(created.status_code, 201, created.text)
            motorcycle_id = created.json()["id"]

            canonical = client.get(f"/motorcycles/{motorcycle_id}")
            self.assertEqual(canonical.status_code, 200, canonical.text)
            canonical_data = canonical.json()
            self.assertNotIn("legacy_data", canonical_data)
            self.assertNotIn("data_source", canonical_data)
            self.assertNotIn("reliability_score", canonical_data)
            self.assertEqual(canonical_data["source_contract"]["canonical"], "motorcycle_data_sources")
            self.assertIn("coverage", canonical_data)
            self.assertIn("blocking_issues", canonical_data)
            self.assertIn("informational_issues", canonical_data)

            legacy = client.get(f"/motorcycles/{motorcycle_id}?include_legacy=true")
            self.assertEqual(legacy.status_code, 200, legacy.text)
            self.assertTrue(legacy.json()["legacy_data"]["deprecated"])

            envelope = client.get("/motorcycles?envelope=true")
            self.assertEqual(envelope.status_code, 200, envelope.text)
            item = next(item for item in envelope.json()["motorcycles"] if item["id"] == motorcycle_id)
            self.assertNotIn("legacy_data", item)
            self.assertEqual(envelope.json()["module_version"], "0.3.1")

            reserved = client.post("/motorcycles/recommendations")
            self.assertEqual(reserved.status_code, 501)
            self.assertIsNone(reserved.json()["algorithm_version"])
            self.assertIsNone(reserved.json()["weights_version"])
            self.assertNotIn("rank", reserved.json())
            self.assertNotIn("score", reserved.json())

            self.assertEqual(client.delete(f"/motorcycles/{motorcycle_id}").status_code, 204)


if __name__ == "__main__":
    unittest.main()
