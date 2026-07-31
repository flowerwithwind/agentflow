"""内置工具执行器（A3 最小版，A4 扩展注册表）。

- 参数校验：按 tools.params_json 的 type / required 规则；
- 演示模式（无外部依赖）：web_search / sql_query / summarize / http_request 返回内置样例；
- 敏感工具（http_request）A3 阶段由规划器决定是否挂审批步骤，执行器不自行拦截。
"""
from __future__ import annotations

from typing import Any

from app.storage import db

# 内置 SQL 样例库（A4 升级为真实 SQLite 只读库）
DEMO_ORDERS = [
    {"id": 1001, "customer": "华东商贸", "amount": 12800.0, "status": "paid", "date": "2026-07-01"},
    {"id": 1002, "customer": "华南实业", "amount": 8600.0, "status": "pending", "date": "2026-07-05"},
    {"id": 1003, "customer": "华北集团", "amount": 23400.0, "status": "paid", "date": "2026-07-12"},
    {"id": 1004, "customer": "西部电商", "amount": 5200.0, "status": "refunded", "date": "2026-07-18"},
    {"id": 1005, "customer": "中部零售", "amount": 15750.0, "status": "paid", "date": "2026-07-24"},
]

DEMO_WEB_RESULTS = [
    {"title": "AI 应用开发趋势 2026", "url": "https://example.com/ai-trends-2026", "snippet": "多模态模型与本地化部署成为企业落地主流方向，Agent 编排工具快速兴起。"},
    {"title": "竞品动态周报", "url": "https://example.com/competitor-weekly", "snippet": "头部厂商本月集中发布流式语音与文档智能助手能力，价格战初现。"},
    {"title": "行业公开资料", "url": "https://example.com/industry-report", "snippet": "市场调研显示，影像修复与超分辨率在电商与档案数字化场景需求增长。"},
]


def _validate_params(tool_key: str, params: dict[str, Any], args: dict[str, Any]) -> dict[str, Any]:
    """按工具参数定义校验：必填缺失 / 类型不符抛 ValueError。"""
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


def _demo_sql_query(args: dict[str, Any]) -> dict[str, Any]:
    sql = str(args.get("sql", "")).strip().lower()
    if not sql.startswith("select"):
        raise ValueError("仅支持只读 SELECT 查询")
    return {"sql": args["sql"], "rows": DEMO_ORDERS, "columns": list(DEMO_ORDERS[0])}


def _demo_summarize(args: dict[str, Any]) -> dict[str, Any]:
    text = str(args.get("text", ""))
    return {"summary": text[:120] + ("…" if len(text) > 120 else ""), "chars": len(text)}


def _demo_http_request(args: dict[str, Any]) -> dict[str, Any]:
    url = str(args.get("url", ""))
    if not url.startswith(("https://", "http://")):
        raise ValueError("URL 必须以 http(s):// 开头")
    return {"url": url, "status": 200, "body": {"ok": True, "demo": True}}


def execute_tool(tool_key: str, args: dict[str, Any]) -> dict[str, Any]:
    """执行内置工具：参数校验 + 演示执行。"""
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
    raise ValueError(f"工具 {tool_key} 尚未实现执行器")
