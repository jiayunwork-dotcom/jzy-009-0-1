"""雷诺数区制判定。

边界语义（需求硬性规定）：
- Re < 2300            -> laminar    层流，闭式 f = 64/Re
- 2300 <= Re < 4000    -> transition 过渡区，未建模，必须返回可区分结果类型
- Re >= 4000           -> turbulent  湍流，隐式方程求根
"""
from __future__ import annotations

from enum import Enum

from .config import LAMINAR_RE_MAX, TURBULENT_RE_MIN


class Regime(str, Enum):
    LAMINAR = "laminar"
    TRANSITION = "transition"
    TURBULENT = "turbulent"


def classify(reynolds_number: float) -> Regime:
    if reynolds_number < LAMINAR_RE_MAX:
        return Regime.LAMINAR
    if reynolds_number < TURBULENT_RE_MIN:
        return Regime.TRANSITION
    return Regime.TURBULENT
