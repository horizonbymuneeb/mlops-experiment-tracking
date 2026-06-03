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


def test_combined_filters(db, seeded):
    filt = RunFilter(status="finished", tags=["wide"], params={"lr": 0.01})
    assert names(query_runs(db, filt)) == ["wider"]


def test_ordering_and_pagination(db, seeded):
    ascending = query_runs(db, RunFilter(order_by="name"))
    assert [record.name for record in ascending] == ["baseline", "failed-run", "wider"]
    descending = query_runs(db, RunFilter(order_by="name", descending=True))
    assert [record.name for record in descending] == ["wider", "failed-run", "baseline"]
    page = query_runs(db, RunFilter(order_by="id", limit=1, offset=1))
    assert [record.id for record in page] == [2]


def test_count_runs_ignores_pagination(db, seeded):
    assert count_runs(db) == 3
    assert count_runs(db, RunFilter(status="finished")) == 2
    assert count_runs(db, RunFilter(status="finished", limit=1)) == 2


def test_build_run_query_has_order_and_limit(db):
    sql, params = build_run_query(RunFilter(limit=5, offset=2))
    assert "ORDER BY r.id ASC" in sql
    assert sql.endswith("LIMIT ? OFFSET ?")
    assert params == [5, 2]


def test_where_clause_without_filters(db):
    where, params = where_clause(RunFilter())
    assert where == ""
    assert params == []


def test_validate_rejects_bad_order(db):
    with pytest.raises(QueryError, match="order_by"):
        RunFilter(order_by="password").validate()


def test_validate_rejects_bad_bounds(db):
    with pytest.raises(QueryError, match="low > high"):
        RunFilter(param_ranges={"lr": (1.0, 0.0)}).validate()
    with pytest.raises(QueryError, match="pair"):
        RunFilter(metric_ranges={"loss": (1.0,)}).validate()


def test_validate_rejects_empty_status_list():
    with pytest.raises(QueryError, match="status filter is empty"):
        RunFilter(status=[]).validate()


def test_normalize_limit_and_offset():
    assert normalize_limit(None) is None
    assert normalize_limit(5) == 5
    for bad in (0, -1, True, "5", MAX_LIMIT + 1):
        with pytest.raises(QueryError):
            normalize_limit(bad)
    assert normalize_offset(0) == 0
    for bad in (-1, True, 1.5):
        with pytest.raises(QueryError):
            normalize_offset(bad)
