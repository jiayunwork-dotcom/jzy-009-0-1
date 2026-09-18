"""核算编排：把校验、区制判定、湍流求根、压降组装成一次完整核算。

本模块只做纯函数式领域编排，不碰 HTTP 与数据库，便于单元测试。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from .errors import RegimeNotModeledError
from .pressure import pressure_drop
from .regimes import Regime, classify
from .turbulence import solve_turbulent_friction
from .validation import (
    validate_core_inputs,
    validate_optional_pressure_inputs,
    validate_regime_override,
)


@dataclass
class FrictionResult:
    """已建模区制（层流/湍流）的正常结果。"""

    regime: Literal["laminar", "turbulent"]
    friction_factor: float
    reynolds_number: float
    relative_roughness: float
    residual_abs: float | None = None  # 层流闭式无残差概念
    iterations: int | None = None
    pressure_drop_pa: float | None = None
    result_type: str = "friction_factor"  # 与过渡区结果区分
    extra: dict[str, Any] = field(default_factory=dict)


def compute_friction(
    reynolds_number: Any,
    relative_roughness: Any,
    *,
    length: Any = None,
    diameter: Any = None,
    velocity: Any = None,
    density: Any = None,
    regime: Any = None,
) -> FrictionResult:
    """执行一次完整核算。

    - 输入不合法（缺字段/非数值/非有限/越界/区制矛盾）：抛 ValidationError；
    - 过渡区：抛 RegimeNotModeledError（可区分的结果类型，由上层转成结构化响应）；
    - 湍流不收敛：抛 RootConvergenceError；
    - 四个压降参数齐全：结果中带 pressure_drop_pa，否则只返回摩阻与区制。
    """
    re, eps = validate_core_inputs(reynolds_number, relative_roughness)
    forced = validate_regime_override(regime, re)
    want_pressure, pinputs = validate_optional_pressure_inputs(length, diameter, velocity, density)

    detected = classify(re)

    if detected is Regime.TRANSITION:
        # 强制层流/湍流在 validate_regime_override 已被挡掉；auto 下明确标注未建模。
        raise RegimeNotModeledError(re)

    residual: float | None = None
    iterations: int | None = None
    if detected is Regime.LAMINAR:
        if forced == "turbulent":  # 理论不可达，双保险
            raise RegimeNotModeledError(re)
        friction = 64.0 / re  # 钉死：层流闭式，绝不套用湍流隐式方程
        regime_name: str = Regime.LAMINAR.value
    else:
        friction, residual, iterations = solve_turbulent_friction(re, eps)
        regime_name = Regime.TURBULENT.value

    result = FrictionResult(
        regime=regime_name,  # type: ignore[arg-type]
        friction_factor=friction,
        reynolds_number=re,
        relative_roughness=eps,
        residual_abs=residual,
        iterations=iterations,
    )
    if want_pressure:
        assert pinputs is not None
        result.pressure_drop_pa = pressure_drop(
            friction,
            pinputs["length"],
            pinputs["diameter"],
            pinputs["velocity"],
            pinputs["density"],
        )
        result.extra = {
            "length": pinputs["length"],
            "diameter": pinputs["diameter"],
            "velocity": pinputs["velocity"],
            "density": pinputs["density"],
        }
    return result
