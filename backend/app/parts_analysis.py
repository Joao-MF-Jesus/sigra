from statistics import mean

from app import models
from app.vehicle_queries import car_query, get_car


POPULAR_MODEL_KEYWORDS = ("onix", "hb20", "gol", "mobi", "ka", "sandero", "etios")


def calculate_part_price_stats(db, vehicle_id: int, part_id: int) -> dict:
    prices = (
        db.query(models.PartPrice)
        .filter(models.PartPrice.vehicle_id == vehicle_id, models.PartPrice.part_id == part_id)
        .all()
    )
    if not prices:
        return {
            "part_id": part_id,
            "vehicle_id": vehicle_id,
            "supplier_count": 0,
            "min_price": None,
            "max_price": None,
            "average_price": None,
            "variation_percent": None,
            "suppliers": [],
            "alerts": ["Sem precos demonstrativos para esta peca."],
        }

    values = [float(item.price) for item in prices]
    min_price = min(values)
    max_price = max(values)
    average_price = mean(values)
    variation_percent = ((max_price - min_price) / min_price) * 100 if min_price else 0
    stats = {
        "part_id": part_id,
        "vehicle_id": vehicle_id,
        "supplier_count": len({item.supplier_id for item in prices}),
        "min_price": round(min_price, 2),
        "max_price": round(max_price, 2),
        "average_price": round(average_price, 2),
        "variation_percent": round(variation_percent, 2),
        "suppliers": [
            {
                "id": item.supplier.id,
                "name": item.supplier.name,
                "type": item.supplier.type,
                "price": round(float(item.price), 2),
                "condition": item.condition,
                "url": item.url,
            }
            for item in prices
        ],
    }
    stats["alerts"] = build_part_price_alerts(stats)
    return stats


def build_part_price_alerts(price_stats: dict) -> list[str]:
    alerts = []
    if price_stats["supplier_count"] == 0:
        return price_stats.get("alerts", [])
    if price_stats["max_price"] and price_stats["average_price"] and price_stats["max_price"] > price_stats["average_price"] * 1.8:
        alerts.append("Maior preco esta mais de 80% acima da media. Compare fornecedores antes de comprar.")
    if price_stats["variation_percent"] and price_stats["variation_percent"] > 100:
        alerts.append("Variacao de preco acima de 100% entre fornecedores.")
    if price_stats["supplier_count"] < 2:
        alerts.append("Baixa disponibilidade demonstrativa de fornecedores.")
    supplier_types = {supplier["type"] for supplier in price_stats["suppliers"]}
    if supplier_types == {"concessionaria"}:
        alerts.append("Peca encontrada apenas em concessionaria na base demonstrativa.")
    return alerts


def calculate_shared_parts_score(db, vehicle_id: int) -> float:
    compatibilities = (
        db.query(models.VehiclePartCompatibility)
        .filter(models.VehiclePartCompatibility.vehicle_id == vehicle_id)
        .all()
    )
    if not compatibilities:
        return 45.0
    score = min(100, 35 + len(compatibilities) * 8)
    for item in compatibilities:
        model_name = f"{item.compatible_vehicle.brand} {item.compatible_vehicle.model}".lower()
        if any(keyword in model_name for keyword in POPULAR_MODEL_KEYWORDS):
            score += 6
        if item.compatibility_type in {"mesma peca", "mesma plataforma", "mesmo motor"}:
            score += 4
    return round(min(100, score), 2)


def calculate_supplier_availability_score(db, vehicle_id: int) -> float:
    prices = db.query(models.PartPrice).filter(models.PartPrice.vehicle_id == vehicle_id).all()
    if not prices:
        return 50.0
    supplier_count = len({item.supplier_id for item in prices})
    supplier_types = len({item.supplier.type for item in prices})
    part_count = len({item.part_id for item in prices})
    return round(min(100, 30 + supplier_count * 8 + supplier_types * 6 + part_count * 2), 2)


def calculate_price_variation_risk(db, vehicle_id: int) -> float:
    part_ids = [item[0] for item in db.query(models.PartPrice.part_id).filter(models.PartPrice.vehicle_id == vehicle_id).distinct()]
    if not part_ids:
        return 35.0
    risks = []
    for part_id in part_ids:
        stats = calculate_part_price_stats(db, vehicle_id, part_id)
        variation = stats["variation_percent"] or 0
        supplier_penalty = 25 if stats["supplier_count"] < 2 else 0
        risks.append(min(100, variation / 2 + supplier_penalty))
    return round(mean(risks), 2)


def calculate_vehicle_parts_summary(db, vehicle_id: int) -> dict:
    vehicle = get_car(db, vehicle_id)
    if vehicle is None:
        return {}
    part_ids = [item[0] for item in db.query(models.PartPrice.part_id).filter(models.PartPrice.vehicle_id == vehicle_id).distinct()]
    part_stats = []
    for part_id in part_ids:
        part = db.get(models.Part, part_id)
        stats = calculate_part_price_stats(db, vehicle_id, part_id)
        stats["part_name"] = part.name if part else f"Peca {part_id}"
        stats["category"] = part.category if part else "outros"
        part_stats.append(stats)

    shared_score = calculate_shared_parts_score(db, vehicle_id)
    availability_score = calculate_supplier_availability_score(db, vehicle_id)
    variation_risk = calculate_price_variation_risk(db, vehicle_id)
    maintenance_index = calculate_maintenance_index(db, vehicle_id)
    compatibilities = (
        db.query(models.VehiclePartCompatibility)
        .filter(models.VehiclePartCompatibility.vehicle_id == vehicle_id)
        .all()
    )
    alerts = [alert for stats in part_stats for alert in stats["alerts"]]
    positives = []
    attention = []
    if shared_score >= 70:
        positives.append("Boa compatibilidade de pecas com outros modelos.")
    else:
        attention.append("Compatibilidade de pecas mais limitada na base demonstrativa.")
    if availability_score >= 70:
        positives.append("Fornecedores variados para as pecas analisadas.")
    else:
        attention.append("Disponibilidade demonstrativa de fornecedores ainda limitada.")
    if variation_risk >= 55:
        attention.append("Algumas pecas apresentam alta variacao de preco.")

    return {
        "vehicle": {
            "id": vehicle.id,
            "brand": vehicle.brand,
            "model": vehicle.model,
            "year": vehicle.year,
        },
        "maintenance_index": maintenance_index,
        "shared_parts_score": shared_score,
        "supplier_availability_score": availability_score,
        "price_variation_risk": variation_risk,
        "abusive_price_risk": variation_risk >= 55,
        "parts": part_stats,
        "compatibilities": [
            {
                "part": item.part.name,
                "compatible_vehicle": f"{item.compatible_vehicle.brand} {item.compatible_vehicle.model}",
                "compatibility_type": item.compatibility_type,
                "confidence_level": item.confidence_level,
                "notes": item.notes,
            }
            for item in compatibilities
        ],
        "alerts": list(dict.fromkeys(alerts + attention)),
        "positives": positives,
        "attention_points": attention,
    }


def calculate_maintenance_index(db, vehicle_id: int) -> float:
    vehicle = get_car(db, vehicle_id)
    if vehicle is None:
        return 0.0
    prices = db.query(models.PartPrice).filter(models.PartPrice.vehicle_id == vehicle_id).all()
    if not prices:
        cost_score = max(
            0,
            min(100, 100 - (float(vehicle.annual_maintenance_cost) / 60)),
        )
        return round((vehicle.parts_availability_score * 0.55) + (cost_score * 0.45), 2)

    average_part_cost = mean([float(item.price) for item in prices])
    cost_score = max(0, min(100, 100 - (average_part_cost / 18)))
    availability = calculate_supplier_availability_score(db, vehicle_id)
    shared = calculate_shared_parts_score(db, vehicle_id)
    variation_risk = calculate_price_variation_risk(db, vehicle_id)
    annual_cost_score = max(
        0,
        min(100, 100 - (float(vehicle.annual_maintenance_cost) / 70)),
    )
    score = (
        availability * 0.24
        + shared * 0.22
        + cost_score * 0.20
        + vehicle.parts_availability_score * 0.16
        + annual_cost_score * 0.14
        - variation_risk * 0.12
    )
    return round(max(0, min(100, score)), 2)


def build_recommender_parts_feedback(db) -> dict[int, dict]:
    feedback = {}
    for vehicle in car_query(db).all():
        summary = calculate_vehicle_parts_summary(db, vehicle.id)
        if not summary:
            continue
        maintenance_index = summary["maintenance_index"]
        adjustment = round((maintenance_index - 60) / 8, 2)
        feedback[vehicle.id] = {
            "maintenance_index": maintenance_index,
            "shared_parts_score": summary["shared_parts_score"],
            "supplier_availability_score": summary["supplier_availability_score"],
            "price_variation_risk": summary["price_variation_risk"],
            "abusive_price_risk": summary["abusive_price_risk"],
            "score_adjustment": max(-8, min(7, adjustment)),
            "summary": summary,
        }
    return feedback
