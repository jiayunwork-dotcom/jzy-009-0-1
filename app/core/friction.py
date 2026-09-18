"""摩阻系数计算：层流闭式公式与湍流 Colebrook 隐式方程。

湍流区使用以 10 为底的残差定义（令 x = 1/sqrt(f)）：

    R(x) = x + 2 * log10( rr / 3.7 + 2.51 * x / Re )

注意 2.51 * x / Re 即 f 形式中的 2.51 / (Re * sqrt(f))。
要求 |R(x)| <= 1e-8（钉死容差）。R'(x) 恒正，根唯一，
因此采用带二分保护的 Newton 法：Newton 步进被夹在当前有根区间内，
区间每轮必定收缩，保证全局收敛；若达到最大迭代仍未把残差压进容差，
抛出 NonConvergenceError，绝不交出残差很大的结果。
"""
from __future__ import annotations

import math

from . import config
from .errors import NonConvergenceError
from .regime import Regime, classify_reynolds

_LOG2_DIV_LN10 = 2.0 / math.log(10.0)  # 2 / ln(10)，导数用


def laminar_friction(reynolds: float) -> float:
    """层流闭式：f = 64 / Re。"""
    return 64.0 / reynolds


def colebrook_residual(friction: float, reynolds: float, relative_roughness: float) -> float:
    """按需求定义的原始残差（f 形式）。

    R = 1/sqrt(f) - ( -2 * log10(rr/3.7 + 2.51/(Re*sqrt(f))) )
      = 1/sqrt(f) + 2 * log10(...)
    """
    sqrt_f = math.sqrt(friction)
    return 1.0 / sqrt_f + 2.0 * math.log10(
        relative_roughness / 3.7 + 2.51 / (reynolds * sqrt_f)
    )


def _residual_x(x: float, reynolds: float, relative_roughness: float) -> float:
    """x = 1/sqrt(f) 形式的同一残差。"""
    return x + 2.0 * math.log10(
        relative_roughness / 3.7 + 2.51 * x / reynolds
    )


def _derivative_x(x: float, reynolds: float, relative_roughness: float) -> float:
    """R(x) 的解析导数，供 Newton 步进；恒为正。"""
    b = 2.51 * x / reynolds
    a = relative_roughness / 3.7 + b
    # d/dx [2 log10(a)] = (2/ln10) * b / (x*a)
    return 1.0 + _LOG2_DIV_LN10 * b / (x * a)


def _haaland_x(reynolds: float, relative_roughness: float) -> float:
    """Haaland 显式初值（同一 10 为底写法），仅用作初始猜测。

    1/sqrt(f) ≈ -1.8 log10( (rr/3.7)^2 + 6.9/Re )
    """
    inside = (relative_roughness / 3.7) ** 2 + 6.9 / reynolds
    return -1.8 * math.log10(inside)


def _bracket_root(reynolds: float, relative_roughness: float) -> tuple[float, float]:
    """构造 R 异号的有根区间 (lo, hi)。

    R(1) = 1 + 2 log10(rr/3.7 + 2.51/Re)，对合法输入
    （Re >= 4000, 0 <= rr < 1）恒负，而 R 严格递增、x→∞ 时 →∞，
    故从 lo=1 向上倍增 hi 即可夹住唯一根（且 f = 1/x² <= 1）。
    """
    lo = 1.0
    if _residual_x(lo, reynolds, relative_roughness) >= 0:
        raise NonConvergenceError(
            "无法构造湍流方程的有根区间（x=1 处残差非负）",
            details={"reynolds": reynolds, "relative_roughness": relative_roughness},
        )
    hi = max(2.0, _haaland_x(reynolds, relative_roughness) * 2.0)
    while _residual_x(hi, reynolds, relative_roughness) <= 0:
        hi *= 2.0
        if hi > 1e30:
            raise NonConvergenceError(
                "无法构造湍流方程的有根区间",
                details={"reynolds": reynolds, "relative_roughness": relative_roughness},
            )
    return lo, hi


def solve_turbulent(
    reynolds: float,
    relative_roughness: float,
    *,
    tolerance: float = config.TOLERANCE,
    max_iterations: int = config.MAX_ITERATIONS,
) -> tuple[float, float, int]:
    """求湍流摩阻系数。

    返回 (friction, residual, iterations)，残差以 f 代回需求定义重新计算。
    不收敛时抛 NonConvergenceError。
    """
    lo, hi = _bracket_root(reynolds, relative_roughness)
    x = max(lo, min(hi, _haaland_x(reynolds, relative_roughness)))

    for iteration in range(1, max_iterations + 1):
        r = _residual_x(x, reynolds, relative_roughness)
        if abs(r) <= tolerance:
            friction = 1.0 / (x * x)
            return friction, colebrook_residual(
                friction, reynolds, relative_roughness
            ), iteration

        # Newton 步进
        d = _derivative_x(x, reynolds, relative_roughness)
        x_newton = x - r / d

        # 夹在当前有根区间内；Newton 越界时退回二分中点
        if not (lo < x_newton < hi):
            x_newton = 0.5 * (lo + hi)
        x = x_newton

        # 收缩有根区间，保证下一轮仍夹得住根
        r_new = _residual_x(x, reynolds, relative_roughness)
        if r_new < 0:
            lo = x
        else:
            hi = x

    raise NonConvergenceError(
        f"湍流隐式方程在 {max_iterations} 次迭代内未收敛到容差 {tolerance:g}",
        details={
            "reynolds": reynolds,
            "relative_roughness": relative_roughness,
            "tolerance": tolerance,
            "max_iterations": max_iterations,
        },
    )


def calculate_friction(
    reynolds: float,
    relative_roughness: float,
) -> tuple[Regime, float | None, float | None, int | None]:
    """按区制返回 (区制, 摩阻系数, 残差, 迭代次数)。

    过渡区摩阻系数、残差、迭代次数均为 None，由上层标明未建模；
    层流为闭式结果，残差与迭代次数为 None（不套用隐式方程）。
    """
    regime = classify_reynolds(reynolds)
    if regime is Regime.LAMINAR:
        return regime, laminar_friction(reynolds), None, None
    if regime is Regime.TRANSITION:
        return regime, None, None, None
    friction, residual, iterations = solve_turbulent(reynolds, relative_roughness)
    return regime, friction, residual, iterations
