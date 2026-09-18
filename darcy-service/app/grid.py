"""雷诺数网格上的摩阻系数序列生成（纯领域逻辑，不落库）。"""
from __future__ import annotations

import math
from typing import Any

from .config import RELATIVE_ROUGHNESS_MAX_EXCLUSIVE
from .errors import ValidationError
from .regimes import Regime, classify
from .turbulence import solve_turbulent_friction
from .validation import finite_float

MAX_GRID_POINTS = 1000


def validate_grid_inputs(
    relative_roughness: Any, reynolds_min: Any, reynolds_max: Any, count: Any, spacing: Any
) -> tuple[float, float, float, int, str]:
    eps = finite_float(relative_roughness, "relative_roughness")
    if eps < 0.0 or eps >= RELATIVE_ROUGHNESS_MAX_EXCLUSIVE:
        raise ValidationError(
            f"relative_roughness 必须在 [0, 1) 内，收到 {eps:g}。",
            field="relative_roughness",
            code="invalid_relative_roughness",
        )
    re_min = finite_float(reynolds_min, "reynolds_min")
    re_max = finite_float(reynolds_max, "reynolds_max")
    if re_min <= 0.0:
        raise ValidationError("reynolds_min 必须为正数。", field="reynolds_min")
    if re_max < re_min:
        raise ValidationError(
            f"reynolds_max({re_max:g}) 不能小于 reynolds_min({re_min:g})。",
            field="reynolds_max",
        )
    if isinstance(count, bool) or not isinstance(count, int):
        # JSON 里 count 是整数；pydantic Any 放行后这里严格拒绝 1.5 / 字符串。
        try:
            count_int = int(count)
            if float(count) != count_int:
                raise ValueError
        except (TypeError, ValueError):
            raise ValidationError("count 必须是 2~1000 的整数。", field="count")
        count = count_int
    if not 2 <= count <= MAX_GRID_POINTS:
        raise ValidationError(f"count 必须在 2~{MAX_GRID_POINTS} 之间，收到 {count}。", field="count")
    if not isinstance(spacing, str) or spacing not in ("log", "linear"):
        raise ValidationError(
            "spacing 只能是 'log' 或 'linear'。", field="spacing", code="invalid_spacing"
        )
    return eps, re_min, re_max, count, spacing


def _grid_values(re_min: float, re_max: float, count: int, spacing: str) -> list[float]:
    if spacing == "log":
        lo, hi = math.log10(re_min), math.log10(re_max)
        return [10.0 ** (lo + (hi - lo) * i / (count - 1)) for i in range(count)]
    step = (re_max - re_min) / (count - 1)
    return [re_min + step * i for i in range(count)]


def build_grid(
    relative_roughness: Any, reynolds_min: Any, reynolds_max: Any, count: Any, spacing: Any
) -> dict[str, Any]:
    eps, re_min, re_max, n, spacing_name = validate_grid_inputs(
        relative_roughness, reynolds_min, reynolds_max, count, spacing
    )
    points: list[dict[str, Any]] = []
    for re in _grid_values(re_min, re_max, n, spacing_name):
        regime = classify(re)
        point: dict[str, Any] = {"reynolds_number": re, "regime": regime.value}
        if regime is Regime.LAMINAR:
            point.update(
                result_type="friction_factor",
                modeled=True,
                friction_factor=64.0 / re,
            )
        elif regime is Regime.TRANSITION:
            point.update(
                result_type="transition_not_modeled",
                modeled=False,
                message="过渡区 [2300, 4000) 未建模。",
            )
        else:
            friction, residual, iterations = solve_turbulent_friction(re, eps)
            point.update(
                result_type="friction_factor",
                modeled=True,
                friction_factor=friction,
                residual_abs=residual,
                iterations=iterations,
            )
        points.append(point)

    return {
        "relative_roughness": eps,
        "reynolds_min": re_min,
        "reynolds_max": re_max,
        "count": n,
        "spacing": spacing_name,
        "points": points,
    }
