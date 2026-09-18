"""HTTP 请求/响应模式。

入参刻意声明为 Any 而不是 float：缺字段、字符串、布尔、NaN 等都放行到
app.validation，由领域层给出带字段名的可读错误，避免 pydantic 默认英文
报文把“第几组、哪个参数”的信息吞掉。
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class _LooseModel(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)


class FrictionRequest(_LooseModel):
    reynolds_number: Any = None
    relative_roughness: Any = None
    # 以下四个可选；全给则顺带计算压降
    length: Any = None
    diameter: Any = None
    velocity: Any = None
    density: Any = None
    # 可选的区制强制：'auto'（默认）/'laminar'/'turbulent'
    regime: Any = None


# 压降接口请求体字段与摩阻接口一致，仅语义上要求四个压降参数齐全。
PressureDropRequest = FrictionRequest


class BatchRequest(_LooseModel):
    cases: Any = Field(default=None, description="多组摩阻核算工况的数组")


class ReynoldsGridRequest(_LooseModel):
    relative_roughness: Any = None
    reynolds_min: Any = None
    reynolds_max: Any = None
    count: Any = 51
    spacing: Any = "log"  # 'log'（默认，对数等距）或 'linear'
