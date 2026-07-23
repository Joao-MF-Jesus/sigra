from __future__ import annotations

import argparse
import json
from pathlib import Path

from release_packaging import build_release_package


def create_package(root: Path, output: Path):
    return build_release_package(
        root=root,
        output=output,
        release_type="technical",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Gera pacote técnico limpo do SIGRA.")
    parser.add_argument(
        "--output",
        default="dist/technical/SIGRA-revisao-tecnica.zip",
        help="Nome ou caminho do ZIP de saída.",
    )
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    output = Path(args.output)
    if not output.is_absolute():
        output = root / output
    result = create_package(root, output)
    print(json.dumps(result.report, ensure_ascii=False, indent=2))
    print(f"archive={result.archive}")
    print(f"report={result.report_path}")
    print(f"checksum={result.checksum_path}")


if __name__ == "__main__":
    main()
