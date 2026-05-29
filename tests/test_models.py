"""Record types, param encoding and timestamp handling."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from tracker.models import (
    RUN_STATUSES,
    ArtifactRecord,
    MetricRecord,
    ParamRecord,
    RunRecord,
    RunSummary,
    TagRecord,
    coerce_metric_value,
    coerce_param_value,
    decode_param_value,
    format_timestamp,
    iso_now,
    parse_timestamp,
    row_to_dict,
    utc_now,
)


@pytest.mark.parametrize(
    "value,expected_type",
    [
        (None, "null"),
        (True, "bool"),
        (False, "bool"),
        (7, "int"),
        (0.5, "float"),
        ("adam", "str"),
        ([1, 2], "json"),
        ({"a": 1}, "json"),
    ],
)
def test_param_roundtrip_keeps_type(value, expected_type):
    encoded, type_name = coerce_param_value(value)
    assert type_name == expected_type
    decoded = decode_param_value(encoded, type_name)
    assert decoded == value
    assert type(decoded) is type(value)


def test_param_int_and_float_are_distinct():
    int_encoded, int_type = coerce_param_value(10)
    float_encoded, float_type = coerce_param_value(10.0)
    assert (int_encoded, int_type) != (float_encoded, float_type)
    assert int_type == "int" and float_type == "float"


def test_param_rejects_non_finite_floats():
    with pytest.raises(ValueError, match="finite"):
        coerce_param_value(float("nan"))
    with pytest.raises(ValueError, match="finite"):
        coerce_param_value(float("inf"))


def test_param_rejects_unsupported_types():
    with pytest.raises(TypeError, match="unsupported parameter type"):
        coerce_param_value(object())


def test_decode_rejects_unknown_type_tag():
    with pytest.raises(ValueError, match="unknown parameter type"):
        decode_param_value("1", "complex")


def test_param_dicts_are_sorted_for_stable_encoding():
    assert coerce_param_value({"b": 2, "a": 1})[0] == coerce_param_value({"a": 1, "b": 2})[0]


@pytest.mark.parametrize("value,expected", [(1, 1.0), (2.5, 2.5), (True, None)])
def test_metric_coercion(value, expected):
    if expected is None:
        with pytest.raises(TypeError):
            coerce_metric_value(value)
    else:
        assert coerce_metric_value(value) == expected
        assert isinstance(coerce_metric_value(value), float)


def test_metric_rejects_nan_and_inf():
    with pytest.raises(ValueError, match="finite"):
        coerce_metric_value(float("nan"))
    with pytest.raises(ValueError, match="finite"):
        coerce_metric_value(float("-inf"))


def test_metric_rejects_strings():
    with pytest.raises(TypeError, match="numeric"):
        coerce_metric_value("0.5")


def test_iso_now_is_parseable_and_utc():
    stamp = iso_now()
    parsed = parse_timestamp(stamp)
    assert parsed.tzinfo is not None
    assert abs((datetime.now(timezone.utc) - parsed).total_seconds()) < 5


def test_timestamp_roundtrip():
    moment = datetime(2026, 3, 4, 5, 6, 7, 890000, tzinfo=timezone.utc)
    text = format_timestamp(moment)
    assert text == "2026-03-04T05:06:07.890000Z"
    assert parse_timestamp(text) == moment


def test_parse_timestamp_accepts_offset_and_naive():
    assert parse_timestamp("2026-03-04T05:06:07+00:00") == datetime(2026, 3, 4, 5, 6, 7, tzinfo=timezone.utc)
    assert parse_timestamp("2026-03-04T05:06:07") == datetime(2026, 3, 4, 5, 6, 7, tzinfo=timezone.utc)


def test_parse_timestamp_rejects_garbage():
    for bad in ("", "yesterday", None):
        with pytest.raises(ValueError):
            parse_timestamp(bad)


def test_format_timestamp_treats_naive_as_utc():
    naive = datetime(2026, 1, 1, 12, 0, 0)
    assert format_timestamp(naive).endswith("Z")


def test_run_record_from_row_and_duration():
    started = datetime(2026, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
    finished = started + timedelta(seconds=90)
    record = RunRecord.from_row(
        {
            "id": 1,
            "name": "a",
            "status": "finished",
            "started_at": format_timestamp(started),
            "finished_at": format_timestamp(finished),
            "host": "h",
            "notes": None,
            "resumed_count": 2,
        }
    )
    assert record.is_finished is True
    assert record.duration_seconds == pytest.approx(90.0)
    assert record.to_dict()["resumed_count"] == 2


def test_run_record_duration_none_while_running():
    record = RunRecord(id=1, name="a", status="running", started_at=iso_now())
    assert record.duration_seconds is None
    assert record.is_finished is False


def test_run_record_rejects_unknown_status():
    with pytest.raises(ValueError, match="unknown run status"):
        RunRecord(id=1, name="a", status="paused", started_at=iso_now())


def test_run_statuses_are_the_documented_set():
    assert RUN_STATUSES == ("running", "finished", "failed", "killed")


def test_param_record_python_value():
    record = ParamRecord.from_row({"run_id": 1, "key": "lr", "value": "0.25", "value_type": "float"})
    assert record.python_value == 0.25
    assert record.to_dict() == {"key": "lr", "value": 0.25, "type": "float"}


def test_metric_record_from_row():
    record = MetricRecord.from_row(
        {"id": 3, "run_id": 1, "key": "loss", "step": 4, "value": 0.5, "recorded_at": iso_now()}
    )
    assert record.step == 4 and record.value == 0.5
    assert record.to_dict()["key"] == "loss"


def test_artifact_and_tag_records():
    artifact = ArtifactRecord.from_row(
        {
            "id": 1,
            "run_id": 2,
            "name": "model.pt",
            "digest": "a" * 64,
            "size_bytes": 10,
            "media_type": "application/octet-stream",
            "created_at": iso_now(),
        }
    )
    assert artifact.to_dict()["name"] == "model.pt"
    tag = TagRecord.from_row({"run_id": 2, "tag": "nightly"})
    assert tag.tag == "nightly"


def test_run_summary_to_dict_sorts_keys():
    summary = RunSummary(
        run=RunRecord(id=1, name="a", status="finished", started_at=iso_now()),
        params={"b": 2, "a": 1},
        latest_metrics={"loss": 0.1},
        metric_counts={"loss": 3},
        tags=("x",),
        artifact_count=1,
    )
    payload = summary.to_dict()
    assert list(payload["params"]) == ["a", "b"]
    assert payload["tags"] == ["x"]
    assert payload["artifact_count"] == 1


def test_row_to_dict_handles_none_and_mapping():
    assert row_to_dict(None) == {}
    assert row_to_dict({"a": 1}) == {"a": 1}


def test_utc_now_is_aware():
    assert utc_now().tzinfo is not None
