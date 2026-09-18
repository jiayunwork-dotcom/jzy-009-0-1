"""领域错误定义。

所有可预期的业务错误都携带机器可读 code 与可读中文说明，
由 Web 层统一转换为结构化错误响应；不得向调用方抛出裸异常。
"""
from __future__ import annotations

from typing import Any


class DomainError(Exception):
    """领域错误基类。"""

    code = "DOMAIN_ERROR"

    def __init__(
        self,
        message: str,
        *,
        field: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.field = field
        self.details = details or {}

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "error": True,
            "code": self.code,
            "message": self.message,
        }
        if self.field is not None:
            payload["field"] = self.field
        if self.details:
            payload["details"] = self.details
        return payload


class ValidationError(DomainError):
    """输入参数非法（缺字段、非数值、非有限、取值范围错误等）。"""

    code = "INVALID_INPUT"


class RegimeConflictError(DomainError):
    """强制指定的区制与实际雷诺数所在区制矛盾。"""

    code = "REGIME_CONFLICT"


class TransitionNotModeledError(DomainError):
    """过渡区（2300 <= Re < 4000）未建模。

    单区核算接口中把它转成 HTTP 422；批量/网格内作为单项错误，
    不影响其他组结果。
    """

    code = "TRANSITION_NOT_MODELED"


class NonConvergenceError(DomainError):
    """湍流隐式方程求根不收敛。"""

    code = "ROOT_NOT_CONVERGED"
