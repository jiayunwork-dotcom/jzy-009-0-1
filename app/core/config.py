"""应用配置。

区制阈值与残差容差是对外承诺的“钉死”常量，
通过 /api/v1/config 接口原样回显。
"""
from __future__ import annotations

import os

# ---- 区制阈值（雷诺数）----
RE_LAMINAR_MAX = 2300.0       # Re < 2300 为层流
RE_TURBULENT_MIN = 4000.0     # Re >= 4000 为湍流
# 2300 <= Re < 4000 为过渡区（未建模）

# ---- 湍流 Colebrook 残差容差（以 10 为底）----
TOLERANCE = 1e-8
MAX_ITERATIONS = 100

# ---- 接口限额 ----
BATCH_MAX_CASES = 500
GRID_MAX_POINTS = 2000

# ---- 预置算例 ----
EXAMPLE_REYNOLDS = 1.0e5
EXAMPLE_RELATIVE_ROUGHNESS = 4.5e-5   # 商用钢管量级 (45 µm / 1 m)
EXAMPLE_EXPECTED_FRICTION = 0.018     # 预期 0.018 量级

# ---- 数据库 ----
# 默认 SQLite，本地文件；Docker Compose 中通过环境变量切到 PostgreSQL。
DEFAULT_SQLITE_URL = "sqlite:///./data/friction.db"


def database_url() -> str:
    return os.environ.get("DATABASE_URL", DEFAULT_SQLITE_URL)


SERVICE_NAME = "darcy-friction-service"
SERVICE_VERSION = "1.0.0"
