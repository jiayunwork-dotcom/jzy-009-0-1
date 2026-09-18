"""持久化模型。"""
from __future__ import annotations

import datetime as _dt

from sqlalchemy import JSON, Boolean, DateTime, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


def _utcnow() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


class CalculationRecord(Base):
    """每次核算请求与结果的持久化记录（含成功与失败）。"""

    __tablename__ = "calculation_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[_dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, index=True)

    # 来源接口：friction / pressure_drop / reynolds_grid / batch
    endpoint: Mapped[str] = mapped_column(String(32), index=True)
    # 批量内联组号（从 0 起）与批次标识；非批量为 None
    batch_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    batch_index: Mapped[int | None] = mapped_column(Integer, nullable=True)

    reynolds_number: Mapped[float | None] = mapped_column(Float, nullable=True, index=True)
    relative_roughness: Mapped[float | None] = mapped_column(Float, nullable=True, index=True)
    forced_regime: Mapped[str | None] = mapped_column(String(16), nullable=True)

    success: Mapped[bool] = mapped_column(Boolean, index=True)
    regime: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    result_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    friction_factor: Mapped[float | None] = mapped_column(Float, nullable=True)
    residual_abs: Mapped[float | None] = mapped_column(Float, nullable=True)
    iterations: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pressure_drop_pa: Mapped[float | None] = mapped_column(Float, nullable=True)

    # 失败原因（校验/未建模/不收敛）与完整请求快照
    error_code: Mapped[str | None] = mapped_column(String(48), nullable=True, index=True)
    error_message: Mapped[str | None] = mapped_column(String, nullable=True)
    error_field: Mapped[str | None] = mapped_column(String(64), nullable=True)
    request_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
