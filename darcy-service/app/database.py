"""数据库引擎与会话管理。

- 默认 SQLite 文件库（零依赖可跑，测试也用它）；
- 环境变量 DATABASE_URL 指向 PostgreSQL（docker-compose）时自动切换；
- 每个请求开短会话，配合 SQLite WAL 或 Postgres 的行级并发，
  保证多请求并发时历史记录互不串扰。
"""
from __future__ import annotations

import os

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

_DEFAULT_SQLITE_PATH = os.environ.get(
    "DARCY_SQLITE_PATH", os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "darcy.db")
)
DATABASE_URL = os.environ.get("DATABASE_URL", f"sqlite:///{_DEFAULT_SQLITE_PATH}")


class Base(DeclarativeBase):
    pass


def _sqlite_file_path(url: str) -> str:
    """从 sqlite URL 取文件路径，用于推断要创建的目录。

    sqlite:////abs/x.db -> /abs/x.db；sqlite:///rel/x.db -> rel/x.db。
    """
    body = url.split("://", 1)[1]
    return body[1:] if body.startswith("/") else body


def _make_engine() -> Engine:
    if DATABASE_URL.startswith("sqlite"):
        # check_same_thread=False：FastAPI 线程池中多线程共享引擎；
        # 会话本身不跨线程共享。WAL 提升读写并发。
        from sqlalchemy.pool import StaticPool

        if ":memory:" in DATABASE_URL:
            return create_engine(
                DATABASE_URL,
                connect_args={"check_same_thread": False},
                poolclass=StaticPool,
                future=True,
            )
        os.makedirs(os.path.dirname(_sqlite_file_path(DATABASE_URL)), exist_ok=True)
        engine = create_engine(
            DATABASE_URL, connect_args={"check_same_thread": False}, future=True
        )
        with engine.begin() as conn:
            conn.exec_driver_sql("PRAGMA journal_mode=WAL;")
            conn.exec_driver_sql("PRAGMA synchronous=NORMAL;")
        return engine
    return create_engine(DATABASE_URL, pool_pre_ping=True, future=True)


engine: Engine = _make_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, class_=Session)


def init_db() -> None:
    """建表（幂等）。entrypoint 等数据库就绪后调用。"""
    from . import models  # noqa: F401  确保模型已注册到 Base.metadata

    Base.metadata.create_all(bind=engine)


def get_session() -> Session:
    return SessionLocal()
