from __future__ import annotations

import argparse

from data_platform.common.config import load_settings
from data_platform.common.database import create_platform_engine
from data_platform.contracts.fipe import FipeTarget
from data_platform.ingestion.fipe.client import FipeHttpClient
from data_platform.ingestion.fipe.loader import BronzeLoader
from data_platform.ingestion.fipe.pipeline import run_pipeline
from data_platform.ingestion.fipe.targets import legacy_car_targets


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Ingestao Bronze manual da FIPE")
    parser.add_argument("--dry-run", action="store_true", help="Coleta e valida sem escrever no banco")
    parser.add_argument("--target", action="append", metavar="TYPE:FIPE_CODE:YEAR_CODE", help="Alvo explicito; pode ser repetido")
    parser.add_argument("--source-reference")
    parser.add_argument("--trigger-type", choices=("manual", "scheduled", "retry", "backfill"), default="manual")
    parser.add_argument("--git-commit")
    return parser


def _parse_target(value: str) -> FipeTarget:
    vehicle_type, code, year_code = value.split(":", 2)
    return FipeTarget(vehicle_type, code, year_code)


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    settings = load_settings()
    targets = [_parse_target(value) for value in args.target] if args.target else legacy_car_targets()
    if not targets:
        raise SystemExit("Nenhum alvo com year_code completo foi encontrado; use --target")
    engine = None
    try:
        loader = None
        if not args.dry_run:
            engine = create_platform_engine(settings.database_url)
            loader = BronzeLoader(engine)
        with FipeHttpClient(settings.fipe_api_url, settings.timeout_seconds) as client:
            result = run_pipeline(targets, client, loader, dry_run=args.dry_run,
                                  trigger_type=args.trigger_type, source_reference=args.source_reference,
                                  git_commit=args.git_commit)
        print(result.to_json())
        return 0 if result.status == "succeeded" else 1
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
