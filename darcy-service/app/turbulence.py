"""湍流区 Colebrook-White 隐式方程求根。

待解的是以十为底的残差（题目钉死的定义）：

    r(f) = 1/sqrt(f)
           + 2 * log10( eps/3.7 + 2.51 / (Re * sqrt(f)) )

求 r(f) = 0 的 Darcy 摩阻系数 f。log 一律为以 10 为底的常用对数。

令 x = 1/sqrt(f)，方程化为关于 x 的单调标量方程，用 Newton 迭代；
Newton 失败时退到有括号的二分法；两条路都不能把残差压进容差时，
抛 RootConvergenceError，绝不返回残差很大的数。
"""
from __future__ import annotations

import math

from .config import RESIDUAL_TOLERANCE, ROOT_MAX_ITERATIONS
from .errors import RootConvergenceError

_LOG10 = math.log10  # 钉死：以十为底
_EPS_DIV_3P7 = 1.0 / 3.7


def colebrook_residual(friction_factor: float, reynolds_number: float, relative_roughness: float) -> float:
    """按题目定义的残差 r(f)。根处 r(f) = 0。"""
    if friction_factor <= 0.0:
        raise ValueError("friction_factor 必须为正")
    inv_sqrt_f = 1.0 / math.sqrt(friction_factor)
    bracket = relative_roughness / 3.7 + 2.51 / (reynolds_number * math.sqrt(friction_factor))
    return inv_sqrt_f + 2.0 * _LOG10(bracket)


def _residual_x(x: float, reynolds_number: float, a: float, b: float) -> float:
    """x = 1/sqrt(f) 形式的残差：x + 2 log10(a + b x)，a=eps/3.7, b=2.51/Re。"""
    return x + 2.0 * _LOG10(a + b * x)


def _haaland_seed(reynolds_number: float, relative_roughness: float) -> float:
    """Haaland 显式初值，已经离 Colebrook 根很近，供 Newton 起步。"""
    inner = (relative_roughness / 3.7) ** 1.11 + 6.9 / reynolds_number
    x = -1.8 * _LOG10(inner)
    # 理论上 x 必为正；极端输入下做一次兜底，避免 sqrt/对数越界。
    return max(x, 1e-6)


def _newton_x(
    reynolds_number: float, relative_roughness: float, a: float, b: float
) -> tuple[float, float, int]:
    """对 g(x) = x + 2 log10(a + b x) 做 Newton 迭代，返回 (x, 残差, 迭代次数)。"""
    x = _haaland_seed(reynolds_number, relative_roughness)
    ln10 = math.log(10.0)
    residual = float("inf")
    iterations = 0
    for iterations in range(1, ROOT_MAX_ITERATIONS + 1):
        inner = a + b * x
        g = x + 2.0 * _LOG10(inner)
        gprime = 1.0 + (2.0 / ln10) * b / inner
        x_new = x - g / gprime
        if x_new <= 0.0:  # 牛顿步越界，夹回正数域
            x_new = x * 0.5
        x = x_new
        residual = abs(g)
        if residual <= RESIDUAL_TOLERANCE:
            return x, residual, iterations
    return x, residual, iterations


def _bisect_x(reynolds_number: float, a: float, b: float) -> tuple[float, float]:
    """Newton 不收敛时的兜底：g(x) 严格单调，二分必中。返回 (x, 残差)。"""
    # 找右括号：g 随 x 单调递增且趋于 +inf。
    lo = 1e-12
    hi = 1.0
    for _ in range(200):
        if _residual_x(hi, reynolds_number, a, b) > 0.0 and a + b * hi > 0.0:
            break
        hi *= 2.0
    else:
        raise RootConvergenceError("二分法无法定位残差括号。")

    g_lo = _residual_x(lo, reynolds_number, a, b)
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        g_mid = _residual_x(mid, reynolds_number, a, b)
        if abs(g_mid) <= RESIDUAL_TOLERANCE:
            return mid, abs(g_mid)
        # g 严格递增：同号则根在另一侧。
        if (g_mid > 0.0) == (g_lo > 0.0):
            lo, g_lo = mid, g_mid
        else:
            hi = mid
    return 0.5 * (lo + hi), abs(_residual_x(0.5 * (lo + hi), reynolds_number, a, b))


def solve_turbulent_friction(
    reynolds_number: float, relative_roughness: float
) -> tuple[float, float, int]:
    """求湍流 Darcy 摩阻系数。

    返回 (friction_factor, 残差绝对值, 迭代次数)。
    残差以 f 形式的 colebrook_residual 复核；超过 RESIDUAL_TOLERANCE 即报错。
    """
    a = relative_roughness / 3.7
    b = 2.51 / reynolds_number

    x, residual_x, iterations = _newton_x(reynolds_number, relative_roughness, a, b)
    used_bisection = False
    if residual_x > RESIDUAL_TOLERANCE:
        x, residual_x = _bisect_x(reynolds_number, a, b)
        used_bisection = True

    friction_factor = 1.0 / (x * x)
    # 用题目给的 f 形式残差做最终验收，而不是只相信变换域里的残差。
    final_residual = abs(colebrook_residual(friction_factor, reynolds_number, relative_roughness))
    if final_residual > RESIDUAL_TOLERANCE:
        raise RootConvergenceError(
            "湍流摩阻系数求根未收敛到钉死容差 "
            f"{RESIDUAL_TOLERANCE:g} 以内，实际残差 {final_residual:g}。",
            residual=final_residual,
        )
    return friction_factor, final_residual, iterations + (1 if used_bisection else 0)
