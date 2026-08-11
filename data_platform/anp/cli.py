from __future__ import annotations

import argparse
import json
import os

from data_platform.anp.loader import AnpFuelPriceLoader
from data_platform.anp.pipeline import AnpExecutionOptions, run_anp_pipeline
from data_platform.anp.sources import ANP_LAST_FOUR_WEEKS_REFERENCE
from data_platform.common.database import create_platform_engine
from data_platform.common.logging import sanitize


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="ANP CSV: Bronze, Silver e Gold shadow")
    parser.add_argument("--source-reference", choices=(ANP_LAST_FOUR_WEEKS_REFERENCE,), required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--git-commit")
    parser.add_argument("--trigger-type", choices=("manual", "scheduled", "retry", "backfill"), default="manual")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    engine = None
    try:
        loader = None
        if not args.dry_run:
            engine = create_platform_engine(os.getenv("DATA_PLATFORM_DATABASE_URL", "").strip())
            loader = AnpFuelPriceLoader(engine)
        result = run_anp_pipeline(
            loader,
            AnpExecutionOptions(
                source_reference=args.source_reference,
                dry_run=args.dry_run,
                trigger_type=args.trigger_type,
                git_commit=args.git_commit,
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
