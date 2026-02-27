"""Parameter diffs, curve alignment and best-run selection."""

from __future__ import annotations

import pytest

from tracker.compare import (
    ComparisonError,
    ParamDiff,
    RunComparison,
    aggregate_metric,
    align_curves,
    best_run,
    compare_runs,
    diff_params,
    format_comparison,
    latest_values,
    metric_table,
    normalize_direction,
    summarize_params,
)
