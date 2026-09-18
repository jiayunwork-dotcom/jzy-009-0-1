"""雷诺数序列接口：POST /api/reynolds-grid。"""
from __future__ import annotations

from fastapi import APIRouter, Response

from ..database import get_session
from ..errors import DomainError
from ..grid import build_grid
from ..models import CalculationRecord
from ..schemas import ReynoldsGridRequest

router = APIRouter(prefix="/api", tags=["grid"])


@router.post("/reynolds-grid")
def reynolds_grid(req: ReynoldsGridRequest, response: Response) -> dict:
    payload = req.model_dump(exclude_none=True)
    try:
        result = build_grid(
            payload.get("relative_roughness"),
            payload.get("reynolds_min"),
            payload.get("reynolds_max"),
            payload.get("count", 51),
            payload.get("spacing", "log"),
        )
    except DomainError as err:
        response.status_code = 422 if err.code == "root_not_converged" else 400
        # 失败的网格请求也留痕，便于排查“谁用什么参数打挂了求根”。
        session = get_session()
        try:
            session.add(
                CalculationRecord(
                    endpoint="reynolds_grid",
                    success=False,
                    error_code=err.code,
                    error_message=err.message,
                    error_field=err.field,
                    request_snapshot=payload,
                )
            )
            session.commit()
        finally:
            session.close()
        return {"ok": False, "error": err.code, "message": err.message, "field": err.field}

    modeled = [p for p in result["points"] if p["modeled"]]
    session = get_session()
    try:
        session.add(
            CalculationRecord(
                endpoint="reynolds_grid",
                success=True,
                regime="mixed" if len({p["regime"] for p in result["points"]}) > 1 else result["points"][0]["regime"],
                relative_roughness=result["relative_roughness"],
                request_snapshot={
                    **payload,
                    "count": result["count"],
                    "spacing": result["spacing"],
                    "modeled_points": len(modeled),
                },
            )
        )
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
    return {"ok": True, **result}
