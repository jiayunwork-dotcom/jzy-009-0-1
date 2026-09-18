"""历史记录仓储：核算结果落库与条件查询。"""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .errors import DomainError
from .models import CalculationRecord
from .service import FrictionResult


def _json_safe(value: Any) -> Any:
    """请求快照里的布尔/数值都可直接 JSON 化；防御性兜底。"""
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)


def record_success(
    session: Session,
    *,
    endpoint: str,
    result: FrictionResult,
    request_snapshot: dict[str, Any],
    batch_id: str | None = None,
    batch_index: int | None = None,
) -> CalculationRecord:
    rec = CalculationRecord(
        endpoint=endpoint,
        batch_id=batch_id,
        batch_index=batch_index,
        reynolds_number=result.reynolds_number,
        relative_roughness=result.relative_roughness,
        forced_regime=request_snapshot.get("regime"),
        success=True,
        regime=result.regime,
        result_type=result.result_type,
        friction_factor=result.friction_factor,
        residual_abs=result.residual_abs,
        iterations=result.iterations,
        pressure_drop_pa=result.pressure_drop_pa,
        request_snapshot=_json_safe(request_snapshot),
    )
    session.add(rec)
    session.flush()  # 拿到 id，但提交时机由调用方控制
    return rec


def record_transition(
    session: Session,
    *,
    endpoint: str,
    reynolds_number: float,
    relative_roughness: float,
    request_snapshot: dict[str, Any],
    batch_id: str | None = None,
    batch_index: int | None = None,
) -> CalculationRecord:
    """过渡区是“可区分的正常响应”，success=True 但 result_type 标明未建模。"""
    rec = CalculationRecord(
        endpoint=endpoint,
        batch_id=batch_id,
        batch_index=batch_index,
        reynolds_number=reynolds_number,
        relative_roughness=relative_roughness,
        forced_regime=request_snapshot.get("regime"),
        success=True,
        regime="transition",
        result_type="transition_not_modeled",
        request_snapshot=_json_safe(request_snapshot),
    )
    session.add(rec)
    session.flush()
    return rec


def record_failure(
    session: Session,
    *,
    endpoint: str,
    error: DomainError,
    request_snapshot: dict[str, Any],
    reynolds_number: float | None = None,
    relative_roughness: float | None = None,
    batch_id: str | None = None,
    batch_index: int | None = None,
) -> CalculationRecord:
    rec = CalculationRecord(
        endpoint=endpoint,
        batch_id=batch_id,
        batch_index=batch_index,
        reynolds_number=reynolds_number if isinstance(reynolds_number, (int, float)) else None,
        relative_roughness=relative_roughness if isinstance(relative_roughness, (int, float)) else None,
        forced_regime=request_snapshot.get("regime") if isinstance(request_snapshot, dict) else None,
        success=False,
        error_code=error.code,
        error_message=error.message,
        error_field=error.field,
        request_snapshot=_json_safe(request_snapshot),
    )
    session.add(rec)
    session.flush()
    return rec


def query_records(
    session: Session,
    *,
    endpoint: str | None = None,
    regime: str | None = None,
    success: bool | None = None,
    batch_id: str | None = None,
    min_reynolds_number: float | None = None,
    max_reynolds_number: float | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[CalculationRecord], int]:
    """按条件查历史，返回 (当前页记录, 满足条件的总数)。"""
    stmt = select(CalculationRecord)
    count_stmt = select(CalculationRecord.id)

    filters = []
    if endpoint is not None:
        filters.append(CalculationRecord.endpoint == endpoint)
    if regime is not None:
        filters.append(CalculationRecord.regime == regime)
    if success is not None:
        filters.append(CalculationRecord.success == success)
    if batch_id is not None:
        filters.append(CalculationRecord.batch_id == batch_id)
    if min_reynolds_number is not None:
        filters.append(CalculationRecord.reynolds_number >= min_reynolds_number)
    if max_reynolds_number is not None:
        filters.append(CalculationRecord.reynolds_number <= max_reynolds_number)

    for f in filters:
        stmt = stmt.where(f)
        count_stmt = count_stmt.where(f)

    total = len(list(session.execute(count_stmt).all()))
    rows = list(
        session.execute(
            stmt.order_by(CalculationRecord.id.desc()).limit(limit).offset(offset)
        ).scalars()
    )
    return rows, total
