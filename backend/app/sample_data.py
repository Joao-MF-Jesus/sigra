from app.recommender import Vehicle


def image_path(brand: str, model: str, year: int) -> str:
    slug = (
        f"{brand}-{model}-{year}"
        .lower()
        .replace(" ", "-")
        .replace(".", "")
    )
    return f"/cars/{slug}.svg"


SEGMENT_DATA = {
    1: ("compact_hatch", 2, 62, 58, 65, 88, 60, 55, 80),
    2: ("compact_sedan", 2, 62, 72, 62, 75, 68, 70, 82),
    3: ("compact_sedan", 2, 66, 78, 64, 65, 72, 78, 84),
    4: ("minivan", 3, 68, 92, 66, 55, 70, 95, 78),
    5: ("compact_suv", 4, 76, 76, 78, 70, 78, 78, 55),
    6: ("compact_hatch", 2, 64, 57, 66, 88, 60, 55, 80),
    7: ("compact_sedan", 2, 65, 70, 66, 78, 68, 70, 82),
    8: ("compact_suv", 4, 80, 82, 80, 65, 80, 84, 45),
    9: ("midsize_sedan", 4, 86, 84, 90, 70, 92, 86, 88),
    10: ("compact_hatch", 2, 60, 58, 62, 85, 66, 58, 78),
    11: ("compact_hatch", 3, 72, 64, 78, 82, 74, 68, 82),
    12: ("compact_suv", 5, 88, 86, 92, 68, 88, 88, 76),
    13: ("compact_minivan", 3, 76, 80, 78, 84, 75, 82, 85),
    14: ("compact_sedan", 3, 78, 78, 80, 76, 82, 80, 86),
    15: ("midsize_sedan", 4, 88, 82, 88, 62, 90, 80, 76),
    16: ("compact_suv", 4, 82, 82, 84, 66, 82, 84, 72),
    17: ("compact_hatch", 1, 55, 55, 50, 85, 55, 50, 60),
    18: ("compact_hatch", 3, 74, 62, 78, 84, 72, 64, 78),
    19: ("compact_sedan", 3, 76, 80, 80, 75, 82, 82, 66),
    20: ("compact_sedan", 2, 60, 72, 58, 76, 68, 72, 78),
    21: ("compact_suv", 4, 82, 80, 86, 68, 84, 82, 72),
    22: ("subcompact", 1, 48, 42, 48, 92, 40, 35, 55),
    23: ("subcompact", 1, 52, 50, 50, 88, 50, 45, 58),
    24: ("compact_hatch", 2, 66, 60, 68, 86, 66, 60, 76),
    25: ("compact_sedan", 3, 70, 78, 72, 76, 76, 78, 72),
    26: ("compact_hatch", 2, 60, 64, 58, 80, 60, 62, 72),
    27: ("compact_sedan", 2, 62, 80, 58, 72, 70, 80, 82),
    28: ("suv", 3, 70, 86, 65, 55, 78, 86, 35),
    29: ("subcompact", 1, 55, 48, 55, 90, 52, 42, 55),
    30: ("compact_sedan", 3, 72, 80, 74, 76, 78, 80, 86),
    31: ("compact_suv", 4, 80, 80, 82, 70, 82, 82, 72),
    32: ("compact_suv", 4, 78, 74, 84, 56, 76, 74, 28),
    33: ("compact_hatch", 2, 62, 55, 60, 86, 60, 54, 70),
    34: ("compact_suv", 3, 68, 74, 66, 56, 72, 74, 35),
}


def segment_data(vehicle_id: int) -> dict[str, float | int | str]:
    category, level, comfort, space, safety, urban, road, family, app = SEGMENT_DATA[vehicle_id]
    return {
        "category": category,
        "segment_level": level,
        "comfort_score": comfort,
        "space_score": space,
        "safety_score": safety,
        "urban_score": urban,
        "road_score": road,
        "family_score": family,
        "app_score": app,
    }


def demo_vehicle(
    id: int,
    brand: str,
    model: str,
    year: int,
    price: float,
    fuel_efficiency_km_l: float,
    annual_maintenance_cost: float,
    reliability_score: float,
    parts_availability_score: float,
    depreciation_rate: float,
    use_cases: tuple[str, ...],
    chronic_issues: tuple[str, ...],
) -> Vehicle:
    return Vehicle(
        id=id,
        brand=brand,
        model=model,
        year=year,
        price=price,
        fuel_efficiency_km_l=fuel_efficiency_km_l,
        annual_maintenance_cost=annual_maintenance_cost,
        reliability_score=reliability_score,
        parts_availability_score=parts_availability_score,
        depreciation_rate=depreciation_rate,
        use_cases=use_cases,
        chronic_issues=chronic_issues,
        image_url=image_path(brand, model, year),
        **segment_data(id),
    )


# Base demonstrativa para o MVP academico. Os valores sao coerentes para
# simulacao e defesa, mas nao substituem cotacoes reais de mercado.
VEHICLES = [
    demo_vehicle(1, "Chevrolet", "Onix LT", 2021, 62000, 13.8, 2600, 80, 93, 9.8, ("cidade", "trabalho", "app"), ("Motores turbo exigem atenção rigorosa à troca de óleo",)),
    demo_vehicle(2, "Chevrolet", "Prisma LT", 2018, 54000, 12.9, 2700, 79, 91, 10.5, ("cidade", "trabalho", "app"), ("Acabamento simples e porta-malas sujeito a desgaste de uso intenso",)),
    demo_vehicle(3, "Chevrolet", "Cobalt LTZ", 2018, 61000, 11.2, 3200, 78, 88, 11.2, ("familia", "trabalho", "app"), ("Consumo urbano maior que hatches compactos",)),
    demo_vehicle(4, "Chevrolet", "Spin LT", 2019, 74000, 10.4, 3600, 77, 86, 11.8, ("familia", "trabalho"), ("Consumo urbano alto quando carregada",)),
    demo_vehicle(5, "Chevrolet", "Tracker LT", 2021, 92000, 11.5, 3900, 79, 84, 12.0, ("familia", "estrada", "suv"), ("Seguro pode ficar elevado em algumas regiões",)),
    demo_vehicle(6, "Hyundai", "HB20 Comfort", 2020, 59000, 13.2, 2800, 82, 86, 10.2, ("cidade", "trabalho"), ("Acabamento interno simples",)),
    demo_vehicle(7, "Hyundai", "HB20S Comfort", 2020, 65000, 12.8, 2950, 82, 85, 10.5, ("cidade", "trabalho", "app"), ("Espaço traseiro apenas mediano",)),
    demo_vehicle(8, "Hyundai", "Creta Attitude", 2019, 86000, 10.2, 3800, 83, 82, 11.8, ("familia", "estrada", "suv"), ("Consumo urbano mais alto que compactos",)),
    demo_vehicle(9, "Toyota", "Corolla GLi", 2018, 86000, 11.8, 3600, 94, 88, 8.5, ("familia", "trabalho", "estrada"), ("Seguro pode ficar elevado em algumas regiões",)),
    demo_vehicle(10, "Toyota", "Etios XLS", 2018, 57000, 13.1, 2700, 92, 85, 8.8, ("cidade", "trabalho", "app"), ("Projeto interno simples",)),
    demo_vehicle(11, "Toyota", "Yaris XL", 2020, 76000, 12.7, 3100, 91, 84, 9.4, ("cidade", "familia", "trabalho"), ("Porta-malas mediano nas versões hatch",)),
    demo_vehicle(12, "Toyota", "Corolla Cross XR", 2022, 132000, 11.0, 4300, 92, 82, 10.8, ("familia", "estrada", "suv"), ("Preço de aquisição elevado para o MVP",)),
    demo_vehicle(13, "Honda", "Fit EX", 2017, 65000, 12.6, 3100, 91, 84, 7.8, ("cidade", "familia", "trabalho"), ("Espaço de porta-malas limitado para viagens longas",)),
    demo_vehicle(14, "Honda", "City LX", 2018, 72000, 12.4, 3200, 90, 83, 8.6, ("familia", "trabalho", "estrada"), ("Seguro pode variar bastante por região",)),
    demo_vehicle(15, "Honda", "Civic EX", 2017, 89000, 10.8, 4100, 90, 80, 9.6, ("familia", "estrada"), ("Manutenção e seguro acima de sedãs compactos",)),
    demo_vehicle(16, "Honda", "HR-V LX", 2018, 88000, 10.7, 3900, 89, 81, 10.2, ("familia", "estrada", "suv"), ("Porta-malas e seguro podem pesar no custo total",)),
    demo_vehicle(17, "Volkswagen", "Gol Trendline", 2019, 50000, 12.5, 2600, 78, 94, 10.0, ("cidade", "trabalho", "app"), ("Projeto antigo e nível de segurança inferior a modelos novos",)),
    demo_vehicle(18, "Volkswagen", "Polo MSI", 2019, 68000, 12.4, 3100, 84, 90, 9.2, ("cidade", "trabalho", "app"), ("Custo de seguro pode variar em capitais",)),
    demo_vehicle(19, "Volkswagen", "Virtus MSI", 2019, 70000, 12.1, 3300, 84, 89, 9.4, ("familia", "estrada", "trabalho"), ("Suspensão pode ter desgaste em piso irregular",)),
    demo_vehicle(20, "Volkswagen", "Voyage Comfortline", 2018, 56000, 12.0, 3000, 79, 92, 10.7, ("cidade", "trabalho", "app"), ("Projeto antigo e acabamento simples",)),
    demo_vehicle(21, "Volkswagen", "T-Cross 200 TSI", 2020, 98000, 10.9, 4100, 84, 86, 11.0, ("familia", "estrada", "suv"), ("Motores turbo exigem manutenção preventiva correta",)),
    demo_vehicle(22, "Fiat", "Mobi Like", 2021, 48000, 13.6, 2400, 76, 91, 12.4, ("cidade", "app"), ("Espaço interno e porta-malas limitados",)),
    demo_vehicle(23, "Fiat", "Uno Attractive", 2018, 45000, 12.9, 2400, 77, 92, 11.8, ("cidade", "trabalho", "app"), ("Projeto simples e acabamento básico",)),
    demo_vehicle(24, "Fiat", "Argo Drive", 2020, 61000, 13.0, 2800, 80, 89, 10.9, ("cidade", "trabalho", "app"), ("Desempenho modesto em versões 1.0 carregadas",)),
    demo_vehicle(25, "Fiat", "Cronos Drive", 2020, 67000, 12.5, 3000, 80, 88, 10.8, ("familia", "trabalho", "app"), ("Acabamento interno simples em versões de entrada",)),
    demo_vehicle(26, "Renault", "Sandero Zen", 2020, 54000, 12.2, 2800, 76, 82, 12.2, ("cidade", "trabalho", "app"), ("Acabamento simples e desvalorização acima da média",)),
    demo_vehicle(27, "Renault", "Logan Zen", 2020, 58000, 12.0, 2900, 76, 82, 12.4, ("familia", "trabalho", "app"), ("Projeto simples e isolamento acústico limitado",)),
    demo_vehicle(28, "Renault", "Duster Zen", 2020, 78000, 10.1, 3700, 78, 78, 11.5, ("familia", "estrada", "suv"), ("Consumo urbano mais alto que hatches compactos",)),
    demo_vehicle(29, "Nissan", "March SV", 2018, 46000, 13.4, 2600, 81, 78, 11.0, ("cidade", "app"), ("Rede de peças menor que concorrentes populares",)),
    demo_vehicle(30, "Nissan", "Versa SV", 2019, 61000, 12.6, 3000, 83, 79, 10.6, ("familia", "trabalho", "app"), ("Acabamento simples e rede de peças mais restrita",)),
    demo_vehicle(31, "Nissan", "Kicks S", 2020, 85000, 11.7, 3500, 84, 78, 10.7, ("familia", "estrada", "suv"), ("Desempenho modesto em retomadas carregado",)),
    demo_vehicle(32, "Jeep", "Renegade Sport", 2019, 82000, 9.5, 4300, 75, 76, 13.0, ("familia", "suv"), ("Consumo elevado e manutenção mais cara",)),
    demo_vehicle(33, "Ford", "Ka SE", 2019, 50000, 13.3, 2700, 79, 80, 11.4, ("cidade", "trabalho", "app"), ("Rede de peças requer atenção após saída da marca do país",)),
    demo_vehicle(34, "Ford", "EcoSport SE", 2018, 67000, 9.8, 3800, 77, 78, 12.6, ("familia", "suv"), ("Consumo alto e projeto mais antigo",)),
]
