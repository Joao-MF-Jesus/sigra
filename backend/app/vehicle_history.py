from collections import Counter, defaultdict
from statistics import mean

from app import models
from app.vehicle_queries import car_query


SEVERITY_WEIGHT = {"baixa": 1, "media": 2, "alta": 3}


def _round(value: float | None) -> float | None:
    return round(value, 2) if value is not None else None


def calculate_model_statistics(db, vehicle_id: int | None = None) -> dict[int, dict]:
    """Calcula indicadores simples a partir dos relatos reais dos usuarios."""
    vehicles = car_query(db).all()
    if vehicle_id is not None:
        vehicles = [vehicle for vehicle in vehicles if vehicle.id == vehicle_id]

    stats: dict[int, dict] = {}
    for vehicle in vehicles:
        reports = db.query(models.VehicleReport).filter(models.VehicleReport.vehicle_id == vehicle.id).all()
        consumptions = (
            db.query(models.FuelConsumptionReport)
            .filter(models.FuelConsumptionReport.vehicle_id == vehicle.id)
            .all()
        )
        categories = Counter(report.problem_category for report in reports)
        severity_points = sum(SEVERITY_WEIGHT.get(report.severity, 1) for report in reports)
        repair_costs = [
            float(report.repair_cost)
            for report in reports
            if report.repair_cost > 0
        ]
        occurrence_kms = [report.occurrence_km for report in reports]
        consumption_by_usage: dict[str, list[float]] = defaultdict(list)
        for item in consumptions:
            consumption_by_usage[item.usage_type].append(item.km_per_liter)

        risk_index = min(100, (len(reports) * 8) + (severity_points * 5))
        avg_consumption = mean([item.km_per_liter for item in consumptions]) if consumptions else None
        expected = vehicle.fuel_efficiency_km_l
        consumption_gap_percent = None
        if avg_consumption:
            consumption_gap_percent = ((avg_consumption - expected) / expected) * 100

        stats[vehicle.id] = {
            "vehicle_id": vehicle.id,
            "brand": vehicle.brand,
            "model": vehicle.model,
            "year": vehicle.year,
            "report_count": len(reports),
            "common_problem_categories": [
                {"category": category, "count": count}
                for category, count in categories.most_common(3)
            ],
            "average_problem_km": _round(mean(occurrence_kms)) if occurrence_kms else None,
            "average_repair_cost": _round(mean(repair_costs)) if repair_costs else None,
            "real_consumption": {
                usage: _round(mean(values))
                for usage, values in sorted(consumption_by_usage.items())
            },
            "real_consumption_average": _round(avg_consumption),
            "consumption_gap_percent": _round(consumption_gap_percent),
            "risk_index": _round(risk_index),
            "attention_points": build_attention_points(categories, risk_index, consumption_gap_percent),
        }
    return stats


def build_attention_points(categories: Counter, risk_index: float, consumption_gap_percent: float | None) -> list[str]:
    points = []
    if categories:
        category, count = categories.most_common(1)[0]
        points.append(f"{count} relato(s) em {category}.")
    if risk_index >= 50:
        points.append("Indice de risco elevado na base de relatos.")
    if consumption_gap_percent is not None and consumption_gap_percent <= -12:
        points.append("Consumo real abaixo do esperado na base demonstrativa.")
    return points


def build_recommendation_feedback(db) -> dict[int, dict]:
    feedback = {}
    for vehicle_id, stats in calculate_model_statistics(db).items():
        penalty = 0.0
        bonus = 0.0
        reasons = []

        if stats["report_count"] >= 3:
            penalty += min(12, stats["report_count"] * 2)
            reasons.append("penalidade por recorrencia de relatos")
        if stats["risk_index"] >= 45:
            penalty += min(10, stats["risk_index"] / 10)
            reasons.append("penalidade por indice de risco")
        if stats["average_repair_cost"] and stats["average_repair_cost"] > 1800:
            penalty += 5
            reasons.append("penalidade por custo medio de reparo")
        if stats["consumption_gap_percent"] is not None and stats["consumption_gap_percent"] <= -12:
            penalty += 6
            reasons.append("penalidade por consumo real abaixo do esperado")

        if 0 < stats["report_count"] and stats["risk_index"] < 30:
            bonus += 3
            reasons.append("bonus por baixa recorrencia de problemas")
        if stats["consumption_gap_percent"] is not None and stats["consumption_gap_percent"] >= 5:
            bonus += 4
            reasons.append("bonus por consumo real favoravel")

        feedback[vehicle_id] = {
            "penalty": round(penalty, 2),
            "bonus": round(bonus, 2),
            "net_adjustment": round(bonus - penalty, 2),
            "reasons": reasons,
            "stats": stats,
        }
    return feedback


def build_preventive_alerts(db, user_vehicle: models.UserVehicle) -> list[dict]:
    reports = (
        db.query(models.VehicleReport)
        .filter(models.VehicleReport.vehicle_id == user_vehicle.vehicle_id)
        .all()
    )
    grouped: dict[str, list[models.VehicleReport]] = defaultdict(list)
    for report in reports:
        grouped[report.problem_category].append(report)

    alerts = []
    for category, items in grouped.items():
        avg_km = mean([item.occurrence_km for item in items])
        distance = avg_km - user_vehicle.current_km
        high_severity_count = len([item for item in items if item.severity == "alta"])
        if -5000 <= distance <= 10000 and len(items) >= 1:
            priority = "alta" if high_severity_count or len(items) >= 3 else "media"
            alerts.append(
                {
                    "category": category,
                    "priority": priority,
                    "reference_km": round(avg_km),
                    "report_count": len(items),
                    "message": (
                        f"Este modelo possui relatos de {category} proximos de "
                        f"{round(avg_km):,} km. Considere uma revisao preventiva."
                    ),
                }
            )
    return sorted(alerts, key=lambda item: (item["priority"] != "alta", item["reference_km"]))
