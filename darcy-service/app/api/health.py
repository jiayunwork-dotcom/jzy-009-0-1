"""运行状态接口：供监控采集。"""
from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import text

from ..database import get_session

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict[str, str]:
    """存活探针：进程活着即可。"""
    return {"status": "ok"}


@router.get("/health/ready")
def readiness() -> dict[str, object]:
    """就绪探针：顺手探测数据库连通性。"""
    try:
        session = get_session()
        try:
            session.execute(text("SELECT 1"))
        finally:
            session.close()
    except Exception as exc:  # noqa: BLE001 - 探针就是要吞掉异常转成状态
        return {"status": "degraded", "database": "unavailable", "detail": str(exc)}
    return {"status": "ok", "database": "available"}
