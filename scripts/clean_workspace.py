from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CACHE_DIRECTORY_NAMES = {
    ".mypy_cache",
    ".npm-cache",
    ".npm-logs",
    ".pnpm-store",
    ".pytest_cache",
    ".ruff_cache",
    "__pycache__",
    "playwright-report",
    "test-results",
    "work",
}
DEPENDENCY_DIRECTORY_NAMES = {".venv", "node_modules", "venv"}
TEMPORARY_DATABASE_MARKERS = {
    "e2e",
    "migration-check",
    "sigra-copy",
    "test",
    "validation",
}
DIAGNOSTIC_EXTENSIONS = {".log", ".tmp", ".trace", ".webm"}
SOURCE_EXTENSIONS = {
    ".css",
    ".csv",
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


def _path_size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def _is_temporary_database(path: Path, root: Path) -> bool:
    relative = path.relative_to(root)
    parts = {part.casefold() for part in relative.parts}
    name = path.name.casefold()
    return "tmp" in parts or any(marker in name for marker in TEMPORARY_DATABASE_MARKERS)


def _entry(path: Path, root: Path, kind: str, selected: bool, reason: str) -> dict:
    return {
        "path": path.relative_to(root).as_posix(),
        "kind": kind,
        "size_bytes": _path_size(path),
        "selected_for_removal": selected,
        "reason": reason,
    }


def _file_metadata(path: Path) -> dict:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    stat = path.stat()
    return {
        "original_path": str(path.resolve()),
        "size_bytes": stat.st_size,
        "sha256": digest.hexdigest(),
        "last_modified_at": datetime.fromtimestamp(
            stat.st_mtime, timezone.utc
        ).isoformat(),
    }


def _backup_legacy_database(path: Path, root: Path) -> dict | None:
    metadata = _file_metadata(path)
    if metadata["size_bytes"] == 0:
        return {**metadata, "backup_path": None, "backup_created": False}

    backup_directory = root / "tmp" / "legacy-database-backups"
    backup_directory.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup_path = backup_directory / f"{path.stem}_{timestamp}{path.suffix}.bak"
    shutil.copy2(path, backup_path)
    backup_metadata = _file_metadata(backup_path)
    if backup_metadata["sha256"] != metadata["sha256"]:
        backup_path.unlink(missing_ok=True)
        raise RuntimeError("Falha de integridade ao criar backup do banco legado.")
    return {
        **metadata,
        "backup_path": str(backup_path.resolve()),
        "backup_created": True,
    }


def scan_workspace(
    root: Path = PROJECT_ROOT,
    *,
    include_dependencies: bool = False,
    include_dist: bool = False,
    include_archives: bool = False,
    include_backups: bool = False,
    include_latest_backup: bool = False,
    include_legacy_databases: bool = False,
) -> dict:
    root = root.resolve()
    canonical_database = (root / "backend" / "sigra.db").resolve()
    legacy_root_database = (root / "sigra.db").resolve()
    candidates: dict[Path, dict] = {}
    discovered_files = []
    skipped_directories = {".agents", ".codex", ".git", ".idea", ".vscode"}
    for current, directory_names, file_names in os.walk(root):
        current_path = Path(current)
        for directory_name in list(directory_names):
            path = current_path / directory_name
            if directory_name in skipped_directories:
                directory_names.remove(directory_name)
                continue
            if directory_name in CACHE_DIRECTORY_NAMES:
                candidates[path] = _entry(
                    path, root, "cache", True, "cache ou artefato de teste"
                )
                directory_names.remove(directory_name)
            elif directory_name in DEPENDENCY_DIRECTORY_NAMES:
                candidates[path] = _entry(
                    path,
                    root,
                    "dependencies",
                    include_dependencies,
                    "dependencias preservadas por padrao",
                )
                directory_names.remove(directory_name)
            elif directory_name == "dist":
                candidates[path] = _entry(
                    path,
                    root,
                    "build",
                    include_dist,
                    "build preservado sem --include-dist",
                )
                directory_names.remove(directory_name)
        discovered_files.extend(current_path / file_name for file_name in file_names)

    backup_paths = [
        path
        for path in discovered_files
        if (
            path.suffix.casefold() == ".bak"
            or "backups" in {part.casefold() for part in path.relative_to(root).parts}
        )
    ]
    latest_backup = (
        max(backup_paths, key=lambda item: item.stat().st_mtime)
        if backup_paths
        else None
    )

    for path in discovered_files:
        resolved = path.resolve()
        suffix = path.suffix.casefold()
        if resolved == canonical_database:
            candidates[path] = _entry(
                path, root, "canonical_database", False, "banco canonico protegido"
            )
        elif resolved == legacy_root_database:
            candidates[path] = _entry(
                path,
                root,
                "legacy_root_database",
                include_legacy_databases,
                (
                    "remocao explicita do banco legado solicitada"
                    if include_legacy_databases
                    else "Banco SQLite legado da raiz. Exige confirmacao especifica."
                ),
            )
        elif path in backup_paths:
            selected = include_backups and (
                path != latest_backup or include_latest_backup
            )
            reason = (
                "backup mais recente protegido"
                if path == latest_backup and not include_latest_backup
                else "backup preservado sem --include-backups"
            )
            candidates[path] = _entry(path, root, "backup", selected, reason)
        elif _is_temporary_database(path, root) and suffix in {
            ".db",
            ".sqlite",
            ".sqlite3",
        }:
            candidates[path] = _entry(
                path, root, "temporary_database", True, "banco temporario reconhecido"
            )
        elif suffix == ".zip":
            candidates[path] = _entry(
                path,
                root,
                "archive",
                include_archives,
                "ZIP preservado sem --include-archives",
            )
        elif suffix in DIAGNOSTIC_EXTENSIONS:
            candidates[path] = _entry(
                path, root, "diagnostic", True, "log ou diagnostico temporario"
            )

    entries = sorted(candidates.values(), key=lambda item: item["path"].casefold())
    selected = [item for item in entries if item["selected_for_removal"]]
    return {
        "mode": "dry-run",
        "root": str(root),
        "canonical_database": str(canonical_database),
        "detected_items": len(entries),
        "selected_items": len(selected),
        "recoverable_bytes": sum(item["size_bytes"] for item in selected),
        "recoverable_mb": round(
            sum(item["size_bytes"] for item in selected) / (1024 * 1024), 3
        ),
        "items": entries,
    }


def clean_workspace(root: Path = PROJECT_ROOT, *, confirm: bool = False, **options) -> dict:
    root = root.resolve()
    report = scan_workspace(root, **options)
    if not confirm:
        return report

    removed = []
    legacy_database_backups = []
    for item in report["items"]:
        if not item["selected_for_removal"]:
            continue
        path = (root / item["path"]).resolve()
        if not _is_within(path, root):
            raise RuntimeError(f"Caminho fora do workspace recusado: {path}")
        if path == (root / "backend" / "sigra.db").resolve():
            raise RuntimeError("O banco canonico nunca pode ser removido.")
        if item["kind"] == "legacy_root_database":
            if not options.get("include_legacy_databases"):
                raise RuntimeError(
                    "Banco legado exige --include-legacy-databases."
                )
            legacy_database_backups.append(
                _backup_legacy_database(path, root)
            )
        if path.is_file() and path.suffix.casefold() in SOURCE_EXTENSIONS:
            raise RuntimeError(f"Arquivo de codigo ou documentacao recusado: {path}")
        if path.is_dir():
            shutil.rmtree(path)
        elif path.exists():
            path.unlink()
        removed.append(item)

    completed = {
        **report,
        "mode": "apply",
        "removed_items": len(removed),
        "removed_bytes": sum(item["size_bytes"] for item in removed),
        "removed": removed,
        "legacy_database_backups": legacy_database_backups,
    }
    log_path = root / "tmp" / "workspace-cleanup.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as stream:
        stream.write(
            json.dumps(
                {
                    "completed_at": datetime.now(timezone.utc).isoformat(),
                    **completed,
                },
                ensure_ascii=False,
            )
            + "\n"
        )
    return completed


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Audita e remove somente artefatos reconhecidos do workspace."
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Somente lista; e o padrao.")
    mode.add_argument("--confirm", action="store_true", help="Confirma as remocoes selecionadas.")
    parser.add_argument("--include-dependencies", action="store_true")
    parser.add_argument("--include-dist", action="store_true")
    parser.add_argument("--include-archives", action="store_true")
    parser.add_argument("--include-backups", action="store_true")
    parser.add_argument("--include-latest-backup", action="store_true")
    parser.add_argument(
        "--include-legacy-databases",
        action="store_true",
        help="Inclui somente o banco SQLite legado da raiz; exige --confirm para remover.",
    )
    args = parser.parse_args()
    if args.include_latest_backup and not args.include_backups:
        parser.error("--include-latest-backup exige --include-backups.")
    report = clean_workspace(
        confirm=args.confirm,
        include_dependencies=args.include_dependencies,
        include_dist=args.include_dist,
        include_archives=args.include_archives,
        include_backups=args.include_backups,
        include_latest_backup=args.include_latest_backup,
        include_legacy_databases=args.include_legacy_databases,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
