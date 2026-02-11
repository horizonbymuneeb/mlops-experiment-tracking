"""CLI wiring: init, list, show, compare, export, search, schema, gc."""

from __future__ import annotations

import json

import pytest
import yaml

from tracker.cli import (
    EXIT_ERROR,
    EXIT_OK,
    build_parser,
    format_table,
    main,
    resolve_config,
)


@pytest.fixture()
def cli(tmp_path, monkeypatch):
    """Run the CLI against a config file inside tmp_path.

    The repo ships a config.yaml, so the tests always point at their own file;
    otherwise a stray `tracker.db` would appear in the checkout.
    """
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "database": {
                    "path": str(tmp_path / "cli.db"),
                    "busy_timeout_ms": 2000,
                    "journal_mode": "WAL",
                    "synchronous": "NORMAL",
                },
                "artifacts": {
                    "directory": str(tmp_path / "artifacts"),
                    "hash_algorithm": "sha256",
                    "verify_on_read": False,
                },
                "metrics": {"auto_step": True, "max_batch": 500},
                "runs": {"allow_reopen": True, "default_notes": ""},
                "cli": {"default_limit": 20, "date_format": "%Y-%m-%d %H:%M"},
            }
        ),
        encoding="utf-8",
    )

    def invoke(*args: str) -> int:
        return main(["--config", str(config_path), *args])

    return invoke, config_path, tmp_path


def seed(config_path):
    """Create two finished runs through the library so the CLI has data."""
    from tracker.cli import open_tracker

    parser = build_parser()
    args = parser.parse_args(["--config", str(config_path), "list"])
    tracker = open_tracker(args)
    run = tracker.start_run("baseline", params={"lr": 0.1}, tags=["nightly"])
    run.log_metric("loss", 0.9, step=0)
    run.log_metric("loss", 0.5, step=1)
    run.finish()
    other = tracker.start_run("wider", params={"lr": 0.01})
    other.log_metric("loss", 0.4, step=0)
    other.finish()
    return tracker, run, other


def test_parser_has_all_commands():
    parser = build_parser()
    actions = [action for action in parser._actions if action.dest == "command"]
    assert actions, "subparsers missing"
    choices = actions[0].choices
    assert set(choices) == {"init", "list", "show", "compare", "export", "search", "schema", "gc"}
