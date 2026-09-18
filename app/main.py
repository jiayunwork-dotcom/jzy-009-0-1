"""FastAPI 应用入口：uvicorn app.main:app"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.api.routes import router
from app.core.config import SERVICE_NAME, SERVICE_VERSION
from app.db.session import SessionLocal, init_db


def create_app() -> FastAPI:
    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        init_db()
        yield

    app = FastAPI(
        title="圆管 Darcy 摩阻系数核算服务",
        version=SERVICE_VERSION,
        description=(
            "纯服务端水力计算组件：按雷诺数与相对粗糙度进行区制判定，"
            "层流走闭式公式，湍流求 Colebrook 隐式方程至钉死容差，"
            "并可计算沿程压降。支持雷诺数网格、批量核算与历史查询。"
        ),
        lifespan=lifespan,
    )
    app.include_router(router)
    app.state.session_factory = SessionLocal

    @app.exception_handler(RequestValidationError)
    async def _on_request_validation(_request: Request, exc: RequestValidationError) -> JSONResponse:
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
                "message": "请求体校验失败："
                + "；".join(
                    f"{e['field'] or '<root>'}: {e['message']}" for e in errors
                ),
                "details": {"errors": errors},
            },
        )

    @app.exception_handler(Exception)
    async def _on_unexpected(_request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(
            status_code=500,
            content={
                "error": True,
                "code": "INTERNAL_ERROR",
                "message": f"服务内部错误：{type(exc).__name__}",
            },
        )

    return app


app = create_app()
