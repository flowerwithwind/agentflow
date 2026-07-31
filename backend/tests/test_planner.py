"""规划器测试（A3 / FR-02）：规则模板 DAG、LLM 降级、环检测、规划落库。"""
from __future__ import annotations

import json
import time

import pytest

from app.services import planner
from app.storage import db

TERMINAL = ("succeeded", "failed", "cancelled")


def _wait_until(pred, timeout=10.0, interval=0.02):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if pred():
            return True
        time.sleep(interval)
    return False


RULE_TASKS = [
    ("竞品分析", "请分析三家竞品的最新动态、功能差异并给出建议。"),
    ("活动策划", "策划一场产品发布会活动，包含流程、预算与物料清单。"),
    ("故障排查", "线上服务报错，请排查故障原因并给出修复方案。"),
    ("数据核对", "请核对本月销售报表与订单数据的一致性并输出差异。"),
]

FIRST_STEP_BY_TASK = {
    "竞品分析": "research_a",
    "活动策划": "goal",
    "故障排查": "collect",
    "数据核对": "extract",
}


@pytest.mark.parametrize(("title", "task"), RULE_TASKS, ids=[t for t, _ in RULE_TASKS])
def test_rule_template_outputs_valid_dag(title, task):
    plan = planner.generate_plan(task)
    assert plan["source"] == "rule"
    steps = plan["steps"]
    assert len(steps) >= 3
    keys = [s["key"] for s in steps]
    assert len(keys) == len(set(keys))  # key 唯一
    for s in steps:
        assert s["key"] and s["name"] and s["role"] and s["prompt"]
        assert s["kind"] in ("llm", "tool", "approval", "report")
        assert "tool" in s
        if s["kind"] == "tool":
            assert s["tool"]
        for dep in s["depends_on"]:
            assert dep in keys  # 依赖必须存在
    assert steps[-1]["kind"] == "report"  # 末步为汇总报告
    assert steps[0]["key"] == FIRST_STEP_BY_TASK[title]  # 关键词命中对应模板


def test_generic_template_fallback(client):
    plan = planner.generate_plan("写一份本周工作总结")
    assert plan["source"] == "rule"
    assert [s["key"] for s in plan["steps"]] == ["understand", "execute", "report"]


def _mock_cfg(api_key="sk-test-123"):
    return {
        "base_url": "https://example.com/v1",
        "model": "deepseek-chat",
        "api_key": api_key,
        "temperature": 0.3,
        "max_tokens": 4096,
    }


def _llm_payload(steps):
    return json.dumps({"steps": steps}, ensure_ascii=False)


def _llm_step(key, name, kind, depends_on, tool=None):
    return {
        "key": key, "name": name, "role": "测试角色", "kind": kind,
        "tool": tool, "prompt": f"执行 {name}", "depends_on": depends_on,
    }


def test_llm_invalid_json_retries_then_falls_back(client, monkeypatch):
    calls: list[str] = []

    def fake_call(cfg, task):
        calls.append(task)
        return "这不是合法 JSON", None

    monkeypatch.setattr(planner, "get_llm_config", lambda: _mock_cfg())
    monkeypatch.setattr(planner, "_call_llm", fake_call)
    plan = planner.generate_plan("请分析竞品")
    assert plan["source"] == "rule"  # 解析失败 → 降级规则规划器
    assert len(calls) == 2  # 首次失败 + 重试 1 次
    assert [s["key"] for s in plan["steps"]] == ["research_a", "research_b", "analyze", "report"]


def test_llm_retry_after_bad_json_succeeds(client, monkeypatch):
    responses = [
        "第一轮输出损坏",
        _llm_payload([
            _llm_step("goal", "活动目标拆解", "llm", []),
            _llm_step("report", "活动策划案", "report", ["goal"]),
        ]),
    ]
    calls: list[str] = []

    def fake_call(cfg, task):
        calls.append(task)
        return responses.pop(0), None

    monkeypatch.setattr(planner, "get_llm_config", lambda: _mock_cfg())
    monkeypatch.setattr(planner, "_call_llm", fake_call)
    plan = planner.generate_plan("策划活动")
    assert plan["source"] == "llm"  # 重试成功不再降级
    assert len(calls) == 2
    assert [s["key"] for s in plan["steps"]] == ["goal", "report"]


def test_llm_valid_json_returns_llm_plan_with_tokens(client, monkeypatch):
    payload = _llm_payload([
        _llm_step("research", "竞品检索", "tool", [], tool="web_search"),
        _llm_step("report", "分析报告", "report", ["research"]),
    ])
    monkeypatch.setattr(planner, "get_llm_config", lambda: _mock_cfg())
    monkeypatch.setattr(
        planner, "_call_llm",
        lambda cfg, task: (payload, {"prompt_tokens": 100, "completion_tokens": 50}),
    )
    plan = planner.generate_plan("分析竞品")
    assert plan["source"] == "llm"
    assert [s["key"] for s in plan["steps"]] == ["research", "report"]
    assert plan["tokens_in"] == 100
    assert plan["tokens_out"] == 50


def test_validate_plan_rejects_cycle():
    steps = [
        {"key": "a", "name": "A", "role": "r", "kind": "llm", "tool": None, "prompt": "p", "depends_on": ["b"]},
        {"key": "b", "name": "B", "role": "r", "kind": "llm", "tool": None, "prompt": "p", "depends_on": ["a"]},
    ]
    with pytest.raises(ValueError, match="环"):
        planner.validate_plan(steps)


def test_validate_plan_rejects_self_dependency():
    steps = [
        {"key": "a", "name": "A", "role": "r", "kind": "llm", "tool": None, "prompt": "p", "depends_on": ["a"]},
    ]
    with pytest.raises(ValueError, match="环"):
        planner.validate_plan(steps)


def test_validate_plan_rejects_missing_dependency():
    steps = [
        {"key": "a", "name": "A", "role": "r", "kind": "llm", "tool": None, "prompt": "p", "depends_on": ["ghost"]},
    ]
    with pytest.raises(ValueError, match="不存在"):
        planner.validate_plan(steps)


def test_validate_plan_rejects_duplicate_keys():
    steps = [
        {"key": "a", "name": "A", "role": "r", "kind": "llm", "tool": None, "prompt": "p", "depends_on": []},
        {"key": "a", "name": "A2", "role": "r", "kind": "report", "tool": None, "prompt": "p", "depends_on": []},
    ]
    with pytest.raises(ValueError, match="重复"):
        planner.validate_plan(steps)


def test_llm_cycle_retries_then_falls_back(client, monkeypatch):
    cyclic = _llm_payload([
        _llm_step("a", "步骤A", "llm", ["b"]),
        _llm_step("b", "步骤B", "llm", ["a"]),
    ])
    calls: list[str] = []

    def fake_call(cfg, task):
        calls.append(task)
        return cyclic, None

    monkeypatch.setattr(planner, "get_llm_config", lambda: _mock_cfg())
    monkeypatch.setattr(planner, "_call_llm", fake_call)
    plan = planner.generate_plan("故障排查")
    assert plan["source"] == "rule"  # 环检测失败 → 重试 1 次 → 降级规则规划器
    assert len(calls) == 2
    assert [s["key"] for s in plan["steps"]] == ["collect", "diagnose", "verify", "report"]


def test_plan_run_persists_complete_fields(client):
    run_id = db.create_run("数据核对", "核对订单与库存数据一致性", db.now_iso())
    plan = planner.plan_run(run_id)
    assert plan is not None
    assert plan["source"] == "rule"
    run = db.get_run(run_id)
    assert run["status"] == "pending"
    saved = db.jloads(run["plan_json"])
    assert saved["version"] == 1
    assert saved["source"] == "rule"
    assert [s["key"] for s in saved["steps"]] == [s["key"] for s in plan["steps"]]
    rows = db.list_steps(run_id)
    assert len(rows) == len(plan["steps"])
    for i, (row, orig) in enumerate(zip(rows, plan["steps"]), start=1):
        assert row["seq"] == i
        assert row["step_key"] == orig["key"]
        assert row["name"] == orig["name"]
        assert row["role"] == orig["role"]
        assert row["kind"] == orig["kind"]
        assert row["tool_key"] == orig["tool"]
        assert row["prompt"] == orig["prompt"]
        assert db.jloads(row["depends_on"]) == orig["depends_on"]
        assert row["status"] == "pending"
    assert [e["type"] for e in db.list_events(run_id)] == ["run_planning", "run_planned"]


def test_plan_run_with_llm_persists_tokens(client, monkeypatch):
    payload = _llm_payload([
        _llm_step("research", "竞品检索", "tool", [], tool="web_search"),
        _llm_step("report", "分析报告", "report", ["research"]),
    ])
    monkeypatch.setattr(planner, "get_llm_config", lambda: _mock_cfg())
    monkeypatch.setattr(
        planner, "_call_llm",
        lambda cfg, task: (payload, {"prompt_tokens": 120, "completion_tokens": 30}),
    )
    run_id = db.create_run("LLM 规划", "分析竞品", db.now_iso())
    plan = planner.plan_run(run_id)
    assert plan is not None
    assert plan["source"] == "llm"
    run = db.get_run(run_id)
    assert run["status"] == "pending"
    assert run["total_tokens"] == 150
    assert db.jloads(run["plan_json"])["source"] == "llm"
    assert [s["step_key"] for s in db.list_steps(run_id)] == ["research", "report"]


def test_llm_config_reads_settings_override(client):
    db.set_setting("model", {
        "base_url": "https://custom.example/v1", "model": "custom-model", "api_key": "sk-custom",
    })
    cfg = planner.get_llm_config()
    assert cfg["base_url"] == "https://custom.example/v1"
    assert cfg["model"] == "custom-model"
    assert cfg["api_key"] == "sk-custom"


def test_generate_plan_without_api_key_uses_rules(client):
    plan = planner.generate_plan("请分析三家竞品的最新动态")
    assert plan["source"] == "rule"


def test_plan_run_rejects_non_pending(client):
    run_id = db.create_run("任务", "分析竞品", db.now_iso())
    db.update_run(run_id, status="running")
    with pytest.raises(ValueError, match="不可规划"):
        planner.plan_run(run_id)


def test_create_run_api_starts_async_execution(client):
    r = client.post("/api/runs", json={"title": "竞争分析", "input_text": "请分析三家竞争产品的最新动态并给出建议。"})
    assert r.status_code == 201
    run_id = r.json()["id"]
    assert _wait_until(lambda: db.get_run(run_id)["status"] in TERMINAL, 15), "run 未到达终态"
    run = db.get_run(run_id)
    assert run["status"] == "succeeded"  # 无 API Key：规则规划 + 演示执行
    detail = client.get(f"/api/runs/{run_id}").json()
    assert len(detail["steps"]) >= 4
    types = [e["type"] for e in db.list_events(run_id)]
    assert types[:3] == ["run_planning", "run_planned", "run_started"]
    assert types[-1] == "run_succeeded"
