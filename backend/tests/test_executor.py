"""执行引擎测试（A3 / FR-03）：DAG 调度、重试退避、超时、审批挂起、取消、重启恢复。"""
from __future__ import annotations

import threading
import time

import pytest

from app.services import executor
from app.storage import db

TERMINAL = ("succeeded", "failed", "cancelled")


def _make_run(title="执行测试", text="请分析三家竞品的最新动态并给出建议。"):
    return db.create_run(title, text, db.now_iso())


def _make_steps(run_id, spec):
    """spec: list of (key, name, kind, depends_on, tool_key)。"""
    now = db.now_iso()
    rows = [
        {
            "run_id": run_id,
            "step_key": key,
            "seq": i,
            "name": name,
            "role": "测试",
            "kind": kind,
            "tool_key": tool,
            "prompt": f"执行 {name}",
            "depends_on": db.jdumps(deps),
            "created_at": now,
        }
        for i, (key, name, kind, deps, tool) in enumerate(spec, start=1)
    ]
    db.insert_steps(rows)


def _set_execution(**kwargs):
    db.set_setting("execution", kwargs)


def _wait_until(pred, timeout=10.0, interval=0.02):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if pred():
            return True
        time.sleep(interval)
    return False


def _wait_run(run_id, timeout=15.0):
    assert _wait_until(lambda: db.get_run(run_id)["status"] in TERMINAL, timeout), "run 未到达终态"
    return db.get_run(run_id)


def _event_types(run_id):
    return [e["type"] for e in db.list_events(run_id)]


def _ok_result(key):
    return {"summary": key, "points": [], "_tokens": (0, 0)}


def _no_plan(monkeypatch):
    """自定义步骤测试跳过规划器：plan_run 保持 pending 状态（A3 执行直接可用）。"""
    monkeypatch.setattr(executor.planner, "plan_run", lambda run_id: None)


def _plan_and_start(monkeypatch, text="请分析三家竞品的最新动态并给出建议。"):
    """A2 语义：先真实规划落库，再置回 pending 启动执行线程。

    A2 的 plan_run 完成后状态为 succeeded（pending → planning → succeeded），
    而执行引擎要求 pending 才可启动；这里同步规划后把状态置回 pending，
    并让执行线程跳过重复规划，既保留真实规划事件（run_planning / run_planned），
    又避免测试轮询到规划期的瞬时 succeeded 状态。
    """
    run_id = _make_run(text=text)
    executor.planner.plan_run(run_id)
    db.update_run(run_id, status="pending")
    monkeypatch.setattr(executor.planner, "plan_run", lambda run_id: None)
    executor.start_run(run_id)
    return run_id


# ---------------------------------------------------------------- 调度


def test_dependency_chain_runs_in_order(monkeypatch):
    _no_plan(monkeypatch)
    run_id = _make_run()
    _make_steps(run_id, [
        ("a", "步骤A", "llm", [], None),
        ("b", "步骤B", "llm", ["a"], None),
        ("c", "步骤C", "llm", ["b"], None),
    ])
    order: list[str] = []
    started: dict[str, float] = {}

    def fake_attempt(step):
        started[step["step_key"]] = time.monotonic()
        order.append(step["step_key"])
        time.sleep(0.05)
        return _ok_result(step["step_key"])

    monkeypatch.setattr(executor, "_attempt_once", fake_attempt)
    executor.start_run(run_id)
    run = _wait_run(run_id)
    assert run["status"] == "succeeded"
    assert order == ["a", "b", "c"]  # 依赖链严格按序
    assert started["b"] - started["a"] >= 0.04  # b 等待 a 完成后才启动
    assert started["c"] - started["b"] >= 0.04


def test_independent_steps_run_in_parallel(monkeypatch):
    _no_plan(monkeypatch)
    run_id = _make_run()
    _make_steps(run_id, [
        ("a", "步骤A", "llm", [], None),
        ("b", "步骤B", "llm", [], None),
    ])
    intervals: dict[str, tuple[float, float]] = {}

    def fake_attempt(step):
        t0 = time.monotonic()
        time.sleep(0.2)
        intervals[step["step_key"]] = (t0, time.monotonic())
        return _ok_result(step["step_key"])

    monkeypatch.setattr(executor, "_attempt_once", fake_attempt)
    executor.start_run(run_id)
    run = _wait_run(run_id)
    assert run["status"] == "succeeded"
    (a0, a1), (b0, b1) = intervals["a"], intervals["b"]
    assert max(a0, b0) < min(a1, b1)  # 执行区间重叠 → 并行


# ---------------------------------------------------------------- 重试与超时


def test_retry_exhausted_marks_failed(monkeypatch):
    _no_plan(monkeypatch)
    run_id = _make_run()
    _make_steps(run_id, [("a", "步骤A", "tool", [], "web_search")])
    _set_execution(max_attempts=2, retry_base_seconds=0.01, step_timeout_seconds=5, parallel=4)

    def boom(tool_key, args):
        raise RuntimeError("模拟工具崩溃")

    monkeypatch.setattr(executor.tools, "execute_tool", boom)
    executor.start_run(run_id)
    run = _wait_run(run_id)
    assert run["status"] == "failed"
    assert "模拟工具崩溃" in run["error"]
    events = _event_types(run_id)
    assert "step_retry" in events and "step_failed" in events and "run_failed" in events
    step = db.list_steps(run_id)[0]
    assert step["status"] == "failed"
    assert "模拟工具崩溃" in step["error"]


def test_step_timeout_marks_failed(monkeypatch):
    _no_plan(monkeypatch)
    run_id = _make_run()
    _make_steps(run_id, [("a", "步骤A", "llm", [], None)])
    _set_execution(max_attempts=2, retry_base_seconds=0.01, step_timeout_seconds=0.1, parallel=4)

    def slow(step):
        time.sleep(0.5)
        return _ok_result(step["step_key"])

    monkeypatch.setattr(executor, "_attempt_once", slow)
    executor.start_run(run_id)
    run = _wait_run(run_id, timeout=20)
    assert run["status"] == "failed"
    step = db.list_steps(run_id)[0]
    assert step["status"] == "failed"
    assert "超时" in step["error"]


def test_success_after_retry(monkeypatch):
    """第一次尝试失败，重试成功 → run 最终 succeeded 且包含 step_retry 事件。"""
    _no_plan(monkeypatch)
    run_id = _make_run()
    _make_steps(run_id, [("a", "步骤A", "tool", [], "web_search")])
    _set_execution(max_attempts=3, retry_base_seconds=0.01, step_timeout_seconds=5, parallel=4)
    calls = {"n": 0}

    def flaky(tool_key, args):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("第一次失败")
        return {"ok": True}

    monkeypatch.setattr(executor.tools, "execute_tool", flaky)
    executor.start_run(run_id)
    run = _wait_run(run_id)
    assert run["status"] == "succeeded"
    assert calls["n"] == 2
    assert "step_retry" in _event_types(run_id)
    step = db.list_steps(run_id)[0]
    assert step["status"] == "succeeded" and step["attempts"] == 2


# ---------------------------------------------------------------- 取消


def test_cancel_pending_run():
    run_id = _make_run()
    executor.request_cancel(run_id)
    run = db.get_run(run_id)
    assert run["status"] == "cancelled"
    assert run["finished_at"] is not None
    assert _event_types(run_id) == ["run_cancelled"]


def test_cancel_running_run_rejected(monkeypatch):
    _no_plan(monkeypatch)
    run_id = _make_run()
    _make_steps(run_id, [("a", "步骤A", "llm", [], None)])
    gate = threading.Event()
    entered = threading.Event()

    def blocked(step):
        entered.set()
        gate.wait(5)
        return _ok_result(step["step_key"])

    monkeypatch.setattr(executor, "_attempt_once", blocked)
    executor.start_run(run_id)
    assert _wait_until(lambda: db.get_run(run_id)["status"] == "running", 5)
    assert _wait_until(entered.is_set, 5)
    with pytest.raises(ValueError, match="不可取消"):
        executor.request_cancel(run_id)
    gate.set()
    run = _wait_run(run_id)
    assert run["status"] == "succeeded"


# ---------------------------------------------------------------- 审批


def test_approval_approve_continues(monkeypatch):
    # A2 规划（活动模板：goal → plan → approve → report）落库后置回 pending 再启动执行
    run_id = _plan_and_start(monkeypatch, text="策划一场产品发布会活动，包含流程与预算。")
    assert _wait_until(lambda: db.get_run(run_id)["status"] == "waiting_approval", 10)
    approval = next(s for s in db.list_steps(run_id) if s["kind"] == "approval")
    assert approval["status"] == "waiting_approval"
    executor.approve_step(approval["id"], "approve", "预算符合要求")
    run = _wait_run(run_id)
    assert run["status"] == "succeeded"
    events = _event_types(run_id)
    assert "approval_requested" in events and "approval_resolved" in events
    final = {s["step_key"]: s["status"] for s in db.list_steps(run_id)}
    assert final["approve"] == "succeeded"
    assert final["report"] == "succeeded"
    assert run["report"] and "任务报告" in run["report"]


def test_approval_reject_skips_downstream(monkeypatch):
    run_id = _plan_and_start(monkeypatch, text="策划一场产品发布会活动，包含流程与预算。")
    assert _wait_until(lambda: db.get_run(run_id)["status"] == "waiting_approval", 10)
    approval = next(s for s in db.list_steps(run_id) if s["kind"] == "approval")
    executor.approve_step(approval["id"], "reject", "预算超标")
    run = _wait_run(run_id)
    assert run["status"] == "succeeded"  # 无失败步骤：跳过即视为完成
    final = {s["step_key"]: s["status"] for s in db.list_steps(run_id)}
    assert final["approve"] == "skipped"
    assert final["report"] == "skipped"
    events = _event_types(run_id)
    assert events.count("step_skipped") >= 2
    assert "已跳过" in run["report"]


# ---------------------------------------------------------------- 恢复与事件流


def test_fail_stale_runs_on_restart():
    run_id = _make_run()
    _make_steps(run_id, [("a", "步骤A", "llm", [], None)])
    db.update_run(run_id, status="running")
    db.update_step(db.list_steps(run_id)[0]["id"], status="running")
    db.fail_stale_runs()
    run = db.get_run(run_id)
    assert run["status"] == "failed"
    assert "重启" in run["error"]
    assert db.list_steps(run_id)[0]["status"] == "failed"


def test_full_event_flow_success(monkeypatch):
    run_id = _plan_and_start(monkeypatch)
    run = _wait_run(run_id)
    assert run["status"] == "succeeded"
    types = _event_types(run_id)
    assert types[0] == "run_planning"
    assert types[1] == "run_planned"
    assert types[2] == "run_started"
    assert types[-1] == "run_succeeded"
    # 每个步骤事件成对：started 先于 succeeded
    started = [i for i, t in enumerate(types) if t == "step_started"]
    succ = [i for i, t in enumerate(types) if t == "step_succeeded"]
    assert len(started) == len(succ) == 4
    assert all(s < e for s, e in zip(started, succ))
    assert "step_retry" not in types and "step_failed" not in types


def test_llm_step_records_tokens(monkeypatch):
    """LLM 步骤（mock chat_completion）token 落库 + run.total_tokens 聚合。"""
    _no_plan(monkeypatch)
    run_id = _make_run()
    _make_steps(run_id, [("a", "步骤A", "llm", [], None)])
    def fake_chat(system, user, cfg=None, timeout_seconds=None):
        return '{"summary":"结论","points":["p1"]}', {"prompt_tokens": 10, "completion_tokens": 20}

    monkeypatch.setattr("app.services.executor.llm.get_llm_config", lambda: {"api_key": "sk-test"})
    monkeypatch.setattr("app.services.executor.llm.has_api_key", lambda cfg=None: True)
    monkeypatch.setattr("app.services.executor.llm.chat_completion", fake_chat)
    executor.start_run(run_id)
    run = _wait_run(run_id)
    assert run["status"] == "succeeded"
    assert run["total_tokens"] == 30  # 执行 token 聚合
    step = db.list_steps(run_id)[0]
    assert step["tokens_in"] == 10 and step["tokens_out"] == 20
    assert db.jloads(step["output_json"])["summary"] == "结论"
