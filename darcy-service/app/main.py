"""FastAPI 应用入口：异常处理、路由装配、启动建表。"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from .api import batch, config as config_api
from .api import friction, grid, health, history
from .database import init_db
from .errors import DomainError


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="圆管 Darcy 摩阻系数核算服务",
    version="1.0.0",
    description=(
        "纯服务端水力计算组件：按雷诺数区制给出 Darcy 摩阻系数，"
        "湍流区以 Colebrook-White 隐式方程求根至钉死容差，"
        "并可按 Darcy-Weisbach 给出沿程压降。"
    ),
    lifespan=lifespan,
)

app.include_router(health.router)
app.include_router(config_api.router)
app.include_router(friction.router)
app.include_router(grid.router)
app.include_router(batch.router)
app.include_router(history.router)


@app.exception_handler(DomainError)
async def domain_error_handler(_: Request, exc: DomainError) -> JSONResponse:
    """领域错误统一结构化输出，不抛出 500。"""
    status = 422 if exc.code == "root_not_converged" else 400
    return JSONResponse(status_code=status, content={"ok": False, **exc.to_dict()})


@app.exception_handler(RequestValidationError)
async def request_validation_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    """请求体本身不是合法 JSON / 顶层结构错误：转成可读结构化错误。"""
    details = []
    for err in exc.errors():
        loc = ".".join(str(p) for p in err.get("loc", []) if p != "body") or "body"
        details.append({"field": loc, "message": err.get("msg", "请求格式不合法")})
    return JSONResponse(
        status_code=400,
        content={
            "ok": False,
            "error": "malformed_request",
            "message": "请求体格式不合法。",
            "details": details,
        },
    )


@app.get("/")
def root() -> dict:
    return {
        "service": "darcy-friction-service",
        "docs": "/docs",
        "endpoints": [
            "POST /api/friction",
            "POST /api/pressure-drop",
            "POST /api/reynolds-grid",
            "POST /api/batch",
            "GET  /api/history",
            "GET  /api/history/{id}",
            "GET  /api/config",
            "GET  /api/example",
            "GET  /health",
            "GET  /health/ready",
        ],
    }


if __name__ == "__main__":  # 本地直跑：python -m app.main
    import uvicorn

    init_db()
    uvicorn.run(app, host="0.0.0.0", port=8000)
