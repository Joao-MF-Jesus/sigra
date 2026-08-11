from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from data_platform.common.database import create_platform_engine
from data_platform.common.logging import sanitize
from data_platform.pbev.loader import PbevLoader
from data_platform.pbev.pipeline import PbevExecutionOptions, run_pbev_pipeline


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="PBE Veicular interno: Bronze, Silver e Gold shadow"
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--asset-dir", default=os.getenv("PBEV_ASSET_DIR"))
    parser.add_argument("--source-reference")
    parser.add_argument("--git-commit")
    parser.add_argument(
        "--trigger-type",
        choices=("manual", "scheduled", "retry", "backfill"),
        default="manual",
    )
    parser.add_argument("--timeout-seconds", type=float, default=1800.0)
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    engine = None
    try:
        loader = None
        if not args.dry_run:
            database_url = os.getenv("DATA_PLATFORM_DATABASE_URL", "").strip()
            engine = create_platform_engine(database_url)
            loader = PbevLoader(engine)
        result = run_pbev_pipeline(
            loader,
            PbevExecutionOptions(
                asset_directory=Path(args.asset_dir) if args.asset_dir else None,
                dry_run=args.dry_run,
                trigger_type=args.trigger_type,
                source_reference=args.source_reference,
                git_commit=args.git_commit,
                timeout_seconds=args.timeout_seconds,
            ),
        )
        print(result.to_json())
        return 0 if result.status in {"succeeded", "deduplicated"} else 1
    except Exception as exc:
        print(json.dumps({"status": "failed", "error": sanitize(exc)}, ensure_ascii=False))
        return 2
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
