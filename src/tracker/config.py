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


@dataclass(frozen=True)
class CliConfig:
    """Presentation defaults for the command line interface."""

    default_limit: int = 20
    date_format: str = "%Y-%m-%d %H:%M"

    def __post_init__(self) -> None:
        if self.default_limit < 1:
            raise ConfigError("cli.default_limit must be >= 1")

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, Any]) -> "CliConfig":
        return cls(
            default_limit=int(mapping["default_limit"]),
            date_format=str(mapping["date_format"]),
        )


@dataclass(frozen=True)
class TrackerConfig:
    """Fully resolved configuration; the object every component receives."""

    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    artifacts: ArtifactConfig = field(default_factory=ArtifactConfig)
    metrics: MetricsConfig = field(default_factory=MetricsConfig)
    runs: RunsConfig = field(default_factory=RunsConfig)
    cli: CliConfig = field(default_factory=CliConfig)
    base_dir: Path = field(default_factory=lambda: Path.cwd())

    def db_path(self) -> Path:
        """Absolute path of the SQLite database file."""
        return resolve_path(self.database.path, self.base_dir)

    def artifact_dir(self) -> Path:
        """Absolute path of the artifact store root."""
        return resolve_path(self.artifacts.directory, self.base_dir)

    def to_dict(self) -> dict[str, Any]:
        return {
            "database": {
                "path": self.database.path,
                "busy_timeout_ms": self.database.busy_timeout_ms,
                "journal_mode": self.database.journal_mode,
                "synchronous": self.database.synchronous,
            },
            "artifacts": {
                "directory": self.artifacts.directory,
                "hash_algorithm": self.artifacts.hash_algorithm,
                "verify_on_read": self.artifacts.verify_on_read,
            },
            "metrics": {
                "auto_step": self.metrics.auto_step,
                "max_batch": self.metrics.max_batch,
            },
            "runs": {
                "allow_reopen": self.runs.allow_reopen,
                "default_notes": self.runs.default_notes,
            },
            "cli": {
                "default_limit": self.cli.default_limit,
                "date_format": self.cli.date_format,
            },
            "base_dir": str(self.base_dir),
        }

    @classmethod
    def from_mapping(
        cls, mapping: Mapping[str, Any], base_dir: Path | str | None = None
    ) -> "TrackerConfig":
        merged = deep_merge(DEFAULT_CONFIG, mapping)
        validate_config(merged)
        root = Path(base_dir) if base_dir is not None else Path.cwd()
        return cls(
            database=DatabaseConfig.from_mapping(merged["database"]),
            artifacts=ArtifactConfig.from_mapping(merged["artifacts"]),
            metrics=MetricsConfig.from_mapping(merged["metrics"]),
            runs=RunsConfig.from_mapping(merged["runs"]),
            cli=CliConfig.from_mapping(merged["cli"]),
            base_dir=root,
        )


def deep_merge(base: Mapping[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    """Recursively merge ``override`` into a copy of ``base``.

    Lists and scalars replace the base value outright; mappings merge key by
    key. The inputs are not mutated.
    """
    result: dict[str, Any] = copy.deepcopy(dict(base))
    for key, value in override.items():
        if key in result and isinstance(result[key], Mapping) and isinstance(value, Mapping):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result
