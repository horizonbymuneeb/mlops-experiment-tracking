"""JSON/CSV export and the matching importer."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from tracker.export import (
    CSV_METRIC_COLUMNS,
    EXPORT_FORMAT,
    EXPORT_VERSION,
    ExportError,
    export_json_file,
    export_manifest,
    export_metrics_csv,
    export_params_csv,
    export_run,
    export_runs,
    export_summary_csv,
    import_runs,
    read_json,
    to_jsonable,
    write_json,
)
from tracker.query import RunFilter


def test_export_run_contains_everything(db, tracker):
    run = tracker.start_run("baseline", params={"lr": 0.1, "amp": True}, tags=["nightly"])
    run.log_metric("loss", 0.5, step=0)
    run.log_metric("loss", 0.4, step=1)
    run.log_artifact(b"payload", name="data.bin")
    run.finish()

    payload = export_run(db, run.id)
    assert payload["run"]["name"] == "baseline"
    assert payload["run"]["status"] == "finished"
    assert payload["params"] == {"lr": 0.1, "amp": True}
    assert payload["tags"] == ["nightly"]
    assert payload["metrics"]["loss"] == [[0, 0.5], [1, 0.4]]
    assert payload["artifacts"][0]["name"] == "data.bin"


def test_export_run_missing(db):
    with pytest.raises(ExportError, match="does not exist"):
        export_run(db, 404)


def test_export_runs_document_shape(db, seeded):
    document = export_runs(db)
    assert document["format"] == EXPORT_FORMAT
    assert document["version"] == EXPORT_VERSION
    assert document["run_count"] == 3
    assert len(document["runs"]) == 3
    assert document["exported_at"].endswith("Z")


def test_export_runs_selection_and_filter(db, seeded):
    only = export_runs(db, run_ids=[seeded[1].id])
    assert only["run_count"] == 1
    assert only["runs"][0]["run"]["name"] == "wider"
    filtered = export_runs(db, run_filter=RunFilter(status="failed"))
    assert filtered["run_count"] == 1
    assert filtered["runs"][0]["run"]["name"] == "failed-run"
    with pytest.raises(ExportError, match="does not exist"):
        export_runs(db, run_ids=[999])


def test_export_runs_can_drop_artifacts(db, tracker):
    run = tracker.start_run("r")
    run.log_artifact(b"x", name="x.bin")
    document = export_runs(db, include_artifacts=False)
    assert document["runs"][0]["artifacts"] == []


def test_json_file_roundtrip(db, seeded, tmp_path):
    target = tmp_path / "export.json"
    written = export_json_file(db, target)
    assert written == target
    payload = read_json(target)
    assert payload["run_count"] == 3
    assert json.loads(target.read_text(encoding="utf-8"))["format"] == EXPORT_FORMAT
