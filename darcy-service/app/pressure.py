"""Darcy-Weisbach 沿程压降。

    dp = f * (L / D) * (rho * v^2 / 2)

满足需求比例关系：
- 与 f、管长 L 成正比；
- 与流速 v 的平方成正比；
- 与管内径 D 成反比。
调用前各量已由 validation 保证为正数。
"""
from __future__ import annotations


def pressure_drop(
    friction_factor: float, length: float, diameter: float, velocity: float, density: float
) -> float:
    return friction_factor * (length / diameter) * (0.5 * density * velocity * velocity)
