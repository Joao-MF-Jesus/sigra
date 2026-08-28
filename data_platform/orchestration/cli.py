from __future__ import annotations

import argparse
from dataclasses import replace
from datetime import date
import json
import os
from uuid import UUID

from data_platform.anp.sources import ANP_LAST_FOUR_WEEKS_REFERENCE
from data_platform.common.config import load_settings
from data_platform.common.database import create_platform_engine
from data_platform.common.logging import sanitize
from data_platform.orchestration.contracts import (
    OrchestrationRequest,
    OrchestrationScope,
    FIPE_STEP_ORDER,
    PartialPolicy,
    PipelineBindings,
    StepName,
    TriggerType,
)
from data_platform.orchestration.policies import ExecutionPolicy
from data_platform.orchestration.prefect_flow import (
    PrefectScheduleConfig,
    run_prefect_flow,
    serve_prefect_flow,
)
from data_platform.orchestration.repository import (
    InMemoryOrchestrationRepository,
    PostgresqlOrchestrationRepository,
    repository_result,
)
from data_platform.orchestration.runner import (
    OrchestrationRunner,
    _result_from_repository,
    build_default_bindings,
)


def _date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("use YYYY-MM-DD") from exc


def _add_run_arguments(parser: argparse.ArgumentParser) -> None:
    default_scope = os.getenv(
        "DATA_PLATFORM_ORCHESTRATION_SCOPE",
        OrchestrationScope.FIPE.value,
    )
    default_start = os.getenv(
        "DATA_PLATFORM_ORCHESTRATION_START_STEP",
        StepName.BRONZE.value,
    )
    default_trigger = os.getenv(
        "DATA_PLATFORM_ORCHESTRATION_TRIGGER_TYPE",
        TriggerType.MANUAL.value,
    )
    default_partial = os.getenv(
        "DATA_PLATFORM_ORCHESTRATION_PARTIAL_POLICY",
        PartialPolicy.CONTINUE.value,
    )
    parser.add_argument(
        "--scope",
        choices=tuple(item.value for item in OrchestrationScope),
        default=default_scope,
        help="fipe (padrao), pbev, anp, integrated_vehicle_cost ou complete",
    )
    parser.add_argument(
        "--from-step",
        choices=tuple(item.value for item in FIPE_STEP_ORDER),
        default=default_start,
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--trigger-type",
        choices=tuple(item.value for item in TriggerType),
        default=default_trigger,
    )
    parser.add_argument(
        "--source-reference",
        default=os.getenv("DATA_PLATFORM_ORCHESTRATION_SOURCE_REFERENCE"),
    )
    parser.add_argument(
        "--git-commit",
        default=os.getenv("DATA_PLATFORM_ORCHESTRATION_GIT_COMMIT"),
    )
    parser.add_argument(
        "--pbev-asset-dir",
        default=os.getenv("PBEV_ASSET_DIR"),
    )
    parser.add_argument(
        "--anp-source-reference",
        choices=(ANP_LAST_FOUR_WEEKS_REFERENCE,),
        default=os.getenv(
            "DATA_PLATFORM_ORCHESTRATION_ANP_SOURCE_REFERENCE",
            ANP_LAST_FOUR_WEEKS_REFERENCE,
        ),
    )
    parser.add_argument("--integrated-geography-level", choices=("municipality", "state"))
    parser.add_argument("--integrated-geography-key")
    parser.add_argument("--integrated-week-start", type=_date)
    parser.add_argument(
        "--integrated-include-additized",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    parser.add_argument(
        "--idempotency-key",
        default=os.getenv("DATA_PLATFORM_ORCHESTRATION_IDEMPOTENCY_KEY"),
    )
    parser.add_argument("--resume", action="store_true")
    parser.add_argument(
        "--partial-policy",
        choices=tuple(item.value for item in PartialPolicy),
        default=default_partial,
    )
    parser.add_argument(
        "--max-attempts",
        type=int,
        default=int(os.getenv("DATA_PLATFORM_ORCHESTRATION_MAX_ATTEMPTS", "2")),
    )
    parser.add_argument(
        "--backoff-seconds",
        type=float,
        default=float(
            os.getenv("DATA_PLATFORM_ORCHESTRATION_BACKOFF_SECONDS", "1")
        ),
    )
    parser.add_argument(
        "--step-timeout-seconds",
        type=float,
        default=float(
            os.getenv("DATA_PLATFORM_ORCHESTRATION_STEP_TIMEOUT_SECONDS", "300")
        ),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Orquestracao FIPE, PBEV, ANP e Gold integrada da plataforma SIGRA"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    run = subparsers.add_parser("run", help="Executa o nucleo local")
    _add_run_arguments(run)
    result = subparsers.add_parser("result", help="Consulta uma execucao")
    result.add_argument("orchestration_run_id", type=UUID)
    prefect = subparsers.add_parser("prefect", help="Executa o flow Prefect local")
    _add_run_arguments(prefect)
    prefect.add_argument(
        "--serve-cron",
        help="Inicia um deployment local agendado com esta expressao cron",
    )
    prefect.add_argument(
        "--timezone",
        default=os.getenv(
            "DATA_PLATFORM_ORCHESTRATION_TIMEZONE",
            "America/Sao_Paulo",
        ),
    )
    prefect.add_argument(
        "--deployment-name",
        default=os.getenv(
            "DATA_PLATFORM_ORCHESTRATION_DEPLOYMENT_NAME",
            "sigra-fipe-medallion",
        ),
    )
    return parser


def _request(args: argparse.Namespace) -> OrchestrationRequest:
    return OrchestrationRequest(
        scope=OrchestrationScope(args.scope),
        start_at=StepName(args.from_step),
        dry_run=args.dry_run,
        trigger_type=TriggerType(args.trigger_type),
        source_reference=args.source_reference,
        git_commit=args.git_commit,
        idempotency_key=args.idempotency_key,
        resume=args.resume,
        pbev_asset_directory=args.pbev_asset_dir,
        anp_source_reference=args.anp_source_reference,
        integrated_geography_level=args.integrated_geography_level,
        integrated_geography_key=args.integrated_geography_key,
        integrated_week_start=args.integrated_week_start,
        integrated_include_additized=args.integrated_include_additized,
    )


def _policy(args: argparse.Namespace) -> ExecutionPolicy:
    timeout = args.step_timeout_seconds
    return ExecutionPolicy(
        max_attempts=args.max_attempts,
        backoff_seconds=args.backoff_seconds,
        timeout_seconds={step_name: timeout for step_name in StepName},
        partial_policy=PartialPolicy(args.partial_policy),
    )


def _unused(_context):
    raise AssertionError("dry-run must not invoke a pipeline")


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    settings = load_settings()
    engine = None
    try:
        if args.command == "result":
            engine = create_platform_engine(settings.database_url)
            repository = PostgresqlOrchestrationRepository(engine)
            run, attempts = repository_result(
                repository,
                args.orchestration_run_id,
            )
            print(_result_from_repository(run, attempts, reused=True).to_json())
            return 0

        request = _request(args)
        policy = _policy(args)
        if request.dry_run:
            repository = InMemoryOrchestrationRepository()
            bindings = PipelineBindings(
                _unused,
                _unused,
                _unused,
                _unused,
                _unused,
            )
        else:
            engine = create_platform_engine(settings.database_url)
            repository = PostgresqlOrchestrationRepository(engine)
            bindings = build_default_bindings(settings)
        runner = OrchestrationRunner(repository, bindings, policy=policy)
        if args.command == "prefect" and args.serve_cron:
            if request.trigger_type == TriggerType.MANUAL:
                request = replace(request, trigger_type=TriggerType.SCHEDULED)
            serve_prefect_flow(
                runner,
                PrefectScheduleConfig(
                    cron=args.serve_cron,
                    timezone=args.timezone,
                    deployment_name=args.deployment_name,
                ),
                request,
            )
            return 0
        result = run_prefect_flow(runner, request) if args.command == "prefect" else runner.run(request)
        print(result.to_json())
        return 0 if result.status.value in {"succeeded", "partial"} else 1
    except Exception as exc:
        print(
            json.dumps(
                {"status": "failed", "error": sanitize(exc)},
                ensure_ascii=False,
            )
        )
        return 2
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
