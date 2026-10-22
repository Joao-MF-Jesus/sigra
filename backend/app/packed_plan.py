"""Lossless storage adapter for the original byte-pinned Revision6 plan.

No alternative plan, JSON rewrite, network, database or reference replacement.
Only a new private scratch file is created, then verified by the unchanged
deployment.load_plan/pinned_json and methodology validators.
"""
import gzip
import hashlib
import os
from pathlib import Path

APPROVED_SHA256 = 'cb70ff5298ffc4c52fc74e44588b2e34a39584b4cacfa6146981670737f3be97'
APPROVED_BYTES = 192101420
STORAGE_FILE = 'release/plan.json.gz'


class PackedPlanBlocked(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def require(value, code):
    if not value:
        raise PackedPlanBlocked(code)


def restore_plan(source, destination, storage, expected, file_pin):
    """Explicit gzip representation; no fallback after any failed guard."""
    require(isinstance(storage, dict) and set(storage) == {
        'schema', 'file', 'compressed_sha256', 'uncompressed_sha256', 'uncompressed_bytes'},
        'EXACT_PACKED_PLAN_STORAGE_CONTRACT_REQUIRED')
    require(storage['schema'] == 'sigra-pinned-gzip-plan-v1' and storage['file'] == STORAGE_FILE
            and type(storage['uncompressed_bytes']) is int and storage['uncompressed_bytes'] == APPROVED_BYTES
            and storage['uncompressed_sha256'] == expected == APPROVED_SHA256,
            'APPROVED_UNCOMPRESSED_PLAN_IDENTITY_REQUIRED')
    require(isinstance(file_pin, str) and len(file_pin) == 64
            and storage['compressed_sha256'] == file_pin,
            'PACKED_PLAN_MANIFEST_PIN_REQUIRED')
    source, destination = Path(source), Path(destination)
    require(source.is_file() and not source.is_symlink(), 'PACKED_PLAN_SOURCE_REQUIRED')
    require(destination.parent.is_dir() and not destination.parent.is_symlink()
            and destination.parent.resolve() != source.parent.resolve(), 'SEPARATE_PLAN_SCRATCH_REQUIRED')
    with source.open('rb') as stream:
        require(hashlib.file_digest(stream, 'sha256').hexdigest() == file_pin,
                'PACKED_PLAN_FILE_CHANGED')
    created = False
    try:
        descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        created = True
        size = 0; digest = hashlib.sha256()
        with os.fdopen(descriptor, 'wb') as output, gzip.open(source, 'rb') as stream:
            while block := stream.read(1024 * 1024):
                size += len(block)
                require(size <= APPROVED_BYTES, 'PACKED_PLAN_DECOMPRESSION_LIMIT_EXCEEDED')
                digest.update(block); output.write(block)
        require(size == APPROVED_BYTES and digest.hexdigest() == expected,
                'RESTORED_PLAN_SIZE_OR_SHA256_DIFFERS')
        return destination
    except BaseException:
        if created:
            try:
                destination.unlink()  # This invocation's new file only.
            except OSError:
                pass  # Never replace the first exception with cleanup failure.
        raise
