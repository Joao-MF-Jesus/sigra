from __future__ import annotations

import argparse

from sqlalchemy import create_engine

from data_platform.common.config import load_settings
from data_platform.publication.loader import GoldLoader
from data_platform.publication.pipeline import (
    rollback_gold_dataset,
    run_gold_publication,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Publicacao manual Gold FIPE")
    subparsers = parser.add_subparsers(dest="command", required=True)

    publish = subparsers.add_parser("publish", help="Publica e ativa um dataset")
    publish.add_argument("--source-reference")
    publish.add_argument(
        "--trigger-type",
        choices=("manual", "scheduled", "retry", "backfill"),
        default="manual",
    )
    publish.add_argument("--git-commit")

    rollback = subparsers.add_parser("rollback", help="Reativa um dataset anterior")
    rollback.add_argument("dataset_version")
    rollback.add_argument("--source-reference")
    rollback.add_argument("--git-commit")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    settings = load_settings()
    if not settings.database_url:
        raise SystemExit("DATA_PLATFORM_DATABASE_URL e obrigatoria")
    engine = create_engine(settings.database_url, pool_pre_ping=True)
    try:
        loader = GoldLoader(engine)
        if args.command == "publish":
            result = run_gold_publication(
                loader,
                trigger_type=args.trigger_type,
                source_reference=args.source_reference,
                git_commit=args.git_commit,
            )
        else:
            result = rollback_gold_dataset(
                loader,
                args.dataset_version,
                source_reference=args.source_reference,
                git_commit=args.git_commit,
            )
        print(result.to_json())
        return 0 if result.status in {"succeeded", "deduplicated", "skipped"} else 1
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
