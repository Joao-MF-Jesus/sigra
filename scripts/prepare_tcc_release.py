"""Freeze a sanitized dirty-checkout delivery; offline only, exclusive output."""
import argparse
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "backend"), str(ROOT)]
from app.release_manifest import release_id, verify_release
from app.deployment import ACCEPTANCE_SHA256, pinned_json, validate_acceptance


def selected(path):
    name = path.relative_to(ROOT).as_posix()
    parts = path.relative_to(ROOT).parts
    if (parts[0] not in {"backend", "frontend", "data_platform", "scripts", "deploy", "docs"}
            or any(p.startswith(".") or p in {"node_modules", "__pycache__", "tests", "dist", "cache", "outputs"} for p in parts)
            or "cache" in path.stem.lower() or path.is_symlink()):
        return False
    if path.suffix.lower() not in {".py", ".json", ".js", ".jsx", ".css", ".html", ".svg", ".webp", ".png", ".jpg", ".ini", ".md", ".yaml", ".sql", ".example", ".dockerfile"}:
        return name == "backend/requirements.txt"
    return True


def freeze(destination, bundle, decision, acceptance):
    destination = destination.resolve()
    if destination.exists() or destination.is_relative_to(ROOT):
        raise ValueError("NEW_EXTERNAL_OUTPUT_DIRECTORY_REQUIRED")
    validate_acceptance(pinned_json(acceptance, ACCEPTANCE_SHA256))
    # Model imports construct an engine but must never default to the legacy SQLite.
    os.environ.update(DATABASE_URL="postgresql+psycopg://offline@127.0.0.1:1/sigra_release_offline_test",
                      DATABASE_ENV="integration", FIPE_AUTO_REFRESH="false", DATABASE_ECHO="false")
    from app.academic_cohort.revision6_homologation import build_plan
    from app.academic_cohort.contracts import json_document
    plan = build_plan(bundle, decision)  # Pinned evidence, same V6 and Revision6 verifier.
    destination.mkdir(parents=True)
    for prefix in ("backend", "frontend", "data_platform", "scripts", "deploy", "docs"):
        for path in (ROOT / prefix).rglob("*"):
            if path.is_file() and selected(path):
                out = destination / path.relative_to(ROOT)
                out.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, out)
    release = destination / "release"
    release.mkdir()
    serialized = json_document({"proposal": asdict(plan.proposal), "replay": plan.replay, "approved_replay": plan.approved_replay})
    (release / "plan.json").write_text(json.dumps(serialized, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    shutil.copyfile(acceptance, release / "functional-acceptance.json")
    files = {}
    prohibited = []
    for path in sorted(destination.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(destination).as_posix()
        if path.suffix in {".py", ".js", ".jsx", ".json", ".yaml", ".md", ".example"}:
            content = path.read_text(encoding="utf-8-sig")
            if re.search(r"(?:postgres(?:ql)?(?:\+psycopg)?|https?)://[^\s/'\"<>:]+:[^\s'\"<>@]+@", content):
                prohibited.append(relative)
        files[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    if prohibited:
        raise ValueError("AUTHENTICATED_URL_IN_RELEASE: " + ",".join(prohibited))
    git = lambda *args: subprocess.check_output(["git", "-C", str(ROOT), *args]).decode().strip()
    manifest = {"schema": "sigra-source-release-v1", "release_id": release_id(files),
                "git_head": git("rev-parse", "HEAD"), "git_branch": git("branch", "--show-current"),
                "working_tree_changes_included": bool(git("status", "--porcelain")),
                "files": files, "runtime_plan_sha256": files["release/plan.json"],
                "functional_acceptance_sha256": ACCEPTANCE_SHA256, "historical_row_changed": 1,
                "collection_enabled": False, "alembic_head": "20261007_0015",
                "candidate_fingerprint": plan.proposal.candidate_fingerprint,
                "approved_fingerprint": plan.proposal.approved_reference_fingerprint,
                "profile_counts": plan.proposal.profile_counts,
                "no_database_or_network_commands": True,
                "excluded": [".git", ".env", "DPAPI", "passwords", "databases", "caches", "raw PDFs",
                             "participant CSV", "node_modules", "venvs", "tatus --short", "test fixtures"]}
    (release / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    verify_release(destination, release / "manifest.json", manifest["release_id"])
    from app.deployment import load_plan
    restored = load_plan(str(release / "plan.json"), files["release/plan.json"])
    if restored.proposal.candidate_fingerprint != plan.proposal.candidate_fingerprint:
        raise ValueError("RUNTIME_PLAN_ROUNDTRIP_DIFFERS")
    archive = destination.with_suffix(".zip")
    if archive.exists():
        raise ValueError("ARCHIVE_ALREADY_EXISTS")
    with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_DEFLATED) as out:
        for path in sorted(destination.rglob("*")):
            if path.is_file():
                out.write(path, path.relative_to(destination).as_posix())
    return {"status": "DEPLOY_RELEASE_PREPARED_COLLECTION_DISABLED", "release_id": manifest["release_id"],
            "manifest_path": str(release / "manifest.json"), "files": len(files), "archive_path": str(archive),
            "archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
            "plan_sha256": files["release/plan.json"], "historical_row_changed": 1,
            "database_contacted": False, "published": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--decision", type=Path, required=True)
    parser.add_argument("--acceptance", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(freeze(args.output, args.bundle, args.decision, args.acceptance), ensure_ascii=False))


if __name__ == "__main__":
    main()
