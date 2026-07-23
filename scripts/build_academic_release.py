from __future__ import annotations

import argparse
import json
from pathlib import Path

from release_packaging import build_release_package


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Gera uma cópia acadêmica controlada do SIGRA sem publicar ou enviar."
    )
    parser.add_argument(
        "--output",
        default="dist/academic/SIGRA-release-academica.zip",
        help="Caminho do ZIP acadêmico.",
    )
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    output = Path(args.output)
    if not output.is_absolute():
        output = root / output
    result = build_release_package(
        root=root,
        output=output,
        release_type="academic",
    )
    print(json.dumps(result.report, ensure_ascii=False, indent=2))
    print(f"archive={result.archive}")
    print(f"report={result.report_path}")
    print(f"checksum={result.checksum_path}")


if __name__ == "__main__":
    main()
