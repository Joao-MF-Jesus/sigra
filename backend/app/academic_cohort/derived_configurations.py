"""Explicit presets and lossless provenance; never alters metrics or gates."""
from copy import deepcopy
from decimal import Decimal
import json
from pathlib import Path

from app.academic_cohort import derived_mass_power
from app.multifactor_recommendation import normalize_multifactor_weights
from data_platform.catalog.profile_pilot_v4 import fingerprint

VERSION = "academic-derived-configurations-v1"
BASE = "academic-derived-base-five-v1"
EXPANDED = "academic-derived-expanded-seven-v1"
PATH = Path(__file__).with_name("derived_configurations_v1.json")
KEYS = ("total_cost", "usage_fit", "comfort", "safety", "performance", "efficiency", "legacy_quality")


def configuration():
    value = json.loads(PATH.read_text(encoding="utf-8"))
    if value["version"] != VERSION or value["method_version"] != derived_mass_power.POLICY or value["enabled_by_default"] is not False:
        raise ValueError("Contrato de configurações acadêmicas inválido")
    if set(value["configurations"]) != {BASE, EXPANDED}:
        raise ValueError("Configurações acadêmicas desconhecidas")
    for preset in value["configurations"].values():
        weights = preset["weights"]
        if set(weights) != set(KEYS) or any(not isinstance(v, str) for v in weights.values()):
            raise ValueError("Declare explicitamente os sete pesos")
        numbers = [Decimal(weights[key]) for key in KEYS]
        if any(not v.is_finite() or v < 0 or v > 100 for v in numbers) or sum(numbers) != 100:
            raise ValueError("Vetor fixo deve somar 100%")
    return value


def preset(identifier):
    config = configuration()
    if identifier not in config["configurations"]:
        raise ValueError("Selecione uma configuração acadêmica disponível")
    return deepcopy(config["configurations"][identifier])


def execution_metadata(identifier, weights):
    config = configuration()
    selected = preset(identifier) if identifier else None
    normalized = normalize_multifactor_weights(weights)
    return {"registry_version": VERSION, "method_version": config["method_version"],
            "configuration_id": identifier, "selection_explicit": identifier is not None,
            "label": selected["label"] if selected else "Pesos explícitos sem preset (compatibilidade anterior)",
            "preset_weights": selected["weights"] if selected else None,
            "actual_weights": deepcopy(weights),
            "normalized_weights_percentage": {k: v * 100 for k, v in normalized.items()},
            "weights_adjusted": (any(weights[k] != Decimal(selected["weights"][k]) for k in KEYS) if selected else None),
            "configuration_contract_fingerprint": fingerprint(config),
            "effective_weights_fingerprint": fingerprint(weights),
            "comparison_warning": config["comparison_warning"],
            "evidence_batch_version": derived_mass_power.VERSION,
            "evidence_batch_sha256": derived_mass_power.EXPECTED_SHA256}


def recorded_configuration(result):
    """Read the server result, not a client's claimed preset or task mapping."""
    metadata = (result.get("multifactor_profile") or {}).get("configuration")
    return deepcopy(metadata) if isinstance(metadata, dict) else None
