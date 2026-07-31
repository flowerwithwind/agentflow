"""健康检查测试。"""
from __future__ import annotations


def test_health_ok(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "AgentFlow"
    assert body["status"] == "ok"
    assert body["storage"] == "ok"
    caps = body["capabilities"]
    assert set(caps) >= {"llm", "demo_mode", "engine", "tool_count"}
    # 测试环境无 Key → 演示模式
    assert caps["llm"] is False
    assert caps["demo_mode"] is True
    assert caps["tool_count"] >= 5
