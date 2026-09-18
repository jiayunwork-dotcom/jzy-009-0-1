"""区制判定。

仅依据雷诺数划分为层流 / 过渡 / 湍流三种区制，
阈值取自 config，判定逻辑集中在此文件，不在别处散落魔数。
"""
from __future__ import annotations

from enum import Enum

from .config import RE_LAMINAR_MAX, RE_TURBULENT_MIN


class Regime(str, Enum):
    LAMINAR = "laminar"        # 层流（闭式公式）
    TRANSITION = "transition"  # 过渡区（未建模）
    TURBULENT = "turbulent"    # 湍流（Colebrook 隐式方程）


def classify_reynolds(reynolds: float) -> Regime:
    if reynolds < RE_LAMINAR_MAX:
        return Regime.LAMINAR
    if reynolds < RE_TURBULENT_MIN:
        return Regime.TRANSITION
    return Regime.TURBULENT
