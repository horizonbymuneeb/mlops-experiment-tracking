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
