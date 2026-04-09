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


def test_defaults_are_complete():
    config = TrackerConfig.from_mapping({})
    assert config.database.busy_timeout_ms == 5000
    assert config.database.journal_mode == "WAL"
    assert config.artifacts.hash_algorithm == "sha256"
    assert config.metrics.auto_step is True
    assert config.runs.allow_reopen is True
    assert config.cli.default_limit == 20


def test_every_default_section_is_used():
    config = TrackerConfig.from_mapping({})
    dumped = config.to_dict()
    for section, values in DEFAULT_CONFIG.items():
        assert section in dumped
        for key in values:
            assert key in dumped[section]


def test_unknown_section_is_rejected():
    with pytest.raises(ConfigError, match="unknown config section"):
        TrackerConfig.from_mapping({"databse": {"path": "x.db"}})


def test_unknown_key_is_rejected():
    with pytest.raises(ConfigError, match="unknown config key database.pathh"):
        TrackerConfig.from_mapping({"database": {"pathh": "x.db"}})


def test_missing_key_is_rejected():
    # from_mapping() fills defaults first; validate_config() is the strict entry
    # point used when checking a hand-written mapping section by section.
    from tracker.config import validate_config

    with pytest.raises(ConfigError, match="missing keys"):
        validate_config({"database": {"path": "x.db"}})


def test_wrong_type_is_rejected():
    with pytest.raises(ConfigError, match="must be an int"):
        TrackerConfig.from_mapping({"metrics": {"auto_step": True, "max_batch": "lots"}})
