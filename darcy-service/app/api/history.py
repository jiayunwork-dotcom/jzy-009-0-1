"""历史查询接口：GET /api/history 与 GET /api/history/{record_id}。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from ..database import get_session
from ..models import CalculationRecord
from . import serialize_record

router = APIRouter(prefix="/api/history", tags=["history"])


@router.get("")
def list_history(
    endpoint: str | None = Query(None, description="按来源接口过滤"),
    regime: str | None = Query(None, description="按区制过滤 laminar/transition/turbulent"),
    success: bool | None = Query(None, description="按成功/失败过滤"),
    batch_id: str | None = Query(None),
    min_re: float | None = Query(None, alias="min_reynolds_number"),
    max_re: float | None = Query(None, alias="max_reynolds_number"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> dict:
    from ..repository import query_records

    session = get_session()
    try:
        records, total = query_records(
            session,
            endpoint=endpoint,
            regime=regime,
            success=success,
            batch_id=batch_id,
            min_reynolds_number=min_re,
            max_reynolds_number=max_re,
            limit=limit,
            offset=offset,
        )
        return {
            "ok": True,
            "total": total,
            "limit": limit,
            "offset": offset,
            "items": [serialize_record(r) for r in records],
        }
    finally:
        session.close()


@router.get("/{record_id}")
def get_record(record_id: int) -> dict:
    session = get_session()
    try:
        rec = session.get(CalculationRecord, record_id)
        if rec is None:
            raise HTTPException(status_code=404, detail=f"历史记录 {record_id} 不存在。")
        return {"ok": True, "item": serialize_record(rec)}
    finally:
        session.close()
