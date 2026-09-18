"""并发互不串扰测试：多线程同时打服务，响应与历史都不能错配。"""
from __future__ import annotations

import math
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

from app.turbulence import colebrook_residual
from app.config import RESIDUAL_TOLERANCE


def _one_call(client, idx: int) -> dict:
    # 每组参数唯一，响应里必须原样带回自己的 Re/eps，便于串扰检测。
    re = 4000.0 + idx * 137.0
    eps = (idx % 10) * 1e-4
    resp = client.post(
        "/api/friction", json={"reynolds_number": re, "relative_roughness": eps}
    )
    return {"idx": idx, "re": re, "eps": eps, "status": resp.status_code, "body": resp.json()}


def test_concurrent_single_requests_isolated(client):
    n = 24
    outcomes: list[dict] = [None] * n  # type: ignore[list-item]
    lock = threading.Lock()

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(_one_call, client, i): i for i in range(n)}
        for fut in as_completed(futures):
            i = futures[fut]
            with lock:
                outcomes[i] = fut.result()

    record_ids = set()
    for o in outcomes:
        assert o["status"] == 200, o
        body = o["body"]
        # 回显参数必须属于自己这组，不能拿到别人的结果
        assert body["reynolds_number"] == o["re"]
        assert body["relative_roughness"] == o["eps"]
        f = body["friction_factor"]
        assert abs(colebrook_residual(f, o["re"], o["eps"])) <= RESIDUAL_TOLERANCE
        assert body["record_id"] not in record_ids  # 每条历史记录 id 唯一
        record_ids.add(body["record_id"])

    # 历史里每条记录也能按自己的参数对上
    for o in outcomes:
        item = client.get(f"/api/history/{o['body']['record_id']}").json()["item"]
        assert item["reynolds_number"] == o["re"]
        assert item["relative_roughness"] == o["eps"]
        assert item["friction_factor"] == o["body"]["friction_factor"]


def test_concurrent_batches_do_not_mix(client):
    def batch_for(base: int):
        cases = [
            {"reynolds_number": 4000 + base + j, "relative_roughness": (j % 5) * 1e-4}
            for j in range(5)
        ]
        resp = client.post("/api/batch", json={"cases": cases})
        return base, resp.json()

    with ThreadPoolExecutor(max_workers=6) as pool:
        batches = list(pool.map(lambda b: batch_for(b), [100 * k for k in range(12)]))

    for base, body in batches:
        assert body["total"] == 5
        assert body["failed"] == 0
        # 用 batch_id 查历史，必须正好是这一批的 5 条，且参数对得上
        hist = client.get(f"/api/history?endpoint=batch&batch_id={body['batch_id']}").json()
        assert hist["total"] == 5
        actual = sorted(i["reynolds_number"] for i in hist["items"])
        expected = sorted(4000 + base + j for j in range(5))
        assert actual == expected
