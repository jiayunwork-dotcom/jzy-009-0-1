"""摩阻核算接口：

- POST /api/friction      单次摩阻核算（带压降可选字段时顺带压降）
- POST /api/pressure-drop 显式压降接口（要求四个压降参数齐全）
- GET  /api/example       预置算例：商用钢管、Re=1e5，f 约 0.018
"""
from __future__ import annotations

from fastapi import APIRouter, Response

from ..config import PRESET_EXAMPLE
from ..database import get_session
from ..errors import DomainError
from ..schemas import FrictionRequest, PressureDropRequest
from . import run_case_and_persist, serialize_error

router = APIRouter(prefix="/api", tags=["friction"])

# 不收敛属于“算不出来”而非“请求格式错”，用 422；其余领域错误用 400。
_STATUS_BY_CODE = {"root_not_converged": 422}


def _status_for(error: DomainError) -> int:
    return _STATUS_BY_CODE.get(error.code, 400)


@router.post("/friction")
def friction(req: FrictionRequest, response: Response) -> dict:
    payload = req.model_dump(exclude_none=True)
    session = get_session()
    try:
        body = run_case_and_persist(session, "friction", payload)
        if not body["ok"]:
            response.status_code = _status_for(_err_from_body(body))
        session.commit()
        return body
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@router.post("/pressure-drop")
def pressure_drop_endpoint(req: PressureDropRequest, response: Response) -> dict:
    payload = req.model_dump(exclude_none=True)
    session = get_session()
    try:
        # 压降接口语义上要求四个几何/流动参数齐全；缺失时领域层会给出
        # incomplete_pressure_inputs 的可读错误。
        body = run_case_and_persist(session, "pressure_drop", payload)
        if body["ok"] and body.get("result_type") == "transition_not_modeled":
            # 过渡区本来就没有 f，原样返回未建模结果，不误导成“缺字段”。
            return body
        if body["ok"] and body.get("pressure_drop_pa") is None:
            # friction 算出来了但没给全压降参数：明确拒绝而非静默忽略。
            from ..errors import ValidationError

            err = ValidationError(
                "压降接口必须同时提供 length/diameter/velocity/density。",
                field="length",
                code="incomplete_pressure_inputs",
            )
            response.status_code = _status_for(err)
            return {"ok": False, **serialize_error(err)}
        if not body["ok"]:
            response.status_code = _status_for(_err_from_body(body))
        session.commit()
        return body
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@router.get("/example")
def preset_example() -> dict:
    """预置算例（只读核算，不落历史）：商用钢管量级粗糙度、Re=1e5。"""
    from ..service import compute_friction

    result = compute_friction(
        PRESET_EXAMPLE["reynolds_number"], PRESET_EXAMPLE["relative_roughness"]
    )
    return {
        "description": "商用钢管量级相对粗糙度、雷诺数十万，f 应在 0.018 量级。",
        "request": PRESET_EXAMPLE,
        "result": {
            "regime": result.regime,
            "friction_factor": result.friction_factor,
            "residual_abs": result.residual_abs,
            "iterations": result.iterations,
        },
    }


def _err_from_body(body: dict) -> DomainError:
    """把 run_case_and_persist 的错误体还原成一个轻量错误以决定状态码。"""
    err = DomainError(
        body.get("message", "核算失败"),
        field=body.get("field"),
        code=body.get("error", "invalid_input"),
    )
    return err
