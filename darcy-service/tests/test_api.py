"""HTTP 接口测试：单次/压降/网格/批量/历史/配置/健康。"""
from __future__ import annotations

import math

from app.config import RESIDUAL_TOLERANCE, LAMINAR_RE_MAX, TURBULENT_RE_MIN


# ---------- 单次摩阻 ----------

def test_laminar_endpoint(client):
    resp = client.post("/api/friction", json={"reynolds_number": 1000, "relative_roughness": 0})
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["regime"] == "laminar"
    assert body["friction_factor"] == 0.064
    assert "residual_abs" not in body


def test_turbulent_endpoint_residual_closed(client):
    resp = client.post("/api/friction", json={"reynolds_number": 100000, "relative_roughness": 0.00015})
    body = resp.json()
    assert resp.status_code == 200
    assert body["regime"] == "turbulent"
    assert abs(body["friction_factor"] - 0.01876) < 5e-4
    assert body["residual_abs"] <= RESIDUAL_TOLERANCE


def test_transition_returns_distinct_type_not_error(client):
    resp = client.post("/api/friction", json={"reynolds_number": 3000, "relative_roughness": 0.0})
    assert resp.status_code == 200  # 合法输入，不是 4xx
    body = resp.json()
    assert body["ok"] is True
    assert body["result_type"] == "transition_not_modeled"
    assert body["modeled"] is False
    assert "friction_factor" not in body


def test_preset_example(client):
    resp = client.get("/api/example")
    body = resp.json()
    f = body["result"]["friction_factor"]
    assert 0.017 < f < 0.019  # 0.018 量级


def test_invalid_re_returns_structured_error(client):
    resp = client.post("/api/friction", json={"reynolds_number": -5, "relative_roughness": 0})
    assert resp.status_code == 400
    body = resp.json()
    assert body["ok"] is False
    assert body["field"] == "reynolds_number"
    assert "正" in body["message"]


def test_missing_field_error(client):
    resp = client.post("/api/friction", json={"relative_roughness": 0})
    assert resp.status_code == 400
    assert resp.json()["field"] == "reynolds_number"


def test_non_numeric_and_non_finite_errors(client):
    # 字符串与布尔在 JSON 解析/校验阶段被结构化拒绝。
    for value in ("abc", True, False):
        resp = client.post(
            "/api/friction", json={"reynolds_number": value, "relative_roughness": 0}
        )
        assert resp.status_code == 400, value
        assert resp.json()["ok"] is False

    # NaN / Infinity 以原始 JSON token 发送（标准 JSON 本不允许）：
    # 服务端必须拒绝且不能崩溃。
    for token in ("NaN", "Infinity", "-Infinity"):
        resp = client.post(
            "/api/friction",
            content=(
                b'{"reynolds_number": ' + token.encode() + b', "relative_roughness": 0}'
            ),
            headers={"content-type": "application/json"},
        )
        assert resp.status_code == 400, token
        assert resp.json()["ok"] is False


def test_malformed_json_body(client):
    resp = client.post(
        "/api/friction",
        content=b"{not json",
        headers={"content-type": "application/json"},
    )
    assert resp.status_code == 400
    assert resp.json()["ok"] is False


def test_regime_conflict_error(client):
    resp = client.post(
        "/api/friction",
        json={"reynolds_number": 1000, "relative_roughness": 0, "regime": "turbulent"},
    )
    assert resp.status_code == 400
    assert resp.json()["error"] == "regime_conflict"


def test_friction_with_pressure_drop(client):
    resp = client.post(
        "/api/friction",
        json={
            "reynolds_number": 100000,
            "relative_roughness": 0.00015,
            "length": 100,
            "diameter": 0.5,
            "velocity": 2,
            "density": 1000,
        },
    )
    body = resp.json()
    assert "pressure_drop_pa" in body
    f = body["friction_factor"]
    expected = f * (100 / 0.5) * 0.5 * 1000 * 4
    assert body["pressure_drop_pa"] == expected


# ---------- 压降接口 ----------

def test_pressure_drop_endpoint(client):
    resp = client.post(
        "/api/pressure-drop",
        json={
            "reynolds_number": 100000,
            "relative_roughness": 0.00015,
            "length": 100,
            "diameter": 0.5,
            "velocity": 2,
            "density": 1000,
        },
    )
    assert resp.status_code == 200
    assert resp.json()["pressure_drop_pa"] > 0


def test_pressure_drop_endpoint_requires_fields(client):
    resp = client.post(
        "/api/pressure-drop", json={"reynolds_number": 100000, "relative_roughness": 0.00015}
    )
    assert resp.status_code == 400
    assert resp.json()["error"] == "incomplete_pressure_inputs"


def test_pressure_drop_endpoint_transition_passthrough(client):
    resp = client.post(
        "/api/pressure-drop",
        json={
            "reynolds_number": 3000,
            "relative_roughness": 0.0,
            "length": 100,
            "diameter": 0.5,
            "velocity": 2,
            "density": 1000,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["result_type"] == "transition_not_modeled"
    assert "pressure_drop_pa" not in body


def test_pressure_length_double_velocity_quadruple(client):
    payload = {
        "reynolds_number": 100000,
        "relative_roughness": 0.00015,
        "diameter": 0.5,
        "density": 1000,
    }

    def call(length, velocity):
        return client.post(
            "/api/pressure-drop", json={**payload, "length": length, "velocity": velocity}
        ).json()["pressure_drop_pa"]

    base = call(100, 2)
    assert call(200, 2) == 2 * base
    assert call(100, 4) == 4 * base


# ---------- 雷诺数网格 ----------

def test_reynolds_grid_log_spacing(client):
    resp = client.post(
        "/api/reynolds-grid",
        json={
            "relative_roughness": 0.00015,
            "reynolds_min": 4000,
            "reynolds_max": 1_000_000,
            "count": 20,
            "spacing": "log",
        },
    )
    assert resp.status_code == 200
    points = resp.json()["points"]
    assert len(points) == 20
    # 全湍流：每个点都闭合且 f 随 Re 单调不增（严格递减）。
    fs = [p["friction_factor"] for p in points]
    for a, b in zip(fs, fs[1:]):
        assert b < a
    for p in points:
        assert p["residual_abs"] <= RESIDUAL_TOLERANCE


def test_reynolds_grid_marks_transition_points(client):
    resp = client.post(
        "/api/reynolds-grid",
        json={
            "relative_roughness": 0.0,
            "reynolds_min": 1000,
            "reynolds_max": 10000,
            "count": 30,
            "spacing": "linear",
        },
    )
    points = resp.json()["points"]
    regimes = {p["regime"] for p in points}
    assert {"laminar", "transition", "turbulent"} <= regimes
    for p in points:
        if p["regime"] == "transition":
            assert p["result_type"] == "transition_not_modeled"
            assert p["modeled"] is False
            assert "friction_factor" not in p
        else:
            assert p["modeled"] is True


def test_reynolds_grid_bad_input(client):
    resp = client.post(
        "/api/reynolds-grid",
        json={"relative_roughness": 2.0, "reynolds_min": 4000, "reynolds_max": 10000},
    )
    assert resp.status_code == 400
    assert resp.json()["ok"] is False


# ---------- 批量：部分失败其余成功 ----------

def test_batch_partial_failure_points_to_index_and_field(client):
    resp = client.post(
        "/api/batch",
        json={
            "cases": [
                {"reynolds_number": 1000, "relative_roughness": 0.0},                 # 层流 OK
                {"reynolds_number": 3000, "relative_roughness": 0.0},                 # 过渡区
                {"reynolds_number": -100, "relative_roughness": 0.0},                 # 非法
                {"reynolds_number": 100000, "relative_roughness": 0.00015},           # 湍流 OK
                {"reynolds_number": 5000, "relative_roughness": "粗"},                # 非数值
                {"reynolds_number": 5000, "relative_roughness": 0.0, "length": -1,
                 "diameter": 0.5, "velocity": 2, "density": 1000},                    # 压降非法
            ]
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 6
    assert body["failed"] == 3  # 第 3、5、6 组
    assert body["succeeded"] == 2  # 仅层流 + 湍流；过渡区单列
    assert body["computed"] == 2
    assert body["transition_not_modeled"] == 1
    results = body["results"]

    assert results[0]["index"] == 1 and results[0]["regime"] == "laminar"
    assert results[1]["result_type"] == "transition_not_modeled"
    # 第 3 组（1 起）的 Re 非法，必须点名 index=3 和字段
    assert results[2]["index"] == 3
    assert results[2]["ok"] is False
    assert results[2]["field"] == "reynolds_number"
    assert "3" in results[2]["message"] or results[2]["index"] == 3
    assert results[3]["regime"] == "turbulent"
    assert results[4]["field"] == "relative_roughness"
    assert results[5]["field"] == "length"


def test_batch_wrong_shape_errors(client):
    assert client.post("/api/batch", json={"cases": []}).status_code == 400
    assert client.post("/api/batch", json={"cases": "x"}).status_code == 400
    assert client.post("/api/batch", json={}).status_code == 400


# ---------- 历史持久化 ----------

def test_history_persists_request_and_result(client):
    resp = client.post(
        "/api/friction",
        json={"reynolds_number": 12345, "relative_roughness": 0.0002},
    )
    record_id = resp.json()["record_id"]

    got = client.get(f"/api/history/{record_id}").json()["item"]
    assert got["reynolds_number"] == 12345
    assert got["relative_roughness"] == 0.0002
    assert got["success"] is True
    assert got["regime"] == "turbulent"
    assert got["friction_factor"] == resp.json()["friction_factor"]
    assert got["endpoint"] == "friction"
    assert got["request_snapshot"]["reynolds_number"] == 12345


def test_history_persists_failures(client):
    resp = client.post(
        "/api/friction", json={"reynolds_number": -1, "relative_roughness": 0}
    )
    rid = resp.json()["record_id"]
    item = client.get(f"/api/history/{rid}").json()["item"]
    assert item["success"] is False
    assert item["error_field"] == "reynolds_number"


def test_history_query_filters(client):
    client.post("/api/friction", json={"reynolds_number": 900, "relative_roughness": 0})
    client.post("/api/friction", json={"reynolds_number": 70000, "relative_roughness": 0.001})

    lam = client.get("/api/history?regime=laminar").json()
    assert all(i["regime"] == "laminar" for i in lam["items"])
    assert lam["total"] >= 1

    failed = client.get("/api/history?success=false").json()
    assert all(i["success"] is False for i in failed["items"])
    assert failed["total"] >= 1

    hi_re = client.get(
        "/api/history?min_reynolds_number=50000&max_reynolds_number=100000"
    ).json()
    assert all(50000 <= i["reynolds_number"] <= 100000 for i in hi_re["items"])
    assert hi_re["total"] >= 1


def test_batch_records_share_batch_id_and_queryable(client):
    body = client.post(
        "/api/batch",
        json={
            "cases": [
                {"reynolds_number": 1000, "relative_roughness": 0},
                {"reynolds_number": 50000, "relative_roughness": 0.001},
            ]
        },
    ).json()
    bid = body["batch_id"]
    hist = client.get(f"/api/history?endpoint=batch&batch_id={bid}").json()
    assert hist["total"] == 2
    # batch_index 从 0 起，且两组不串
    by_index = {i["batch_index"]: i for i in hist["items"]}
    assert by_index[0]["reynolds_number"] == 1000
    assert by_index[1]["reynolds_number"] == 50000


def test_history_not_found(client):
    assert client.get("/api/history/99999999").status_code == 404


# ---------- 配置 / 健康 ----------

def test_config_echoes_thresholds_and_tolerance(client):
    body = client.get("/api/config").json()
    th = body["thresholds"]
    assert th["laminar_re_max"] == LAMINAR_RE_MAX
    assert th["turbulent_re_min"] == TURBULENT_RE_MIN
    assert body["turbulent_root"]["residual_tolerance"] == RESIDUAL_TOLERANCE
    assert body["turbulent_root"]["log_base"] == 10
    assert body["regimes"]["transition"]["modeled"] is False


def test_health_endpoints(client):
    assert client.get("/health").json()["status"] == "ok"
    ready = client.get("/health/ready").json()
    assert ready["status"] == "ok"
    assert ready["database"] == "available"
