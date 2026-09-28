"""Content pins and atomic JSON files; hashes are integrity checks, not signatures."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path

from pydantic import BaseModel

from starling_bench.models import FilePin, SealedSpec, Spec


class BenchError(Exception):
    """A user-actionable experiment failure."""


def plain(value):
    return value.model_dump(mode="json") if isinstance(value, BaseModel) else value


def digest(value) -> str:
    data = json.dumps(plain(value), sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(data.encode()).hexdigest()


def sha256(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def pin(path: Path) -> FilePin:
    # Preserve a library's requested SONAME when its path is a symlink.
    path = Path(os.path.abspath(path.expanduser()))
    if not path.is_file():
        raise BenchError(f"not a regular file: {path}")
    return FilePin(path=str(path), sha256=sha256(path), size=path.stat().st_size)


def verify_pin(value: FilePin) -> None:
    path = Path(value.path)
    if not path.is_file() or path.stat().st_size != value.size or sha256(path) != value.sha256:
        raise BenchError(f"artifact changed or missing: {path}")


def write_json(path: Path, value, *, exclusive: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(plain(value), indent=2, sort_keys=True, allow_nan=False) + "\n"
    if exclusive:
        with path.open("x", encoding="utf-8") as target:
            target.write(data)
        return
    descriptor, tmp = tempfile.mkstemp(prefix=".write-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as target:
            target.write(data)
            target.flush()
            os.fsync(target.fileno())
        os.replace(tmp, path)
    finally:
        Path(tmp).unlink(missing_ok=True)


def seal(spec: Spec) -> SealedSpec:
    return SealedSpec(spec=spec, sha256=digest(spec))


def load_spec(path: Path) -> SealedSpec:
    value = SealedSpec.model_validate_json(path.read_text())
    if digest(value.spec) != value.sha256:
        raise BenchError("spec seal does not match; create a new spec for changed rules")
    return value


def verify_inputs(spec: Spec) -> None:
    files = [spec.model, *(c.audio for c in spec.clips)]
    for arm in (spec.baseline, spec.candidate):
        files.extend((arm.binary, *arm.runtime_files))
    for value in {(v.path, v.sha256): v for v in files}.values():
        verify_pin(value)
