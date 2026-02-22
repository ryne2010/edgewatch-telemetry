from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy.dialects import postgresql, sqlite

from api.app.routes.devices import _json_metric_text_expr, get_timeseries, get_timeseries_multi


def test_json_metric_text_expr_postgres_uses_text_extraction_operator() -> None:
    expr = _json_metric_text_expr("water_pressure_psi", "postgresql")
    sql = str(expr.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
    assert "->>" in sql


def test_json_metric_text_expr_sqlite_uses_json_extract() -> None:
    expr = _json_metric_text_expr("water_pressure_psi", "sqlite")
    sql = str(expr.compile(dialect=sqlite.dialect(), compile_kwargs={"literal_binds": True}))
    assert "json_extract" in sql.lower()


def test_get_timeseries_rejects_invalid_metric_key() -> None:
    with pytest.raises(HTTPException) as exc:
        get_timeseries(
            device_id="demo-well-001",
            metric="bad-key",
            bucket="minute",
            since=None,
            until=None,
            limit=100,
        )
    assert exc.value.status_code == 400
    assert "metric must match" in str(exc.value.detail)


def test_get_timeseries_multi_rejects_invalid_metric_keys() -> None:
    with pytest.raises(HTTPException) as exc:
        get_timeseries_multi(
            device_id="demo-well-001",
            metrics=["water_pressure_psi", "bad-key"],
            bucket="minute",
            since=None,
            until=None,
            limit=100,
        )
    assert exc.value.status_code == 400
    assert "invalid metric key" in str(exc.value.detail)
