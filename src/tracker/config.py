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
