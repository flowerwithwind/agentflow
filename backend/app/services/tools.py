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

DEMO_DIFF = """--- a/backend/user_service.py
+++ b/backend/user_service.py
@@ -1,20 +1,24 @@
 import sqlite3
+import os
 
 def get_user(user_id):
-    conn = sqlite3.connect("users.db")
-    cur = conn.execute("SELECT * FROM users WHERE id=" + str(user_id))
+    conn = sqlite3.connect("users.db")
+    sql = "SELECT * FROM users WHERE id=" + str(user_id)
+    cur = conn.execute(sql)
     row = cur.fetchone()
+    cur.close()
     conn.close()
     return row
+
+def admin_check(env):
+    if env == "prod":
+        return True
+    return False
+
+def delete_all():
+    os.system("rm -rf /tmp/cache")
+    data = []
+    for i in range(len(data)):
+        print(data[i])
+    return data
+"""

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


# ---------------------------------------------------------------- code_review（A7）

_REVIEW_CATEGORIES = ("正确性", "安全", "性能", "可维护性", "风格")

# (pattern, category, severity, message, suggestion)
_REVIEW_RULES: list[tuple[str, str, str, str, str]] = [
    ("eval(", "安全", "critical", "使用 eval() 执行动态代码，存在任意代码执行风险", "改用 ast.literal_eval 或明确的数据解析方案"),
    ("exec(", "安全", "critical", "使用 exec() 执行动态代码，存在任意代码执行风险", "移除动态执行，改为受控的白名单逻辑"),
    ("pickle.loads", "安全", "critical", "反序列化不可信数据可能导致任意代码执行", "改用 JSON 或校验来源后再反序列化"),
    ("os.system(", "安全", "critical", "os.system 直接执行 shell 命令，存在注入风险", "改用 subprocess.run(..., shell=False) 传参数列表"),
    ("shell=True", "安全", "warning", "subprocess 使用 shell=True，命令注入面扩大", "使用 shell=False 并传入参数列表"),
    ("+ str(", "安全", "warning", "SQL 或命令由字符串拼接构造，存在注入风险", "使用参数化查询（? 占位符）或参数列表"),
    ('"SELECT', "安全", "warning", "SQL 语句字符串拼接，存在注入风险", "使用参数化查询（? 占位符）"),
    ("'SELECT", "安全", "warning", "SQL 语句字符串拼接，存在注入风险", "使用参数化查询（? 占位符）"),
    ("except:", "正确性", "warning", "裸 except 吞掉所有异常，掩盖真实错误", "捕获具体异常类型并记录日志"),
    ("== None", "正确性", "suggestion", "使用 == None 判断空值", "改用 is None"),
    ("!= None", "正确性", "suggestion", "使用 != None 判断空值", "改用 is not None"),
    ("range(len(", "性能", "warning", "通过下标遍历集合，性能与可读性均差", "直接遍历元素或使用 enumerate"),
    ("for i in range", "性能", "suggestion", "for 循环中使用 range 下标访问", "直接迭代容器元素"),
    ("cur.close()", "可维护性", "warning", "手动关闭连接/游标，异常路径会泄漏资源", "使用 with 语句或 contextlib.closing"),
    ("conn.close()", "可维护性", "warning", "手动管理连接生命周期，异常路径会泄漏资源", "使用 with 语句自动管理连接"),
]


def _rule_review(diff: str, language: str, focus: list[str]) -> list[dict[str, Any]]:
    """规则审查：按行扫描常见问题模式，输出结构化 issues。"""
    focus_set = set(focus)
    issues: list[dict[str, Any]] = []
    lines = diff.splitlines()
    for lineno, line in enumerate(lines, start=1):
        if not line.startswith(("+", " ")):  # 只审查新增/上下文行，跳过 - 删除行
            continue
        for pattern, category, severity, message, suggestion in _REVIEW_RULES:
            if focus_set and category not in focus_set:
                continue
            if pattern in line:
                issues.append({
                    "category": category,
                    "severity": severity,
                    "line": lineno,
                    "code": line.strip()[:80],
                    "message": message,
                    "suggestion": suggestion,
                })
    return issues


def _dedupe_issues(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str, int]] = set()
    result = []
    for it in issues:
        key = (it["category"], it["message"], it["line"])
        if key in seen:
            continue
        seen.add(key)
        result.append(it)
    return result


def _review_score(issues: list[dict[str, Any]]) -> int:
    weight = {"critical": 15, "warning": 6, "suggestion": 2}
    deducted = sum(weight.get(i["severity"], 2) for i in issues)
    return max(0, min(100, 100 - deducted))


def _demo_code_review(args: dict[str, Any]) -> dict[str, Any]:
    """多维代码审查（A7）：PR URL 或 diff 文本 → 规则审查输出结构化评审。"""
    diff = str(args.get("diff") or "").strip()
    language = str(args.get("language") or "").strip() or "未知"
    focus = [str(x) for x in (args.get("focus") or [])]
    mode = "diff"
    sample = False
    if diff.lower().startswith(("http://", "https://")):
        mode = "pr_url"
        sample = True
        note = "演示模式不拉取远端 PR，改用内置样例 diff 进行规则审查"
        diff = DEMO_DIFF
    elif diff.lower() == "sample":
        sample = True
        note = "使用内置样例 diff（sample）"
        diff = DEMO_DIFF
    else:
        note = ""
    issues = _dedupe_issues(_rule_review(diff, language, focus))
    by_category = {c: sum(1 for i in issues if i["category"] == c) for c in _REVIEW_CATEGORIES}
    score = _review_score(issues)
    summary = (
        f"共发现 {len(issues)} 个问题（安全 {by_category['安全']}、正确性 {by_category['正确性']}、"
        f"性能 {by_category['性能']}、可维护性 {by_category['可维护性']}、风格 {by_category['风格']}），"
        f"评分 {score}/100。"
    )
    result: dict[str, Any] = {
        "mode": mode,
        "sample": sample,
        "language": language,
        "focus": focus,
        "score": score,
        "summary": summary,
        "issues": issues,
        "by_category": by_category,
    }
    if note:
        result["note"] = note
    return result


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
    if tool_key == "code_review":
        return _demo_code_review(args)
    # 自定义工具：仅存参数定义，演示模式返回参数回显（接入真实实现后替换此输出）
    return {
        "demo": True,
        "tool": tool_key,
        "args": args,
        "output": "自定义工具仅注册参数定义，演示模式返回参数回显",
    }
