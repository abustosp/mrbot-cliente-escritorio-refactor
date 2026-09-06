#!/usr/bin/env python3
"""Scan release contents for high-confidence secret material.

The scanner is intentionally dependency-free so Linux and Windows use the same
implementation. Environment files are rejected by name before their contents
could be opened. Any traversal or read error is a failure.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path
from typing import Iterator


class ScanError(RuntimeError):
    """Raised when the scan cannot prove that the package is safe."""


_ENV_FILE_RE = re.compile(r"^(?:\.env|.*\.env(?:\..*)?)$", re.IGNORECASE)
_SECRET_PATTERNS = (
    ("private key", re.compile(rb"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----")),
    ("AWS access key", re.compile(rb"\bAKIA[0-9A-Z]{16}\b")),
    (
        "GitHub token",
        re.compile(rb"\b(?:gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,})\b"),
    ),
    ("Google API key", re.compile(rb"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("Slack token", re.compile(rb"\bxox[baprs]-[0-9A-Za-z-]{10,}\b")),
    ("OpenAI-style API key", re.compile(rb"\bsk-[A-Za-z0-9_-]{20,}\b")),
    (
        "credential assignment",
        re.compile(
            rb"(?ix)\b(?:api[_-]?key|secret(?:[_-]?key)?|access[_-]?token|"
            rb"auth[_-]?token|password|private[_-]?key)\s*[:=]\s*"
            rb"(?:\"[^\"\r\n]{16,}\"|'[^'\r\n]{16,}'|[A-Za-z0-9+/=_-]{16,})"
        ),
    ),
)


def is_env_file(path: Path) -> bool:
    """Return whether *path* has an environment-file name, case-insensitively."""

    return _ENV_FILE_RE.fullmatch(path.name) is not None


def _iter_files(root: Path) -> Iterator[Path]:
    """Yield regular files, refusing unsafe filesystem entries."""

    def on_error(error: OSError) -> None:
        raise ScanError(f"No se pudo recorrer el paquete: {error}") from error

    for directory, dirnames, filenames in os.walk(
        root, topdown=True, followlinks=False, onerror=on_error
    ):
        directory_path = Path(directory)
        dirnames.sort()
        filenames.sort()

        for name in list(dirnames):
            path = directory_path / name
            if is_env_file(path):
                raise ScanError(f"El paquete contiene un archivo .env: {path.name}")
            if path.is_symlink():
                raise ScanError(f"El paquete contiene un enlace simbolico: {path.name}")

        for name in filenames:
            path = directory_path / name
            # Check the name before any operation that could open or follow it.
            if is_env_file(path):
                raise ScanError(f"El paquete contiene un archivo .env: {path.name}")
            if path.is_symlink():
                raise ScanError(f"El paquete contiene un enlace simbolico: {path.name}")
            if not path.is_file():
                raise ScanError(f"El paquete contiene una entrada no regular: {path.name}")
            yield path


def _scan_file(path: Path, root: Path) -> None:
    if is_env_file(path):
        raise ScanError(f"Se rechazo la lectura de un archivo .env: {path.name}")

    try:
        contents = path.read_bytes()
    except OSError as error:
        raise ScanError(f"No se pudo leer un archivo del paquete: {path.name}") from error

    for label, pattern in _SECRET_PATTERNS:
        if pattern.search(contents):
            relative_path = path.relative_to(root)
            raise ScanError(f"Contenido sensible detectado en {relative_path} ({label})")


def scan(root: Path) -> int:
    """Scan *root* and return the number of regular files inspected."""

    if not root.exists() or not root.is_dir():
        raise ScanError(f"El directorio del paquete no existe: {root}")

    scanned = 0
    for path in _iter_files(root):
        _scan_file(path, root)
        scanned += 1

    if scanned == 0:
        raise ScanError("El directorio del paquete esta vacio")
    return scanned


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package_dir", type=Path)
    args = parser.parse_args(argv)

    try:
        scanned = scan(args.package_dir)
    except ScanError as error:
        print(f"Secret scan failed closed: {error}", file=sys.stderr)
        return 1
    except Exception as error:  # pragma: no cover - defensive fail-closed guard
        print(f"Secret scan failed closed unexpectedly: {type(error).__name__}", file=sys.stderr)
        return 1

    print(f"Secret scan passed: {scanned} file(s) inspected")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
