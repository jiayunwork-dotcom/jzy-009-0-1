# 圆管 Darcy 摩阻系数核算服务

纯服务端水力计算组件（FastAPI + SQLAlchemy）。上游提交雷诺数与相对粗糙度，
服务按区制返回 Darcy 摩阻系数，湍流区求 Colebrook 隐式方程至钉死容差，
并可选计算沿程压降。支持雷诺数网格、批量核算与历史查询持久化。

## 区制与公式

| 区制 | 雷诺数范围 | 处理方式 |
|---|---|---|
| 层流 laminar | `Re < 2300` | 闭式公式 `f = 64 / Re`，不套用隐式方程 |
| 过渡 transition | `2300 <= Re < 4000` | **未建模**，返回可区分的结果类型 `TRANSITION_NOT_MODELED`（HTTP 422），不用层流/湍流公式充数 |
| 湍流 turbulent | `Re >= 4000` | Colebrook 隐式方程求根，残差（以 10 为底）必须 `|R| <= 1e-8` |

湍流残差定义（`x = 1/sqrt(f)`，对数为常用对数 log10）：

```
R = 1/sqrt(f) + 2·log10( ε/D / 3.7 + 2.51 / (Re·sqrt(f)) )
```

求根采用 Haaland 显式初值 + 带二分保护的 Newton 法，有根区间每轮必定收缩；
达到最大迭代（100 次）仍未进入容差时返回 `ROOT_NOT_CONVERGED` 错误，
绝不交出残差很大的数。

沿程压降（Darcy–Weisbach），在已有合法 f 的前提下，四项几何/物性参数
**同时提供**时才计算；全缺则只返回摩阻：

```
Δp = f · (L / D) · 0.5 · ρ · V²
```

## 参数合法性（计算前拒绝，结构化错误）

- `reynolds` 必填，必须为有限数值且 `> 0`
- `relative_roughness` 必填，必须为有限数值且 `0 <= rr < 1`
- `pipe_length / diameter / velocity / density` 可选但必须全给；一旦出现就必须 `> 0`
- `force_regime` 与实际区制矛盾时返回 `REGIME_CONFLICT`（如层流 Re 强制湍流）
- 缺字段、非数值、NaN/Infinity、请求体损坏均返回 400 结构化错误，不崩溃

## 接口（前缀 `/api/v1`）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/health` | 存活探针（监控采集） |
| GET | `/health/ready` | 就绪探针（含数据库连通性） |
| GET | `/config` | 回显区制阈值、残差容差（1e-8，底 10）与预置算例 |
| GET | `/example` | 预置算例：商用钢管 `rr=4.5e-5, Re=1e5`，f ≈ 0.0182 |
| POST | `/friction` | 单次摩阻核算（可附带压降字段） |
| POST | `/pressure-drop` | 压降核算（必须提供全部 L/D/V/ρ） |
| POST | `/reynolds-grid` | 同一粗糙度下按雷诺数对数网格生成摩阻序列 |
| POST | `/batch` | 多工况批量；部分失败不影响其余，逐项给出 `case_index` 与错误字段 |
| POST | `/history/query` | 按区制/雷诺数区间/粗糙度等条件分页查询历史（含失败留痕） |

### 单次核算示例

```bash
curl -s -X POST localhost:8000/api/v1/friction \
  -H 'Content-Type: application/json' \
  -d '{"reynolds":100000,"relative_roughness":4.5e-5}'
# {"status":"ok","regime":"turbulent","friction_factor":0.01822998...,
#  "residual":-1.3e-11,"residual_tolerance":1e-8,"iterations":3,...}
```

附带压降：

```bash
curl -s -X POST localhost:8000/api/v1/friction -H 'Content-Type: application/json' -d '{
  "reynolds":100000,"relative_roughness":4.5e-5,
  "pipe_length":100,"diameter":0.5,"velocity":2,"density":1000}'
```

批量（过渡区与非法参数仅影响自己那一项）：

```bash
curl -s -X POST localhost:8000/api/v1/batch -H 'Content-Type: application/json' -d '{
  "cases":[
    {"reynolds":1000,"relative_roughness":0},
    {"reynolds":3000,"relative_roughness":0},
    {"reynolds":100000,"relative_roughness":4.5e-5}
  ]}'
```

错误体结构：

```json
{"error": true, "code": "TRANSITION_NOT_MODELED",
 "message": "雷诺数 3000 位于过渡区 [2300, 4000)，该区未建模……",
 "field": "reynolds", "details": {...}}
```

## 本地运行（SQLite，零外部依赖）

```bash
python3 -m venv --without-pip .venv
python3 -m ensurepip || curl -sS https://bootstrap.pypa.io/get-pip.py | .venv/bin/python
.venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app.main:app --reload
# 交互式文档：http://localhost:8000/docs
```

## Docker Compose 一键启动（PostgreSQL）

```bash
docker compose up --build
# API:  http://localhost:8000/api/v1/health
```

`DATABASE_URL` 默认指向 Compose 内的 Postgres；不设置时自动退回本地 SQLite
（`./data/friction.db`，自动建库建表）。

## 测试

```bash
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest
```

覆盖（90+ 用例）：

- 层流 `f = 64/Re`；Re 加倍则 f 减半
- 湍流残差代回定义闭合在 `1e-8` 以内（多组 Re×粗糙度组合）
- 仅加大粗糙度，同一 Re 下 f 严格升高
- 光滑管高 Re 下 f 仍随 Re 单调下降，不退化为常数
- 过渡区返回 `TRANSITION_NOT_MODELED` 可区分类型
- 压降：管长加倍→Δp 加倍，流速加倍→Δp 四倍，内径加倍→Δp 减半
- 非正/非数值/非有限/超范围参数、矛盾 force_regime 全部被拒
- 批量部分失败：标明第几组、哪个字段，其余成功
- 历史持久化（成功与失败均留痕）与条件查询
- 多线程并发互不串扰，批量 batch_id 不交错，无 HTTP 500

## 代码结构

```
app/
  core/
    config.py       # 钉死阈值/容差常量与 DB 配置
    regime.py       # 区制判定（层流/过渡/湍流）
    friction.py     # 层流闭式 + 湍流 Colebrook 求根（残差/收敛）
    pressure.py     # Darcy–Weisbach 压降
    validation.py   # 数值/范围/压降字段语义校验
    errors.py       # 结构化领域错误
  api/
    schemas.py      # Pydantic 请求/响应模型
    routes.py       # HTTP 路由与错误映射
  services/
    calculation.py  # 编排：校验→区制→求根→压降→持久化（单次/批量/网格/历史）
  db/
    session.py      # 引擎/会话（SQLite WAL 或 PostgreSQL）
    models.py       # 持久化模型
    repository.py   # 历史写入与条件查询
  main.py           # 应用工厂
tests/              # pytest 自动化测试
docker-compose.yml  # 服务 + PostgreSQL 一键启动
```
