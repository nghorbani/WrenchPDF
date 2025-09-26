"""Helpers for tracking and cleaning up temporary files."""

from __future__ import annotations

import contextlib
import json
import tempfile
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Set

__all__ = [
    "DEFAULT_TTL",
    "TempFileTracker",
    "cleanup_expired_paths",
    "register_temp_path",
    "remove_temp_path",
    "unregister_temp_path",
]

DEFAULT_TTL = timedelta(days=1)
_REGISTRY_PATH = Path(tempfile.gettempdir()) / "wrentchpdf-temp-files.json"
_REGISTRY_LOCK = threading.RLock()


def _read_registry() -> Dict[str, float]:
    if not _REGISTRY_PATH.exists():
        return {}
    try:
        data = json.loads(_REGISTRY_PATH.read_text())
    except (json.JSONDecodeError, OSError):  # pragma: no cover - defensive IO guard
        return {}
    if not isinstance(data, dict):  # pragma: no cover - guard against unexpected format
        return {}
    return {
        str(Path(key)): float(value)
        for key, value in data.items()
        if isinstance(key, str) and isinstance(value, (int, float))
    }


def _write_registry(entries: Dict[str, float]) -> None:
    try:
        _REGISTRY_PATH.write_text(json.dumps(entries))
    except OSError:  # pragma: no cover - best effort persistence
        pass


def _cleanup_entry(path: Path) -> None:
    with contextlib.suppress(OSError):
        path.unlink(missing_ok=True)


def cleanup_expired_paths(now: datetime | None = None) -> None:
    """Remove registry entries whose expiry has passed or files are gone."""
    timestamp = (now or datetime.now(timezone.utc)).timestamp()
    with _REGISTRY_LOCK:
        registry = _read_registry()
        updated: Dict[str, float] = {}
        for path_str, expires_at in registry.items():
            path = Path(path_str)
            if expires_at <= timestamp or not path.exists():
                _cleanup_entry(path)
                continue
            updated[path_str] = expires_at
        if updated != registry:
            _write_registry(updated)


def register_temp_path(path: str | Path, *, ttl: timedelta | None = None) -> None:
    """Record a path in the registry and prune expired entries."""
    path_obj = Path(path)
    ttl = ttl or DEFAULT_TTL
    expires_at = datetime.now(timezone.utc) + ttl
    with _REGISTRY_LOCK:
        registry = _read_registry()
        now_ts = datetime.now(timezone.utc).timestamp()
        changed = False
        for path_str, expiry in list(registry.items()):
            candidate = Path(path_str)
            if expiry <= now_ts or not candidate.exists():
                _cleanup_entry(candidate)
                del registry[path_str]
                changed = True
        registry[str(path_obj)] = expires_at.timestamp()
        changed = True
        if changed:
            _write_registry(registry)


def unregister_temp_path(path: str | Path) -> None:
    path_str = str(Path(path))
    with _REGISTRY_LOCK:
        registry = _read_registry()
        if path_str in registry:
            del registry[path_str]
            _write_registry(registry)


def remove_temp_path(path: str | Path) -> None:
    """Delete a temp file and unregister it from the registry."""
    path_obj = Path(path)
    _cleanup_entry(path_obj)
    unregister_temp_path(path_obj)


@dataclass
class TempFileTracker:
    """Session-scoped helper that tracks temp artifacts for eager cleanup."""

    ttl: timedelta = DEFAULT_TTL
    _paths: Set[Path] = field(default_factory=set)
    _lock: threading.RLock = field(default_factory=threading.RLock, init=False, repr=False)

    def add(self, path: str | Path) -> None:
        path_obj = Path(path)
        register_temp_path(path_obj, ttl=self.ttl)
        with self._lock:
            self._paths.add(path_obj)

    def discard(self, path: str | Path, *, remove: bool = False) -> None:
        path_obj = Path(path)
        if remove:
            remove_temp_path(path_obj)
        else:
            unregister_temp_path(path_obj)
        with self._lock:
            self._paths.discard(path_obj)

    def cleanup(self) -> None:
        with self._lock:
            for path in list(self._paths):
                remove_temp_path(path)
            self._paths.clear()

    def __del__(self) -> None:  # pragma: no cover - best effort GC hook
        with contextlib.suppress(Exception):
            self.cleanup()


cleanup_expired_paths()
