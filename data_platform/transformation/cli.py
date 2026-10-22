from __future__ import annotations

import argparse

from sqlalchemy import create_engine

from data_platform.common.config import load_settings
from data_platform.transformation.loader import SilverLoader
from data_platform.transformation.pipeline import run_silver_pipeline


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Transformacao manual Silver FIPE")
    parser.add_argument("--dry-run", action="store_true", help="Valida sem escrever")
    parser.add_argument("--source-reference")
    parser.add_argument(
        "--trigger-type",
        choices=("manual", "scheduled", "retry", "backfill"),
        default="manual",
    )
    parser.add_argument("--git-commit")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    settings = load_settings()
    if not settings.database_url:
        raise SystemExit("DATA_PLATFORM_DATABASE_URL e obrigatoria")
    engine = create_engine(settings.database_url, pool_pre_ping=True)
    try:
        result = run_silver_pipeline(
            SilverLoader(engine),
            dry_run=args.dry_run,
            trigger_type=args.trigger_type,
            source_reference=args.source_reference,
            git_commit=args.git_commit,
        )
        print(result.to_json())
        return 0 if result.status in {"succeeded", "skipped"} else 1
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
