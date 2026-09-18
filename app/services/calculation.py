"""核算编排：区制判定 -> 求根 -> 压降 -> 持久化。

HTTP 层只做协议适配，业务规则全部集中于此。
每个请求使用独立数据库会话，配合每请求独立的输入/结果对象，
并发请求之间不共享可变状态。
"""
from __future__ import annotations

import math
import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.core import config
from app.core.errors import (
    DomainError,
    RegimeConflictError,
    TransitionNotModeledError,
    ValidationError,
)
from app.core.friction import calculate_friction
from app.core.pressure import pressure_drop
from app.core.regime import Regime, classify_reynolds
from app.core.validation import collect_pressure_inputs, validate_relative_roughness, validate_reynolds
from app.db import repository
from app.db.session import get_session, write_lock

# 各服务接口在历史记录中的来源标记
SOURCE_SINGLE = "single"
SOURCE_BATCH = "batch"
SOURCE_GRID = "grid"


def _check_force_regime(
    regime: Regime, force_regime: str | None, reynolds: float
) -> None:
    if force_regime is None:
        return
    if force_regime == "turbulent" and regime is not Regime.TURBULENT:
        raise RegimeConflictError(
            f"请求强制按湍流计算，但雷诺数 {reynolds:g} 位于{_regime_label(regime)}"
            f"（湍流需 Re >= {config.RE_TURBULENT_MIN:g}）",
            field="force_regime",
            details={
                "forced": "turbulent",
                "actual_regime": regime.value,
                "reynolds": reynolds,
            },
        )
    if force_regime == "laminar" and regime is not Regime.LAMINAR:
        raise RegimeConflictError(
            f"请求强制按层流计算，但雷诺数 {reynolds:g} 位于{_regime_label(regime)}"
            f"（层流需 Re < {config.RE_LAMINAR_MAX:g}）",
            field="force_regime",
            details={
                "forced": "laminar",
                "actual_regime": regime.value,
                "reynolds": reynolds,
            },
        )


def _regime_label(regime: Regime) -> str:
    return {
        Regime.LAMINAR: "层流区",
        Regime.TRANSITION: "过渡区",
        Regime.TURBULENT: "湍流区",
    }[regime]


def _json_safe(value: Any) -> Any:
    """把 NaN/Infinity 等不可被标准 JSON 表达的值清洗成 None/字符串。"""
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, (int, str, bool)) or value is None:
        return value
    return str(value)


def _safe_scalar(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        return float(value)
    return None


def _persist(
    *,
    source: str,
    batch_id: str | None,
    request_payload: dict[str, Any],
    reynolds: float,
    relative_roughness: float,
    force_regime: str | None,
    regime_value: str,
    result_payload: dict[str, Any] | None,
    friction: float | None,
    residual: float | None,
    iterations: int | None,
    pressure: float | None,
    status: str,
    error_code: str | None = None,
    error_message: str | None = None,
) -> int:
    """落库一次核算。SQLite 下串行写，PG 下各自短事务。"""
    with write_lock():
        session: Session = get_session()
        try:
            record = repository.insert_record(
                session,
                source=source,
                batch_id=batch_id,
                reynolds=_safe_scalar(reynolds),
                relative_roughness=_safe_scalar(relative_roughness),
                force_regime=force_regime,
                regime=regime_value,
                friction_factor=friction,
                residual=residual,
                iterations=iterations,
                pressure_drop_pa=pressure,
                status=status,
                error_code=error_code,
                error_message=(error_message or "")[:500] or None,
                request_payload=_json_safe(request_payload),
                result_payload=_json_safe(result_payload),
            )
            return record.id  # type: ignore[no-any-return]
        finally:
            session.close()


_REQUIRED_CASE_FIELDS = ("reynolds", "relative_roughness")
_FIELD_LABELS = {"reynolds": "雷诺数", "relative_roughness": "相对粗糙度"}


def compute_case(
    *,
    reynolds: Any = None,
    relative_roughness: Any = None,
    force_regime: Any = None,
    pipe_length: Any = None,
    diameter: Any = None,
    velocity: Any = None,
    density: Any = None,
    source: str = SOURCE_SINGLE,
    batch_id: str | None = None,
    persist: bool = True,
) -> dict[str, Any]:
    """执行一组工况核算并落库，返回结果字典。

    正常返回带 status=ok 的结果；过渡区/不收敛等业务情形抛 DomainError，
    由调用方（单接口 / 批量 / 网格）决定如何呈现，失败同样留痕。
    """
    raw_request = {
        "reynolds": reynolds,
        "relative_roughness": relative_roughness,
        "force_regime": force_regime,
        "pipe_length": pipe_length,
        "diameter": diameter,
        "velocity": velocity,
        "density": density,
    }
    for name in _REQUIRED_CASE_FIELDS:
        if raw_request[name] is None:
            raise ValidationError(
                f"缺少必填字段 {name}（{_FIELD_LABELS[name]}）", field=name
            )
    if force_regime is not None and force_regime not in ("laminar", "turbulent"):
        raise ValidationError(
            f"force_regime 只能是 laminar 或 turbulent，收到 {force_regime!r}",
            field="force_regime",
        )
    # 先给一个保守的区制，仅用于失败留痕；校验失败不进入任何计算
    regime_pre = (
        classify_reynolds(reynolds)
        if isinstance(reynolds, (int, float)) and not isinstance(reynolds, bool)
        and math.isfinite(reynolds)
        else Regime.TRANSITION
    )
    try:
        # 领域校验先于一切计算（Pydantic 的 gt 约束不拦截 Infinity）
        reynolds = validate_reynolds(reynolds)
        relative_roughness = validate_relative_roughness(relative_roughness)
        regime_pre = classify_reynolds(reynolds)

        _check_force_regime(regime_pre, force_regime, reynolds)

        pressure_inputs, has_pressure = collect_pressure_inputs(
            {
                "pipe_length": pipe_length,
                "diameter": diameter,
                "velocity": velocity,
                "density": density,
            }
        )

        regime, friction, residual, iterations = calculate_friction(
            reynolds, relative_roughness
        )

        if regime is Regime.TRANSITION:
            raise TransitionNotModeledError(
                f"雷诺数 {reynolds:g} 位于过渡区 "
                f"[{config.RE_LAMINAR_MAX:g}, {config.RE_TURBULENT_MIN:g})，"
                "该区制未建模：既不套用层流公式也不套用湍流隐式方程",
                field="reynolds",
                details={
                    "reynolds": reynolds,
                    "laminar_max": config.RE_LAMINAR_MAX,
                    "turbulent_min": config.RE_TURBULENT_MIN,
                },
            )

        result: dict[str, Any] = {
            "status": "ok",
            "regime": regime.value,
            "reynolds": reynolds,
            "relative_roughness": relative_roughness,
            "friction_factor": friction,
        }
        if regime is Regime.TURBULENT:
            result["residual"] = residual
            result["residual_tolerance"] = config.TOLERANCE
            result["iterations"] = iterations
        else:
            # 层流闭式：明确标注不适用残差/隐式方程
            result["residual"] = None
            result["formula"] = "f = 64 / Re"

        pressure_value: float | None = None
        if has_pressure:
            pressure_value = pressure_drop(
                friction,  # type: ignore[arg-type]
                pipe_length=pressure_inputs["pipe_length"],
                diameter=pressure_inputs["diameter"],
                velocity=pressure_inputs["velocity"],
                density=pressure_inputs["density"],
            )
            result["pressure_drop"] = {
                "value_pa": pressure_value,
                "formula": "dp = f * (L/D) * 0.5 * rho * V^2",
                "inputs": pressure_inputs,
            }

        record_id = None
        if persist:
            record_id = _persist(
                source=source,
                batch_id=batch_id,
                request_payload=raw_request,
                reynolds=reynolds,
                relative_roughness=relative_roughness,
                force_regime=force_regime,
                regime_value=regime.value,
                result_payload=result,
                friction=friction,
                residual=residual,
                iterations=iterations,
                pressure=pressure_value,
                status="ok",
            )
        result["record_id"] = record_id
        return result

    except DomainError as exc:
        if persist:
            _persist(
                source=source,
                batch_id=batch_id,
                request_payload=raw_request,
                reynolds=reynolds,
                relative_roughness=relative_roughness,
                force_regime=force_regime,
                regime_value=regime_pre.value,
                result_payload=None,
                friction=None,
                residual=None,
                iterations=None,
                pressure=None,
                status="error",
                error_code=exc.code,
                error_message=exc.message,
            )
        raise


def compute_batch(cases: list[dict[str, Any]]) -> dict[str, Any]:
    """批量核算：逐组独立计算，某组失败不影响其余各组，结果顺序与输入一致。"""
    if len(cases) > config.BATCH_MAX_CASES:
        raise ValidationError(
            f"批量工况数不得超过 {config.BATCH_MAX_CASES} 组，收到 {len(cases)} 组",
            field="cases",
        )
    batch_id = str(uuid.uuid4())
    items: list[dict[str, Any]] = []
    success_count = 0
    failure_count = 0
    for index, case in enumerate(cases):
        if not isinstance(case, dict):
            failure_count += 1
            items.append({
                "error": True,
                "code": "INVALID_INPUT",
                "message": f"第 {index} 组工况必须是 JSON 对象",
                "field": "cases",
                "case_index": index,
            })
            continue
        try:
            item = compute_case(
                source=SOURCE_BATCH,
                batch_id=batch_id,
                **case,
            )
            item["case_index"] = index
            items.append(item)
            success_count += 1
        except TypeError as exc:
            # 未知字段等
            failure_count += 1
            items.append({
                "error": True,
                "code": "INVALID_INPUT",
                "message": f"第 {index} 组工况参数无法识别：{exc}",
                "field": "cases",
                "case_index": index,
            })
        except DomainError as exc:
            failure_count += 1
            err = exc.to_dict()
            err["case_index"] = index
            bad_re = case.get("reynolds")
            if isinstance(bad_re, (int, float)) and not isinstance(bad_re, bool) and math.isfinite(bad_re) and bad_re > 0:
                err["regime"] = classify_reynolds(bad_re).value
            items.append(err)

    return {
        "batch_id": batch_id,
        "total": len(cases),
        "success_count": success_count,
        "failure_count": failure_count,
        "results": items,
    }


def compute_reynolds_grid(
    *,
    reynolds_min: float,
    reynolds_max: float,
    relative_roughness: float,
    points: int,
    include_transition: bool = False,
) -> dict[str, Any]:
    """在 [reynolds_min, reynolds_max] 上按对数等距生成 Re 网格并逐点核算。"""
    if not isinstance(points, bool) and isinstance(points, (int, float)):
        if not math.isfinite(points) or points <= 0:
            raise ValidationError(
                f"网格点数必须为正整数，收到 {points!r}", field="points"
            )
    if points > config.GRID_MAX_POINTS:
        raise ValidationError(
            f"网格点数不得超过 {config.GRID_MAX_POINTS}，收到 {points}",
            field="points",
        )
    reynolds_min = validate_reynolds(reynolds_min)
    reynolds_max = validate_reynolds(reynolds_max)
    relative_roughness = validate_relative_roughness(relative_roughness)
    if reynolds_min >= reynolds_max:
        raise ValidationError(
            f"reynolds_min({reynolds_min:g}) 必须小于 reynolds_max({reynolds_max:g})",
            field="reynolds_min",
        )

    if points == 1:
        reynolds_list = [reynolds_min]
    else:
        log_lo, log_hi = math.log10(reynolds_min), math.log10(reynolds_max)
        step = (log_hi - log_lo) / (points - 1)
        reynolds_list = [10.0 ** (log_lo + step * i) for i in range(points)]

    grid_id = str(uuid.uuid4())
    entries: list[dict[str, Any]] = []
    for index, reynolds in enumerate(reynolds_list):
        regime = classify_reynolds(reynolds)
        if regime is Regime.TRANSITION and not include_transition:
            entries.append(
                {
                    "case_index": index,
                    "reynolds": reynolds,
                    "regime": regime.value,
                    "skipped": True,
                    "reason": "transition_not_modeled",
                }
            )
            continue
        try:
            item = compute_case(
                reynolds=reynolds,
                relative_roughness=relative_roughness,
                source=SOURCE_GRID,
                batch_id=grid_id,
            )
            item["case_index"] = index
            entries.append(item)
        except DomainError as exc:
            err = exc.to_dict()
            err["case_index"] = index
            err["reynolds"] = reynolds
            err["regime"] = regime.value
            entries.append(err)

    return {
        "grid_id": grid_id,
        "relative_roughness": relative_roughness,
        "points_requested": points,
        "points": entries,
    }


def query_history(params: dict[str, Any]) -> dict[str, Any]:
    session = get_session()
    try:
        rows, total = repository.query_records(
            session,
            regime=params.get("regime"),
            reynolds_min=params.get("reynolds_min"),
            reynolds_max=params.get("reynolds_max"),
            relative_roughness=params.get("relative_roughness"),
            limit=params.get("limit", 100),
            offset=params.get("offset", 0),
        )
        return {
            "total": total,
            "limit": params.get("limit", 100),
            "offset": params.get("offset", 0),
            "records": [repository.record_to_dict(r) for r in rows],
        }
    finally:
        session.close()
