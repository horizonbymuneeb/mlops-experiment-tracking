"""Configuration objects and YAML loading for the tracker.

``config.yaml`` in the repository root holds the tunables; every key has a
default here so the file can stay minimal. Paths in the YAML are resolved
relative to the YAML file itself (not the process CWD), which keeps the
tracker usable from any directory once it is pointed at a config file.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

import yaml

DEFAULT_CONFIG: dict[str, Any] = {
    "database": {
        "path": "tracker.db",
        "busy_timeout_ms": 5000,
        "journal_mode": "WAL",
        "synchronous": "NORMAL",
    },
    "artifacts": {
        "directory": "artifacts",
        "hash_algorithm": "sha256",
        "verify_on_read": False,
    },
    "metrics": {
        "auto_step": True,
        "max_batch": 500,
    },
    "runs": {
        "allow_reopen": True,
        "default_notes": "",
    },
    "cli": {
        "default_limit": 20,
        "date_format": "%Y-%m-%d %H:%M",
    },
}

JOURNAL_MODES = ("DELETE", "TRUNCATE", "PERSIST", "MEMORY", "WAL", "OFF")
SYNC_MODES = ("OFF", "NORMAL", "FULL", "EXTRA")
HASH_ALGORITHMS = ("sha256", "sha1", "md5")

# section -> key -> expected python type (bool is checked before int because
# bool is a subclass of int in python).
_SECTION_TYPES: dict[str, dict[str, type]] = {
    "database": {
        "path": str,
        "busy_timeout_ms": int,
        "journal_mode": str,
        "synchronous": str,
    },
    "artifacts": {
        "directory": str,
        "hash_algorithm": str,
        "verify_on_read": bool,
    },
    "metrics": {
        "auto_step": bool,
        "max_batch": int,
    },
    "runs": {
        "allow_reopen": bool,
        "default_notes": str,
    },
    "cli": {
        "default_limit": int,
        "date_format": str,
    },
}


class ConfigError(ValueError):
    """Raised when a config mapping is malformed or an override is unknown."""


@dataclass(frozen=True)
class DatabaseConfig:
    """Where the SQLite file lives and how connections behave."""

    path: str = "tracker.db"
    busy_timeout_ms: int = 5000
    journal_mode: str = "WAL"
    synchronous: str = "NORMAL"

    def __post_init__(self) -> None:
        if not self.path:
            raise ConfigError("database.path must not be empty")
        if self.busy_timeout_ms < 0:
            raise ConfigError("database.busy_timeout_ms must be >= 0")
        if self.journal_mode.upper() not in JOURNAL_MODES:
            raise ConfigError(
                f"database.journal_mode must be one of {JOURNAL_MODES}, "
                f"got {self.journal_mode!r}"
            )
        if self.synchronous.upper() not in SYNC_MODES:
            raise ConfigError(
                f"database.synchronous must be one of {SYNC_MODES}, "
                f"got {self.synchronous!r}"
            )

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, Any]) -> "DatabaseConfig":
        return cls(
            path=str(mapping["path"]),
            busy_timeout_ms=int(mapping["busy_timeout_ms"]),
            journal_mode=str(mapping["journal_mode"]),
            synchronous=str(mapping["synchronous"]),
        )


@dataclass(frozen=True)
class ArtifactConfig:
    """Content-addressed artifact store settings."""

    directory: str = "artifacts"
    hash_algorithm: str = "sha256"
    verify_on_read: bool = False

    def __post_init__(self) -> None:
        if not self.directory:
            raise ConfigError("artifacts.directory must not be empty")
        if self.hash_algorithm not in HASH_ALGORITHMS:
            raise ConfigError(
                f"artifacts.hash_algorithm must be one of {HASH_ALGORITHMS}, "
                f"got {self.hash_algorithm!r}"
            )

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, Any]) -> "ArtifactConfig":
        return cls(
            directory=str(mapping["directory"]),
            hash_algorithm=str(mapping["hash_algorithm"]),
            verify_on_read=bool(mapping["verify_on_read"]),
        )


@dataclass(frozen=True)
class MetricsConfig:
    """How metric rows are written."""

    auto_step: bool = True
    max_batch: int = 500

    def __post_init__(self) -> None:
        if self.max_batch < 1:
            raise ConfigError("metrics.max_batch must be >= 1")

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, Any]) -> "MetricsConfig":
        return cls(auto_step=bool(mapping["auto_step"]), max_batch=int(mapping["max_batch"]))


@dataclass(frozen=True)
class RunsConfig:
    """Run lifecycle policy."""

    allow_reopen: bool = True
    default_notes: str = ""

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, Any]) -> "RunsConfig":
        return cls(
            allow_reopen=bool(mapping["allow_reopen"]),
            default_notes=str(mapping["default_notes"]),
        )
