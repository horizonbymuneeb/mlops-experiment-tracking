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
