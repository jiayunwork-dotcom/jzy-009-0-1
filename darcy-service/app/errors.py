"""领域层抛出的结构化错误。

不直接依赖 FastAPI，保证核心核算逻辑可脱离 HTTP 单独使用/测试。
"""
from __future__ import annotations

from typing import Any


class DomainError(ValueError):
    """所有可预期的领域错误基类，携带可读说明与问题参数名。"""

    def __init__(self, message: str, field: str | None = None, code: str = "invalid_input"):
        super().__init__(message)
        self.message = message
        self.field = field
        self.code = code

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"error": self.code, "message": self.message}
        if self.field is not None:
            payload["field"] = self.field
        return payload


class ValidationError(DomainError):
    """输入缺字段、类型不对、非有限值等校验错误。"""

    def __init__(self, message: str, field: str | None = None, code: str = "validation_error"):
        super().__init__(message, field=field, code=code)


class RegimeNotModeledError(DomainError):
    """过渡区（2300 <= Re < 4000）未建模，不得用层流/湍流公式充数。"""

    def __init__(self, reynolds_number: float):
        super().__init__(
            f"reynolds_number={reynolds_number:g} 落在过渡区 [2300, 4000)，"
            "该区制未建模，不提供摩阻系数。",
            field="reynolds_number",
            code="transition_not_modeled",
        )
        self.reynolds_number = reynolds_number


class RootConvergenceError(DomainError):
    """湍流隐式方程求根不收敛：宁可报错，也不交一个残差很大的数。"""

    def __init__(self, message: str, residual: float | None = None):
        super().__init__(message, field="friction_factor", code="root_not_converged")
        self.residual = residual

    def to_dict(self) -> dict[str, Any]:
        payload = super().to_dict()
        if self.residual is not None:
            payload["residual_abs"] = self.residual
        return payload
