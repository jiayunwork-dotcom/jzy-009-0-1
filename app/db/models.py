"""持久化模型：每次核算请求与其结果落一行。"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class CalculationRecord(Base):
    __tablename__ = "calculation_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, index=True
    )
    # 请求来源类型：single / batch（组内每行仍独立落库）/ grid
    source: Mapped[str] = mapped_column(String(16), default="single", index=True)
    batch_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)

    # 输入（参数校验失败时可能为空，原始值见 request_payload）
    reynolds: Mapped[float | None] = mapped_column(Float, nullable=True, index=True)
    relative_roughness: Mapped[float | None] = mapped_column(Float, nullable=True, index=True)
    force_regime: Mapped[str | None] = mapped_column(String(16), nullable=True)

    # 结果
    regime: Mapped[str] = mapped_column(String(16), index=True)  # laminar/transition/turbulent
    friction_factor: Mapped[float | None] = mapped_column(Float, nullable=True)
    residual: Mapped[float | None] = mapped_column(Float, nullable=True)
    iterations: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pressure_drop_pa: Mapped[float | None] = mapped_column(Float, nullable=True)

    # 失败的核算也留痕（如过渡区、不收敛），便于审计
    status: Mapped[str] = mapped_column(String(16), default="ok", index=True)  # ok / error
    error_code: Mapped[str | None] = mapped_column(String(48), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(512), nullable=True)

    # 原始请求 / 结果快照
    request_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    result_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
