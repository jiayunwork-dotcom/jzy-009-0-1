#!/bin/sh
# 等待数据库就绪并建表，然后启动 HTTP 服务。
# 使用 SQLAlchemy 引擎连接，因此 PostgreSQL 与 SQLite 均适用。
set -e

python - <<'PY'
import sys
import time

from app.database import init_db

last_err = None
for attempt in range(60):
    try:
        init_db()
        print("database is ready; schema ensured.", flush=True)
        break
    except Exception as exc:  # 数据库容器可能尚未就绪
        last_err = exc
        print(f"waiting for database (attempt {attempt + 1}/60): {exc}", flush=True)
        time.sleep(1)
else:
    print(f"database not available, giving up: {last_err}", flush=True)
    sys.exit(1)
PY

exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
