"""Offline candidate validation. No database, API calls, or implicit seed."""
import argparse
import json
from pathlib import Path

from pydantic import TypeAdapter, ValidationError

from data_platform.catalog.contracts import Dossier
from data_platform.catalog.intake import intake_report, load_selection


def main(argv=None):
    parser = argparse.ArgumentParser(description="Audita candidatos SIGRA sem ativar registros")
    parser.add_argument("--batch", type=int, choices=(1, 2, 3))
    parser.add_argument("--dossiers", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[2]
    report_path = args.report.resolve()
    if report_path == root or root in report_path.parents:
        parser.error("report must remain outside the repository")
    if report_path.exists():
        parser.error("preserve existing report; use a new report path")
    try:
        dossiers = TypeAdapter(tuple[Dossier, ...]).validate_json(args.dossiers.read_text(encoding="utf-8")) if args.dossiers else ()
        result = intake_report(load_selection(), dossiers, batch=args.batch)
    except (ValidationError, ValueError, OSError):
        # Pydantic's default error text includes raw input, possibly a rejected
        # authenticated URL. Never echo an untrusted dossier in diagnostics.
        print(json.dumps({"status": "invalid_input", "activated": 0, "database_accessed": False}))
        return 2
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items() if key != "rows"}, ensure_ascii=False))
    return 2 if result["blocked"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
