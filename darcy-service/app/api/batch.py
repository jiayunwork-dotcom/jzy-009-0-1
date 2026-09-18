"""批量核算接口：POST /api/batch。

某一组非法时指出是第几组（1 起）、哪个参数；其余各组照常返回。
"""
from __future__ import annotations

from fastapi import APIRouter

from ..database import get_session
from ..errors import ValidationError
from ..schemas import BatchRequest
from . import new_batch_id, run_case_and_persist

router = APIRouter(prefix="/api", tags=["batch"])

MAX_BATCH_CASES = 500


@router.post("/batch")
def batch(req: BatchRequest) -> dict:
    cases = req.cases
    if cases is None:
        raise _http_validation("缺少必填字段 cases。", field="cases", code="missing_field")
    if not isinstance(cases, list):
        raise _http_validation("cases 必须是工况数组。", field="cases", code="not_a_list")
    if len(cases) == 0:
        raise _http_validation("cases 不能为空数组。", field="cases", code="empty_batch")
    if len(cases) > MAX_BATCH_CASES:
        raise _http_validation(
            f"批量最多 {MAX_BATCH_CASES} 组，收到 {len(cases)} 组。",
            field="cases",
            code="batch_too_large",
        )

    batch_id = new_batch_id()
    session = get_session()
    results: list[dict] = []
    computed_count = 0
    failure_count = 0
    transition_count = 0
    try:
        for index, case in enumerate(cases):
            if not isinstance(case, dict):
                err = ValidationError(
                    f"第 {index + 1} 组工况必须是对象，收到 {type(case).__name__}。",
                    field="case",
                    code="invalid_case",
                )
                from .. import repository

                rec = repository.record_failure(
                    session,
                    endpoint="batch",
                    error=err,
                    request_snapshot={"case": repr(case)},
                    batch_id=batch_id,
                    batch_index=index,
                )
                results.append(
                    {
                        "ok": False,
                        "index": index + 1,
                        "record_id": rec.id,
                        "error": err.code,
                        "field": err.field,
                        "message": err.message,
                    }
                )
                failure_count += 1
                continue

            body = run_case_and_persist(
                session, "batch", case, batch_id=batch_id, batch_index=index
            )
            body["index"] = index + 1
            if body["ok"]:
                if body.get("result_type") == "transition_not_modeled":
                    transition_count += 1
                else:
                    computed_count += 1
            else:
                failure_count += 1
            results.append(body)
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

    return {
        "ok": True,
        "batch_id": batch_id,
        "total": len(results),
        # computed：真正给出摩擦系数的组；transition 单独计；failed：非法/不收敛。
        "succeeded": computed_count,
        "computed": computed_count,
        "failed": failure_count,
        "transition_not_modeled": transition_count,
        "results": results,
    }


def _http_validation(message: str, *, field: str, code: str) -> ValidationError:
    return ValidationError(message, field=field, code=code)
