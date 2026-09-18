"""输入校验。

Web 层的 Pydantic 负责缺字段 / 非数值 / 非有限等结构校验；
本模块负责取值范围与跨字段语义校验，保证领域函数永远拿到合法输入，
也可供批量场景对单组工况复用。
"""
from __future__ import annotations

import math
from typing import Any

from .errors import ValidationError

# 压降所需的四个几何/物性字段
PRESSURE_FIELDS = ("pipe_length", "diameter", "velocity", "density")
_PRESSURE_FIELD_LABELS = {
    "pipe_length": "管长",
    "diameter": "管内径",
    "velocity": "平均流速",
    "density": "流体密度",
}


def require_finite_number(name: str, value: Any, label: str | None = None) -> float:
    """要求 value 为有限实数；布尔值按非法处理（bool 是 int 的子类）。"""
    label = label or name
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValidationError(f"{label}必须是数值", field=name)
    value = float(value)
    if not math.isfinite(value):
        raise ValidationError(f"{label}必须是有限数值（不能为 NaN 或无穷）", field=name)
    return value


def validate_reynolds(value: Any) -> float:
    reynolds = require_finite_number("reynolds", value, "雷诺数")
    if reynolds <= 0:
        raise ValidationError(
            f"雷诺数必须为正值，收到 {reynolds:g}", field="reynolds"
        )
    return reynolds


def validate_relative_roughness(value: Any) -> float:
    rr = require_finite_number(
        "relative_roughness", value, "相对粗糙度"
    )
    if rr < 0:
        raise ValidationError(
            f"相对粗糙度不得为负，收到 {rr:g}", field="relative_roughness"
        )
    if rr >= 1:
        raise ValidationError(
            f"相对粗糙度必须小于 1，收到 {rr:g}", field="relative_roughness"
        )
    return rr


def collect_pressure_inputs(
    provided: dict[str, Any],
) -> tuple[dict[str, float], bool]:
    """从给定字典中提取压降字段。

    返回 (合法的正字段字典, 是否出现全部四个字段)。
    - 一个都没给（值均为 None）：返回 ({}, False)，调用方跳过压降；
    - 给了一部分：抛 INVALID_INPUT 并列出缺失字段；
    - 给了但非数值/非有限/非正（含显式的 0）：按字段拒绝。
    """
    present = {k: provided.get(k) for k in PRESSURE_FIELDS if provided.get(k) is not None}
    if not present:
        return {}, False
    if len(present) != len(PRESSURE_FIELDS):
        missing_keys = [k for k in PRESSURE_FIELDS if k not in present]
        missing = [_PRESSURE_FIELD_LABELS[k] for k in missing_keys]
        raise ValidationError(
            "压降计算需要同时提供管长、管内径、平均流速与流体密度，"
            f"当前缺少：{'、'.join(missing)}",
            field="pressure_inputs",
            details={"missing": missing_keys},
        )
    cleaned: dict[str, float] = {}
    for key, raw in present.items():
        val = require_finite_number(key, raw, _PRESSURE_FIELD_LABELS[key])
        if val <= 0:
            raise ValidationError(
                f"{_PRESSURE_FIELD_LABELS[key]}必须为正值，收到 {val:g}", field=key
            )
        cleaned[key] = val
    return cleaned, True
