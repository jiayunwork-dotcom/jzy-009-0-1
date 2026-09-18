"""输入校验：把“非数值 / 缺失 / 非有限值 / 越界”统一挡在计算之前。

刻意不依赖 pydantic，原因有二：
1. 批量核算要对“第 i 组、哪个字段”给出精确错误，逐组手工校验更直接；
2. 核心规则测试可不经过 HTTP 直接调用。
"""
from __future__ import annotations

import math
from typing import Any

from .config import (
    LAMINAR_RE_MAX,
    PRESSURE_DROP_FIELDS,
    RELATIVE_ROUGHNESS_MAX_EXCLUSIVE,
    TURBULENT_RE_MIN,
)
from .errors import ValidationError

# bool 是 int 的子类，但 True/False 绝不是合法的水力参数。
_NUMERIC_TYPES = (int, float)


def finite_float(value: Any, field: str) -> float:
    """把入参解析为有限浮点数；拒绝缺失、布尔、字符串、NaN、Inf。"""
    if value is None:
        raise ValidationError(f"缺少必填字段 {field}。", field=field, code="missing_field")
    if isinstance(value, bool) or not isinstance(value, _NUMERIC_TYPES):
        raise ValidationError(
            f"字段 {field} 必须是数值，收到 {type(value).__name__}。",
            field=field,
            code="not_a_number",
        )
    result = float(value)
    if not math.isfinite(result):
        raise ValidationError(f"字段 {field} 必须是有限数值，收到 {value!r}。", field=field, code="not_finite")
    return result


def validate_core_inputs(reynolds_number: Any, relative_roughness: Any) -> tuple[float, float]:
    """校验摩阻核算的两个必填量，并施加物理合法性约束。"""
    re = finite_float(reynolds_number, "reynolds_number")
    eps = finite_float(relative_roughness, "relative_roughness")

    if re <= 0.0:
        raise ValidationError(
            f"reynolds_number 必须为正数，收到 {re:g}。",
            field="reynolds_number",
            code="non_positive_reynolds_number",
        )
    if eps < 0.0:
        raise ValidationError(
            f"relative_roughness 不能为负，收到 {eps:g}。",
            field="relative_roughness",
            code="negative_relative_roughness",
        )
    if eps >= RELATIVE_ROUGHNESS_MAX_EXCLUSIVE:
        raise ValidationError(
            f"relative_roughness 必须小于 1，收到 {eps:g}。",
            field="relative_roughness",
            code="relative_roughness_too_large",
        )
    return re, eps


def validate_optional_pressure_inputs(
    length: Any, diameter: Any, velocity: Any, density: Any
) -> tuple[bool, dict[str, float] | None]:
    """校验压降可选字段。

    约定：四个量要么全给（计算压降），要么全不给（只算摩阻，不报错）。
    给了一部分、或任一为非正值，都在计算压降前拒绝。
    """
    raw = {
        "length": length,
        "diameter": diameter,
        "velocity": velocity,
        "density": density,
    }
    present = {name: val for name, val in raw.items() if val is not None}
    if not present:
        return False, None
    missing = [name for name in PRESSURE_DROP_FIELDS if name not in present]
    if missing:
        raise ValidationError(
            "压降参数需同时提供 length/diameter/velocity/density，缺少：" + ", ".join(missing) + "。",
            field=missing[0],
            code="incomplete_pressure_inputs",
        )

    parsed: dict[str, float] = {}
    for name in PRESSURE_DROP_FIELDS:
        val = finite_float(raw[name], name)
        if val <= 0.0:
            raise ValidationError(
                f"压降参数 {name} 必须为正数，收到 {val:g}。", field=name, code="non_positive_pressure_input"
            )
        parsed[name] = val
    return True, parsed


def validate_regime_override(regime: Any, reynolds_number: float) -> str | None:
    """校验调用方对区制的强制要求，并检查其与雷诺数是否矛盾。

    - None / "auto"：按区制自动判定；
    - "laminar" / "turbulent"：只允许在对应雷诺数范围内强制，否则报矛盾错误；
    - 过渡区永远无法被强制（该区未建模）。
    """
    if regime is None:
        return None
    if not isinstance(regime, str):
        raise ValidationError(
            f"regime 必须是 'auto'/'laminar'/'turbulent' 字符串，收到 {type(regime).__name__}。",
            field="regime",
            code="invalid_regime",
        )
    normalized = regime.strip().lower()
    if normalized == "auto":
        return None
    if normalized not in ("laminar", "turbulent"):
        raise ValidationError(
            f"regime 只能取 'auto'、'laminar'、'turbulent'，收到 {regime!r}。",
            field="regime",
            code="invalid_regime",
        )
    if normalized == "laminar" and reynolds_number >= LAMINAR_RE_MAX:
        raise ValidationError(
            f"矛盾请求：强制层流结果，但 reynolds_number={reynolds_number:g} 不在层流区 (Re < 2300)。",
            field="regime",
            code="regime_conflict",
        )
    if normalized == "turbulent" and reynolds_number < TURBULENT_RE_MIN:
        raise ValidationError(
            f"矛盾请求：强制湍流结果，但 reynolds_number={reynolds_number:g} 不在湍流区 (Re >= 4000)。",
            field="regime",
            code="regime_conflict",
        )
    return normalized
