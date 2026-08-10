from __future__ import annotations

from dataclasses import asdict
from datetime import date, datetime
from decimal import Decimal
import hashlib
import json
from typing import Any, Iterable, Mapping
from uuid import UUID, uuid4

from data_platform.common.logging import sanitize
from data_platform.contracts.gold_vehicle_features import (
    GOLD_MINIMUM_COVERAGE,
    GOLD_SOURCE_NAME,
    GOLD_VEHICLE_TYPE,
    GoldBlockedMapping,
    GoldPublicationPlan,
    GoldPublicationResult,
    GoldRollbackResult,
    GoldScopeRow,
    GoldSnapshotCandidate,
)
from data_platform.publication.loader import GoldLoader
from data_platform.quality.gold_checks import (
    calculate_coverage,
    issue_resolution_is_coherent,
    valid_reference_month,
)


class GoldPublicationError(RuntimeError):
    """Falha tecnica Gold com mensagem sanitizada."""


def _json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, dict):
        return {key: _json_value(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def _fingerprint(
    scope: Iterable[GoldScopeRow],
    candidates: Iterable[GoldSnapshotCandidate],
    blocked: Iterable[GoldBlockedMapping],
    issues: Iterable[Mapping[str, Any]],
) -> str:
    payload = {
        "contract": "gold-vehicle-features-v1",
        "source_name": GOLD_SOURCE_NAME,
        "vehicle_type": GOLD_VEHICLE_TYPE,
        "scope": [
            {
                "mapping_id": row.mapping_id,
                "mapping_status": row.mapping_status,
                "vehicle_sk": row.vehicle_sk,
                "vehicle_type": row.vehicle_type,
                "source_vehicle_key": row.source_vehicle_key,
                "fipe_code": row.fipe_code,
                "year_code": row.year_code,
            }
            for row in sorted(scope, key=lambda item: item.mapping_id)
        ],
        "candidates": [
            asdict(item)
            for item in sorted(candidates, key=lambda item: item.vehicle_sk)
        ],
        "blocked": [
            {"mapping_id": item.mapping_id, "reason_code": item.reason_code}
            for item in sorted(blocked, key=lambda item: item.mapping_id)
        ],
        "issues": [
            {
                "layer_name": str(item["layer_name"]),
                "entity_name": str(item["entity_name"]),
                "record_reference": item["record_reference"],
                "rule_code": str(item["rule_code"]),
                "severity": str(item["severity"]),
                "resolution_status": str(item["resolution_status"]),
            }
            for item in sorted(
                issues,
                key=lambda issue: (
                    str(issue["layer_name"]),
                    str(issue["entity_name"]),
                    str(issue["record_reference"] or ""),
                    str(issue["rule_code"]),
                    str(issue["resolution_status"]),
                ),
            )
        ],
    }
    canonical = json.dumps(
        _json_value(payload),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _record_references(row: GoldScopeRow) -> set[str]:
    references = {f"silver.vehicle_source_mapping:{row.mapping_id}"}
    if row.vehicle_sk is not None:
        references.add(f"silver.vehicle_identity:{row.vehicle_sk}")
    if row.silver_price_id is not None:
        references.add(f"silver.vehicle_price_history:{row.silver_price_id}")
    return references


def _issue_effects(
    row: GoldScopeRow,
    issues: Iterable[Mapping[str, Any]],
) -> tuple[bool, bool]:
    references = _record_references(row)
    blocks = False
    warns = False
    for issue in issues:
        if issue["layer_name"] != "gold":
            continue
        if issue["record_reference"] not in references:
            continue
        status = str(issue["resolution_status"])
        severity = str(issue["severity"])
        if status == "open" and severity == "critical":
            blocks = True
        elif status == "accepted" or severity in {"warning", "error"}:
            warns = True
    return blocks, warns


def _global_quality_effects(
    issues: Iterable[Mapping[str, Any]],
) -> tuple[tuple[str, ...], bool]:
    blockers: list[str] = []
    warns = False
    safe_prefixes = (
        "silver.vehicle_source_mapping:",
        "silver.vehicle_identity:",
        "silver.vehicle_price_history:",
    )
    for issue in issues:
        status = str(issue["resolution_status"])
        severity = str(issue["severity"])
        reference = str(issue["record_reference"] or "")
        if not issue_resolution_is_coherent(status, issue["resolved_at"]):
            blockers.append("INCOHERENT_ISSUE_RESOLUTION")
            continue
        if issue["layer_name"] == "silver":
            if status == "open" and severity == "critical":
                blockers.append(f"SILVER_CRITICAL:{issue['issue_id']}")
            elif status == "accepted" or severity in {"warning", "error"}:
                warns = True
            continue
        if issue["layer_name"] == "gold":
            safely_attributable = reference.startswith(safe_prefixes)
            historical_run_issue = reference.startswith("gold.publication_run:")
            if safely_attributable or historical_run_issue:
                continue
            if status == "open" and severity == "critical":
                blockers.append(f"GOLD_GLOBAL_CRITICAL:{issue['issue_id']}")
            elif status == "accepted" or severity in {"warning", "error"}:
                warns = True
    return tuple(sorted(set(blockers))), warns


def _blocked(row: GoldScopeRow, code: str, message: str) -> GoldBlockedMapping:
    return GoldBlockedMapping(row.mapping_id, code, message)


def _rollback_quality_mismatches(
    snapshot_quality: Mapping[int, str],
    current_candidates: Iterable[GoldSnapshotCandidate],
) -> tuple[int, ...]:
    current_quality = {
        candidate.vehicle_sk: candidate.base_quality_status
        for candidate in current_candidates
    }
    return tuple(
        sorted(
            vehicle_sk
            for vehicle_sk, stored_quality in snapshot_quality.items()
            if stored_quality == "passed"
            and current_quality.get(vehicle_sk) == "warning"
        )
    )


def _evaluate_scope_row(
    row: GoldScopeRow,
    issues: Iterable[Mapping[str, Any]],
    *,
    as_of: date,
    now: datetime,
    global_warning: bool,
) -> GoldSnapshotCandidate | GoldBlockedMapping:
    if row.mapping_status != "matched":
        return _blocked(
            row,
            f"MAPPING_{row.mapping_status.upper()}",
            "Current Silver mapping is not matched",
        )
    if row.vehicle_sk is None:
        return _blocked(row, "MISSING_VEHICLE", "Matched mapping has no vehicle identity")
    if row.source_vehicle_key != f"{row.fipe_code}:{row.year_code}":
        return _blocked(
            row,
            "INVALID_SOURCE_KEY",
            "Silver mapping has an invalid deterministic source key",
        )
    if (
        row.identity_vehicle_sk != row.vehicle_sk
        or row.identity_vehicle_type != GOLD_VEHICLE_TYPE
        or not row.brand_name
        or not row.model_name
        or not row.fuel_type
        or row.identity_run_id is None
    ):
        return _blocked(
            row,
            "INVALID_IDENTITY_LINEAGE",
            "Silver identity lineage is incomplete or incompatible",
        )
    if row.is_zero_km is None:
        return _blocked(row, "INVALID_MODEL_YEAR", "Silver model year state is missing")
    if row.is_zero_km and row.model_year is not None:
        return _blocked(row, "INVALID_MODEL_YEAR", "Zero-km identity has a model year")
    if not row.is_zero_km and (
        row.model_year is None or not 1900 <= row.model_year <= 2100
    ):
        return _blocked(row, "INVALID_MODEL_YEAR", "Silver model year is invalid")
    if (
        row.silver_price_id is None
        or row.price_vehicle_sk != row.vehicle_sk
        or row.price_amount is None
        or row.currency != "BRL"
        or row.reference_month is None
        or row.price_collected_at is None
        or row.data_confidence is None
        or row.price_run_id is None
    ):
        return _blocked(
            row,
            "MISSING_ELIGIBLE_PRICE",
            "Current Silver price lineage is incomplete",
        )
    if row.price_amount <= 0 or not Decimal("0") <= row.data_confidence <= Decimal("100"):
        return _blocked(row, "INVALID_PRICE", "Current Silver price is invalid")
    if not valid_reference_month(row.reference_month, as_of=as_of):
        return _blocked(
            row,
            "INVALID_REFERENCE_MONTH",
            "Silver price reference month is invalid or future",
        )
    if row.price_collected_at > now:
        return _blocked(
            row,
            "FUTURE_COLLECTION_TIME",
            "Silver price collection timestamp is in the future",
        )
    issue_blocks, issue_warns = _issue_effects(row, issues)
    if issue_blocks:
        return _blocked(
            row,
            "APPLICABLE_CRITICAL_ISSUE",
            "An open critical Gold issue blocks this mapping",
        )
    return GoldSnapshotCandidate(
        mapping_id=row.mapping_id,
        vehicle_sk=row.vehicle_sk,
        vehicle_type=row.vehicle_type,
        brand_name=row.brand_name,
        model_name=row.model_name,
        version_name=row.version_name,
        model_year=row.model_year,
        is_zero_km=row.is_zero_km,
        fuel_type=row.fuel_type,
        transmission_type=row.transmission_type,
        silver_price_id=row.silver_price_id,
        fipe_code=row.fipe_code,
        year_code=row.year_code,
        source_vehicle_key=row.source_vehicle_key,
        current_price=row.price_amount,
        currency=row.currency,
        price_source=row.source_name,
        price_reference_month=row.reference_month,
        price_collected_at=row.price_collected_at,
        data_confidence=row.data_confidence,
        base_quality_status=(
            "warning" if global_warning or issue_warns else "passed"
        ),
        silver_identity_run_id=row.identity_run_id,
        silver_mapping_run_id=row.mapping_run_id,
        silver_price_run_id=row.price_run_id,
    )


def build_publication_plan(
    scope: Iterable[GoldScopeRow],
    issues: Iterable[Mapping[str, Any]],
    *,
    as_of: date,
    now: datetime,
) -> GoldPublicationPlan:
    scope_rows = tuple(scope)
    issue_rows = tuple(issues)
    global_blockers, global_warning = _global_quality_effects(issue_rows)
    candidates: list[GoldSnapshotCandidate] = []
    blocked: list[GoldBlockedMapping] = []
    for row in scope_rows:
        result = _evaluate_scope_row(
            row,
            issue_rows,
            as_of=as_of,
            now=now,
            global_warning=global_warning,
        )
        if isinstance(result, GoldBlockedMapping):
            blocked.append(result)
        else:
            candidates.append(result)

    by_vehicle: dict[int, list[GoldSnapshotCandidate]] = {}
    for candidate in candidates:
        by_vehicle.setdefault(candidate.vehicle_sk, []).append(candidate)
    duplicate_mapping_ids = {
        item.mapping_id
        for grouped in by_vehicle.values()
        if len(grouped) > 1
        for item in grouped
    }
    if duplicate_mapping_ids:
        candidates = [
            item for item in candidates if item.mapping_id not in duplicate_mapping_ids
        ]
        blocked.extend(
            GoldBlockedMapping(
                mapping_id,
                "DUPLICATE_VEHICLE_MAPPING",
                "More than one eligible current mapping points to the same vehicle",
                severity="critical",
            )
            for mapping_id in sorted(duplicate_mapping_ids)
        )

    candidates.sort(key=lambda item: (item.vehicle_sk, item.mapping_id))
    blocked.sort(key=lambda item: item.mapping_id)
    expected = len(scope_rows)
    published = len(candidates)
    coverage = calculate_coverage(expected, published)
    base_quality = (
        "warning"
        if global_warning
        or any(item.base_quality_status == "warning" for item in candidates)
        else "passed"
    )
    fingerprint = _fingerprint(scope_rows, candidates, blocked, issue_rows)
    return GoldPublicationPlan(
        expected_count=expected,
        published_count=published,
        blocked_count=expected - published,
        coverage_percentage=coverage,
        fingerprint=fingerprint,
        base_quality_status=base_quality,
        candidates=tuple(candidates),
        blocked_mappings=tuple(blocked),
        global_blockers=global_blockers,
    )


def _skipped_publication(message: str) -> GoldPublicationResult:
    return GoldPublicationResult(
        pipeline_run_id=None,
        dataset_version=None,
        status="skipped",
        expected_count=0,
        published_count=0,
        blocked_count=0,
        coverage_percentage=Decimal("0.00"),
        fingerprint=None,
        issues_recorded=0,
        errors=(message,),
    )


def run_gold_publication(
    loader: GoldLoader,
    *,
    trigger_type: str = "manual",
    source_reference: str | None = None,
    git_commit: str | None = None,
) -> GoldPublicationResult:
    if not loader.is_postgresql:
        return _skipped_publication(
            "SQLite no-op: Gold Vehicle Features requires PostgreSQL"
        )

    run_id = uuid4()
    placeholder = f"gold-building-{str(run_id)[:12]}"
    try:
        loader.start_run(
            run_id,
            placeholder,
            pipeline_name="fipe_vehicle_features_gold",
            trigger_type=trigger_type,
            source_reference=source_reference,
            git_commit=git_commit,
        )
    except Exception as exc:
        raise GoldPublicationError(
            f"failed to start Gold pipeline run: {sanitize(exc)}"
        ) from None

    result: GoldPublicationResult | None = None
    try:
        with loader.publication_transaction() as connection:
            now = loader.database_now(connection)
            scope = loader.fetch_scope(connection)
            issues = loader.fetch_applicable_issues(connection)
            plan = build_publication_plan(
                scope,
                issues,
                as_of=now.date(),
                now=now,
            )
            dataset_version = (
                f"gold-fipe-car-v1-{plan.fingerprint[:12]}-{str(run_id)[:8]}"
            )
            loader.update_run_dataset_version(connection, run_id, dataset_version)
            loader.resolve_cleared_blocked_issues(
                connection,
                run_id,
                {item.mapping_id for item in plan.blocked_mappings},
            )
            issue_ids = {
                loader.record_blocked_issue(connection, run_id, item)
                for item in plan.blocked_mappings
            }

            rejection_rules: list[tuple[str, str, str, Mapping[str, Any]]] = []
            if plan.expected_count == 0:
                rejection_rules.append(
                    (
                        "GOLD_EMPTY_SCOPE",
                        "critical",
                        "Gold publication scope has no current vehicle mappings",
                        {"expected_count": 0},
                    )
                )
            if plan.global_blockers:
                rejection_rules.append(
                    (
                        "GOLD_GLOBAL_QUALITY_BLOCKER",
                        "critical",
                        "Open global critical issues block Gold activation",
                        {"blocker_count": len(plan.global_blockers)},
                    )
                )
            if plan.expected_count > 0 and plan.published_count == 0:
                rejection_rules.append(
                    (
                        "GOLD_NO_PUBLISHABLE_VEHICLES",
                        "critical",
                        "Gold publication produced no eligible vehicles",
                        {"expected_count": plan.expected_count},
                    )
                )
            if (
                plan.expected_count > 0
                and plan.coverage_percentage < GOLD_MINIMUM_COVERAGE
            ):
                rejection_rules.append(
                    (
                        "GOLD_COVERAGE_BELOW_THRESHOLD",
                        "critical",
                        "Gold coverage is below the required threshold",
                        {
                            "coverage_percentage": plan.coverage_percentage,
                            "minimum_coverage": GOLD_MINIMUM_COVERAGE,
                        },
                    )
                )
            for rule, severity, message, details in rejection_rules:
                issue_ids.add(
                    loader.record_run_issue(
                        connection,
                        run_id,
                        rule_code=rule,
                        severity=severity,
                        message=message,
                        details=details,
                    )
                )

            if rejection_rules:
                loader.finish_run(
                    connection,
                    run_id,
                    "rejected",
                    expected=plan.expected_count,
                    inserted=0,
                    deduplicated=0,
                    rejected=plan.blocked_count,
                    error_summary="; ".join(item[0] for item in rejection_rules),
                )
                result = GoldPublicationResult(
                    pipeline_run_id=str(run_id),
                    dataset_version=dataset_version,
                    status="rejected",
                    expected_count=plan.expected_count,
                    published_count=plan.published_count,
                    blocked_count=plan.blocked_count,
                    coverage_percentage=plan.coverage_percentage,
                    fingerprint=plan.fingerprint,
                    issues_recorded=len(issue_ids),
                    errors=tuple(item[0] for item in rejection_rules),
                )
            else:
                active = loader.active_dataset(connection)
                if active is not None and active["dataset_fingerprint"] == plan.fingerprint:
                    if not loader.validate_dataset_snapshot(connection, active):
                        raise RuntimeError("Active Gold dataset failed snapshot validation")
                    if (
                        int(active["expected_vehicle_count"]) != plan.expected_count
                        or int(active["published_vehicle_count"])
                        != plan.published_count
                        or int(active["blocked_vehicle_count"]) != plan.blocked_count
                    ):
                        raise RuntimeError("Active Gold dataset has inconsistent counts")
                    loader.update_run_dataset_version(
                        connection,
                        run_id,
                        str(active["dataset_version"]),
                    )
                    loader.finish_run(
                        connection,
                        run_id,
                        "succeeded",
                        expected=plan.expected_count,
                        inserted=0,
                        deduplicated=plan.published_count,
                        rejected=plan.blocked_count,
                    )
                    result = GoldPublicationResult(
                        pipeline_run_id=str(run_id),
                        dataset_version=str(active["dataset_version"]),
                        status="deduplicated",
                        expected_count=plan.expected_count,
                        published_count=plan.published_count,
                        blocked_count=plan.blocked_count,
                        coverage_percentage=plan.coverage_percentage,
                        fingerprint=plan.fingerprint,
                        issues_recorded=len(issue_ids),
                    )
                else:
                    minimum_reference = min(
                        item.price_reference_month for item in plan.candidates
                    )
                    maximum_reference = max(
                        item.price_reference_month for item in plan.candidates
                    )
                    loader.insert_dataset(
                        connection,
                        run_id,
                        dataset_version,
                        plan,
                        minimum_reference_month=minimum_reference,
                        maximum_reference_month=maximum_reference,
                    )
                    loader.insert_snapshot(
                        connection,
                        run_id,
                        dataset_version,
                        plan.candidates,
                        now,
                    )
                    inserted_dataset = loader.dataset(connection, dataset_version)
                    if inserted_dataset is None or not loader.validate_dataset_snapshot(
                        connection, inserted_dataset
                    ):
                        raise RuntimeError("New Gold dataset failed snapshot validation")
                    previous = str(active["dataset_version"]) if active is not None else None
                    loader.activate_dataset(
                        connection,
                        run_id,
                        dataset_version,
                        previous_dataset_version=previous,
                        activation_type="replacement" if previous else "initial",
                        activated_at=now,
                    )
                    loader.finish_run(
                        connection,
                        run_id,
                        "succeeded",
                        expected=plan.expected_count,
                        inserted=plan.published_count,
                        deduplicated=0,
                        rejected=plan.blocked_count,
                    )
                    result = GoldPublicationResult(
                        pipeline_run_id=str(run_id),
                        dataset_version=dataset_version,
                        status="succeeded",
                        expected_count=plan.expected_count,
                        published_count=plan.published_count,
                        blocked_count=plan.blocked_count,
                        coverage_percentage=plan.coverage_percentage,
                        fingerprint=plan.fingerprint,
                        issues_recorded=len(issue_ids),
                    )
        assert result is not None
        return result
    except Exception as exc:
        safe_error = sanitize(exc)
        try:
            loader.finish_failed(run_id, safe_error)
        except Exception as finish_exc:
            safe_error = (
                f"{safe_error}; failed to finalize Gold run: {sanitize(finish_exc)}"
            )
        raise GoldPublicationError(safe_error) from None


def rollback_gold_dataset(
    loader: GoldLoader,
    dataset_version: str,
    *,
    source_reference: str | None = None,
    git_commit: str | None = None,
) -> GoldRollbackResult:
    if not loader.is_postgresql:
        return GoldRollbackResult(
            pipeline_run_id=None,
            dataset_version=dataset_version,
            previous_dataset_version=None,
            status="skipped",
            expected_count=0,
            published_count=0,
            blocked_count=0,
            coverage_percentage=Decimal("0.00"),
            errors=("SQLite no-op: Gold rollback requires PostgreSQL",),
        )

    run_id = uuid4()
    placeholder = f"gold-rollback-{str(run_id)[:12]}"
    try:
        loader.start_run(
            run_id,
            placeholder,
            pipeline_name="fipe_vehicle_features_gold_rollback",
            trigger_type="manual",
            source_reference=source_reference or dataset_version,
            git_commit=git_commit,
        )
    except Exception as exc:
        raise GoldPublicationError(
            f"failed to start Gold rollback run: {sanitize(exc)}"
        ) from None

    result: GoldRollbackResult | None = None
    try:
        with loader.publication_transaction() as connection:
            now = loader.database_now(connection)
            target = loader.dataset(connection, dataset_version)
            active = loader.active_dataset(connection)
            if target is None:
                raise ValueError("Requested Gold dataset does not exist")
            if not loader.validate_dataset_snapshot(connection, target):
                raise ValueError("Requested Gold dataset failed snapshot validation")
            if active is None:
                raise ValueError("Gold rollback requires an active dataset")
            if active["dataset_version"] == dataset_version:
                loader.update_run_dataset_version(connection, run_id, dataset_version)
                loader.finish_run(
                    connection,
                    run_id,
                    "succeeded",
                    expected=int(target["expected_vehicle_count"]),
                    inserted=0,
                    deduplicated=int(target["published_vehicle_count"]),
                    rejected=int(target["blocked_vehicle_count"]),
                )
                result = GoldRollbackResult(
                    pipeline_run_id=str(run_id),
                    dataset_version=dataset_version,
                    previous_dataset_version=dataset_version,
                    status="deduplicated",
                    expected_count=int(target["expected_vehicle_count"]),
                    published_count=int(target["published_vehicle_count"]),
                    blocked_count=int(target["blocked_vehicle_count"]),
                    coverage_percentage=Decimal(target["coverage_percentage"]),
                )
            else:
                scope = loader.fetch_scope(connection)
                issues = loader.fetch_applicable_issues(connection)
                current_plan = build_publication_plan(
                    scope,
                    issues,
                    as_of=now.date(),
                    now=now,
                )
                target_quality = loader.snapshot_base_quality_by_vehicle(
                    connection,
                    dataset_version,
                )
                target_vehicle_ids = set(target_quality)
                eligible_vehicle_ids = {
                    item.vehicle_sk for item in current_plan.candidates
                }
                invalid_target_ids = target_vehicle_ids - eligible_vehicle_ids
                quality_mismatch_ids = _rollback_quality_mismatches(
                    target_quality,
                    current_plan.candidates,
                )
                published = len(target_vehicle_ids)
                expected = current_plan.expected_count
                coverage = (
                    calculate_coverage(expected, published)
                    if expected > 0 and published <= expected
                    else Decimal("0.00")
                )
                rejection_codes: list[str] = []
                if current_plan.global_blockers:
                    rejection_codes.append("GOLD_GLOBAL_QUALITY_BLOCKER")
                if invalid_target_ids:
                    rejection_codes.append("GOLD_ROLLBACK_INELIGIBLE_SNAPSHOT")
                if quality_mismatch_ids:
                    rejection_codes.append("GOLD_ROLLBACK_QUALITY_MISMATCH")
                if expected <= 0 or published <= 0 or published > expected:
                    rejection_codes.append("GOLD_ROLLBACK_INVALID_COUNTS")
                if expected > 0 and coverage < GOLD_MINIMUM_COVERAGE:
                    rejection_codes.append("GOLD_COVERAGE_BELOW_THRESHOLD")
                issue_ids = {
                    loader.record_blocked_issue(connection, run_id, item)
                    for item in current_plan.blocked_mappings
                }
                for candidate in current_plan.candidates:
                    if candidate.vehicle_sk not in target_vehicle_ids:
                        issue_ids.add(
                            loader.record_blocked_issue(
                                connection,
                                run_id,
                                GoldBlockedMapping(
                                    candidate.mapping_id,
                                    "ROLLBACK_SNAPSHOT_GAP",
                                    "Requested rollback snapshot does not contain this current mapping",
                                ),
                            )
                        )
                if rejection_codes:
                    quality_mismatch = bool(quality_mismatch_ids)
                    issue_ids.add(
                        loader.record_run_issue(
                            connection,
                            run_id,
                            rule_code=(
                                "GOLD_ROLLBACK_QUALITY_MISMATCH"
                                if quality_mismatch
                                else "GOLD_ROLLBACK_REJECTED"
                            ),
                            severity="critical",
                            message=(
                                "Gold rollback snapshot quality is incompatible "
                                "with current quality requirements"
                                if quality_mismatch
                                else "Gold rollback failed current quality validation"
                            ),
                            details={
                                "rejection_count": len(rejection_codes),
                                "quality_mismatch_count": len(quality_mismatch_ids),
                            },
                        )
                    )
                    loader.update_run_dataset_version(connection, run_id, dataset_version)
                    loader.finish_run(
                        connection,
                        run_id,
                        "rejected",
                        expected=expected,
                        inserted=0,
                        deduplicated=0,
                        rejected=max(0, expected - published),
                        error_summary="; ".join(rejection_codes),
                    )
                    result = GoldRollbackResult(
                        pipeline_run_id=str(run_id),
                        dataset_version=dataset_version,
                        previous_dataset_version=str(active["dataset_version"]),
                        status="rejected",
                        expected_count=expected,
                        published_count=published,
                        blocked_count=max(0, expected - published),
                        coverage_percentage=coverage,
                        errors=tuple(rejection_codes),
                    )
                else:
                    loader.update_run_dataset_version(connection, run_id, dataset_version)
                    loader.activate_dataset(
                        connection,
                        run_id,
                        dataset_version,
                        previous_dataset_version=str(active["dataset_version"]),
                        activation_type="rollback",
                        activated_at=now,
                    )
                    loader.finish_run(
                        connection,
                        run_id,
                        "succeeded",
                        expected=expected,
                        inserted=published,
                        deduplicated=0,
                        rejected=expected - published,
                    )
                    result = GoldRollbackResult(
                        pipeline_run_id=str(run_id),
                        dataset_version=dataset_version,
                        previous_dataset_version=str(active["dataset_version"]),
                        status="succeeded",
                        expected_count=expected,
                        published_count=published,
                        blocked_count=expected - published,
                        coverage_percentage=coverage,
                    )
        assert result is not None
        return result
    except Exception as exc:
        safe_error = sanitize(exc)
        try:
            loader.finish_failed(run_id, safe_error)
        except Exception as finish_exc:
            safe_error = (
                f"{safe_error}; failed to finalize Gold rollback: {sanitize(finish_exc)}"
            )
        raise GoldPublicationError(safe_error) from None
