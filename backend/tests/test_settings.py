"""设置 API 测试。"""
from __future__ import annotations


def test_default_settings(client):
    body = client.get("/api/settings").json()
    assert body["model"]["model"] == "deepseek-chat"
    assert body["model"]["api_key"] == ""  # 不回显
    assert body["execution"]["parallel"] == 4
    assert body["capabilities"]["demo_mode"] is True


def test_save_model_settings_keeps_api_key(client):
    r = client.put("/api/settings", json={
        "model": {"model": "gpt-4o-mini", "temperature": 0.5, "api_key": "sk-test-123"},
    })
    assert r.status_code == 200
    body = r.json()
    assert body["model"]["model"] == "gpt-4o-mini"
    assert body["model"]["temperature"] == 0.5
    # 写入后回显掩码
    assert body["model"]["api_key"] == "***"
    assert body["capabilities"]["llm"] is True

    # 再次保存不改 api_key → 保留原值
    r2 = client.put("/api/settings", json={"model": {"model": "qwen-max"}})
    assert r2.json()["model"]["model"] == "qwen-max"
    assert r2.json()["model"]["api_key"] == "***"


def test_save_execution_settings(client):
    r = client.put("/api/settings", json={"execution": {"parallel": 8, "max_attempts": 5}})
    assert r.status_code == 200
    exec_cfg = r.json()["execution"]
    assert exec_cfg["parallel"] == 8
    assert exec_cfg["max_attempts"] == 5
    assert exec_cfg["step_timeout_seconds"] == 120  # 未改动的保持默认
