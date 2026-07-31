"""code_review 内置工具测试（A7）：参数校验、规则审查结构、PR URL 模式、端到端一键跑通。"""
from __future__ import annotations

import threading
import time

import pytest
from app.services import executor, planner, tools
from app.storage import db

_CATEGORIES = {"正确性", "安全", "性能", "可维护性", "风格"}


def _wait_until(pred, timeout=10.0, interval=0.02):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if pred():
            return True
        time.sleep(interval)
    return False


def test_code_review_param_validation():
    with pytest.raises(ValueError):
        tools.execute_tool("code_review", {})  # 缺必填 diff
    with pytest.raises(ValueError):
        tools.execute_tool("code_review", {"diff": "sample", "unknown": 1})  # 未知参数
    with pytest.raises(ValueError):
        tools.execute_tool("code_review", {"diff": 123})  # 类型错误


def test_code_review_sample_output_structure():
    out = tools.execute_tool("code_review", {"diff": "sample", "language": "python", "focus": ["正确性", "安全", "性能"]})
    assert out["mode"] == "diff"
    assert out["sample"] is True
    assert out["score"] >= 0 and out["score"] <= 100
    assert out["summary"]
    assert out["issues"], "样例 diff 应至少发现一个问题"
    for issue in out["issues"]:
        assert issue["category"] in _CATEGORIES
        assert issue["severity"] in ("critical", "warning", "suggestion")
        assert issue["line"] > 0
        assert issue["message"] and issue["suggestion"]
    # focus 只影响对应类别
    cats = {i["category"] for i in out["issues"]}
    assert cats <= {"正确性", "安全", "性能"}


def test_code_review_pr_url_mode():
    out = tools.execute_tool("code_review", {"diff": "https://github.com/example/repo/pull/42", "language": "python"})
    assert out["mode"] == "pr_url"
    assert "演示" in out["note"]
    assert out["issues"]


def test_code_review_clean_diff_no_issues():
    clean = "+import json\n+def load(path):\n+    with open(path, encoding=\"utf-8\") as f:\n+        return json.load(f)\n"
    out = tools.execute_tool("code_review", {"diff": clean})
    assert out["issues"] == []
    assert out["score"] == 100


def test_code_review_run_end_to_end(client):
    """端到端：code_review 步骤作为任务一步跑通（无 Key 一键样例）。"""
    rid = db.create_run("代码审查演示", "审查一段演示代码", db.now_iso())
    plan = {"source": "rule", "tokens_in": 0, "tokens_out": 0, "steps": planner.validate_plan([
        {"key": "review", "name": "代码审查", "role": "审查员", "kind": "tool", "tool": "code_review",
         "prompt": "审查代码质量", "depends_on": []},
        {"key": "report", "name": "审查报告", "role": "报告", "kind": "report", "tool": None,
         "prompt": "汇总审查结论", "depends_on": ["review"]},
    ])}
    planner.save_plan(rid, plan)
    db.update_run(rid, status="running")
    thread = threading.Thread(target=executor._execute_run, args=(rid,), daemon=True)
    thread.start()
    assert _wait_until(lambda: db.get_run(rid)["status"] in ("succeeded", "failed"), 15), "run 未结束"
    assert db.get_run(rid)["status"] == "succeeded"
    review = db.get_step_by_key(rid, "review")
    out = db.jloads(review["output_json"], {})
    assert out.get("score") is not None
    assert out.get("issues") and out["issues"][0]["category"] in _CATEGORIES
    report = db.get_run(rid)["report"]
    assert "代码审查" in report
