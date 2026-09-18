"""测试夹具：每个测试会话使用独立的临时 SQLite 数据库。"""
from __future__ import annotations

import os
import tempfile

import pytest

# 必须在导入 app.* 之前设置数据库地址
_tmp_dir = tempfile.mkdtemp(prefix="friction-test-")
_db_path = os.path.join(_tmp_dir, "test.db")
os.environ["DATABASE_URL"] = f"sqlite:///{_db_path}"

from fastapi.testclient import TestClient  # noqa: E402

from app.db.session import SessionLocal, engine, init_db  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _database():
    init_db()
    yield
    engine.dispose()


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def db_session():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
