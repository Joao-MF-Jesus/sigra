from __future__ import annotations

import argparse
import json
import os

from data_platform.carpedia.loader import CarpediaVehicleSpecsLoader
from data_platform.carpedia.pipeline import CarpediaExecutionOptions, run_carpedia_pipeline
from data_platform.common.database import create_platform_engine
from data_platform.common.logging import sanitize
from data_platform.contracts.carpedia_vehicle_specs import CarpediaTarget
from data_platform.ingestion.carpedia.client import CarpediaApiClient


def _target(value: str) -> CarpediaTarget:
    try:
        external_id, year = value.split(":", 1)
        return CarpediaTarget(int(external_id), int(year))
    except (TypeError, ValueError) as exc:
        raise argparse.ArgumentTypeError("target must use official_id:model_year") from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Carpedia interno: Bronze, Silver e Gold shadow de especificações"
    )
    parser.add_argument("--target", action="append", type=_target, default=[])
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--git-commit")
    parser.add_argument(
        "--trigger-type",
        choices=("manual", "scheduled", "retry", "backfill"),
        default="manual",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    engine = None
    try:
        loader = client = None
        if not args.dry_run:
            engine = create_platform_engine(os.getenv("DATA_PLATFORM_DATABASE_URL", ""))
            loader = CarpediaVehicleSpecsLoader(engine)
            client = CarpediaApiClient()
        result = run_carpedia_pipeline(
            loader,
            client,
            CarpediaExecutionOptions(
                targets=tuple(args.target),
                dry_run=args.dry_run,
                trigger_type=args.trigger_type,
                git_commit=args.git_commit,
            ),
        )
        print(result.to_json())
        return 0 if result.status in {"planned", "succeeded", "deduplicated"} else 1
    except Exception as exc:
        print(json.dumps({"status": "failed", "error": sanitize(exc)}, ensure_ascii=False))
        return 2
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
