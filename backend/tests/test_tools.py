"""工具注册表与内置工具测试（A4 / FR-04）。"""
from __future__ import annotations

import json
import threading
import time

import pytest

from app.services import executor, planner, tools
from app.storage import db


def _wait_until(pred, timeout=10.0, interval=0.02) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if pred():
            return True
        time.sleep(interval)
    return False


# ---------------------------------------------------------------- 注册表 API

def test_list_builtin_tools(client):
    resp = client.get("/api/tools").json()
    keys = {t["key"] for t in resp}
    assert {"web_search", "sql_query", "http_request", "summarize", "approve"} <= keys
    approve = next(t for t in resp if t["key"] == "approve")
    assert approve["sensitive"] is True
    assert approve["is_builtin"] is True
    http = next(t for t in resp if t["key"] == "http_request")
    assert http["sensitive"] is True


def test_create_custom_tool(client):
    r = client.post("/api/tools", json={
        "key": "my_tool", "name": "自定义工具", "description": "测试",
        "params": {"x": {"type": "string", "required": True}}, "sensitive": False,
    })
    assert r.status_code == 201
    body = r.json()
    assert body["key"] == "my_tool"
    assert body["is_builtin"] is False
    assert body["params"]["x"]["required"] is True


def test_create_duplicate_tool_409(client):
    r = client.post("/api/tools", json={"key": "web_search", "name": "重复", "description": ""})
    assert r.status_code == 409


def test_update_custom_tool(client):
    client.post("/api/tools", json={
        "key": "my_tool", "name": "旧名", "description": "旧描述",
        "params": {"x": {"type": "string", "required": True}}, "sensitive": False,
    })
    r = client.put("/api/tools/my_tool", json={
        "key": "my_tool", "name": "新名", "description": "新描述",
        "params": {"x": {"type": "integer", "required": False}}, "sensitive": True,
    })
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "新名"
    assert body["params"]["x"]["type"] == "integer"
    assert body["sensitive"] is True


def test_update_builtin_tool_409(client):
    r = client.put("/api/tools/web_search", json={"key": "web_search", "name": "改名", "description": ""})
    assert r.status_code == 409


def test_delete_custom_tool(client):
    client.post("/api/tools", json={"key": "temp_tool", "name": "临时", "description": ""})
    r = client.delete("/api/tools/temp_tool")
    assert r.status_code == 200
    keys = {t["key"] for t in client.get("/api/tools").json()}
    assert "temp_tool" not in keys
    assert client.delete("/api/tools/temp_tool").status_code == 404


def test_delete_builtin_tool_409(client):
    assert client.delete("/api/tools/web_search").status_code == 409


# ---------------------------------------------------------------- 参数校验

def test_execute_tool_validates_params():
    with pytest.raises(ValueError, match="缺少必填参数"):
        tools.execute_tool("web_search", {})
    with pytest.raises(ValueError, match="未知参数"):
        tools.execute_tool("web_search", {"query": "q", "extra": 1})
    with pytest.raises(ValueError, match="类型应为 string"):
        tools.execute_tool("web_search", {"query": 123})


def test_web_search_demo():
    out = tools.execute_tool("web_search", {"query": "AI 应用开发趋势"})
    assert out["query"] == "AI 应用开发趋势"
    assert isinstance(out["results"], list) and out["results"]


def test_summarize_demo():
    out = tools.execute_tool("summarize", {"text": "今天完成了并行开发计划。"})
    assert out["summary"].startswith("今天完成了")
    assert out["chars"] == len("今天完成了并行开发计划。")


def test_execute_unknown_tool():
    with pytest.raises(ValueError, match="不存在"):
        tools.execute_tool("ghost_tool", {})


# ---------------------------------------------------------------- sql_query 真实只读样例库

def test_sql_query_returns_rows():
    out = tools.execute_tool("sql_query", {"sql": "SELECT * FROM orders LIMIT 5"})
    assert out["columns"] == ["id", "customer", "amount", "status", "date"]
    assert len(out["rows"]) == 5
    assert out["rows"][0]["customer"]


def test_sql_query_aggregate():
    out = tools.execute_tool("sql_query", {
        "sql": "SELECT status, COUNT(*) AS n, SUM(amount) AS total FROM orders GROUP BY status",
    })
    rows = {r["status"]: r for r in out["rows"]}
    assert rows["paid"]["total"] > 0
    assert rows["paid"]["n"] >= 3


def test_sql_query_rejects_non_select():
    for sql in (
        "DELETE FROM orders",
        "INSERT INTO orders VALUES(1,1,1,'x','2026')",
        "UPDATE orders SET status='paid'",
        "DROP TABLE orders",
        "PRAGMA table_info(orders)",
    ):
        with pytest.raises(ValueError):
            tools.execute_tool("sql_query", {"sql": sql})


def test_sql_query_rejects_multi_statement():
    with pytest.raises(ValueError, match="单条"):
        tools.execute_tool("sql_query", {"sql": "SELECT 1; SELECT 2"})


def test_sql_query_rejects_comments():
    with pytest.raises(ValueError, match="注释"):
        tools.execute_tool("sql_query", {"sql": "SELECT 1 -- 注释"})


def test_sql_query_enforces_row_cap():
    out = tools.execute_tool("sql_query", {"sql": "SELECT * FROM orders"})
    assert len(out["rows"]) <= 100
    assert out["row_count"] == 6  # 样例库 6 行全部返回
    assert out["truncated"] is False


def test_sql_query_timeout_guard():
    with pytest.raises(ValueError, match="超时"):
        tools.execute_tool("sql_query", {
            "sql": "WITH RECURSIVE cnt(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM cnt WHERE x < 1000000) "
                   "SELECT COUNT(*) FROM cnt",
        })


# ---------------------------------------------------------------- http_request 白名单

def test_http_request_rejects_non_whitelisted():
    cases = [
        ("https://evil.example.net/path", "白名单"),
        ("http://127.0.0.1/x", "白名单"),
        ("ftp://example.com/x", "http"),
        ("https://example.com:8443/x", "端口"),
    ]
    for url, msg in cases:
        with pytest.raises(ValueError, match=msg):
            tools.execute_tool("http_request", {"url": url})


def test_http_request_whitelisted_get(monkeypatch):
    calls: dict[str, str] = {}

    class FakeResp:
        status = 200

        def __init__(self):
            self.headers = {"Content-Type": "application/json"}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, n=-1):
            return json.dumps({"ok": True, "from": "fake"}).encode()

    def fake_urlopen(req, timeout=5):
        calls["url"] = req.full_url
        return FakeResp()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    out = tools.execute_tool("http_request", {"url": "https://example.com/api/demo"})
    assert out["status"] == 200
    assert out["body"]["ok"] is True
    assert calls["url"] == "https://example.com/api/demo"


def test_http_request_demo_fallback_on_network_error(monkeypatch):
    def boom(req, timeout=5):
        raise ConnectionError("网络不可用")

    monkeypatch.setattr("urllib.request.urlopen", boom)
    out = tools.execute_tool("http_request", {"url": "https://example.com/api/demo"})
    assert out["body"]["demo"] is True


# ---------------------------------------------------------------- 自定义工具注册与调用

def test_custom_tool_execute_demo(client):
    client.post("/api/tools", json={
        "key": "stock_check", "name": "库存查询", "description": "查询商品库存（演示）",
        "params": {"sku": {"type": "string", "required": True}, "limit": {"type": "integer", "required": False}},
        "sensitive": False,
    })
    out = tools.execute_tool("stock_check", {"sku": "A-100", "limit": 10})
    assert out["demo"] is True
    assert out["args"] == {"sku": "A-100", "limit": 10}
    with pytest.raises(ValueError, match="缺少必填参数"):
        tools.execute_tool("stock_check", {})


def test_custom_tool_used_in_run(client):
    """自定义工具注册后可在任务流程中执行（演示参数由执行器按参数定义生成）。"""
    client.post("/api/tools", json={
        "key": "stock_check", "name": "库存查询", "description": "演示",
        "params": {"sku": {"type": "string", "required": True}}, "sensitive": False,
    })
    rid = db.create_run("自定义工具演示", "查询 A-100 库存", db.now_iso())
    plan = {"source": "rule", "tokens_in": 0, "tokens_out": 0, "steps": planner.validate_plan([
        {"key": "check", "name": "库存查询", "role": "执行者", "kind": "tool", "tool": "stock_check",
         "prompt": "查询 A-100 库存", "depends_on": []},
        {"key": "report", "name": "汇总", "role": "报告", "kind": "report", "tool": None,
         "prompt": "汇总结果", "depends_on": ["check"]},
    ])}
    planner.save_plan(rid, plan)
    db.update_run(rid, status="running")
    executor._execute_run(rid)
    assert _wait_until(lambda: db.get_run(rid)["status"] in ("succeeded", "failed"), 10)
    assert db.get_run(rid)["status"] == "succeeded"
    step = db.get_step_by_key(rid, "check")
    out = db.jloads(step["output_json"], {})
    assert out["demo"] is True
    assert out["args"]["sku"] == "查询 A-100 库存"


# ---------------------------------------------------------------- 敏感工具审批前置

def test_planner_forces_approval_before_sensitive_tool():
    plan = planner.validate_plan([
        {"key": "fetch", "name": "拉取外部接口", "role": "执行者", "kind": "tool", "tool": "http_request",
         "prompt": "请求外部接口获取数据", "depends_on": []},
        {"key": "report", "name": "汇总", "role": "报告", "kind": "report", "tool": None,
         "prompt": "汇总结果", "depends_on": ["fetch"]},
    ])
    keys = [s["key"] for s in plan]
    assert "approve_fetch" in keys
    appr = next(s for s in plan if s["key"] == "approve_fetch")
    fetch = next(s for s in plan if s["key"] == "fetch")
    assert appr["kind"] == "approval"
    assert fetch["depends_on"] == ["approve_fetch"]
    assert appr["depends_on"] == []
    assert keys.index("approve_fetch") < keys.index("fetch")


def test_planner_skips_approval_if_already_depends_on_approval():
    plan = planner.validate_plan([
        {"key": "check", "name": "人工确认", "role": "审批人", "kind": "approval", "tool": None,
         "prompt": "确认后继续", "depends_on": []},
        {"key": "fetch", "name": "拉取外部接口", "role": "执行者", "kind": "tool", "tool": "http_request",
         "prompt": "请求外部接口", "depends_on": ["check"]},
        {"key": "report", "name": "汇总", "role": "报告", "kind": "report", "tool": None,
         "prompt": "汇总", "depends_on": ["fetch"]},
    ])
    assert [s["key"] for s in plan] == ["check", "fetch", "report"]


def test_non_sensitive_tool_does_not_get_approval():
    plan = planner.validate_plan([
        {"key": "search", "name": "检索", "role": "调研员", "kind": "tool", "tool": "web_search",
         "prompt": "检索", "depends_on": []},
        {"key": "report", "name": "汇总", "role": "报告", "kind": "report", "tool": None,
         "prompt": "汇总", "depends_on": ["search"]},
    ])
    assert [s["key"] for s in plan] == ["search", "report"]


def test_deps_met_blocks_sensitive_tool_without_approved_approval(client):
    rid = db.create_run("敏感", "拉取外部接口", db.now_iso())
    plan = planner.validate_plan([
        {"key": "fetch", "name": "拉取外部接口", "role": "执行者", "kind": "tool", "tool": "http_request",
         "prompt": "请求外部接口获取数据", "depends_on": []},
        {"key": "report", "name": "汇总", "role": "报告", "kind": "report", "tool": None,
         "prompt": "汇总结果", "depends_on": ["fetch"]},
    ])
    planner.save_plan(rid, {"source": "rule", "steps": plan, "tokens_in": 0, "tokens_out": 0})
    steps = {s["step_key"]: s for s in db.list_steps(rid)}
    status = {k: "pending" for k in steps}
    # 审批未通过 → 敏感工具步骤不可调度
    assert executor._deps_met(steps["fetch"], status) is False
    # 审批通过 → 可调度
    status["approve_fetch"] = "succeeded"
    assert executor._deps_met(steps["fetch"], status) is True
    # 审批被跳过（拒绝）→ 仍不可调度
    status2 = {k: "pending" for k in steps}
    status2["approve_fetch"] = "skipped"
    assert executor._deps_met(steps["fetch"], status2) is False


def test_sensitive_tool_run_requires_approval_end_to_end(client):
    """端到端：敏感工具步骤在审批通过前保持 pending，审批通过后任务成功。"""
    rid = db.create_run("敏感工具演示", "拉取外部接口", db.now_iso())
    plan = {"source": "rule", "tokens_in": 0, "tokens_out": 0, "steps": planner.validate_plan([
        {"key": "fetch", "name": "拉取外部接口", "role": "执行者", "kind": "tool", "tool": "http_request",
         "prompt": "请求外部接口获取数据", "depends_on": []},
        {"key": "report", "name": "汇总", "role": "报告", "kind": "report", "tool": None,
         "prompt": "汇总结果", "depends_on": ["fetch"]},
    ])}
    planner.save_plan(rid, plan)
    db.update_run(rid, status="running")
    thread = threading.Thread(target=executor._execute_run, args=(rid,), daemon=True)
    thread.start()
    try:
        assert _wait_until(lambda: db.get_run(rid)["status"] == "waiting_approval", 10), "未到达审批挂起"
        fetch = db.get_step_by_key(rid, "fetch")
        assert fetch["status"] == "pending", "敏感工具在审批前不得执行"
        appr = db.get_step_by_key(rid, "approve_fetch")
        executor.approve_step(appr["id"], "approve", "同意")
        assert _wait_until(lambda: db.get_run(rid)["status"] in ("succeeded", "failed"), 10)
        assert db.get_run(rid)["status"] == "succeeded"
    finally:
        thread.join(timeout=5)
