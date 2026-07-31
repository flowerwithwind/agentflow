"""规划器服务（A3 / FR-02）：规则模板 + LLM 规划 + DAG 校验与落库。

- 规则规划器：按关键词匹配内置模板（竞品分析/活动策划/故障排查/数据核对），兜底通用模板；
- LLM 规划器：OpenAI 兼容接口 + JSON Schema 输出，解析失败重试 1 次后降级为规则规划器；
- 环检测：depends_on 构成环或引用不存在的步骤时拒绝并报错。
"""
from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from app.models import StepKind
from app.services import llm
from app.storage import db
from app.utils.logging import get_logger

logger = get_logger("planner")


class PlanStep(BaseModel):
    """规划步骤模型：与 steps 表字段一一对应。"""

    key: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")
    name: str = Field(min_length=1, max_length=128)
    role: str = Field(min_length=1, max_length=64)
    kind: StepKind
    tool: str | None = None
    prompt: str = Field(min_length=1)
    depends_on: list[str] = []


# ---------------------------------------------------------------- 规则模板


def _step(
    key: str,
    name: str,
    role: str,
    kind: str,
    prompt: str,
    depends_on: list[str] | None = None,
    tool: str | None = None,
) -> dict[str, Any]:
    return {
        "key": key,
        "name": name,
        "role": role,
        "kind": kind,
        "tool": tool,
        "prompt": prompt,
        "depends_on": list(depends_on or []),
    }


def _competitive_analysis_steps(task: str) -> list[dict[str, Any]]:
    return [
        _step("research_a", "竞品动态检索", "调研员", "tool", f"检索目标竞品的最新动态、功能更新与市场信息：{task}", tool="web_search"),
        _step("research_b", "行业趋势检索", "调研员", "tool", f"检索行业趋势、公开资料与第三方评价：{task}", tool="web_search"),
        _step("analyze", "竞品对比分析", "分析师", "llm", f"基于检索结果对比竞品优劣势、定位差异并给出建议：{task}", depends_on=["research_a", "research_b"]),
        _step("report", "竞品分析报告", "报告撰写", "report", f"汇总分析结论，输出结构化的竞品分析报告：{task}", depends_on=["analyze"]),
    ]


def _event_planning_steps(task: str) -> list[dict[str, Any]]:
    return [
        _step("goal", "活动目标拆解", "策划师", "llm", f"明确活动目标、目标受众、预算与时间约束：{task}"),
        _step("plan", "活动方案设计", "策划师", "llm", f"设计活动流程、物料、人员分工与风险预案：{task}", depends_on=["goal"]),
        _step("approve", "活动方案人工审批", "审批人", "approval", f"人工审批活动方案，确认预算与执行风险：{task}", depends_on=["plan"]),
        _step("report", "活动策划案", "报告撰写", "report", f"输出可执行的完整活动策划案：{task}", depends_on=["approve"]),
    ]


def _troubleshooting_steps(task: str) -> list[dict[str, Any]]:
    return [
        _step("collect", "故障信息收集", "运维工程师", "tool", f"收集故障现象、报错日志与相关上下文：{task}", tool="web_search"),
        _step("diagnose", "根因分析", "诊断专家", "llm", f"分析可能原因、影响范围并给出排查路径：{task}", depends_on=["collect"]),
        _step("verify", "数据验证", "数据分析师", "tool", f"查询相关数据验证根因假设：{task}", depends_on=["diagnose"], tool="sql_query"),
        _step("report", "故障排查报告", "报告撰写", "report", f"输出根因结论、影响面与修复建议：{task}", depends_on=["verify"]),
    ]


def _data_reconciliation_steps(task: str) -> list[dict[str, Any]]:
    return [
        _step("extract", "数据提取", "数据分析师", "tool", f"查询并提取待核对的数据源：{task}", tool="sql_query"),
        _step("compare", "差异核对", "数据分析师", "llm", f"逐项核对数据差异、口径与异常记录：{task}", depends_on=["extract"]),
        _step("report", "核对结论报告", "报告撰写", "report", f"输出核对结论、差异清单与修正建议：{task}", depends_on=["compare"]),
    ]


def _generic_steps(task: str) -> list[dict[str, Any]]:
    return [
        _step("understand", "任务理解", "规划师", "llm", f"理解任务目标、范围、约束与交付要求：{task}"),
        _step("execute", "任务执行", "执行专员", "llm", f"按步骤完成任务的执行并产出中间结果：{task}", depends_on=["understand"]),
        _step("report", "结果汇总", "报告撰写", "report", f"汇总执行结果并输出最终交付物：{task}", depends_on=["execute"]),
    ]


TEMPLATES: list[tuple[str, list[str], Callable[[str], list[dict[str, Any]]]]] = [
    ("competitive_analysis", ["竞品", "竞对", "竞争对手", "分析", "调研", "市场", "对比"], _competitive_analysis_steps),
    ("event_planning", ["活动", "策划", "方案", "发布会", "营销", "推广", "沙龙", "峰会"], _event_planning_steps),
    ("troubleshooting", ["故障", "排查", "报错", "异常", "宕机", "崩溃", "定位", "线上问题"], _troubleshooting_steps),
    ("data_reconciliation", ["数据", "核对", "校验", "对账", "报表", "一致性", "差异"], _data_reconciliation_steps),
]


def _match_template(task_text: str) -> Callable[[str], list[dict[str, Any]]]:
    """按关键词命中数选择模板，无命中时兜底通用模板。"""
    best_builder = _generic_steps
    best_score = 0
    for _name, keywords, builder in TEMPLATES:
        score = sum(1 for kw in keywords if kw in task_text)
        if score > best_score:
            best_builder, best_score = builder, score
    return best_builder


# ---------------------------------------------------------------- DAG 校验


def _find_cycle(steps: list[dict[str, Any]]) -> list[str] | None:
    """DFS 检测依赖环，返回环路径；无环返回 None。"""
    deps: dict[str, set[str]] = {s["key"]: set(s["depends_on"]) for s in steps}
    visiting: set[str] = set()
    visited: set[str] = set()

    def dfs(key: str, path: list[str]) -> list[str] | None:
        if key in visiting:
            return path[path.index(key):] + [key]
        if key in visited:
            return None
        visiting.add(key)
        path.append(key)
        for dep in deps[key]:
            cycle = dfs(dep, path)
            if cycle:
                return cycle
        path.pop()
        visiting.remove(key)
        visited.add(key)
        return None

    for key in deps:
        cycle = dfs(key, [])
        if cycle:
            return cycle
    return None


def validate_plan(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """校验步骤 DAG：字段完整、key 唯一、依赖存在、无环；返回规范化后的步骤。"""
    if not steps:
        raise ValueError("规划结果为空：未生成任何步骤")
    normalized: list[dict[str, Any]] = []
    for step in steps:
        try:
            normalized.append(PlanStep(**step).model_dump(mode="json"))
        except ValidationError as exc:
            first = exc.errors()[0] if exc.errors() else {}
            raise ValueError(f"步骤字段非法（{first.get('loc', '?')}）: {first.get('msg', str(exc))}") from exc
    keys = [s["key"] for s in normalized]
    if len(set(keys)) != len(keys):
        raise ValueError("步骤 key 重复，无法构成 DAG")
    key_set = set(keys)
    for step in normalized:
        for dep in step["depends_on"]:
            if dep not in key_set:
                raise ValueError(f"步骤 {step['key']} 依赖不存在的步骤: {dep}")
    cycle = _find_cycle(normalized)
    if cycle:
        raise ValueError("步骤依赖构成环: " + " -> ".join(cycle))
    return normalized


# ---------------------------------------------------------------- 规则规划器


def plan_with_rules(task_text: str) -> list[dict[str, Any]]:
    """规则规划：按关键词匹配模板生成合法 DAG，无匹配时使用通用模板。"""
    return validate_plan(_match_template(task_text)(task_text))


# ---------------------------------------------------------------- LLM 规划器

LLM_PLAN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "steps": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "key": {"type": "string"},
                    "name": {"type": "string"},
                    "role": {"type": "string"},
                    "kind": {"type": "string", "enum": ["llm", "tool", "approval", "report"]},
                    "tool": {"type": ["string", "null"]},
                    "prompt": {"type": "string"},
                    "depends_on": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["key", "name", "role", "kind", "prompt", "depends_on"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["steps"],
}

SYSTEM_PROMPT = """你是 AgentFlow 的任务规划器，负责把用户的一句话任务拆解为可执行的步骤 DAG。
要求：
1. 只输出严格 JSON（不要 Markdown 代码块、不要任何多余文字），结构为 {"steps": [...]}；
2. 每个步骤必须包含 key/name/role/kind/tool/prompt/depends_on 字段；
3. key 为小写字母开头的唯一标识；kind 只能是 llm|tool|approval|report；
4. kind 为 tool 时 tool 必须给出工具 key（如 web_search、sql_query、summarize、http_request）；
5. depends_on 是上游步骤 key 数组：不允许引用不存在的 key，不允许构成环；
6. 最后一个步骤必须是 kind=report 的汇总步骤。"""


def get_llm_config() -> dict[str, Any]:
    """读取 LLM 配置：app/config.py 默认值，settings 表可覆盖。"""
    return llm.get_llm_config()


def _call_llm(cfg: dict[str, Any], task_text: str) -> tuple[str, dict[str, Any] | None]:
    """调用共享 LLM 层（app/services/llm.py），返回 (content, usage)。"""
    user_prompt = (
        f"任务文本：{task_text}\n\n"
        f"请严格按以下 JSON Schema 输出规划结果：\n{json.dumps(LLM_PLAN_SCHEMA, ensure_ascii=False)}"
    )
    return llm.chat_completion(SYSTEM_PROMPT, user_prompt, cfg)

def _parse_llm_steps(content: str) -> list[dict[str, Any]]:
    """解析 LLM 输出：剥离代码块 → JSON 解析 → 字段/DAG 校验。"""
    data = llm.parse_json_object(content)
    steps = data.get("steps")
    if not isinstance(steps, list):
        raise TypeError("LLM 输出缺少 steps 数组")
    return validate_plan(steps)

def plan_with_llm(task_text: str, cfg: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """LLM 规划：解析失败重试 1 次，仍失败返回 None（由调用方降级为规则规划器）。"""
    cfg = cfg or get_llm_config()
    for attempt in (1, 2):
        try:
            content, usage = _call_llm(cfg, task_text)
            steps = _parse_llm_steps(content)
            usage = usage or {}
            return {
                "source": "llm",
                "steps": steps,
                "tokens_in": int(usage.get("prompt_tokens") or 0),
                "tokens_out": int(usage.get("completion_tokens") or 0),
            }
        except Exception as exc:  # noqa: BLE001 - LLM 网络/解析任一失败均降级为规则规划器
            logger.warning("LLM 规划第 %s 次尝试失败: %s", attempt, exc)
    return None


# ---------------------------------------------------------------- 规划编排与落库


def _rule_plan(task_text: str) -> dict[str, Any]:
    return {"source": "rule", "steps": plan_with_rules(task_text), "tokens_in": 0, "tokens_out": 0}


def generate_plan(task_text: str) -> dict[str, Any]:
    """规划入口：无 API key 直接规则规划器；有 key 时 LLM 优先，失败降级规则规划器。"""
    cfg = get_llm_config()
    if not cfg.get("api_key"):
        return _rule_plan(task_text)
    llm_plan = plan_with_llm(task_text, cfg)
    if llm_plan is None:
        return _rule_plan(task_text)
    return llm_plan


def save_plan(run_id: int, plan: dict[str, Any]) -> None:
    """规划结果落库：steps 写入 steps 表，摘要写入 runs.plan_json。"""
    now = db.now_iso()
    rows = [
        {
            "run_id": run_id,
            "step_key": s["key"],
            "seq": idx,
            "name": s["name"],
            "role": s["role"],
            "kind": s["kind"],
            "tool_key": s.get("tool"),
            "prompt": s.get("prompt"),
            "depends_on": db.jdumps(s.get("depends_on") or []),
            "created_at": now,
        }
        for idx, s in enumerate(plan["steps"], start=1)
    ]
    db.insert_steps(rows)
    plan_json = {"source": plan["source"], "steps": plan["steps"], "version": 1}
    db.update_run(
        run_id,
        plan_json=db.jdumps(plan_json),
        total_tokens=plan.get("tokens_in", 0) + plan.get("tokens_out", 0),
    )


def plan_run(run_id: int) -> dict[str, Any] | None:
    """为任务执行规划并落库：状态 pending → planning → pending（交由执行引擎调度）/ failed。"""
    run = db.get_run(run_id)
    if not run:
        raise ValueError(f"任务不存在: {run_id}")
    if run["status"] != "pending":
        raise ValueError(f"任务状态 {run['status']} 不可规划")
    db.update_run(run_id, status="planning")
    db.insert_event(run_id, "run_planning", {"run_id": run_id})
    try:
        plan = generate_plan(run["input_text"])
        save_plan(run_id, plan)
        if db.get_run(run_id)["status"] == "cancelled":
            return None
        db.update_run(run_id, status="pending")
        db.insert_event(
            run_id,
            "run_planned",
            {"run_id": run_id, "source": plan["source"], "step_count": len(plan["steps"])},
        )
        logger.info("任务 %s 规划完成: source=%s steps=%d", run_id, plan["source"], len(plan["steps"]))
        return plan
    except Exception as exc:
        logger.exception("任务 %s 规划失败", run_id)
        db.update_run(run_id, status="failed", error=str(exc), finished_at=db.now_iso())
        db.insert_event(run_id, "run_failed", {"run_id": run_id, "error": str(exc)})
        return None