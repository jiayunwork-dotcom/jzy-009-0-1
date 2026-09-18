"""HTTP 辅助：结果序列化与“单次核算 + 落库”的统一入口。"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from ..errors import DomainError, RegimeNotModeledError
from .. import repository
from ..models import CalculationRecord
from ..service import FrictionResult, compute_friction


def serialize_success(result: FrictionResult) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "result_type": "friction_factor",
        "modeled": True,
        "regime": result.regime,
        "reynolds_number": result.reynolds_number,
        "relative_roughness": result.relative_roughness,
        "friction_factor": result.friction_factor,
    }
    if result.residual_abs is not None:
        payload["residual_abs"] = result.residual_abs
        payload["iterations"] = result.iterations
    if result.pressure_drop_pa is not None:
        payload["pressure_drop_pa"] = result.pressure_drop_pa
        payload.update(result.extra)
    return payload


def serialize_transition(reynolds_number: float, relative_roughness: float) -> dict[str, Any]:
    return {
        "result_type": "transition_not_modeled",
        "modeled": False,
        "regime": "transition",
        "reynolds_number": reynolds_number,
        "relative_roughness": relative_roughness,
        "message": (
            f"reynolds_number={reynolds_number:g} 落在过渡区 [2300, 4000)，"
            "该区制未建模，未计算摩阻系数。"
        ),
    }


def serialize_error(error: DomainError) -> dict[str, Any]:
    body = error.to_dict()
    body["message"] = error.message
    return body


def serialize_record(rec: CalculationRecord) -> dict[str, Any]:
    return {
        "id": rec.id,
        "created_at": rec.created_at.isoformat() if rec.created_at else None,
        "endpoint": rec.endpoint,
        "batch_id": rec.batch_id,
        "batch_index": rec.batch_index,
        "reynolds_number": rec.reynolds_number,
        "relative_roughness": rec.relative_roughness,
        "forced_regime": rec.forced_regime,
        "success": rec.success,
        "regime": rec.regime,
        "result_type": rec.result_type,
        "friction_factor": rec.friction_factor,
        "residual_abs": rec.residual_abs,
        "iterations": rec.iterations,
        "pressure_drop_pa": rec.pressure_drop_pa,
        "error_code": rec.error_code,
        "error_message": rec.error_message,
        "error_field": rec.error_field,
        "request_snapshot": rec.request_snapshot,
    }


def run_case_and_persist(
    session: Session,
    endpoint: str,
    payload: dict[str, Any],
    *,
    batch_id: str | None = None,
    batch_index: int | None = None,
) -> dict[str, Any]:
    """对一组工况执行核算并落库，返回可直接放入 HTTP 响应的 JSON 结构。

    - 成功（层流/湍流）：{"ok": True, ...结果}
    - 过渡区未建模：{"ok": True, "result_type": "transition_not_modeled", ...}
      （合法输入、可区分结果类型，按正常结果处理，不计失败）
    - 非法/矛盾/不收敛：{"ok": False, "error": {...}}
    """
    re = payload.get("reynolds_number")
    eps = payload.get("relative_roughness")

    def _failure(err: DomainError) -> dict[str, Any]:
        rec = repository.record_failure(
            session,
            endpoint=endpoint,
            error=err,
            request_snapshot=payload,
            reynolds_number=re if isinstance(re, (int, float)) and not isinstance(re, bool) else None,
            relative_roughness=eps
            if isinstance(eps, (int, float)) and not isinstance(eps, bool)
            else None,
            batch_id=batch_id,
            batch_index=batch_index,
        )
        body = serialize_error(err)
        body["ok"] = False
        body["record_id"] = rec.id
        return body

    try:
        result = compute_friction(
            re,
            eps,
            length=payload.get("length"),
            diameter=payload.get("diameter"),
            velocity=payload.get("velocity"),
            density=payload.get("density"),
            regime=payload.get("regime"),
        )
    except RegimeNotModeledError:
        # 先解析出合法数值用于记录；compute_friction 抛异常时输入已过校验，
        # 为稳妥这里再转一次，失败则按错误处理。
        try:
            re_f = float(re)
            eps_f = float(eps)
        except (TypeError, ValueError):
            return _failure(DomainError("过渡区记录失败：输入无法解析。", code="validation_error"))
        rec = repository.record_transition(
            session,
            endpoint=endpoint,
            reynolds_number=re_f,
            relative_roughness=eps_f,
            request_snapshot=payload,
            batch_id=batch_id,
            batch_index=batch_index,
        )
        body = serialize_transition(re_f, eps_f)
        body["ok"] = True
        body["record_id"] = rec.id
        return body
    except DomainError as err:
        return _failure(err)

    rec = repository.record_success(
        session,
        endpoint=endpoint,
        result=result,
        request_snapshot=payload,
        batch_id=batch_id,
        batch_index=batch_index,
    )
    body = serialize_success(result)
    body["ok"] = True
    body["record_id"] = rec.id
    return body


def new_batch_id() -> str:
    return uuid.uuid4().hex
