from sqlalchemy.orm import Query, Session

from app import models
from app.vehicle_domain import VehicleType


def car_query(db: Session) -> Query:
    """Consulta-base dos fluxos exclusivamente automotivos."""
    return db.query(models.Vehicle).filter(models.Vehicle.vehicle_type == VehicleType.CAR.value)


def get_car(db: Session, vehicle_id: int) -> models.Vehicle | None:
    return car_query(db).filter(models.Vehicle.id == vehicle_id).one_or_none()
