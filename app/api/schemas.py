"""Pydantic 请求 / 响应模型。"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.config import (
    EXAMPLE_RELATIVE_ROUGHNESS,
    EXAMPLE_REYNOLDS,
    RE_LAMINAR_MAX,
    RE_TURBULENT_MIN,
    TOLERANCE,
)


# ---------------- 单次核算 ----------------

class FrictionRequest(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)

    reynolds: float = Field(..., description="雷诺数，必须为正有限值")
    relative_roughness: float = Field(..., description="相对粗糙度 ε/D，取值 [0, 1)")
    # 调用方可声明预期区制；与雷诺数实际区制矛盾时拒绝
    force_regime: Literal["laminar", "turbulent"] | None = Field(
        default=None, description="强制要求的区制（laminar/turbulent），矛盾时报错"
    )
    # 可选压降字段：要么全给，要么都不给（范围由领域层校验）
    pipe_length: float | None = Field(default=None, description="管长 L (>0)")
    diameter: float | None = Field(default=None, description="管内径 D (>0)")
    velocity: float | None = Field(default=None, description="平均流速 V (>0)")
    density: float | None = Field(default=None, description="流体密度 ρ (>0)")


class LenientCase(BaseModel):
    """批量场景下的宽松工况模型：只保证 JSON 可解析、字段名存在；

    缺字段 / 非数值 / 非有限 / 取值范围错误全部作为该组的单项错误返回，
    其余各组照常计算。bool、字符串等也不会被强行 coerce。
    """
    model_config = ConfigDict(extra="ignore")

    reynolds: Any = None
    relative_roughness: Any = None
    force_regime: Any = None
    pipe_length: Any = None
    diameter: Any = None
    velocity: Any = None
    density: Any = None


class StructuredError(BaseModel):
    error: bool = True
    code: str
    message: str
    field: str | None = None
    details: dict[str, Any] | None = None
    case_index: int | None = Field(
        default=None, description="批量场景下出错的是第几组（从 0 起）"
    )


# ---------------- 批量 ----------------

class BatchRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    # 元素允许是任意 JSON：合法对象走核算，非对象在结果中作为该组错误，
    # 不让单个坏元素拖垮整批。
    cases: list[Any] = Field(..., min_length=1)

    @field_validator("cases")
    @classmethod
    def _normalize_cases(cls, values: list[Any]) -> list[Any]:
        normalized: list[Any] = []
        for v in values:
            if isinstance(v, dict):
                normalized.append(LenientCase(**v))
            else:
                normalized.append(v)  # 保留原值，服务层生成单项错误
        return normalized


# ---------------- 雷诺数网格 ----------------

class ReynoldsGridRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    reynolds_min: float = Field(..., gt=0.0)
    reynolds_max: float = Field(..., gt=0.0)
    relative_roughness: float = Field(..., ge=0.0, lt=1.0)
    points: int = Field(..., gt=0, description="网格点数（含端点，按对数等距）")
    include_transition: bool = Field(
        default=False,
        description="网格点落入过渡区时是否以未建模错误返回；默认跳过过渡点",
    )


# ---------------- 历史查询 ----------------

class HistoryQuery(BaseModel):
    model_config = ConfigDict(extra="ignore")

    regime: Literal["laminar", "transition", "turbulent"] | None = None
    reynolds_min: float | None = Field(default=None, gt=0.0)
    reynolds_max: float | None = Field(default=None, gt=0.0)
    relative_roughness: float | None = Field(default=None, ge=0.0, lt=1.0)
    limit: int = Field(default=100, gt=0, le=1000)
    offset: int = Field(default=0, ge=0)


class ConfigResponse(BaseModel):
    service: str
    version: str
    re_laminar_max: float
    re_turbulent_min: float
    transition_range: str
    residual_tolerance: float
    residual_base: int
    max_iterations: int
    example: dict[str, Any]
