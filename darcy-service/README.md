# 圆管 Darcy 摩阻系数核算服务

纯服务端水力计算组件（FastAPI + SQLAlchemy + PostgreSQL/SQLite）。上游把流动工况
交给它，按雷诺数区制核算 Darcy 摩阻系数；湍流区用 Colebrook-White 隐式方程求根，
把以十为底的残差压到钉死容差以内；需要时按 Darcy-Weisbach 给沿程压降。
每次请求与结果持久化，可按条件查历史。

不涉及管网调度、前端页面或账户体系。

## 核算规则

| 区制 | 雷诺数范围 | 处理 |
|---|---|---|
| 层流 `laminar` | `Re < 2300` | 闭式解 `f = 64 / Re`，与粗糙度无关，绝不套用湍流方程 |
| 过渡区 `transition` | `2300 <= Re < 4000` | **未建模**，返回可区分结果类型 `transition_not_modeled`，不用层/湍公式充数 |
| 湍流 `turbulent` | `Re >= 4000` | 解 Colebrook-White 隐式方程至残差容差 `1e-10` |

湍流残差（`log10`，以 10 为底）：

```
R(f) = 1/√f + 2·log10( ε/3.7 + 2.51/(Re·√f) )
```

求根：令 `x = 1/√f` 做 Newton 迭代（Haaland 显式初值），失败退化为有括号二分；
最终仍把 `f` 代回上面的 f 形式残差验收，超过容差即返回
`422 root_not_converged`，绝不交出残差很大的数。

压降（四个参数齐全才算，Darcy-Weisbach）：

```
Δp = f · (L / D) · ρ · v² / 2
```

与 f、L 成正比，与 v² 成正比，与 D 成反比。

## 快速开始（Docker Compose，含 PostgreSQL）

```bash
docker compose up --build
# 服务：http://localhost:8000  交互式文档：/docs
```

容器启动时会等数据库就绪并自动建表。健康检查：`GET /health`、`GET /health/ready`。

## 本地开发（无需 Docker，SQLite 零依赖）

```bash
pip install -r requirements.txt
python -m app.main          # 或 uvicorn app.main:app --reload
# 默认 SQLite 文件库位于 ./data/darcy.db
DATABASE_URL=postgresql+psycopg2://darcy:darcy@localhost:5432/darcy   # 也可切 Postgres
```

## 接口

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/friction` | 单次摩阻核算；带 `length/diameter/velocity/density` 时顺带压降 |
| POST | `/api/pressure-drop` | 压降接口（四个压降参数必须齐全） |
| POST | `/api/reynolds-grid` | 同一相对粗糙度下按雷诺数网格生成摩阻序列（`log`/`linear`） |
| POST | `/api/batch` | 一次提交多组工况；非法组点名第几组、哪个字段，其余照常 |
| GET | `/api/history` | 历史条件查询（接口/区制/成败/batch_id/Re 区间/分页） |
| GET | `/api/history/{id}` | 单条历史 |
| GET | `/api/config` | 回显区制阈值、残差容差、log 底数等钉死配置 |
| GET | `/api/example` | 预置算例：商用钢管量级、Re=1e5，f≈0.0188 |
| GET | `/health`、`/health/ready` | 存活/就绪（含数据库探测） |

### 示例

```bash
# 层流
curl -X POST localhost:8000/api/friction -H 'content-type: application/json' \
  -d '{"reynolds_number":1200,"relative_roughness":0}'
# -> {"regime":"laminar","friction_factor":0.05333,...}

# 湍流 + 压降
curl -X POST localhost:8000/api/friction -H 'content-type: application/json' -d '{
  "reynolds_number":100000,"relative_roughness":0.00015,
  "length":100,"diameter":0.5,"velocity":2,"density":1000}'

# 过渡区（HTTP 200，但结果类型标明未建模）
curl -X POST localhost:8000/api/friction -H 'content-type: application/json' \
  -d '{"reynolds_number":3000,"relative_roughness":0}'
# -> {"result_type":"transition_not_modeled","modeled":false,"regime":"transition",...}

# 批量
curl -X POST localhost:8000/api/batch -H 'content-type: application/json' -d '{
  "cases":[{"reynolds_number":1000,"relative_roughness":0},
           {"reynolds_number":-5,"relative_roughness":0}]}'
# 第 2 组失败并指出 field=reynolds_number，第 1 组照常返回
```

可选字段 `"regime": "auto"|"laminar"|"turbulent"` 用于强制区制；
例如层流雷诺数却要求湍流（或反过来）会返回 `400 regime_conflict`，不拿错误公式充数。

## 错误约定

- `400`：校验类（缺字段/非数值/非有限值/Re≤0/ε<0 或 ε≥1/压降参数非正/区制矛盾）；
- `422 root_not_converged`：湍流求根不收敛；
- `200 + result_type=transition_not_modeled`：过渡区合法输入但未建模（可区分结果类型，不是错误）。

所有错误体都是结构化可读 JSON：`{"ok":false,"error":...,"message":...,"field":...}`，
并同样落历史（`success=false` 带错误码与字段），服务不抛 500。

## 模块划分

```
app/
  config.py       区制阈值、残差容差等钉死配置（/api/config 原样回显）
  errors.py       结构化领域错误（校验 / 过渡区未建模 / 求根不收敛）
  validation.py   输入校验（有限数值、物理范围、压降参数、区制矛盾）
  regimes.py      区制判定
  turbulence.py   Colebrook-White 求根（Newton + 二分兜底、残差验收）
  pressure.py     Darcy-Weisbach 压降
  grid.py         雷诺数网格序列
  service.py      一次核算的领域编排（纯逻辑，不碰 HTTP/DB）
  database.py     引擎/会话（SQLite 或 Postgres）
  models.py       历史记录 ORM
  repository.py   落库与条件查询
  schemas.py      HTTP 入参模式
  api/            friction / batch / grid / history / config / health 路由
  main.py         应用装配与异常处理
tests/            领域规则 + HTTP + 并发 共 60+ 用例
```

区制判定、湍流求根、压降、校验、持久化分属不同文件；每请求独立 DB 会话，
批量/网格各自一次事务，并发下历史不错乱。

## 测试

```bash
pip install -r requirements.txt
pytest -q
```

覆盖：层流 `f=64/Re`、Re 加倍 f 减半、湍流残差代回闭合（容差内）、
粗糙度增大 f 升高、光滑管高 Re 下 f 继续下降、过渡区标明未建模、
管长加倍压降加倍/流速加倍压降四倍、各类非法参数拒绝、批量部分失败其余成功、
历史持久化与条件查询、多线程并发互不串扰。
