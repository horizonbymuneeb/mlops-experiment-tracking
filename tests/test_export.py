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


def test_write_json_is_sorted_and_atomic(tmp_path):
    target = tmp_path / "out.json"
    write_json(target, {"b": 1, "a": [1, 2]})
    text = target.read_text(encoding="utf-8")
    assert text.index('"a"') < text.index('"b"')
    assert text.endswith("\n")


def test_read_json_rejects_garbage(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(ExportError, match="not valid JSON"):
        read_json(bad)
    listing = tmp_path / "list.json"
    listing.write_text("[1, 2]", encoding="utf-8")
    with pytest.raises(ExportError, match="JSON object"):
        read_json(listing)


def test_metrics_csv(db, seeded, tmp_path):
    target = tmp_path / "metrics.csv"
    export_metrics_csv(db, target)
    with open(target, newline="", encoding="utf-8") as handle:
        rows = list(csv.reader(handle))
    assert tuple(rows[0]) == CSV_METRIC_COLUMNS
    assert len(rows) == 1 + 8  # 3 + 3 + 2 metric points
    assert {row[2] for row in rows[1:]} == {"loss"}
    assert rows[1][1] in {"baseline", "wider", "failed-run"}


def test_metrics_csv_run_selection(db, seeded, tmp_path):
    target = tmp_path / "one.csv"
    export_metrics_csv(db, target, [seeded[1].id])
    with open(target, newline="", encoding="utf-8") as handle:
        rows = list(csv.reader(handle))
    assert len(rows) == 4


def test_params_csv(db, seeded, tmp_path):
    target = tmp_path / "params.csv"
    export_params_csv(db, target)
    with open(target, newline="", encoding="utf-8") as handle:
        rows = list(csv.reader(handle))
    assert rows[0][:3] == ["run_id", "run_name", "key"]
    keys = {row[2] for row in rows[1:]}
    assert keys == {"lr", "epochs", "width"}
    lr_row = next(row for row in rows[1:] if row[2] == "lr")
    assert json.loads(lr_row[3]) in (0.1, 0.01)


def test_summary_csv(db, seeded, tmp_path):
    target = tmp_path / "summary.csv"
    export_summary_csv(db, target)
    with open(target, newline="", encoding="utf-8") as handle:
        rows = list(csv.reader(handle))
    assert len(rows) == 4
    assert rows[0][1] == "name"
    finished = next(row for row in rows[1:] if row[1] == "baseline")
    assert finished[2] == "finished"
    assert float(finished[5]) >= 0.0


def test_export_manifest(db, tracker):
    run = tracker.start_run("r")
    first = run.log_artifact(b"one", name="one.bin")
    second = tracker.start_run("r2")
    second.log_artifact(b"one", name="copy.bin")
    manifest = export_manifest(db)
    assert manifest["blob_count"] == 1
    assert manifest["total_bytes"] == 3
    entry = manifest["blobs"][first.digest]
    assert len(entry["references"]) == 2


def test_to_jsonable_handles_nested_and_rejects_objects():
    assert to_jsonable({"a": (1, 2), "b": Path("x")}) == {"a": [1, 2], "b": "x"}
    with pytest.raises(ExportError, match="cannot serialise"):
        to_jsonable(object())


def test_import_runs_creates_new_ids(db, seeded, tmp_path):
    document = export_runs(db)
    created = import_runs(db, document)
    assert len(created) == 3
    assert created[0] != seeded[0].id
    imported = export_run(db, created[0])
    assert imported["run"]["name"] == "baseline"
    assert imported["params"] == {"lr": 0.1, "epochs": 2}
    assert imported["tags"] == ["nightly"]
    assert imported["metrics"]["loss"] == [[0, 0.9], [1, 0.7], [2, 0.6]]
