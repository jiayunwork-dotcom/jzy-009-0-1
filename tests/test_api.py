"""HTTP / 服务编排 / 持久化 / 并发集成测试。"""
from __future__ import annotations

import concurrent.futures
import json

from app.db import repository
from app.db.session import SessionLocal
from app.services import calculation as service


# ---------- 健康与配置 ----------

def test_health(client):
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    r2 = client.get("/api/v1/health/ready")
    assert r2.status_code == 200
    assert r2.json()["database"] == "ok"


def test_config_endpoint(client):
    cfg = client.get("/api/v1/config").json()
    assert cfg["re_laminar_max"] == 2300.0
    assert cfg["re_turbulent_min"] == 4000.0
    assert cfg["transition_range"] == "[2300, 4000)"
    assert cfg["residual_tolerance"] == 1e-8
    assert cfg["residual_base"] == 10
    assert cfg["example"]["reynolds"] == 1e5


# ---------- 单次核算 ----------

def test_preset_example_endpoint(client):
    body = client.get("/api/v1/example").json()
    assert body["regime"] == "turbulent"
    assert 0.017 <= body["friction_factor"] <= 0.019
    assert abs(body["residual"]) <= 1e-8


def test_friction_laminar_http(client):
    r = client.post("/api/v1/friction", json={"reynolds": 1000, "relative_roughness": 0.0})
    assert r.status_code == 200
    body = r.json()
    assert body["regime"] == "laminar"
    assert body["friction_factor"] == 0.064
    assert body["residual"] is None
    assert "pressure_drop" not in body


def test_friction_turbulent_http_example(client):
    r = client.post(
        "/api/v1/friction",
        json={"reynolds": 100000, "relative_roughness": 4.5e-5},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["regime"] == "turbulent"
    assert 0.017 <= body["friction_factor"] <= 0.019
    assert abs(body["residual"]) <= 1e-8


def test_transition_returns_distinguishable_type(client):
    r = client.post("/api/v1/friction", json={"reynolds": 3000, "relative_roughness": 0.0})
    assert r.status_code == 422
    body = r.json()
    assert body["error"] is True
    assert body["code"] == "TRANSITION_NOT_MODELED"
    assert body["field"] == "reynolds"
    # 结果中绝不能出现伪造的摩阻系数
    assert "friction_factor" not in body


def test_missing_field_is_structured_error(client):
    r = client.post("/api/v1/friction", json={"reynolds": 1000})
    assert r.status_code == 400
    body = r.json()
    assert body["code"] == "INVALID_REQUEST"
    assert "relative_roughness" in body["message"]


def test_non_numeric_field_rejected(client):
    r = client.post(
        "/api/v1/friction",
        json={"reynolds": "fast", "relative_roughness": 0.0},
    )
    assert r.status_code == 400
    assert r.json()["code"] == "INVALID_REQUEST"


def test_non_positive_reynolds_rejected_http(client):
    r = client.post("/api/v1/friction", json={"reynolds": -5, "relative_roughness": 0.0})
    assert r.status_code == 400
    body = r.json()
    assert body["error"] is True
    assert body["field"] == "reynolds"


def test_non_finite_values_rejected(client):
    # JSON 裸 token NaN/Infinity 被 Python json 库原样发出；
    # 服务必须把它们当非有限值拒绝，而不是算出数。
    for token in ("NaN", "Infinity", "-Infinity"):
        r = client.post(
            "/api/v1/friction",
            content=f'{{"reynolds": {token}, "relative_roughness": 0.0}}',
            headers={"Content-Type": "application/json"},
        )
        assert r.status_code == 400, (token, r.status_code, r.text)
        assert r.json()["code"] in ("INVALID_REQUEST", "INVALID_INPUT")

    # 相对粗糙度为 Infinity 同样拒绝（gt/lt 约束拦不住 Infinity）
    r = client.post(
        "/api/v1/friction",
        content='{"reynolds": 100000, "relative_roughness": Infinity}',
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code == 400


def test_roughness_range_rejected_http(client):
    for rr in (-0.1, 1.0, 5.0):
        r = client.post("/api/v1/friction", json={"reynolds": 1e5, "relative_roughness": rr})
        assert r.status_code == 400
        assert r.json()["error"] is True


def test_force_regime_conflict_http(client):
    r = client.post(
        "/api/v1/friction",
        json={"reynolds": 1000, "relative_roughness": 0.0, "force_regime": "turbulent"},
    )
    assert r.status_code == 409
    assert r.json()["code"] == "REGIME_CONFLICT"


def test_no_crash_on_garbage_body(client):
    r = client.post(
        "/api/v1/friction",
        content="not json",
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code == 400
    assert r.json()["error"] is True


# ---------- 压降 ----------

def test_friction_with_pressure_drop(client):
    payload = {
        "reynolds": 100000,
        "relative_roughness": 4.5e-5,
        "pipe_length": 100.0,
        "diameter": 0.5,
        "velocity": 2.0,
        "density": 1000.0,
    }
    r = client.post("/api/v1/friction", json=payload)
    body = r.json()
    f = body["friction_factor"]
    expected = f * (100.0 / 0.5) * 0.5 * 1000.0 * 4.0
    assert body["pressure_drop"]["value_pa"] == expected


def test_pressure_drop_endpoint_scaling(client):
    base = {
        "reynolds": 1e5,
        "relative_roughness": 0.0,
        "pipe_length": 100.0,
        "diameter": 0.5,
        "velocity": 2.0,
        "density": 1000.0,
    }
    dp1 = client.post("/api/v1/pressure-drop", json=base).json()["value_pa"]

    doubled_L = {**base, "pipe_length": 200.0}
    assert client.post("/api/v1/pressure-drop", json=doubled_L).json()["value_pa"] == 2 * dp1

    doubled_V = {**base, "velocity": 4.0}
    assert client.post("/api/v1/pressure-drop", json=doubled_V).json()["value_pa"] == 4 * dp1


def test_pressure_drop_endpoint_requires_all_fields(client):
    r = client.post(
        "/api/v1/pressure-drop",
        json={"reynolds": 1e5, "relative_roughness": 0.0, "pipe_length": 100.0},
    )
    assert r.status_code == 400
    assert r.json()["code"] == "INVALID_INPUT"


def test_pressure_drop_non_positive_fields_rejected(client):
    base = {
        "reynolds": 1e5, "relative_roughness": 0.0,
        "pipe_length": 100.0, "diameter": 0.5, "velocity": 2.0, "density": 1000.0,
    }
    for field in ("pipe_length", "diameter", "velocity", "density"):
        bad = {**base, field: 0.0}
        r = client.post("/api/v1/friction", json=bad)
        assert r.status_code == 400, (field, r.text)
        assert r.json()["field"] == field


# ---------- 雷诺数网格 ----------

def test_reynolds_grid(client):
    r = client.post(
        "/api/v1/reynolds-grid",
        json={
            "reynolds_min": 1e4,
            "reynolds_max": 1e6,
            "relative_roughness": 0.0,
            "points": 5,
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert len(body["points"]) == 5
    # 对数等距，首末即端点
    assert body["points"][0]["reynolds"] == 1e4
    assert abs(body["points"][-1]["reynolds"] - 1e6) / 1e6 < 1e-12
    fs = [p["friction_factor"] for p in body["points"]]
    assert fs == sorted(fs, reverse=True)  # 光滑管：Re 升 f 降
    for p in body["points"]:
        assert abs(p["residual"]) <= 1e-8


def test_grid_skips_transition_by_default(client):
    r = client.post(
        "/api/v1/reynolds-grid",
        json={"reynolds_min": 2000, "reynolds_max": 5000, "relative_roughness": 0.0, "points": 7},
    )
    body = r.json()
    transition_points = [p for p in body["points"] if p.get("regime") == "transition"]
    assert transition_points and all(p.get("skipped") for p in transition_points)


def test_grid_include_transition_reports_unmodeled(client):
    r = client.post(
        "/api/v1/reynolds-grid",
        json={
            "reynolds_min": 2000, "reynolds_max": 5000,
            "relative_roughness": 0.0, "points": 7,
            "include_transition": True,
        },
    )
    body = r.json()
    bad = [p for p in body["points"] if p.get("regime") == "transition"]
    assert bad and all(p.get("code") == "TRANSITION_NOT_MODELED" for p in bad)


def test_grid_validates_range(client):
    r = client.post(
        "/api/v1/reynolds-grid",
        json={"reynolds_min": 1e6, "reynolds_max": 1e4, "relative_roughness": 0.0, "points": 5},
    )
    assert r.status_code == 400


# ---------- 批量：部分失败其余成功 ----------

def test_batch_partial_failure(client):
    payload = {
        "cases": [
            {"reynolds": 1000.0, "relative_roughness": 0.0},                        # 0 层流 ok
            {"reynolds": 3000.0, "relative_roughness": 0.0},                        # 1 过渡区 未建模
            {"reynolds": 1e5, "relative_roughness": 4.5e-5},                        # 2 湍流 ok
            {"reynolds": -10.0, "relative_roughness": 0.0},                         # 3 非法 Re
            {"reynolds": 1e5, "relative_roughness": 2.0},                           # 4 非法粗糙度
        ]
    }
    r = client.post("/api/v1/batch", json=payload)
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 5
    assert body["success_count"] == 2
    assert body["failure_count"] == 3
    results = body["results"]
    assert [x["case_index"] for x in results] == [0, 1, 2, 3, 4]

    assert results[0]["status"] == "ok" and results[0]["regime"] == "laminar"
    assert results[1]["code"] == "TRANSITION_NOT_MODELED" and results[1]["case_index"] == 1
    assert results[2]["status"] == "ok" and 0.017 < results[2]["friction_factor"] < 0.019
    assert results[3]["field"] == "reynolds" and results[3]["case_index"] == 3
    assert results[4]["field"] == "relative_roughness" and results[4]["case_index"] == 4
    # 同批同 batch_id
    assert all("batch_id" not in x or body["batch_id"] for x in results)


def test_batch_empty_rejected(client):
    r = client.post("/api/v1/batch", json={"cases": []})
    assert r.status_code == 400


# ---------- 历史持久化 ----------

def test_history_persisted_and_queryable(client):
    r = client.post(
        "/api/v1/friction",
        json={"reynolds": 50000, "relative_roughness": 1.2e-4},
    )
    record_id = r.json()["record_id"]
    assert record_id is not None

    session = SessionLocal()
    try:
        rows, total = repository.query_records(session, reynolds_min=50000, reynolds_max=50000)
        assert total >= 1
        row = next(x for x in rows if x.id == record_id)
        assert row.regime == "turbulent"
        assert abs(row.residual) <= 1e-8
        assert row.relative_roughness == 1.2e-4
        assert row.status == "ok"
    finally:
        session.close()

    # HTTP 查询接口
    q = client.post(
        "/api/v1/history/query",
        json={"regime": "turbulent", "reynolds_min": 50000, "reynolds_max": 50000},
    ).json()
    assert any(rec["id"] == record_id for rec in q["records"])


def test_failed_calculation_also_audited(client):
    client.post("/api/v1/friction", json={"reynolds": 3000, "relative_roughness": 0.0})
    q = client.post(
        "/api/v1/history/query",
        json={"status_nonexistent": 1},  # 未知字段被忽略
    )
    body = q.json()
    err_records = [
        r for r in body["records"]
        if r["status"] == "error" and r["error_code"] == "TRANSITION_NOT_MODELED"
    ]
    assert err_records


def test_history_pagination(client):
    body = client.post("/api/v1/history/query", json={"limit": 2, "offset": 0}).json()
    assert len(body["records"]) <= 2
    assert body["limit"] == 2


# ---------- 并发互不串扰 ----------

def test_concurrent_requests_isolated(client):
    scenarios = [
        (1000.0, 0.0),       # 层流 f=0.064
        (1e5, 4.5e-5),       # 湍流 ~0.018
        (1e6, 0.0),          # 光滑高 Re
        (2000.0, 1e-3),      # 层流 f=0.032
        (5e4, 5e-4),         # 湍流粗糙
    ]

    def call(scn):
        re, rr = scn
        r = client.post("/api/v1/friction", json={"reynolds": re, "relative_roughness": rr})
        return re, rr, r

    with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
        outcomes = list(pool.map(call, scenarios * 20))

    for re, rr, r in outcomes:
        assert r.status_code == 200, (re, rr, r.status_code, r.text)
        body = r.json()
        if re < 2300:
            assert body["regime"] == "laminar"
            assert abs(body["friction_factor"] - 64.0 / re) < 1e-12
        else:
            assert body["regime"] == "turbulent"
            assert abs(body["residual"]) <= 1e-8
        # 回显输入必须与该请求自身一致
        assert body["reynolds"] == re
        assert body["relative_roughness"] == rr


def test_concurrent_batch_records_not_interleaved(client):
    """并发批量：每批的 batch_id 只关联自己的组。"""
    def submit_batch(idx):
        cases = [
            {"reynolds": 1000.0 + idx, "relative_roughness": 0.0},
            {"reynolds": 1e5 + idx, "relative_roughness": 4.5e-5},
            {"reynolds": 3000.0, "relative_roughness": 0.0},  # 失败项
        ]
        r = client.post("/api/v1/batch", json={"cases": cases})
        return idx, r.json()

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        batches = list(pool.map(submit_batch, range(12)))

    session = SessionLocal()
    try:
        for idx, body in batches:
            rows, total = repository.query_records(session, batch_id=body["batch_id"])
            assert total == 3
            # 输入没有跨批串味
            res = {r.reynolds for r in rows}
            assert {1000.0 + idx, 1e5 + idx, 3000.0} == res
            statuses = sorted(r.status for r in rows)
            assert statuses == ["error", "ok", "ok"]
    finally:
        session.close()


def test_service_direct_compute_with_persistence_roundtrip():
    result = service.compute_case(
        reynolds=80000.0,
        relative_roughness=2.0e-4,
        pipe_length=10.0,
        diameter=0.2,
        velocity=1.5,
        density=900.0,
    )
    assert result["status"] == "ok"
    assert result["pressure_drop"]["value_pa"] > 0
    from app.db.models import CalculationRecord

    session = SessionLocal()
    try:
        row = session.get(CalculationRecord, result["record_id"])
        assert row.pressure_drop_pa == result["pressure_drop"]["value_pa"]
    finally:
        session.close()
