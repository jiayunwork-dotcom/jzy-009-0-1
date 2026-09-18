"""配置回显接口：GET /api/config。

回显区制阈值与湍流残差容差等钉死配置，供调用方对齐口径。
"""
from __future__ import annotations

from fastapi import APIRouter

from ..config import (
    LAMINAR_RE_MAX,
    PRESET_EXAMPLE,
    PRESSURE_DROP_FIELDS,
    RELATIVE_ROUGHNESS_MAX_EXCLUSIVE,
    RELATIVE_ROUGHNESS_MIN,
    RESIDUAL_TOLERANCE,
    ROOT_MAX_ITERATIONS,
    TURBULENT_RE_MIN,
)

router = APIRouter(prefix="/api", tags=["config"])


@router.get("/config")
def get_config() -> dict:
    return {
        "ok": True,
        "regimes": {
            "laminar": {"reynolds_number": f"Re < {LAMINAR_RE_MAX:g}", "formula": "f = 64 / Re"},
            "transition": {
                "reynolds_number": f"{LAMINAR_RE_MAX:g} <= Re < {TURBULENT_RE_MIN:g}",
                "modeled": False,
                "result_type": "transition_not_modeled",
            },
            "turbulent": {
                "reynolds_number": f"Re >= {TURBULENT_RE_MIN:g}",
                "equation": "1/sqrt(f) + 2*log10(eps/3.7 + 2.51/(Re*sqrt(f))) = 0",
                "log_base": 10,
            },
        },
        "thresholds": {
            "laminar_re_max": LAMINAR_RE_MAX,
            "turbulent_re_min": TURBULENT_RE_MIN,
            "relative_roughness_range": [
                RELATIVE_ROUGHNESS_MIN,
                RELATIVE_ROUGHNESS_MAX_EXCLUSIVE,
            ],
        },
        "turbulent_root": {
            "residual_tolerance": RESIDUAL_TOLERANCE,
            "max_iterations": ROOT_MAX_ITERATIONS,
            "log_base": 10,
        },
        "pressure_drop": {
            "formula": "dp = f * (L/D) * rho * v^2 / 2",
            "required_fields": list(PRESSURE_DROP_FIELDS),
        },
        "preset_example": PRESET_EXAMPLE,
    }
