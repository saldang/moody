"""Tiny environment-based configuration helpers (no extra dependency)."""

from __future__ import annotations

import os
from pathlib import Path


def env(name: str, default: str | None = None, *, required: bool = False) -> str:
    """Read an env var; an empty value counts as unset (compose passes ``${X:-}`` as "")."""
    value = os.environ.get(name) or default
    if required and not value:
        raise RuntimeError(f"Missing required environment variable {name}")
    return value or ""


def env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    return int(raw) if raw else default


def read_secret(name: str, default: str | None = None) -> str:
    """Read a secret from ``$NAME_FILE`` (docker secrets) or, as a fallback, ``$NAME``.

    Secrets should be provided as files: environment variables leak easily
    (``docker inspect``, crash dumps, child processes).
    """
    file_path = os.environ.get(f"{name}_FILE")
    if file_path:
        return Path(file_path).read_text(encoding="utf-8").strip()
    value = os.environ.get(name, default)
    if value is None:
        raise RuntimeError(f"Missing secret {name} (set {name}_FILE)")
    return value
