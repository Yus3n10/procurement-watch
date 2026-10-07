"""Fetch and verify the pinned raw snapshot."""

import hashlib
import urllib.request
from pathlib import Path

from . import config


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def verify(raw_dir: Path, manifest: dict | None = None) -> list[str]:
    """Return a list of problems. Empty means the snapshot matches the manifest."""
    manifest = manifest or config.load_manifest()
    problems = []
    for name, expected in manifest["files"].items():
        path = raw_dir / name
        if not path.exists():
            problems.append(f"{name}: missing")
        elif path.stat().st_size != expected["bytes"]:
            problems.append(f"{name}: size {path.stat().st_size}, expected {expected['bytes']}")
        elif sha256(path) != expected["sha256"]:
            problems.append(f"{name}: checksum mismatch")
    return problems


def fetch(raw_dir: Path, manifest: dict | None = None) -> None:
    """Download any file that is missing or does not match the manifest."""
    manifest = manifest or config.load_manifest()
    raw_dir.mkdir(parents=True, exist_ok=True)
    base = f"{manifest['source']}/resolve/{manifest['revision']}"
    for name, expected in manifest["files"].items():
        path = raw_dir / name
        if path.exists() and path.stat().st_size == expected["bytes"] and sha256(path) == expected["sha256"]:
            continue
        urllib.request.urlretrieve(f"{base}/{name}", path)
    problems = verify(raw_dir, manifest)
    if problems:
        raise RuntimeError("raw snapshot failed verification: " + "; ".join(problems))
