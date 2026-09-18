"""沿程压降（Darcy–Weisbach）。

    Δp = f * (L / D) * 0.5 * ρ * V²

与摩阻系数、管长成正比，与流速平方成正比，与管内径成反比。
正值校验在 validation.collect_pressure_inputs 中完成。
"""
from __future__ import annotations


def pressure_drop(
    friction: float,
    *,
    pipe_length: float,
    diameter: float,
    velocity: float,
    density: float,
) -> float:
    return friction * (pipe_length / diameter) * 0.5 * density * velocity * velocity
