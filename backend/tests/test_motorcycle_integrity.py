import unittest
from unittest.mock import Mock

class MotorcycleIntegrityTest(unittest.TestCase):
    def test_create_rolls_back_when_flush_fails(self):
        from app.repository import create_motorcycle
        from app.schemas import MotorcycleCreate
        from backend.tests.test_motorcycles import VALID_MOTORCYCLE

        db = Mock()
        db.flush.side_effect = RuntimeError("falha controlada")
        with self.assertRaises(RuntimeError):
            create_motorcycle(db, MotorcycleCreate.model_validate(VALID_MOTORCYCLE))
        db.rollback.assert_called_once()
        db.commit.assert_not_called()

    def test_create_is_atomic_when_specification_insert_fails_after_parent_insert(self):
        from sqlalchemy import create_engine, event
        from sqlalchemy.orm import Session

        from app.database import Base
        from app.models import Motorcycle, MotorcycleObjectiveSpecification
        from app.repository import create_motorcycle
        from app.schemas import MotorcycleCreate
        from backend.tests.test_motorcycles import VALID_MOTORCYCLE

        engine = create_engine("sqlite:///:memory:")
        with engine.connect() as connection:
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        Base.metadata.create_all(engine)

        def fail_specification_insert(_mapper, _connection, _target):
            raise RuntimeError("falha controlada após inserir a entidade principal")

        event.listen(MotorcycleObjectiveSpecification, "before_insert", fail_specification_insert)
        try:
            with Session(engine) as db:
                with self.assertRaises(RuntimeError):
                    create_motorcycle(db, MotorcycleCreate.model_validate(VALID_MOTORCYCLE))
                self.assertEqual(db.query(Motorcycle).count(), 0)
                self.assertEqual(db.query(MotorcycleObjectiveSpecification).count(), 0)
        finally:
            event.remove(MotorcycleObjectiveSpecification, "before_insert", fail_specification_insert)
            engine.dispose()

    def test_one_to_one_constraint_and_cascade_delete(self):
        from sqlalchemy import create_engine
        from sqlalchemy.exc import IntegrityError
        from sqlalchemy.orm import Session

        from app.database import Base
        from app.models import Motorcycle, MotorcycleSpecification

        engine = create_engine("sqlite:///:memory:")
        with engine.connect() as connection:
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        Base.metadata.create_all(engine)
        with Session(engine) as db:
            motorcycle = Motorcycle(
                brand="Honda", model="Teste", year=2025, price=20000,
                city_consumption=30, road_consumption=34, annual_maintenance_cost=2000,
                reliability_score=80, parts_availability_score=80, depreciation_rate=10,
                data_source="demonstration", data_confidence=30, vehicle_type="motorcycle",
            )
            motorcycle.specifications = MotorcycleSpecification(
                engine_displacement_cc=160, motorcycle_category="street", wet_weight_kg=130,
                seat_height_mm=780, tank_capacity_l=12, has_abs=True,
                recommended_experience="beginner", urban_score=80, road_score=60,
                passenger_comfort_score=50, luggage_score=30,
            )
            db.add(motorcycle)
            db.commit()
            motorcycle_id = motorcycle.id

            db.add(MotorcycleSpecification(
                motorcycle_id=motorcycle_id, engine_displacement_cc=160, motorcycle_category="street",
                wet_weight_kg=130, seat_height_mm=780, tank_capacity_l=12, has_abs=True,
                recommended_experience="beginner", urban_score=80, road_score=60,
                passenger_comfort_score=50, luggage_score=30,
            ))
            with self.assertRaises(IntegrityError):
                db.commit()
            db.rollback()

            specification = db.query(MotorcycleSpecification).filter_by(motorcycle_id=motorcycle_id).one()
            db.delete(specification)
            db.commit()
            db.expire_all()
            self.assertIsNotNone(db.get(Motorcycle, motorcycle_id))
            self.assertIsNone(db.get(Motorcycle, motorcycle_id).specifications)

            db.delete(db.get(Motorcycle, motorcycle_id))
            db.commit()
            self.assertIsNone(db.query(MotorcycleSpecification).filter_by(motorcycle_id=motorcycle_id).first())
        engine.dispose()
