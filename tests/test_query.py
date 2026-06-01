"""Filters, ordering, pagination and read helpers."""

from __future__ import annotations

import pytest

from tracker.query import (
    MAX_LIMIT,
    QueryError,
    RunFilter,
    build_run_query,
    count_runs,
    distinct_metric_keys,
    distinct_param_keys,
    distinct_tags,
    escape_like,
    fetch_artifacts,
    fetch_latest_metric,
    fetch_metric_keys,
    fetch_metric_rows,
    fetch_metric_series,
    fetch_params,
    fetch_summary,
    fetch_tags,
    normalize_limit,
    normalize_offset,
    query_runs,
    run_detail,
    search_runs,
    where_clause,
)


def names(records):
    return sorted(record.name for record in records)


def test_filter_by_status(db, seeded):
    assert names(query_runs(db, RunFilter(status="finished"))) == ["baseline", "wider"]
    assert names(query_runs(db, RunFilter(status="failed"))) == ["failed-run"]
    assert len(query_runs(db, RunFilter(status=["finished", "failed"]))) == 3


def test_filter_by_name_like(db, seeded):
    assert names(query_runs(db, RunFilter(name_like="wid"))) == ["wider"]
    assert names(query_runs(db, RunFilter(name_like="RUN"))) == ["failed-run"]


def test_like_wildcards_are_escaped(db, seeded):
    db.execute_write("UPDATE runs SET name = '100%_done' WHERE name = 'wider'")
    assert names(query_runs(db, RunFilter(name_like="%"))) == ["100%_done"]
    assert names(query_runs(db, RunFilter(name_like="_"))) == ["100%_done"]


def test_filter_requires_all_tags(db, seeded):
    assert names(query_runs(db, RunFilter(tags=["nightly"]))) == ["baseline", "wider"]
    assert names(query_runs(db, RunFilter(tags=["nightly", "wide"]))) == ["wider"]
    assert query_runs(db, RunFilter(tags=["missing"])) == []


def test_filter_by_param_equality(db, seeded):
    assert names(query_runs(db, RunFilter(params={"lr": 0.1}))) == ["baseline", "failed-run"]
    assert names(query_runs(db, RunFilter(params={"lr": 0.1, "epochs": 5}))) == ["failed-run"]


def test_param_equality_is_type_strict(db, seeded):
    assert len(query_runs(db, RunFilter(params={"epochs": 2}))) == 2
    assert query_runs(db, RunFilter(params={"epochs": 2.0})) == []


def test_param_ranges(db, seeded):
    assert names(query_runs(db, RunFilter(param_ranges={"lr": (0.05, 0.2)}))) == [
        "baseline",
        "failed-run",
    ]
    assert names(query_runs(db, RunFilter(param_ranges={"epochs": (None, 2)}))) == [
        "baseline",
        "wider",
    ]


def test_metric_ranges_match_any_point(db, seeded):
    cheap = query_runs(db, RunFilter(metric_ranges={"loss": (None, 0.5)}))
    assert names(cheap) == ["wider"]
    expensive = query_runs(db, RunFilter(metric_ranges={"loss": (1.0, None)}))
    assert names(expensive) == ["failed-run"]
