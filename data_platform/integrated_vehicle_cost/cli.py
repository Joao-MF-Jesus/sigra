from __future__ import annotations

import argparse
from datetime import date
import json
import os

from data_platform.common.database import create_platform_engine
from data_platform.common.logging import sanitize
from data_platform.integrated_vehicle_cost.loader import IntegratedVehicleCostLoader
from data_platform.integrated_vehicle_cost.pipeline import (
    IntegratedPublicationRequest,
    IntegratedVehicleCostOptions,
    rollback_integrated_vehicle_cost,
    run_integrated_vehicle_cost_pipeline,
)


def _date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("week-start must use YYYY-MM-DD") from exc


def _request_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--geography-level",
        required=True,
        choices=("municipality", "state"),
    )
    parser.add_argument("--geography-key", required=True)
    parser.add_argument("--week-start", required=True, type=_date)
    parser.add_argument("--no-additized", action="store_true")


def _execution_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--trigger-type",
        choices=("manual", "scheduled", "retry", "backfill"),
        default="manual",
    )
    parser.add_argument("--git-commit")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Gold analitica integrada FIPE + PBEV + ANP"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    publish = commands.add_parser("publish", help="materializa e publica o shadow")
    _request_arguments(publish)
    _execution_arguments(publish)
    dry_run = commands.add_parser("dry-run", help="gera um plano puro e sanitizado")
    _request_arguments(dry_run)
    rollback = commands.add_parser("rollback", help="reativa um dataset elegivel")
    rollback.add_argument("dataset_version")
    _execution_arguments(rollback)
    return parser


def _request(args: argparse.Namespace) -> IntegratedPublicationRequest:
    return IntegratedPublicationRequest(
        geography_level=args.geography_level,
        geography_key=args.geography_key,
        week_start=args.week_start,
        include_additized=not args.no_additized,
    )


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    engine = None
    try:
        if args.command == "dry-run":
            result = run_integrated_vehicle_cost_pipeline(
                None,
                IntegratedVehicleCostOptions(request=_request(args), dry_run=True),
            )
        else:
            database_url = os.getenv("DATA_PLATFORM_DATABASE_URL", "").strip()
            engine = create_platform_engine(database_url)
            loader = IntegratedVehicleCostLoader(engine)
            if args.command == "publish":
                result = run_integrated_vehicle_cost_pipeline(
                    loader,
                    IntegratedVehicleCostOptions(
                        request=_request(args),
                        trigger_type=args.trigger_type,
                        git_commit=args.git_commit,
                    ),
                )
            else:
                result = rollback_integrated_vehicle_cost(
                    loader,
                    args.dataset_version,
                    trigger_type=args.trigger_type,
                    git_commit=args.git_commit,
                )
        print(result.to_json())
        return 0 if result.status in {"succeeded", "deduplicated", "dry_run"} else 1
    except Exception as exc:
        print(
            json.dumps(
                {"status": "failed", "error": sanitize(exc)},
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 2
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
