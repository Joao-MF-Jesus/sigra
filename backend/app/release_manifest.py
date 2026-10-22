"""Content identity of the prepared dirty-checkout release, not just Git HEAD."""
import hashlib
import json
from pathlib import Path, PurePosixPath


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def release_id(files):
    return "sigra-" + hashlib.sha256(canonical(files)).hexdigest()[:24]


def verify_release(root, manifest_file, expected_id):
    root = Path(root).resolve(strict=True)
    manifest_path = Path(manifest_file).resolve(strict=True)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema") != "sigra-source-release-v1" or not manifest.get("files"):
        raise ValueError("RELEASE_MANIFEST_REQUIRED")
    if manifest.get("release_id") != expected_id or release_id(manifest["files"]) != expected_id:
        raise ValueError("RELEASE_ID_DIFFERS")
    actual = {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()
              and p.resolve() != manifest_path and "__pycache__" not in p.parts
              and not p.relative_to(root).as_posix().startswith("frontend/dist/")}
    if actual != set(manifest["files"]):
        raise ValueError("RELEASE_FILE_SET_DIFFERS")
    for name, expected in manifest["files"].items():
        relative = PurePosixPath(name)
        if relative.is_absolute() or ".." in relative.parts or "\\" in name or ":" in name:
            raise ValueError("UNSAFE_RELEASE_PATH")
        path = root / name
        if path.is_symlink() or not path.resolve(strict=True).is_relative_to(root):
            raise ValueError("RELEASE_PATH_ESCAPES")
        with path.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != expected:
                raise ValueError("RELEASE_FILE_CHANGED")
    return manifest
