"""Fail-closed planning of the selected catalog; never an implicit seed.

The operational Vehicle model has mandatory numeric evidence. Missing records
stay here as candidates instead of being converted to invented NOT NULL values.
"""
from __future__ import annotations

from collections import Counter
import hashlib
from pathlib import Path

from data_platform.catalog.contracts import Blocker, Candidate, Dossier, Selection
from data_platform.contracts.fipe import FipeTarget
from data_platform.contracts.pbev import AUDITED_ASSET_BY_YEAR


SELECTION_PATH = Path(__file__).with_name("selection_v1.json")
SOURCE_HASH = "8e2401a447ab6e39360f03db4f09ed96596123ebd2e9715caeade4ad76f1c884"
REQUIRED_FIELDS = {
    "annual_maintenance_cost": "BRL/year",
    "reliability_score": "score/100",
    "parts_availability_score": "score/100",
    "depreciation_rate": "percent/year",
    "comfort_score": "score/100",
    "space_score": "score/100",
    "safety_score": "score/100",
    "urban_score": "score/100",
    "road_score": "score/100",
    "family_score": "score/100",
    "app_score": "score/100",
    "segment_level": "level/5",
    "consumption_city": "km/l",
    "consumption_highway": "km/l",
}
CONFIGURATION_FIELDS = {"brand", "model", "version", "model_year", "motor", "transmission", "fuel"}


def load_selection(path: Path = SELECTION_PATH) -> Selection:
    selection = Selection.model_validate_json(path.read_text(encoding="utf-8"))
    if selection.source.sha256 != SOURCE_HASH:
        raise ValueError("canonical workbook hash differs")
    if selection.source.sheets != ("Resumo", "Candidatos_66", "Catalogo_atual", "Criterios_e_fontes"):
        raise ValueError("canonical workbook sheets differ")
    if [r.id for r in selection.baseline] != list(range(1, 35)):
        raise ValueError("baseline must preserve IDs 1..34")
    if [r.id for r in selection.candidates] != list(range(35, 101)):
        raise ValueError("selection must contain exactly IDs 35..100 in order")
    groups = Counter(r.collection_group for r in selection.candidates)
    if len(groups) != 6 or set(groups.values()) != {11}:
        raise ValueError("selection must contain six collection groups of eleven")
    for group in groups:
        if sorted(r.collection_order for r in selection.candidates if r.collection_group == group) != list(range(1, 12)):
            raise ValueError("collection order must be unique within each group")
    keys = [(r.brand.casefold().strip(), r.model_family.casefold().strip()) for r in selection.candidates]
    if len(set(keys)) != 66:
        raise ValueError("duplicate candidate commercial family")
    baseline_keys = {(r.brand.casefold().strip(), r.model.casefold().strip()) for r in selection.baseline}
    if baseline_keys.intersection(keys):
        raise ValueError("candidate overlaps existing catalog")
    return selection


def assess(candidate: Candidate, dossier: Dossier | None = None) -> tuple[Blocker, ...]:
    """Completeness gate only. Passing is not proof of source review or activation."""
    dossier = dossier or Dossier(candidate_id=candidate.id)
    if dossier.candidate_id != candidate.id:
        raise ValueError("dossier belongs to a different candidate")
    issues = []

    def block(code, field, reason):
        issues.append(Blocker(code=code, field=field, reason=reason))

    identity = dossier.identity
    if identity is None:
        block("EXACT_FIPE_IDENTITY_MISSING", "identity", "Código, ano FIPE, descrição completa e preço ainda não aprovados.")
        block("EXACT_PBEV_MAPPING_MISSING", "identity", "Linha PBEV da mesma versão, ano, motor, transmissão e combustível não aprovada.")
    else:
        if identity.candidate_key != candidate.candidate_key or identity.target_version != candidate.target_version:
            block("TARGET_VERSION_REVIEW_REQUIRED", "identity", "A revisão não corresponde à versão-alvo canônica; nenhuma substituição automática.")
        if int(identity.year_code.split("-", 1)[0]) != candidate.model_year:
            block("MODEL_YEAR_MISMATCH", "identity", "Ano FIPE diferente do ano-alvo.")
        if identity.pbev_cycle != candidate.model_year:
            block("PBEV_YEAR_REVIEW_REQUIRED", "identity", "Ciclo PBEV diferente do ano-alvo exige nova evidência explícita.")
        asset = AUDITED_ASSET_BY_YEAR.get(identity.pbev_cycle)
        if asset is None or identity.pbev_source.sha256 != asset.sha256:
            block("PBEV_ASSET_NOT_AUDITED", "identity", "Hash do documento não corresponde ao ativo PBEV auditado.")
        for field in sorted(CONFIGURATION_FIELDS):
            if not identity.configuration_evidence.get(field, "").strip():
                block("CONFIGURATION_EVIDENCE_MISSING", field, "Equivalência exata entre as configurações FIPE e PBEV não documentada.")
        # Existing legacy TCO has one consumption value and no per-vehicle fuel
        # selector. Do not coerce diesel/hybrid/electric into gasoline here.
        if identity.fuel not in {"gasoline", "flex"}:
            block("FUEL_ADAPTER_NOT_VALIDATED", "fuel", "Compatibilidade com o contrato financeiro legado ainda não validada.")
    for field, unit in REQUIRED_FIELDS.items():
        evidence = dossier.fields.get(field)
        if evidence is None or evidence.kind == "unavailable" or evidence.value is None:
            block("FIELD_EVIDENCE_MISSING", field, f"Sem fonte ou método reproduzível em {unit}; ausência não equivale a zero.")
            continue
        if evidence.kind == "demonstrative":
            block("DEMONSTRATIVE_NOT_ACTIVATABLE", field, "Estimativa demonstrativa não habilita um novo modelo como dado validado.")
        if evidence.unit != unit:
            block("UNIT_MISMATCH", field, f"Unidade obrigatória: {unit}.")
        value = evidence.value
        if value < 0 or (unit == "score/100" and value > 100) or (unit == "km/l" and value <= 0):
            block("VALUE_OUT_OF_RANGE", field, "Valor fora da faixa do contrato.")
        if unit == "level/5" and (value < 1 or value > 5 or value != value.to_integral_value()):
            block("VALUE_OUT_OF_RANGE", field, "Segmento deve ser inteiro de 1 a 5 com evidência.")
        if field.startswith("consumption_") and evidence.kind != "observed":
            block("PBEV_CONSUMPTION_REQUIRED", field, "Consumo deve vir da linha PBEV exata, não de rubrica ou média.")
        if field.startswith("consumption_") and identity and identity.pbev_source not in evidence.references:
            block("PBEV_CONSUMPTION_LINEAGE_MISMATCH", field, "Consumo não referencia a mesma evidência PBEV da identidade.")
    unknown = set(dossier.fields) - set(REQUIRED_FIELDS)
    if unknown:
        block("UNKNOWN_FIELDS", "fields", "Campos fora do contrato: " + ",".join(sorted(unknown)))
    return tuple(issues)


def fipe_target(candidate: Candidate, dossier: Dossier) -> FipeTarget:
    if assess(candidate, dossier):
        raise ValueError("candidate is blocked; no source ingestion target may be emitted")
    assert dossier.identity is not None
    return FipeTarget("car", dossier.identity.fipe_code, dossier.identity.year_code)


def intake_report(selection: Selection, dossiers: tuple[Dossier, ...] = (), *, batch: int | None = None) -> dict:
    if batch not in (None, 1, 2, 3):
        raise ValueError("invalid batch")
    by_id = {r.candidate_id: r for r in dossiers}
    if len(by_id) != len(dossiers):
        raise ValueError("ambiguous duplicate dossiers; no automatic selection")
    canonical_keys = [(r.identity.fipe_code, r.identity.year_code) for r in dossiers if r.identity]
    if len(set(canonical_keys)) != len(canonical_keys):
        raise ValueError("ambiguous duplicate canonical identities; no automatic selection")
    rows = []
    for candidate in selection.candidates:
        if batch is not None and candidate.batch != batch:
            continue
        dossier = by_id.get(candidate.id)
        issues = assess(candidate, dossier)
        identity = dossier.identity if dossier else None
        rows.append({
            "id": candidate.id, "brand": candidate.brand, "model": candidate.model_family,
            "target_version": candidate.target_version, "year": candidate.model_year,
            "batch": candidate.batch, "candidate_key": candidate.candidate_key,
            "canonical_key": f"fipe:car:{identity.fipe_code}:{identity.year_code}" if identity else None,
            "fipe_code": identity.fipe_code if identity else None,
            "year_code": identity.year_code if identity else None,
            "pbev_row_hash": identity.pbev_row_hash if identity else None,
            "status": "blocked" if issues else "dossier_complete_pending_source_and_integration_validation",
            "active": False,
            "blockers": [r.model_dump() for r in issues],
            "unavailable_fields": [r.field for r in issues if r.code == "FIELD_EVIDENCE_MISSING"],
        })
    return {
        "method_version": "catalog-intake-v1", "selection_id": selection.selection_id,
        "selection_sha256": hashlib.sha256(selection.model_dump_json().encode()).hexdigest(),
        "selected": len(rows), "blocked": sum(r["status"] == "blocked" for r in rows),
        "activated": 0, "database_accessed": False, "rows": rows,
        "status": "incomplete_not_activated",
        "next_gate": "exact_source_evidence_and_legacy_activation_adapter",
    }
