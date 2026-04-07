"""Config defaults, YAML loading and validation."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from tracker.config import (
    DEFAULT_CONFIG,
    ArtifactConfig,
    CliConfig,
    ConfigError,
    DatabaseConfig,
    MetricsConfig,
    RunsConfig,
    TrackerConfig,
    deep_merge,
    load_config,
    resolve_path,
    write_default_config,
)
