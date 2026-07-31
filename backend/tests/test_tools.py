"""工具注册表测试。"""
from __future__ import annotations


def test_list_builtin_tools(client):
    tools = client.get("/api/tools").json()
    keys = {t["key"] for t in tools}
    assert {"web_search", "sql_query", "http_request", "summarize", "approve"} <= keys
    approve = next(t for t in tools if t["key"] == "approve")
    assert approve["sensitive"] is True
    assert approve["is_builtin"] is True


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
