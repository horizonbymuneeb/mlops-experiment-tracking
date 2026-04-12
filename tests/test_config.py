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


def test_bool_is_not_accepted_as_int():
    with pytest.raises(ConfigError, match="must be an int"):
        TrackerConfig.from_mapping({"metrics": {"auto_step": True, "max_batch": True}})


def test_invalid_journal_mode_rejected():
    with pytest.raises(ConfigError, match="journal_mode"):
        DatabaseConfig(journal_mode="turbo")


def test_negative_busy_timeout_rejected():
    with pytest.raises(ConfigError, match="busy_timeout_ms"):
        DatabaseConfig(busy_timeout_ms=-1)


def test_invalid_hash_algorithm_rejected():
    with pytest.raises(ConfigError, match="hash_algorithm"):
        ArtifactConfig(hash_algorithm="crc32")


def test_cli_limit_must_be_positive():
    with pytest.raises(ConfigError, match="default_limit"):
        CliConfig(default_limit=0)


def test_metrics_max_batch_must_be_positive():
    with pytest.raises(ConfigError, match="max_batch"):
        MetricsConfig(max_batch=0)


def test_deep_merge_is_recursive_and_pure():
    base = {"a": {"b": 1, "c": 2}, "d": 3}
    override = {"a": {"c": 9}}
    merged = deep_merge(base, override)
    assert merged == {"a": {"b": 1, "c": 9}, "d": 3}
    assert base == {"a": {"b": 1, "c": 2}, "d": 3}, "deep_merge must not mutate its input"


def test_deep_merge_replaces_lists():
    assert deep_merge({"a": [1, 2]}, {"a": [3]}) == {"a": [3]}


def test_load_config_reads_yaml_and_resolves_relative_paths(tmp_path):
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(
        yaml.safe_dump({"database": {"path": "db/custom.db"}, "metrics": {"max_batch": 5}}),
        encoding="utf-8",
    )
    config = load_config(cfg_file)
    assert config.metrics.max_batch == 5
    assert config.db_path() == (tmp_path / "db" / "custom.db").resolve()
    assert config.artifact_dir() == (tmp_path / "artifacts").resolve()
