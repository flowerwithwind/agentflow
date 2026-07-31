"""内置工具执行器（A4 / FR-04）。

- 参数校验：按 tools.params_json 的 type / required 规则；
- sql_query：内置只读 SQLite 样例库（data/demo.db），仅允许单条 SELECT，
  强制行数上限与执行超时（进度回调守卫）；
- http_request：GET 白名单域名（config.HTTP_ALLOWED_HOSTS），网络不可用时
  自动降级为演示响应（离线可演示）；
- 自定义工具：仅存参数定义，校验后返回参数回显演示输出。
"""
from __future__ import annotations

import json
import sqlite3
import urllib.parse
import urllib.request
from typing import Any

from app.config import HTTP_ALLOWED_HOSTS
from app.storage import db, demo_db

# 演示检索样例（离线可用）
DEMO_WEB_RESULTS = [
    {"title": "AI 应用开发趋势 2026", "url": "https://example.com/ai-trends-2026", "snippet": "多模态模型与本地化部署成为企业落地主流方向，Agent 编排工具快速兴起。"},
    {"title": "竞品动态周报", "url": "https://example.com/competitor-weekly", "snippet": "头部厂商本月集中发布流式语音与文档智能助手能力，价格战初现。"},
    {"title": "行业公开资料", "url": "https://example.com/industry-report", "snippet": "市场调研显示，影像修复与超分辨率在电商与档案数字化场景需求增长。"},
]

_SQL_FORBIDDEN_KEYWORDS = (
    "insert", "update", "delete", "drop", "alter", "create", "replace",
    "attach", "detach", "pragma", "vacuum", "begin", "commit", "rollback",
    "savepoint", "release", "execute", "reindex", "import",
)
_SQL_MAX_ROWS = 100          # 行数上限（返回 100 行，超出标记 truncated）
_SQL_PROGRESS_INTERVAL = 1000  # 每 1000 个 VM 指令回调一次进度守卫
_SQL_PROGRESS_LIMIT = 200      # 回调超过 200 次视为执行超时（约 20 万指令）


def _validate_params(tool_key: str, params: dict[str, Any], args: dict[str, Any]) -> dict[str, Any]:
    """按工具参数定义校验：必填缺失 / 类型不符 / 未知参数抛 ValueError。"""
    unknown = set(args) - set(params)
    if unknown:
        raise ValueError(f"工具 {tool_key} 收到未知参数: {sorted(unknown)}")
    for name, spec in params.items():
        if spec.get("required") and name not in args:
            raise ValueError(f"工具 {tool_key} 缺少必填参数: {name}")
        if name in args:
            want = spec.get("type")
            # JSON Schema 类型名 → Python 类型名（string→str / integer→int / number→float / boolean→bool）
            got = type(args[name]).__name__
            py_name = {"string": "str", "integer": "int", "number": "float", "boolean": "bool"}.get(want)
            if py_name is not None and got != py_name:
                raise ValueError(f"参数 {name} 类型应为 {want}，实际为 {got}")
    return args


def _demo_web_search(args: dict[str, Any]) -> dict[str, Any]:
    query = str(args.get("query", ""))[:80]
    return {"query": query, "results": DEMO_WEB_RESULTS}


def _check_readonly_sql(sql: str) -> str:
    """校验 SQL：仅允许单条 SELECT；禁危险关键字与注释；缺失 LIMIT 时强制追加行数上限。"""
    stripped = sql.strip()
    if not stripped:
        raise ValueError("SQL 不能为空")
    if ";" in stripped.rstrip(";"):
        raise ValueError("仅支持单条 SQL 语句")
    lowered = stripped.lower()
    first_kw = lowered.split(None, 1)[0] if lowered.split(None, 1) else ""
    is_select = first_kw == "select" or (first_kw == "with" and " select " in (" " + lowered + " "))
    if not is_select:
        raise ValueError("仅支持只读 SELECT 查询")
    for kw in _SQL_FORBIDDEN_KEYWORDS:
        if f" {kw} " in f" {lowered} ":
            raise ValueError(f"SQL 包含禁止关键字: {kw}")
    if "--" in stripped or "/*" in stripped:
        raise ValueError("SQL 不允许包含注释")
    if "limit" not in lowered:
        stripped = stripped.rstrip(";") + f" LIMIT {_SQL_MAX_ROWS + 1}"
    return stripped


def _demo_sql_query(args: dict[str, Any]) -> dict[str, Any]:
    """真实只读 SQLite 样例库查询：白名单校验 + 行数上限 + 进度守卫超时。"""
    sql = _check_readonly_sql(str(args["sql"]))
    conn = demo_db.connect_readonly()
    calls: dict[str, int] = {"n": 0}

    def _progress_guard() -> None:
        calls["n"] += 1
        if calls["n"] > _SQL_PROGRESS_LIMIT:
            raise sqlite3.OperationalError("SQL 查询执行超时")

    try:
        conn.set_progress_handler(_progress_guard, _SQL_PROGRESS_INTERVAL)
        cur = conn.execute(sql)
        columns = [d[0] for d in cur.description]
        rows = [dict(r) for r in cur.fetchmany(_SQL_MAX_ROWS + 1)]
        return {
            "sql": args["sql"],
            "columns": columns,
            "rows": rows[:_SQL_MAX_ROWS],
            "row_count": len(rows[:_SQL_MAX_ROWS]),
            "truncated": len(rows) > _SQL_MAX_ROWS,
        }
    except sqlite3.OperationalError as exc:
        if "interrupt" in str(exc).lower():
            raise ValueError("SQL 查询执行超时（进度守卫已终止）") from exc
        raise ValueError(f"SQL 查询失败: {exc}") from exc
    finally:
        conn.set_progress_handler(None, 0)
        conn.close()


def _demo_summarize(args: dict[str, Any]) -> dict[str, Any]:
    text = str(args.get("text", ""))
    return {"summary": text[:120] + ("…" if len(text) > 120 else ""), "chars": len(text)}


def _check_whitelisted_url(url: str) -> str:
    """校验 URL：http(s) 协议、主机在白名单（含子域名）、不携带自定义端口。"""
    try:
        parsed = urllib.parse.urlsplit(url)
    except ValueError as exc:
        raise ValueError(f"URL 非法: {url}") from exc
    if parsed.scheme not in ("http", "https"):
        raise ValueError("URL 必须以 http:// 或 https:// 开头")
    host = (parsed.hostname or "").lower()
    if not host:
        raise ValueError("URL 缺少主机名")
    if parsed.port not in (None, 80, 443):
        raise ValueError("URL 不允许自定义端口")
    allowed = any(host == h or host.endswith("." + h) for h in HTTP_ALLOWED_HOSTS)
    if not allowed:
        raise ValueError(f"域名不在白名单: {host}")
    return url


def _demo_http_request(args: dict[str, Any]) -> dict[str, Any]:
    """GET 白名单域名；网络不可用/超时/HTTP 错误自动降级为演示响应（离线可演示）。"""
    url = _check_whitelisted_url(str(args["url"]))
    try:
        req = urllib.request.Request(
            url, method="GET",
            headers={"User-Agent": "AgentFlow-Demo/1.0", "Accept": "application/json, text/plain"},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            raw = resp.read(262144)
            content_type = resp.headers.get("Content-Type", "")
            try:
                body = json.loads(raw) if "json" in content_type else raw.decode("utf-8", "replace")[:4000]
            except (ValueError, UnicodeDecodeError):
                body = raw[:4000].decode("utf-8", "replace")
            return {"url": url, "status": resp.status, "content_type": content_type, "body": body}
    except Exception as exc:  # noqa: BLE001 - 网络不可用/超时/HTTP 错误均降级演示响应
        return {
            "url": url,
            "status": 200,
            "body": {"ok": True, "demo": True, "note": f"网络不可用（{type(exc).__name__}），返回演示响应"},
        }


def execute_tool(tool_key: str, args: dict[str, Any]) -> dict[str, Any]:
    """执行工具：参数校验 + 内置实现 / 自定义工具演示回显。"""
    row = db.get_tool_by_key(tool_key)
    if row is None:
        raise ValueError(f"工具不存在: {tool_key}")
    params = db.jloads(row["params_json"], {})
    args = _validate_params(tool_key, params, args)
    if tool_key == "web_search":
        return _demo_web_search(args)
    if tool_key == "sql_query":
        return _demo_sql_query(args)
    if tool_key == "summarize":
        return _demo_summarize(args)
    if tool_key == "http_request":
        return _demo_http_request(args)
    # 自定义工具：仅存参数定义，演示模式返回参数回显（接入真实实现后替换此输出）
    return {
        "demo": True,
        "tool": tool_key,
        "args": args,
        "output": "自定义工具仅注册参数定义，演示模式返回参数回显",
    }
