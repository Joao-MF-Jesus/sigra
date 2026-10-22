from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from decimal import Decimal
import re
import unicodedata
from typing import Iterable, Mapping, Sequence

from data_platform.contracts.pbev import (
    PBEV_MATCHER_VERSION,
    ExternalVehicleIdentity,
    ExternalVehicleMapping,
    MappingStatus,
    MatchMethod,
    ParsedPbevRow,
)


MATCH_WEIGHTS = {
    "brand": Decimal("10"),
    "model": Decimal("20"),
    "year": Decimal("10"),
    "version": Decimal("20"),
    "motor": Decimal("15"),
    "transmission": Decimal("10"),
    "fuel_propulsion": Decimal("10"),
    "body_style": Decimal("5"),
}

ENGINE_DISPLACEMENT_TOLERANCE_CC = Decimal("50")

_BRAND_ALIASES = {
    "volkswagen": "vw",
    "vw": "vw",
    "vw volkswagen": "vw",
    "volkswagen vw": "vw",
    "chevrolet": "chevrolet",
    "gm chevrolet": "chevrolet",
    "caoa chery": "chery",
    "chery": "chery",
}
_GENERIC_VERSION_WORDS = frozenset(
    {
        "a",
        "aro",
        "at",
        "aut",
        "automatico",
        "cv",
        "flex",
        "hatch",
        "hatchback",
        "l",
        "m",
        "mec",
        "mecanico",
        "mt",
        "p",
        "rodas",
        "sedan",
        "t",
        "v",
    }
)
_GENERIC_MODEL_WORDS = frozenset(
    {
        "automatico",
        "aut",
        "combustivel",
        "econoflex",
        "flex",
        "flexone",
        "flexpower",
        "gasolina",
        "hatch",
        "hatchback",
        "manual",
        "mec",
        "novo",
        "new",
        "portas",
        "sedan",
        "tflex",
    }
)
_AUTOMATIC_TRANSMISSIONS = frozenset({"automatic", "automated", "cvt"})
_COMPATIBLE_VERSION_SUFFIX_WORDS = frozenset({"live", "start", "stop"})
_VERSION_TOKEN_ALIASES = {"llive": "live"}


def normalize_match_text(value: str | None) -> str:
    if not value:
        return ""
    decomposed = unicodedata.normalize("NFKD", value)
    text = "".join(char for char in decomposed if not unicodedata.combining(char))
    text = re.sub(r"[^a-z0-9]+", " ", text.casefold())
    return " ".join(text.split())


def _tokens(value: str | None) -> set[str]:
    return {item for item in normalize_match_text(value).split() if item}


def _split_alphanumeric_tokens(value: str | None) -> set[str]:
    normalized = normalize_match_text(value)
    expanded = re.sub(r"(?<=\d)(?=[a-z])|(?<=[a-z])(?=\d)", " ", normalized)
    return {item for item in expanded.split() if item}


def _brand(value: str | None) -> str:
    normalized = normalize_match_text(value)
    return _BRAND_ALIASES.get(normalized, normalized)


def _model_signature(value: str | None) -> tuple[str, ...]:
    tokens = [
        item
        for item in normalize_match_text(value).split()
        if item not in _GENERIC_MODEL_WORDS
        and not re.fullmatch(r"\d+(?:v|p|cv)?", item)
        and not re.fullmatch(r"my\d{2,4}", item)
    ]
    if not tokens:
        return ()
    primary = tokens[0]
    if primary == "onix":
        qualifiers = tuple(item for item in ("plus", "joy") if item in tokens)
        return (primary, *qualifiers)
    if primary == "corolla" and "cross" in tokens:
        return (primary, "cross")
    if primary == "t" and len(tokens) > 1 and tokens[1] == "cross":
        return ("t", "cross")
    return (primary,)


def _model_compatible(target: ExternalVehicleIdentity, candidate: ParsedPbevRow) -> bool:
    expected = _model_signature(target.catalog_model_name or target.model_name)
    observed = _model_signature(candidate.model_name)
    return bool(expected and observed and expected == observed)


def _meaningful_version_tokens(value: str | None) -> set[str]:
    return {
        _VERSION_TOKEN_ALIASES.get(item, item)
        for item in _split_alphanumeric_tokens(value)
        if item not in _GENERIC_VERSION_WORDS
        and not (item.isdigit() and int(item) < 100)
        and not re.fullmatch(r"my\d{2,4}", item)
    }


def _identity_version_tokens(value: str | None) -> tuple[str, ...]:
    return tuple(
        sorted(
            _VERSION_TOKEN_ALIASES.get(item, item)
            for item in normalize_match_text(value).split()
            if item not in _GENERIC_VERSION_WORDS
            and not re.fullmatch(r"my\d{2,4}", item)
        )
    )


def _version_evidence(
    target: ExternalVehicleIdentity,
    candidate: ParsedPbevRow,
) -> tuple[bool, bool, bool]:
    explicit = _meaningful_version_tokens(target.version_name)
    if not explicit and target.catalog_model_name:
        catalog = _meaningful_version_tokens(target.catalog_model_name)
        model = _meaningful_version_tokens(candidate.model_name)
        explicit = catalog - model
    if not explicit:
        return False, False, False
    candidate_version = _meaningful_version_tokens(candidate.version_name)
    if not candidate_version:
        return False, False, False
    matched = explicit.issubset(candidate_version)
    if not matched:
        return False, True, False
    extras = candidate_version - explicit
    grouped = bool(candidate.version_name and re.search(r"[/|]", candidate.version_name))
    if extras and not grouped and not extras.issubset(_COMPATIBLE_VERSION_SUFFIX_WORDS):
        return False, True, False
    return True, False, not extras


def _displacement_cc(value: str | None) -> Decimal | None:
    if not value:
        return None
    decomposed = unicodedata.normalize("NFKD", value)
    text = "".join(char for char in decomposed if not unicodedata.combining(char))
    text = text.casefold().replace("³", "3")
    cc_match = re.search(r"(?<!\d)(\d{1,2}(?:[.\s]\d{3})|\d{3,4})\s*(?:cc|cm\s*3)\b", text)
    if cc_match:
        displacement = Decimal(re.sub(r"[.\s]", "", cc_match.group(1)))
        return displacement if Decimal("600") <= displacement <= Decimal("8000") else None
    litre_match = re.search(r"(?<!\d)(\d{1,2}[.,]\d)(?:\s*[lt])?(?=\s|[-/]|$)", text)
    if not litre_match:
        return None
    displacement = Decimal(litre_match.group(1).replace(",", ".")) * Decimal("1000")
    return displacement if Decimal("600") <= displacement <= Decimal("8000") else None


def _motor_compatible(target: str | None, candidate: str | None) -> tuple[bool, bool]:
    if not target:
        return False, False
    target_cc = _displacement_cc(target)
    candidate_cc = _displacement_cc(candidate)
    if target_cc is None or candidate_cc is None:
        return False, False
    compatible = abs(target_cc - candidate_cc) <= ENGINE_DISPLACEMENT_TOLERANCE_CC
    return compatible, not compatible


def _transmission_kind(value: str | None) -> str | None:
    normalized = normalize_match_text(value)
    if not normalized:
        return None
    if re.search(r"\bcvt\b", normalized):
        return "cvt"
    if re.search(r"\bmta\b|\bdct\b|dupla embreagem", normalized):
        return "automated"
    if re.search(r"\bmanual\b|\bmec\b|\bmt\b|\bm\s*\d\b", normalized):
        return "manual"
    if re.search(r"\bautomatic|\baut\b|\bat\b|\ba\s*\d\b", normalized):
        return "automatic"
    return None


def _transmission_compatible(target: str | None, candidate: str | None) -> tuple[bool, bool]:
    if not target:
        return False, False
    target_kind = _transmission_kind(target)
    candidate_kind = _transmission_kind(candidate)
    if target_kind is None or candidate_kind is None:
        return False, False
    if target_kind == "automatic":
        compatible = candidate_kind in _AUTOMATIC_TRANSMISSIONS
        return compatible, not compatible
    return target_kind == candidate_kind, target_kind != candidate_kind


def _qualified_model_year(*values: str | None) -> int | None:
    for value in values:
        if not value:
            continue
        normalized = normalize_match_text(value)
        match = re.search(r"\bmy\s*(\d{2,4})\b", normalized)
        if not match:
            match = re.search(r"\b(20\d{2})\b", normalized)
        if match:
            year = int(match.group(1))
            return 2000 + year if year < 100 else year
    return None


def _body_kind(*values: str | None) -> str | None:
    normalized = " ".join(normalize_match_text(value) for value in values if value)
    if not normalized:
        return None
    if "hatch" in normalized:
        return "hatch"
    if re.search(r"\bsedan\b|\bseda\b", normalized):
        return "sedan"
    if "utilitario esportivo" in normalized or re.search(r"\bsuv\b|\bcrossover\b", normalized):
        return "suv"
    if "picape" in normalized or "pickup" in normalized:
        return "pickup"
    if "minivan" in normalized:
        return "minivan"
    return None


def _door_count(*values: str | None) -> int | None:
    for value in values:
        normalized = normalize_match_text(value)
        match = re.search(r"\b([2345])\s*p\b|\b([2345])\s*portas?\b", normalized)
        if match:
            return int(match.group(1) or match.group(2))
    return None


def _candidate_identity_key(candidate: ParsedPbevRow) -> tuple[object, ...]:
    return (
        _brand(candidate.brand_name),
        _model_signature(candidate.model_name),
        _qualified_model_year(candidate.model_name, candidate.version_name) or candidate.raw.cycle_year,
        _identity_version_tokens(candidate.version_name),
        _displacement_cc(candidate.motor_description),
        _transmission_kind(candidate.transmission_code),
        candidate.fuel_type,
        _body_kind(candidate.model_name, candidate.category_name),
        _door_count(candidate.model_name, candidate.version_name, candidate.category_name),
    )


def _missing_version_has_comparable_versioned_peer(
    target: ExternalVehicleIdentity,
    candidate: ParsedPbevRow,
    candidates: Sequence[ParsedPbevRow],
) -> bool:
    if not _meaningful_version_tokens(target.version_name) or _meaningful_version_tokens(candidate.version_name):
        return False
    for peer in candidates:
        if peer is candidate or not _meaningful_version_tokens(peer.version_name):
            continue
        if _brand(target.brand_name) != _brand(peer.brand_name):
            continue
        if not _model_compatible(target, peer):
            continue
        peer_year = _qualified_model_year(peer.model_name, peer.version_name)
        if peer.raw.cycle_year != target.model_year or peer_year not in {None, target.model_year}:
            continue
        motor_match, _ = _motor_compatible(target.motor_description, peer.motor_description)
        if target.motor_description and not motor_match:
            continue
        transmission_match, _ = _transmission_compatible(
            target.transmission_type,
            peer.transmission_code,
        )
        if target.transmission_type and not transmission_match:
            continue
        fuel_match, _ = _fuel_compatible(target.fuel_type, peer.fuel_type)
        if not fuel_match:
            continue
        return True
    return False


def _fuel_compatible(target: str, candidate: str | None) -> tuple[bool, bool]:
    if not candidate:
        return False, False
    expected = normalize_match_text(target)
    aliases = {"flex fuel": "flex", "gasolina": "gasoline", "etanol": "ethanol", "eletrico": "electric"}
    expected = aliases.get(expected, expected)
    return expected == candidate, expected != candidate


def score_candidate(
    target: ExternalVehicleIdentity,
    candidate: ParsedPbevRow,
) -> tuple[Decimal, Mapping[str, object], tuple[str, ...]]:
    evidence: dict[str, object] = {}
    conflicts: list[str] = []
    score = Decimal("0")

    brand_match = _brand(target.brand_name) == _brand(candidate.brand_name)
    evidence["brand"] = brand_match
    if not brand_match:
        conflicts.append("brand")
    else:
        score += MATCH_WEIGHTS["brand"]

    model_match = _model_compatible(target, candidate)
    evidence["model"] = model_match
    if not model_match:
        conflicts.append("model")
    else:
        score += MATCH_WEIGHTS["model"]

    qualified_year = _qualified_model_year(candidate.model_name, candidate.version_name)
    year_match = target.model_year == candidate.raw.cycle_year and qualified_year in {
        None,
        target.model_year,
    }
    evidence["year"] = {
        "matched": year_match,
        "cycle_year": candidate.raw.cycle_year,
        "qualified_year": qualified_year,
    }
    if not year_match:
        conflicts.append("year")
    else:
        score += MATCH_WEIGHTS["year"]

    version_match, version_conflict, version_exact = _version_evidence(target, candidate)
    evidence["version"] = {
        "matched": version_match,
        "conflict": version_conflict,
        "exact": version_exact,
    }
    if version_match:
        score += MATCH_WEIGHTS["version"]
    elif version_conflict:
        conflicts.append("version")

    motor_match, motor_conflict = _motor_compatible(target.motor_description or target.model_name, candidate.motor_description)
    evidence["motor"] = {"matched": motor_match, "conflict": motor_conflict}
    if motor_match:
        score += MATCH_WEIGHTS["motor"]
    elif motor_conflict:
        conflicts.append("motor")

    transmission_match, transmission_conflict = _transmission_compatible(target.transmission_type or target.model_name, candidate.transmission_code)
    evidence["transmission"] = {"matched": transmission_match, "conflict": transmission_conflict}
    if transmission_match:
        score += MATCH_WEIGHTS["transmission"]
    elif transmission_conflict:
        conflicts.append("transmission")

    fuel_match, fuel_conflict = _fuel_compatible(target.fuel_type, candidate.fuel_type)
    evidence["fuel_propulsion"] = {"matched": fuel_match, "conflict": fuel_conflict}
    if fuel_match:
        score += MATCH_WEIGHTS["fuel_propulsion"]
    elif fuel_conflict:
        conflicts.append("fuel")

    target_body = _body_kind(target.body_style, target.model_name)
    candidate_body = _body_kind(candidate.model_name, candidate.category_name)
    body_match = bool(target_body and candidate_body and target_body == candidate_body)
    body_conflict = bool(target_body and candidate_body and target_body != candidate_body)
    evidence["body_style"] = {
        "matched": body_match,
        "conflict": body_conflict,
        "target": target_body,
        "candidate": candidate_body,
    }
    if body_match:
        score += MATCH_WEIGHTS["body_style"]
    elif body_conflict:
        conflicts.append("body_style")

    target_doors = target.evidence.get("door_count") or _door_count(target.model_name)
    candidate_doors = _door_count(candidate.model_name, candidate.version_name, candidate.category_name)
    doors_match = bool(target_doors and candidate_doors and int(target_doors) == candidate_doors)
    doors_conflict = bool(target_doors and candidate_doors and int(target_doors) != candidate_doors)
    evidence["doors"] = {
        "matched": doors_match,
        "conflict": doors_conflict,
        "target": target_doors,
        "candidate": candidate_doors,
    }
    if doors_conflict:
        conflicts.append("doors")

    return score, evidence, tuple(conflicts)


def match_vehicle(
    target: ExternalVehicleIdentity,
    candidates: Iterable[ParsedPbevRow],
) -> ExternalVehicleMapping:
    identity_evidence = {
        "vehicle_sk": target.vehicle_sk,
        "external_catalog_reference": target.external_catalog_reference,
        "brand_name": target.brand_name,
        "model_name": target.model_name,
        "catalog_model_name": target.catalog_model_name,
        "model_year": target.model_year,
        "fuel_type": target.fuel_type,
        "version_name": target.version_name,
        "motor_description": target.motor_description,
        "transmission_type": target.transmission_type,
        "body_style": target.body_style,
        "door_count": target.evidence.get("door_count"),
    }
    if target.catalog_conflict:
        return ExternalVehicleMapping(
            target_identity_hash=target.identity_hash,
            target_identity_evidence=identity_evidence,
            mapping_status=MappingStatus.REJECTED,
            match_method=MatchMethod.CATALOG_CONFLICT,
            matcher_version=PBEV_MATCHER_VERSION,
            confidence=Decimal("0.00"),
            review_required=True,
            evidence={"catalog_conflict": True, **dict(target.evidence)},
            decision_reason="catalog identity conflicts with FIPE evidence",
        )

    candidates = tuple(candidates)
    scored = []
    rejected_candidates: list[Mapping[str, object]] = []
    for candidate in candidates:
        score, evidence, conflicts = score_candidate(target, candidate)
        if _missing_version_has_comparable_versioned_peer(target, candidate, candidates):
            conflicts = (*conflicts, "version")
            evidence = {
                **dict(evidence),
                "version": {
                    **dict(evidence["version"]),
                    "conflict": True,
                    "missing_amid_comparable_versioned_candidates": True,
                },
            }
        candidate_evidence = {
            "source_record_key": candidate.raw.source_record_key,
            "row_hash": candidate.raw.row_hash,
            "score": str(score),
            "conflicts": conflicts,
            "semantic_identity": _candidate_identity_key(candidate),
        }
        if any(
            item in conflicts
            for item in (
                "brand",
                "model",
                "year",
                "version",
                "fuel",
                "motor",
                "transmission",
                "body_style",
                "doors",
            )
        ):
            rejected_candidates.append(candidate_evidence)
            continue
        scored.append((score, candidate, evidence, conflicts, candidate_evidence))
    if not scored:
        return ExternalVehicleMapping(
            target_identity_hash=target.identity_hash,
            target_identity_evidence=identity_evidence,
            mapping_status=MappingStatus.NOT_FOUND,
            match_method=MatchMethod.NO_CANDIDATE,
            matcher_version=PBEV_MATCHER_VERSION,
            confidence=None,
            review_required=False,
            evidence={
                "candidate_count": 0,
                "rejected_candidates": tuple(rejected_candidates),
            },
            decision_reason="no compatible PBEV candidate",
        )

    scored.sort(key=lambda item: (-item[0], item[1].raw.row_hash))
    top_score = scored[0][0]
    leaders = [item for item in scored if item[0] == top_score]
    materially_different = len({item[1].material_metrics_key for item in leaders}) > 1
    semantic_identity_count = len({_candidate_identity_key(item[1]) for item in leaders})
    eligible_candidates = tuple(item[4] for item in scored)
    if len(leaders) > 1 and (materially_different or semantic_identity_count > 1):
        reason = (
            "top-scoring candidates have materially different metrics"
            if materially_different
            else "top-scoring candidates represent multiple identities"
        )
        return ExternalVehicleMapping(
            target_identity_hash=target.identity_hash,
            target_identity_evidence=identity_evidence,
            mapping_status=MappingStatus.AMBIGUOUS,
            match_method=MatchMethod.SCORED_RULE,
            matcher_version=PBEV_MATCHER_VERSION,
            confidence=top_score,
            review_required=True,
            evidence={
                "candidate_count": len(scored),
                "candidates": eligible_candidates,
                "rejected_candidates": tuple(rejected_candidates),
                "top_tie_count": len(leaders),
                "semantic_identity_count": semantic_identity_count,
                "materially_different": materially_different,
            },
            decision_reason=reason,
        )

    selected = leaders[0][1]
    if top_score >= Decimal("95"):
        status = MappingStatus.MATCHED
        method = MatchMethod.EXACT_RULE if top_score == Decimal("100") else MatchMethod.SCORED_RULE
        reason = (
            "equivalent candidates satisfy all required evidence"
            if len(leaders) > 1
            else "unique candidate satisfies all required evidence"
        )
    elif top_score >= Decimal("75"):
        status = MappingStatus.PENDING
        method = MatchMethod.SCORED_RULE
        reason = "candidate requires manual review"
    else:
        status = MappingStatus.AMBIGUOUS
        method = MatchMethod.SCORED_RULE
        reason = "candidate evidence is insufficient for automatic matching"
    return ExternalVehicleMapping(
        target_identity_hash=target.identity_hash,
        target_identity_evidence=identity_evidence,
        mapping_status=status,
        match_method=method,
        matcher_version=PBEV_MATCHER_VERSION,
        confidence=top_score,
        review_required=status in {MappingStatus.PENDING, MappingStatus.AMBIGUOUS},
        evidence={
            "candidate_count": len(scored),
            "candidates": eligible_candidates,
            "rejected_candidates": tuple(rejected_candidates),
            "selected_source_record_key": selected.raw.source_record_key,
            "selected_row_hash": selected.raw.row_hash,
            "dimensions": leaders[0][2],
            "equivalent_candidate_count": len(leaders),
            "semantic_identity_count": semantic_identity_count,
        },
        decision_reason=reason,
        vehicle_sk=target.vehicle_sk if status == MappingStatus.MATCHED else None,
        selected_raw_row_id=selected.raw.pbev_raw_row_id,
    )


def supersede_mapping(
    previous: ExternalVehicleMapping,
    *,
    status: MappingStatus,
    reviewer: str,
    reviewed_at: datetime,
    vehicle_sk: int | None,
    selected_raw_row_id: int | None,
    reason: str,
) -> ExternalVehicleMapping:
    if previous.mapping_decision_id is None:
        raise ValueError("persisted mapping is required for supersession")
    return ExternalVehicleMapping(
        target_identity_hash=previous.target_identity_hash,
        target_identity_evidence=previous.target_identity_evidence,
        mapping_status=status,
        match_method=MatchMethod.MANUAL_REVIEW,
        matcher_version=previous.matcher_version,
        confidence=Decimal("100.00") if status == MappingStatus.MATCHED else previous.confidence,
        review_required=False,
        evidence={**dict(previous.evidence), "manual_review": True},
        decision_reason=reason,
        vehicle_sk=vehicle_sk if status == MappingStatus.MATCHED else None,
        selected_raw_row_id=selected_raw_row_id,
        reviewed_by=reviewer,
        reviewed_at=reviewed_at,
        supersedes_mapping_id=previous.mapping_decision_id,
    )


def match_all(
    targets: Sequence[ExternalVehicleIdentity],
    rows: Sequence[ParsedPbevRow],
) -> tuple[ExternalVehicleMapping, ...]:
    by_year: dict[int, list[ParsedPbevRow]] = {}
    for row in rows:
        if row.raw.extraction_status == "parsed":
            by_year.setdefault(row.raw.cycle_year, []).append(row)
    return tuple(match_vehicle(target, by_year.get(target.model_year, ())) for target in targets)
