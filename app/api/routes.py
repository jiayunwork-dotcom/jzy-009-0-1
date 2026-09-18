"""HTTP 路由：摩阻核算 / 压降 / 雷诺数序列 / 批量 / 历史 / 配置 / 健康。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError as PydanticValidationError

from app.api.schemas import (
    BatchRequest,
    ConfigResponse,
    FrictionRequest,
    HistoryQuery,
    ReynoldsGridRequest,
)
from app.core import config
from app.core.errors import (
    DomainError,
    NonConvergenceError,
    RegimeConflictError,
    TransitionNotModeledError,
    ValidationError as DomainValidationError,
)
from app.services import calculation as service

router = APIRouter(prefix="/api/v1")


def _error_response(exc: DomainError, status_code: int) -> JSONResponse:
    return JSONResponse(status_code=status_code, content=exc.to_dict())


@router.get("/health")
def health() -> dict[str, Any]:
    """基本运行状态，供监控采集。"""
    return {
        "status": "ok",
        "service": config.SERVICE_NAME,
        "version": config.SERVICE_VERSION,
    }


@router.get("/health/ready")
def readiness(request: Request) -> JSONResponse:
    """就绪探针：验证数据库可连通。"""
    from sqlalchemy import text

    try:
        session = request.app.state.session_factory()
        try:
            session.execute(text("SELECT 1"))
        finally:
            session.close()
        return JSONResponse(
            status_code=200,
            content={"status": "ready", "database": "ok"},
        )
    except Exception as exc:  # 监控视角：任何依赖故障都要可见
        return JSONResponse(
            status_code=503,
            content={"status": "unavailable", "database": str(exc)[:200]},
        )


@router.get("/config")
def get_config() -> ConfigResponse:
    """回显区制阈值与残差容差配置。"""
    return ConfigResponse(
        service=config.SERVICE_NAME,
        version=config.SERVICE_VERSION,
        re_laminar_max=config.RE_LAMINAR_MAX,
        re_turbulent_min=config.RE_TURBULENT_MIN,
        transition_range=f"[{config.RE_LAMINAR_MAX:g}, {config.RE_TURBULENT_MIN:g})",
        residual_tolerance=config.TOLERANCE,
        residual_base=10,
        max_iterations=config.MAX_ITERATIONS,
        example={
            "description": "商用钢管量级相对粗糙度，雷诺数十万，摩阻系数约 0.018 量级",
            "reynolds": config.EXAMPLE_REYNOLDS,
            "relative_roughness": config.EXAMPLE_RELATIVE_ROUGHNESS,
            "expected_friction_order": config.EXAMPLE_EXPECTED_FRICTION,
        },
    )


@router.get("/example")
def preset_example() -> JSONResponse:
    """预置算例：商用钢管量级相对粗糙度 + 雷诺数十万，f 应在 0.018 量级。"""
    result = service.compute_case(
        reynolds=config.EXAMPLE_REYNOLDS,
        relative_roughness=config.EXAMPLE_RELATIVE_ROUGHNESS,
    )
    result["note"] = "预置算例：商用钢管量级，f 预期 0.018 量级"
    return JSONResponse(status_code=200, content=result)


@router.post("/friction", status_code=200)
def friction_endpoint(payload: FrictionRequest) -> JSONResponse:
    """单次摩阻核算（含可选压降）。"""
    try:
        result = service.compute_case(**payload.model_dump())
        return JSONResponse(status_code=200, content=result)
    except TransitionNotModeledError as exc:
        # 可区分的结果类型：HTTP 422 + 专用 code
        return _error_response(exc, 422)
    except RegimeConflictError as exc:
        return _error_response(exc, 409)
    except NonConvergenceError as exc:
        return _error_response(exc, 422)
    except DomainValidationError as exc:
        return _error_response(exc, 400)


@router.post("/pressure-drop")
def pressure_drop_endpoint(payload: FrictionRequest) -> JSONResponse:
    """压降接口：要求显式给出全部四个几何/物性字段，否则拒绝。"""
    data = payload.model_dump()
    missing = [
        k for k in ("pipe_length", "diameter", "velocity", "density")
        if data.get(k) is None
    ]
    if missing:
        return _error_response(
            DomainValidationError(
                "压降接口必须同时提供管长 pipe_length、管内径 diameter、"
                f"平均流速 velocity、流体密度 density；缺少：{'、'.join(missing)}",
                field=",".join(missing),
            ),
            400,
        )
    try:
        result = service.compute_case(**data)
    except TransitionNotModeledError as exc:
        return _error_response(exc, 422)
    except RegimeConflictError as exc:
        return _error_response(exc, 409)
    except NonConvergenceError as exc:
        return _error_response(exc, 422)
    except DomainValidationError as exc:
        return _error_response(exc, 400)
    return JSONResponse(
        status_code=200,
        content={
            "regime": result["regime"],
            "reynolds": result["reynolds"],
            "relative_roughness": result["relative_roughness"],
            "friction_factor": result["friction_factor"],
            **result.get("pressure_drop", {}),
            "record_id": result.get("record_id"),
        },
    )


@router.post("/reynolds-grid")
def reynolds_grid_endpoint(payload: ReynoldsGridRequest) -> JSONResponse:
    """按雷诺数网格生成同一相对粗糙度下的摩阻系数序列。"""
    try:
        result = service.compute_reynolds_grid(**payload.model_dump())
    except DomainValidationError as exc:
        return _error_response(exc, 400)
    except DomainError as exc:
        return _error_response(exc, 422)
    return JSONResponse(status_code=200, content=result)


@router.post("/batch")
def batch_endpoint(payload: BatchRequest) -> JSONResponse:
    """批量核算：部分组非法时其余组照常返回，并标明第几组、哪个参数。"""
    # 宽松解析为 dict（未提供的字段不补默认值，交给领域层按字段报错）；
    # 非对象元素原样透传，由服务层生成该组的单项错误。
    cases = [
        c.model_dump(exclude_unset=True) if hasattr(c, "model_dump") else c
        for c in payload.cases
    ]
    result = service.compute_batch(cases)
    # 批量为部分成功语义：HTTP 始终 200，逐项给出 ok / error
    return JSONResponse(status_code=200, content=result)


@router.post("/history/query")
def history_query_endpoint(payload: HistoryQuery) -> JSONResponse:
    """按条件查询持久化的核算历史。"""
    return JSONResponse(status_code=200, content=service.query_history(payload.model_dump(exclude_unset=True, exclude_none=True)))


def register_exception_handlers(app: Any) -> None:
    """把请求体结构问题统一转成带说明的结构化错误，不抛 500。"""

    @app.exception_handler(PydanticValidationError)
    async def _on_pydantic_error(_request: Request, exc: PydanticValidationError) -> JSONResponse:
        errors = []
        for err in exc.errors():
            loc = ".".join(str(p) for p in err.get("loc", []) if p != "body")
            errors.append(
                {
                    "field": loc or None,
                    "message": err.get("msg", "参数非法"),
                    "type": err.get("type"),
                }
            )
        return JSONResponse(
            status_code=400,
            content={
                "error": True,
                "code": "INVALID_REQUEST",
                "message": "请求体校验失败：" + "；".join(
                    f"{e['field'] or '<root>'}: {e['message']}" for e in errors
                ),
                "details": {"errors": errors},
            },
        )

    @app.exception_handler(Exception)
    async def _on_unexpected(_request: Request, exc: Exception) -> JSONResponse:
        # 兜底：任何意外都返回结构化错误而不是裸堆栈
        return JSONResponse(
            status_code=500,
            content={
                "error": True,
                "code": "INTERNAL_ERROR",
                "message": f"服务内部错误：{type(exc).__name__}",
            },
        )
