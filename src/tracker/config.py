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
