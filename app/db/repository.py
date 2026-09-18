"""历史记录仓储：写入与条件查询。"""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import CalculationRecord


def insert_record(session: Session, **fields: Any) -> CalculationRecord:
    record = CalculationRecord(**fields)
    session.add(record)
    session.commit()
    session.refresh(record)
    return record


def query_records(
    session: Session,
    *,
    regime: str | None = None,
    reynolds_min: float | None = None,
    reynolds_max: float | None = None,
    relative_roughness: float | None = None,
    status: str | None = None,
    source: str | None = None,
    batch_id: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[CalculationRecord], int]:
    """按条件分页查询，返回 (当前页记录, 满足条件的总数)。"""
    filters = []
    if regime is not None:
        filters.append(CalculationRecord.regime == regime)
    if reynolds_min is not None:
        filters.append(CalculationRecord.reynolds >= reynolds_min)
    if reynolds_max is not None:
        filters.append(CalculationRecord.reynolds <= reynolds_max)
    if relative_roughness is not None:
        filters.append(CalculationRecord.relative_roughness == relative_roughness)
    if status is not None:
        filters.append(CalculationRecord.status == status)
    if source is not None:
        filters.append(CalculationRecord.source == source)
    if batch_id is not None:
        filters.append(CalculationRecord.batch_id == batch_id)

    stmt = select(CalculationRecord)
    count_stmt = select(CalculationRecord.id)
    for f in filters:
        stmt = stmt.where(f)
        count_stmt = count_stmt.where(f)

    total = len(session.execute(count_stmt).all())
    rows = session.execute(
        stmt.order_by(CalculationRecord.id.desc())
        .limit(limit)
        .offset(offset)
    ).scalars().all()
    return list(rows), total


def record_to_dict(record: CalculationRecord) -> dict[str, Any]:
    return {
        "id": record.id,
        "created_at": record.created_at.isoformat() if record.created_at else None,
        "source": record.source,
        "batch_id": record.batch_id,
        "reynolds": record.reynolds,
        "relative_roughness": record.relative_roughness,
        "force_regime": record.force_regime,
        "regime": record.regime,
        "friction_factor": record.friction_factor,
        "residual": record.residual,
        "iterations": record.iterations,
        "pressure_drop_pa": record.pressure_drop_pa,
        "status": record.status,
        "error_code": record.error_code,
        "error_message": record.error_message,
        "request": record.request_payload,
        "result": record.result_payload,
    }
