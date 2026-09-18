"""测试环境配置：在导入应用前把数据库指到临时 SQLite 文件。

必须在任何 app.* 模块导入之前设置 DATABASE_URL，因为 app.database
在导入时就读取环境变量建引擎。
"""
from __future__ import annotations

import os
import sys
import tempfile

import pytest

_TMPDIR = tempfile.mkdtemp(prefix="darcy-test-")
_DB_PATH = os.path.join(_TMPDIR, "test.db")
os.environ["DATABASE_URL"] = f"sqlite:///{_DB_PATH}"
os.environ.setdefault("DARCY_SQLITE_PATH", _DB_PATH)

# 保证从 tests/ 目录直接 pytest 时也能找到项目根。
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from fastapi.testclient import TestClient  # noqa: E402

from app.database import init_db  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(scope="session")
def client():
    init_db()
    with TestClient(app) as c:
        yield c
