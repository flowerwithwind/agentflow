"""执行引擎（A3 / FR-03）：DAG 调度、重试、超时、审批挂起、事件流。

状态机（run）：pending → planning → running → succeeded / failed / cancelled
步骤状态机：pending → running → succeeded / failed / skipped（审批挂起时 waiting_approval）
"""
from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from typing import Any

from app.services import llm, planner, tools
from app.services.settings import get_execution_settings
from app.storage import db
from app.utils.logging import get_logger

logger = get_logger("executor")

APPROVAL_TIMEOUT_POLL_SECONDS = 0.2

# 审批唤醒事件：run_id -> threading.Event（审批 API / 取消时 set）
_APPROVAL_EVENTS: dict[int, threading.Event] = {}
_APPROVAL_LOCK = threading.Lock()


class RejectedError(Exception):
    """审批拒绝：步骤置 skipped，下游级联跳过。"""


class CancelledError(Exception):
    """任务已取消：终止当前执行。"""


def _event_for(run_id: int) -> threading.Event:
    with _APPROVAL_LOCK:
        ev = _APPROVAL_EVENTS.get(run_id)
        if ev is None:
            ev = threading.Event()
            _APPROVAL_EVENTS[run_id] = ev
        return ev


def _drop_event(run_id: int) -> None:
    with _APPROVAL_LOCK:
        _APPROVAL_EVENTS.pop(run_id, None)


# ---------------------------------------------------------------- 入口


def start_run(run_id: int) -> None:
    """后台线程启动完整流程（规划 → 执行）。"""
    threading.Thread(target=_run_flow, args=(run_id,), daemon=True, name=f"run-{run_id}").start()


def _run_flow(run_id: int) -> None:
    run = db.get_run(run_id)
    if run is None or run["status"] != "pending":
        logger.warning("run %s 状态 %s 不可启动", run_id, run["status"] if run else "N/A")
        return
    try:
        # 规划（A2 规划器）
        planner.plan_run(run_id)
        run = db.get_run(run_id)
        if run["status"] != "pending":
            # 规划期间被取消
            return
        # 执行
        db.update_run(run_id, status="running")
        db.insert_event(run_id, "run_started", {"run_id": run_id})
        _execute_run(run_id)
    except Exception as exc:
        logger.exception("run %s 执行异常", run_id)
        db.insert_event(run_id, "run_failed", {"run_id": run_id, "error": str(exc)})
        db.update_run(run_id, status="failed", error=str(exc), finished_at=db.now_iso())


# ---------------------------------------------------------------- 调度


def _is_approval_step(run_id: int, step_key: str) -> bool:
    row = db.get_step_by_key(run_id, step_key)
    return row is not None and row["kind"] == "approval"


def _deps_met(step, status: dict[str, str]) -> bool:
    deps = db.jloads(step["depends_on"], [])
    if not all(status.get(d) in ("succeeded", "skipped") for d in deps):
        return False
    # A4：敏感工具步骤必须依赖一个已通过的审批步骤，否则不允许调度
    if step["kind"] == "tool" and step["tool_key"]:
        row = db.get_tool_by_key(step["tool_key"])
        if (
            row is not None
            and bool(row["sensitive"])
            and not any(
                status.get(d) == "succeeded" and _is_approval_step(step["run_id"], d) for d in deps
            )
        ):
            return False
    return True


def _blocked_by_failure(step, status: dict[str, str]) -> bool:
    """依赖链上存在 failed / skipped 步骤 → 本步骤应跳过。"""
    deps = db.jloads(step["depends_on"], [])
    for d in deps:
        if status.get(d) in ("failed", "skipped"):
            return True
        if status.get(d) == "pending":
            dep_row = db.get_step_by_key(step["run_id"], d)
            if dep_row is not None and _blocked_by_failure(dep_row, status):
                return True
    return False


def _execute_run(run_id: int) -> None:
    settings = get_execution_settings()
    parallel = int(settings.get("parallel", 4))
    max_attempts = int(settings.get("max_attempts", 3))
    timeout_s = float(settings.get("step_timeout_seconds", 120))
    retry_base_s = float(settings.get("retry_base_seconds", 1.0))

    steps = db.list_steps(run_id)
    by_key = {s["step_key"]: s for s in steps}
    status: dict[str, str] = {s["step_key"]: s["status"] for s in steps}
    submitted: dict[str, Any] = {}  # step_key -> Future

    with ThreadPoolExecutor(max_workers=max(1, min(parallel, len(steps)))) as pool:
        while True:
            run = db.get_run(run_id)
            if run is None or run["status"] == "cancelled":
                return
            # 回收已完成 future
            for key in list(submitted):
                fut = submitted[key]
                if not fut.done():
                    continue
                submitted.pop(key)
                try:
                    fut.result()
                    status[key] = "succeeded"
                except RejectedError:
                    # 审批拒绝：本步骤 skipped，级联跳过由调度轮处理（事件先落库避免观察者竞态）
                    db.insert_event(run_id, "step_skipped", {"step_key": key, "reason": "审批拒绝"}, by_key[key]["id"])
                    db.update_step(by_key[key]["id"], status="skipped", finished_at=db.now_iso())
                    status[key] = "skipped"
                except CancelledError:
                    return
                except Exception as exc:  # noqa: BLE001 - 重试耗尽后的步骤失败
                    # 优先保留 _run_step 已落库的失败原因（如超时消息），避免被空消息覆盖
                    step_row = db.get_step(by_key[key]["id"])
                    err = (step_row["error"] if step_row and step_row["error"] else None) or str(exc) or "步骤执行失败"
                    db.insert_event(run_id, "step_failed", {"step_key": key, "error": err}, by_key[key]["id"])
                    db.update_step(by_key[key]["id"], status="failed", error=err, finished_at=db.now_iso())
                    status[key] = "failed"
            # 级联跳过：依赖失败/被跳过 的 pending 步骤
            for s in steps:
                if status[s["step_key"]] == "pending" and _blocked_by_failure(s, status):
                    db.insert_event(run_id, "step_skipped", {"step_key": s["step_key"], "reason": "上游失败"}, s["id"])
                    db.update_step(s["id"], status="skipped", finished_at=db.now_iso())
                    status[s["step_key"]] = "skipped"
            # 调度就绪步骤
            if not submitted:
                ready = [s for s in steps if status[s["step_key"]] == "pending" and _deps_met(s, status)]
                if not ready:
                    break
                for s in ready:
                    submitted[s["step_key"]] = pool.submit(
                        _run_step, s, max_attempts, timeout_s, retry_base_s
                    )
            time.sleep(0.02)

    # 终态判定（事件先落库再改状态：观察者看到终态时事件必然完整）
    run = db.get_run(run_id)
    if run is None or run["status"] != "running":
        return
    steps_now = db.list_steps(run_id)
    failed = [s for s in steps_now if status.get(s["step_key"]) == "failed"]
    if failed:
        first = min(failed, key=lambda s: s["seq"])
        err = first["error"] or "步骤执行失败"
        db.insert_event(run_id, "run_failed", {"run_id": run_id, "error": err})
        db.update_run(run_id, status="failed", error=err, finished_at=db.now_iso())
        return
    # 成功：汇总报告 + token / 耗时（用最新步骤数据）
    report_md = _generate_report(run_id, steps_now, status)
    total_tokens = sum(int(s["tokens_in"] or 0) + int(s["tokens_out"] or 0) for s in steps_now)
    created = db.get_run(run_id)["created_at"]
    total_ms = _elapsed_ms(created, db.now_iso())
    db.insert_event(run_id, "run_succeeded", {"run_id": run_id, "steps": len(steps_now), "report_chars": len(report_md)})
    db.update_run(
        run_id,
        status="succeeded",
        report=report_md,
        total_tokens=total_tokens,
        total_duration_ms=total_ms,
        finished_at=db.now_iso(),
    )
    logger.info("run %s 完成: %d 步, %d tokens", run_id, len(steps_now), total_tokens)


# ---------------------------------------------------------------- 单步执行


def _run_step(step, max_attempts: int, timeout_s: float, retry_base_s: float) -> dict[str, Any]:
    """单步骤执行：重试（指数退避）+ 超时；返回步骤输出。"""
    step_id, run_id = step["id"], step["run_id"]
    last_error = ""
    for attempt in range(1, max_attempts + 1):
        started = time.monotonic()
        db.update_step(step_id, status="running", attempts=attempt, error=None)
        db.insert_event(
            run_id, "step_started", {"step_key": step["step_key"], "attempt": attempt}, step_id
        )
        try:
            with ThreadPoolExecutor(max_workers=1) as ex:
                fut = ex.submit(_attempt_once, step)
                result = fut.result(timeout=timeout_s)
            tokens_in, tokens_out = result.pop("_tokens", (0, 0))
            db.insert_event(
                run_id,
                "step_succeeded",
                {"step_key": step["step_key"], "output_keys": list(result)},
                step_id,
            )
            db.update_step(
                step_id,
                status="succeeded",
                output_json=db.jdumps(result),
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                duration_ms=int((time.monotonic() - started) * 1000),
                finished_at=db.now_iso(),
            )
            return result
        except RejectedError:
            # 调度循环负责置 skipped 并级联
            raise
        except CancelledError:
            raise
        except Exception as exc:
            if isinstance(exc, FutureTimeout):
                last_error = f"步骤执行超时（>{timeout_s:g}s）"
            else:
                last_error = str(exc)
            duration_ms = int((time.monotonic() - started) * 1000)
            if attempt < max_attempts:
                db.insert_event(
                    run_id, "step_retry", {"step_key": step["step_key"], "attempt": attempt, "error": last_error}, step_id
                )
                db.update_step(
                    step_id,
                    status="pending",
                    error=f"第 {attempt} 次尝试失败: {last_error}",
                    duration_ms=duration_ms,
                )
                time.sleep(retry_base_s * (2 ** (attempt - 1)))
            else:
                db.update_step(
                    step_id,
                    status="failed",
                    error=last_error,
                    duration_ms=duration_ms,
                    finished_at=db.now_iso(),
                )
                raise RuntimeError(last_error) from exc
    raise RuntimeError(last_error)  # pragma: no cover - 不可达


def _attempt_once(step) -> dict[str, Any]:
    """单次执行（无写库副作用，超时丢弃结果安全）。"""
    kind = step["kind"]
    if kind == "tool":
        return _execute_tool_step(step)
    if kind == "approval":
        return _wait_approval(step)
    if kind == "report":
        return _execute_report_step(step)
    return _execute_llm_step(step)


# ---------------------------------------------------------------- 各类步骤


def _execute_llm_step(step) -> dict[str, Any]:
    cfg = llm.get_llm_config()
    if not llm.has_api_key(cfg):
        return _mock_llm(step)
    system = "你是 AgentFlow 的执行智能体，只输出严格 JSON 对象（不要 Markdown 代码块），结构由用户消息指定。"
    user = f"任务上下文：{step['prompt']}\n\n请输出一个 JSON 对象，包含 summary（结论摘要）与 points（要点数组）两个字段。"
    content, usage = llm.chat_completion(system, user, cfg)
    result = llm.parse_json_object(content)
    tokens_in, tokens_out = llm.usage_to_tokens(usage)
    result["_tokens"] = (tokens_in, tokens_out)
    return result


def _mock_llm(step) -> dict[str, Any]:
    """无 Key 演示模式：基于 prompt 生成规则化输出。"""
    text = step["prompt"] or ""
    first = text[:60]
    return {
        "summary": f"（演示模式）已处理：{first}",
        "points": [f"要点 1：{first}", "要点 2：基于规则模板的演示输出", "要点 3：配置 API Key 后可切换真实 LLM"],
        "source": "demo",
        "_tokens": (0, 0),
    }


def _tool_args_from_prompt(step) -> dict[str, Any]:
    """演示模式：从 prompt 规则提取工具参数（A4 支持自定义工具按参数定义生成）。"""
    tool = step["tool_key"]
    text = (step["prompt"] or "")[:200]
    if tool == "web_search":
        return {"query": text}
    if tool == "sql_query":
        return {"sql": "SELECT * FROM orders LIMIT 5"}
    if tool == "summarize":
        return {"text": text}
    if tool == "http_request":
        return {"url": "https://example.com/api/demo"}
    # A4：自定义工具按参数定义生成演示参数（必填 string → prompt 文本，其余按类型给默认值）
    row = db.get_tool_by_key(tool)
    params = db.jloads(row["params_json"], {}) if row else {}
    args: dict[str, Any] = {}
    for name, spec in params.items():
        if not spec.get("required"):
            continue
        param_type = spec.get("type")
        if param_type == "integer":
            args[name] = 1
        elif param_type == "number":
            args[name] = 1.0
        elif param_type == "boolean":
            args[name] = True
        elif param_type == "array":
            args[name] = []
        else:
            args[name] = text
    return args


def _execute_tool_step(step) -> dict[str, Any]:
    args = _tool_args_from_prompt(step)
    result = tools.execute_tool(step["tool_key"], args)
    result["_tokens"] = (0, 0)
    return result


def _execute_report_step(step) -> dict[str, Any]:
    """报告步骤：聚合已完成步骤输出生成 Markdown（A6 完善引用与导出）。"""
    steps = db.list_steps(step["run_id"])
    sections = []
    for s in steps:
        if s["status"] != "succeeded":
            continue
        out = db.jloads(s["output_json"], {})
        summary = out.get("summary") or out.get("report") or str(out)[:200]
        sections.append(f"### {s['seq']}. {s['name']}（{s['role']}）\n\n{summary}\n")
    md = f"# 执行报告\n\n{''.join(sections)}".strip()
    return {"report": md, "source_steps": [s["step_key"] for s in steps if s["status"] == "succeeded"], "_tokens": (0, 0)}


def _generate_report(run_id: int, steps, status: dict[str, str]) -> str:
    """终局报告：全部成功/跳过步骤的聚合（含跳过说明）。"""
    sections = []
    for s in steps:
        st = status.get(s["step_key"])
        if st == "succeeded":
            out = db.jloads(s["output_json"], {})
            body = out.get("summary") or out.get("report") or str(out)[:200]
            sections.append(f"### {s['seq']}. {s['name']}（{s['role']}）\n\n{body}\n")
        elif st == "skipped":
            sections.append(f"### {s['seq']}. {s['name']}（{s['role']}）\n\n_已跳过（上游未完成或审批未通过）_\n")
    run = db.get_run(run_id)
    md = (
        f"# 任务报告：{run['title']}\n\n"
        f"**输入**：{run['input_text']}\n\n"
        + "".join(sections)
    )
    return md.strip()


def _wait_approval(step) -> dict[str, Any]:
    """审批步骤：置 waiting_approval 并挂起，等待审批通过或任务取消。"""
    run_id = step["run_id"]
    db.insert_event(run_id, "approval_requested", {"step_key": step["step_key"]}, step["id"])
    db.update_step(step["id"], status="waiting_approval")
    db.update_run(run_id, status="waiting_approval")
    ev = _event_for(run_id)
    try:
        while True:
            if ev.wait(timeout=APPROVAL_TIMEOUT_POLL_SECONDS):
                break
            run = db.get_run(run_id)
            if run is None or run["status"] == "cancelled":
                raise CancelledError("任务已取消")
        # 审批已处理：若未被取消则恢复执行中
        run = db.get_run(run_id)
        if run is None or run["status"] == "cancelled":
            raise CancelledError("任务已取消")
        db.update_run(run_id, status="running")
        approvals = db.list_approvals(run_id)
        mine = [a for a in approvals if a["step_id"] == step["id"]]
        if not mine:
            raise CancelledError("审批记录缺失")
        last = mine[-1]
        db.insert_event(
            run_id,
            "approval_resolved",
            {"step_key": step["step_key"], "action": last["action"], "reason": last["reason"] or ""},
            step["id"],
        )
        if last["action"] == "approve":
            return {"approved": True, "reason": last["reason"] or "", "_tokens": (0, 0)}
        raise RejectedError(f"审批拒绝: {last['reason'] or '未提供理由'}")
    finally:
        _drop_event(run_id)


# ---------------------------------------------------------------- 外部控制


def approve_step(step_id: int, action: str, reason: str) -> None:
    """审批接口：校验状态 → 记录 → 唤醒执行线程。"""
    step = db.get_step(step_id)
    if step is None:
        raise ValueError("步骤不存在")
    if step["status"] != "waiting_approval":
        raise ValueError(f"步骤状态 {step['status']} 不可审批")
    db.create_approval(step["run_id"], step_id, action, reason)
    _event_for(step["run_id"]).set()


def request_cancel(run_id: int) -> None:
    """取消任务：仅允许 running 之前（A3 语义）；唤醒挂起的审批。"""
    run = db.get_run(run_id)
    if run is None:
        raise ValueError("任务不存在")
    if run["status"] in ("succeeded", "failed", "cancelled"):
        raise ValueError(f"任务已处于终态 {run['status']}")
    if run["status"] == "running":
        raise ValueError("任务执行中不可取消")
    db.insert_event(run_id, "run_cancelled", {"run_id": run_id})
    db.update_run(run_id, status="cancelled", finished_at=db.now_iso())
    _event_for(run_id).set()


def _elapsed_ms(start_iso: str, end_iso: str) -> int:
    from datetime import datetime

    fmt = "%Y-%m-%dT%H:%M:%S"
    try:
        s = datetime.strptime(start_iso[:19], fmt)  # noqa: DTZ007 - 全项目统一本地时间
        e = datetime.strptime(end_iso[:19], fmt)  # noqa: DTZ007 - 全项目统一本地时间
        return max(0, int((e - s).total_seconds() * 1000))
    except ValueError:
        return 0
