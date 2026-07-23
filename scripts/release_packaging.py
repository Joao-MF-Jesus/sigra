from __future__ import annotations

import hashlib
import json
import re
import subprocess
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


SKIP_DIRECTORIES = {
    ".git",
    ".agents",
    ".codex",
    ".idea",
    ".vscode",
    ".npm-cache",
    ".npm-cache-validation",
    ".pnpm-store",
    ".venv",
    ".venv-validation",
    "venv",
    "node_modules",
    "dist",
    "work",
    "outputs",
    "tmp",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "playwright-report",
    "test-results",
}
SKIP_EXTENSIONS = {
    ".bak",
    ".db",
    ".log",
    ".sqlite",
    ".sqlite3",
    ".tmp",
    ".zip",
    ".trace",
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
}
TEXT_EXTENSIONS = {
    "",
    ".css",
    ".csv",
    ".env",
    ".example",
    ".html",
    ".ini",
    ".js",
    ".json",
    ".jsx",
    ".md",
    ".mjs",
    ".ps1",
    ".py",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
}
MAX_INCLUDED_FILE_BYTES = 10 * 1024 * 1024
STABILIZATION_BUILD = "2026.07.1"
SECRET_PATTERNS = {
    "private_key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "aws_access_key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "github_token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b"),
    "openai_key": re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    "credentialed_database_url": re.compile(
        r"\b(?:postgres(?:ql)?(?:\+\w+)?|mysql|mariadb|mongodb(?:\+srv)?)://"
        r"[^:\s/@]+:[^@\s/]+@",
        re.IGNORECASE,
    ),
}


class ReleaseValidationError(RuntimeError):
    pass


@dataclass(frozen=True)
class ReleaseResult:
    archive: Path
    report_path: Path
    checksum_path: Path
    report: dict


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source_commit(root: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            capture_output=True,
            check=True,
            text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip() or None


def _skip_reason(path: Path, root: Path) -> str | None:
    relative = path.relative_to(root)
    if any(part in SKIP_DIRECTORIES for part in relative.parts):
        return "excluded_directory"
    if path.suffix.lower() in SKIP_EXTENSIONS:
        return "excluded_extension"
    if path.name != ".env.example" and (path.name == ".env" or path.name.startswith(".env.")):
        return "forbidden_environment_file"
    return None


def _scan_text_for_secrets(path: Path) -> list[str]:
    if path.suffix.lower() not in TEXT_EXTENSIONS and path.name != ".env.example":
        return []
    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    return [name for name, pattern in SECRET_PATTERNS.items() if pattern.search(content)]


def collect_release_files(root: Path) -> tuple[list[Path], int, list[dict]]:
    included = []
    excluded_files = 0
    violations = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        reason = _skip_reason(path, root)
        if reason:
            excluded_files += 1
            if reason == "forbidden_environment_file" and not any(
                part in SKIP_DIRECTORIES for part in path.relative_to(root).parts
            ):
                violations.append(
                    {"path": path.relative_to(root).as_posix(), "reason": reason}
                )
            continue
        if path.stat().st_size > MAX_INCLUDED_FILE_BYTES:
            violations.append(
                {
                    "path": path.relative_to(root).as_posix(),
                    "reason": "unexpected_file_size",
                    "size_bytes": path.stat().st_size,
                }
            )
            continue
        secret_types = _scan_text_for_secrets(path)
        if secret_types:
            violations.append(
                {
                    "path": path.relative_to(root).as_posix(),
                    "reason": "possible_secret",
                    "types": secret_types,
                }
            )
            continue
        included.append(path)
    return included, excluded_files, violations


def build_release_package(
    *,
    root: Path,
    output: Path,
    release_type: str,
) -> ReleaseResult:
    root = root.resolve()
    output = output.resolve()
    if release_type not in {"academic", "technical"}:
        raise ValueError("release_type deve ser academic ou technical")
    if release_type == "academic":
        for required in ("NOTICE.md", "ACADEMIC_RELEASE.md"):
            if not (root / required).is_file():
                raise ReleaseValidationError(f"Arquivo obrigatório ausente: {required}")

    included, excluded_files, violations = collect_release_files(root)
    if violations:
        raise ReleaseValidationError(
            "A varredura de release encontrou itens bloqueadores:\n"
            + json.dumps(violations, ensure_ascii=False, indent=2)
        )

    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        output.unlink()
    generated_at = datetime.now(timezone.utc).isoformat()
    source_commit = _source_commit(root)
    manifest_entries = [
        {
            "path": path.relative_to(root).as_posix(),
            "size_bytes": path.stat().st_size,
            "sha256": _sha256(path),
        }
        for path in included
    ]
    metadata = {
        "project": "SIGRA",
        "release_type": release_type,
        "stabilization_build": STABILIZATION_BUILD,
        "generated_at": generated_at,
        "source_commit": source_commit,
        "functional_versions": {
            "cars_algorithm": "2.1.2",
            "cars_weights": "cars-v1",
            "financing_module": "1.0.3",
            "financing_calculation_method": "price-v1.2",
            "motorcycles_module": "0.3.1",
            "motorcycles_algorithm": None,
            "motorcycles_weights": None,
        },
        "contains_database": False,
        "contains_secrets": False,
    }
    manifest = {
        "metadata": metadata,
        "included_files": len(manifest_entries) + 2,
        "files": manifest_entries,
    }
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in included:
            archive.write(path, path.relative_to(root).as_posix())
        archive.writestr(
            "RELEASE_METADATA.json",
            json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        )
        archive.writestr(
            "MANIFEST.json",
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        )

    with zipfile.ZipFile(output) as archive:
        nested_archives = [name for name in archive.namelist() if name.lower().endswith(".zip")]
        database_files = [
            name
            for name in archive.namelist()
            if Path(name).suffix.lower() in {".db", ".sqlite", ".sqlite3"}
        ]
    if nested_archives or database_files:
        output.unlink(missing_ok=True)
        raise ReleaseValidationError("O pacote contém arquivo aninhado ou banco de dados proibido.")

    archive_hash = _sha256(output)
    checksum_path = output.with_suffix(output.suffix + ".sha256")
    checksum_path.write_text(f"{archive_hash}  {output.name}\n", encoding="ascii")
    report = {
        "release_type": release_type,
        "included_files": len(manifest_entries) + 2,
        "excluded_files": excluded_files,
        "archive_size_mb": round(output.stat().st_size / (1024 * 1024), 3),
        "sha256": archive_hash,
        "contains_secrets": False,
        "contains_database": False,
        "manifest": "MANIFEST.json",
        "source_commit": source_commit,
        "stabilization_build": STABILIZATION_BUILD,
    }
    report_path = output.with_suffix(output.suffix + ".report.json")
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return ReleaseResult(
        archive=output,
        report_path=report_path,
        checksum_path=checksum_path,
        report=report,
    )
