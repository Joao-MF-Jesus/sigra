BRAND_CATALOG_SLUGS = {
    "chevrolet": "chevrolet",
    "honda": "honda",
    "hyundai": "hyundai",
    "renault": "renault",
    "toyota": "toyota",
    "volkswagen": "volkswagen",
}

MODEL_CATALOG_PATHS = {
    ("chevrolet", "onix"): "cross/chevrolet/11522/",
    ("honda", "fit"): "cross/honda/13101/",
    ("renault", "duster"): "cross/renault/10319/",
    ("toyota", "corolla"): "cross/toyota/11560/",
}


def base_model_name(model: str) -> str:
    return model.strip().lower().replace(" gli", "").replace(" ex", "").replace(" comfort", "").replace(" lt", "").replace(" zen", "").replace(" msi", "")


def get_parts_catalog(brand: str, model: str = "") -> dict:
    normalized_brand = brand.strip().lower()
    normalized_model = base_model_name(model)
    model_path = MODEL_CATALOG_PATHS.get((normalized_brand, normalized_model))
    slug = BRAND_CATALOG_SLUGS.get(normalized_brand)
    base_url = "https://www.nemigaparts.com/cat_spares/"

    if model_path:
        return {
            "provider": "NemigaParts CrossDoc",
            "brand": brand,
            "model": model,
            "url": f"{base_url}{model_path}",
            "available": True,
            "target_level": "model",
            "note": "Catalogo tecnico aberto direto na pagina do modelo.",
        }

    return {
        "provider": "NemigaParts CrossDoc",
        "brand": brand,
        "model": model,
        "url": f"{base_url}cross/{slug}/" if slug else base_url,
        "available": slug is not None,
        "target_level": "brand" if slug else "catalog",
        "note": "Catalogo tecnico por marca. Modelo especifico ainda nao mapeado.",
    }
