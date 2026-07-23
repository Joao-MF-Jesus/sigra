ONLINE_CAR_RESULTS = [
    {
        "id": "corolla-gli-2018",
        "brand": "Toyota",
        "model": "Corolla GLi",
        "year": 2018,
        "body_type": "Sedan",
        "fuel": "Flex",
        "transmission": "Automatico",
        "engine": "2.0",
        "source": "Imagem online demonstrativa",
        "image_url": "https://images.unsplash.com/photo-1553440569-bcc63803a83d?auto=format&fit=crop&w=900&q=80",
    },
    {
        "id": "fit-ex-2017",
        "brand": "Honda",
        "model": "Fit EX",
        "year": 2017,
        "body_type": "Hatch",
        "fuel": "Flex",
        "transmission": "CVT",
        "engine": "1.5",
        "source": "Imagem online demonstrativa",
        "image_url": "https://images.unsplash.com/photo-1549925862-990d57cc4e44?auto=format&fit=crop&w=900&q=80",
    },
    {
        "id": "hb20-comfort-2020",
        "brand": "Hyundai",
        "model": "HB20 Comfort",
        "year": 2020,
        "body_type": "Hatch",
        "fuel": "Flex",
        "transmission": "Manual/Automatico",
        "engine": "1.0",
        "source": "Imagem online demonstrativa",
        "image_url": "https://images.unsplash.com/photo-1541899481282-d53bffe3c35d?auto=format&fit=crop&w=900&q=80",
    },
    {
        "id": "onix-lt-2021",
        "brand": "Chevrolet",
        "model": "Onix LT",
        "year": 2021,
        "body_type": "Hatch",
        "fuel": "Flex",
        "transmission": "Automatico",
        "engine": "1.0 turbo",
        "source": "Imagem online demonstrativa",
        "image_url": "https://images.unsplash.com/photo-1552519507-da3b142c6e3d?auto=format&fit=crop&w=900&q=80",
    },
    {
        "id": "duster-zen-2020",
        "brand": "Renault",
        "model": "Duster Zen",
        "year": 2020,
        "body_type": "SUV",
        "fuel": "Flex",
        "transmission": "Manual/CVT",
        "engine": "1.6",
        "source": "Imagem online demonstrativa",
        "image_url": "https://images.unsplash.com/photo-1533473359331-0135ef1b58bf?auto=format&fit=crop&w=900&q=80",
    },
    {
        "id": "virtus-msi-2019",
        "brand": "Volkswagen",
        "model": "Virtus MSI",
        "year": 2019,
        "body_type": "Sedan",
        "fuel": "Flex",
        "transmission": "Manual/Automatico",
        "engine": "1.6",
        "source": "Imagem online demonstrativa",
        "image_url": "https://images.unsplash.com/photo-1617788138017-80ad40651399?auto=format&fit=crop&w=900&q=80",
    },
]


def slug(value: str) -> str:
    return value.strip().lower().replace(" ", "-")


def search_query(result: dict) -> str:
    return f"{result['brand']} {result['model']} {result['year']}".replace(" ", "%20")


def build_purchase_url(result: dict) -> str:
    brand = slug(result["brand"])
    model = slug(result["model"])
    year = result["year"]
    return f"https://www.webmotors.com.br/carros/estoque/{brand}/{model}/de.{year}/ate.{year}"


def official_source(result: dict) -> dict:
    brand = result["brand"].lower()
    official_urls = {
        "chevrolet": "https://www.chevrolet.com.br/comprar-carro",
        "honda": "https://www.honda.com.br/automoveis/seminovos",
        "hyundai": "https://www.hyundai.com.br",
        "renault": "https://www.renault.com.br/veiculos.html",
        "toyota": "https://www.toyota.com.br",
        "volkswagen": "https://www.vw.com.br/pt.html",
    }
    return {
        "name": "Concessionaria oficial",
        "type": "official",
        "url": official_urls.get(brand, "https://www.google.com/search?q=" + search_query(result)),
    }


def choose_best_purchase_source(result: dict, sources: list[dict]) -> dict:
    # Para usados/seminovos, marketplace com filtro de modelo/ano tende a ser mais direto.
    # Para carros recentes, a concessionaria oficial vira boa alternativa.
    if result["year"] >= 2022:
        return sources[2]
    if result["year"] >= 2019:
        return sources[0]
    return sources[1]


def purchase_sources(result: dict) -> list[dict]:
    query = search_query(result)
    return [
        {
            "name": "Webmotors",
            "type": "marketplace",
            "url": build_purchase_url(result),
        },
        {
            "name": "OLX",
            "type": "marketplace",
            "url": f"https://www.olx.com.br/autos-e-pecas/carros-vans-e-utilitarios?q={query}",
        },
        official_source(result),
    ]


def hydrate_result(result: dict) -> dict:
    sources = purchase_sources(result)
    best_source = choose_best_purchase_source(result, sources)
    return {
        **result,
        "purchase_url": best_source["url"],
        "best_purchase_source": best_source,
        "purchase_sources": sources,
        "technical_specs": {
            "Carroceria": result["body_type"],
            "Combustivel": result["fuel"],
            "Cambio": result["transmission"],
            "Motor": result["engine"],
            "Ano": str(result["year"]),
        },
    }


def normalize_tokens(value: str) -> set[str]:
    return {token for token in value.lower().replace("-", " ").split() if len(token) > 1}


def find_online_matches(brand: str, model: str, year: int, limit: int = 1) -> list[dict]:
    brand_normalized = brand.strip().lower()
    model_tokens = normalize_tokens(model)
    scored_results = []

    for result in ONLINE_CAR_RESULTS:
        score = 0
        if result["brand"].lower() == brand_normalized:
            score += 5
        score += len(model_tokens.intersection(normalize_tokens(result["model"]))) * 3
        score -= abs(result["year"] - year) * 0.25
        if score > 0:
            scored_results.append((score, result))

    scored_results.sort(key=lambda item: item[0], reverse=True)
    return [hydrate_result(result) for _, result in scored_results[:limit]]


def search_online_cars(query: str) -> list[dict]:
    normalized = query.strip().lower()
    results = ONLINE_CAR_RESULTS
    if normalized:
        results = [
            result
            for result in ONLINE_CAR_RESULTS
            if normalized in f"{result['brand']} {result['model']} {result['year']}".lower()
        ]

    return [hydrate_result(result) for result in results]
