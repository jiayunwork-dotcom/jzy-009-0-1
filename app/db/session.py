"""数据库引擎与会话。

默认 SQLite（本地单机即可跑）；DATABASE_URL 指向 PostgreSQL 时同样可用。
SQLite 下开启 WAL 并以 StaticPool 单连接承载，多线程下由服务层串行化写入；
PostgreSQL 下使用 QueuePool，事务天然隔离并发请求。
"""
from __future__ import annotations

import os
import threading

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import DEFAULT_SQLITE_URL, database_url


class Base(DeclarativeBase):
    pass


_url = database_url()
_is_sqlite = _url.startswith("sqlite")

_connect_args: dict[str, object] = {}
if _is_sqlite:
    # 确保数据目录存在
    db_path = _url.split("///", 1)[-1]
    if db_path and ":memory:" not in db_path:
        os.makedirs(os.path.dirname(os.path.abspath(db_path)) or ".", exist_ok=True)
    _connect_args = {"check_same_thread": False, "timeout": 30}

engine: Engine = create_engine(
    _url,
    connect_args=_connect_args,
    future=True,
)

if _is_sqlite:
    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_conn, _record):  # noqa: ANN001
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA busy_timeout=30000")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

# SQLite 写入串行化，避免 database is locked 与历史错乱；PG 下为空操作
_write_lock = threading.Lock()


def init_db() -> None:
    # 避免模型未注册导致的建表遗漏
    from app.db import models  # noqa: F401

    Base.metadata.create_all(bind=engine)


def get_session() -> Session:
    return SessionLocal()


def write_lock():
    return _write_lock if _is_sqlite else _NullCtx()


class _NullCtx:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False
