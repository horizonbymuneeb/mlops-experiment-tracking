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
