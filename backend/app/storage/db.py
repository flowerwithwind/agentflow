"""SQLite 存储层：连接管理、建表、DAO。

设计约定：
- 每次操作独立连接（WAL 模式），简单可靠；
- 时间统一 ISO 8601 字符串（本地时间）；
- JSON 字段以 TEXT 存储。
"""
from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Iterable
from contextlib import contextmanager
from typing import Any

from app.config import DB_PATH
from app.models import now_iso

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  title TEXT NOT NULL,
  input_text TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',
  plan_json TEXT,
  report TEXT,
  error TEXT,
  total_tokens INTEGER NOT NULL DEFAULT 0,
  total_duration_ms INTEGER,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  finished_at TEXT
);

CREATE TABLE IF NOT EXISTS steps (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
  step_key TEXT NOT NULL,
  seq INTEGER NOT NULL,
  name TEXT NOT NULL,
  role TEXT NOT NULL,
  kind TEXT NOT NULL,
  tool_key TEXT,
  prompt TEXT,
  depends_on TEXT NOT NULL DEFAULT '[]',
  status TEXT NOT NULL DEFAULT 'pending',
  input_json TEXT,
  output_json TEXT,
  citations_json TEXT,
  tokens_in INTEGER NOT NULL DEFAULT 0,
  tokens_out INTEGER NOT NULL DEFAULT 0,
  duration_ms INTEGER,
  attempts INTEGER NOT NULL DEFAULT 0,
  error TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  finished_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_steps_run ON steps(run_id, seq);

CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
  step_id INTEGER REFERENCES steps(id) ON DELETE CASCADE,
  seq INTEGER NOT NULL,
  type TEXT NOT NULL,
  payload_json TEXT,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_run ON events(run_id, seq);

CREATE TABLE IF NOT EXISTS tools (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  key TEXT UNIQUE NOT NULL,
  name TEXT NOT NULL,
  description TEXT,
  params_json TEXT NOT NULL DEFAULT '{}',
  sensitive INTEGER NOT NULL DEFAULT 0,
  is_builtin INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS approvals (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id INTEGER NOT NULL,
  step_id INTEGER NOT NULL REFERENCES steps(id) ON DELETE CASCADE,
  action TEXT,
  reason TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
  key TEXT PRIMARY KEY,
  value_json TEXT NOT NULL
);
"""


def jdumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False)


def jloads(raw: str | None, default: Any = None) -> Any:
    if raw is None or raw == "":
        return default
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return default


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


@contextmanager
def get_conn() -> Iterable[sqlite3.Connection]:
    conn = _connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# 事件 seq 分配锁：并行步骤多线程写事件，MAX(seq)+1 必须原子（WAL 独立连接存在竞态）
_EVENT_SEQ_LOCK = threading.Lock()


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with get_conn() as conn:
        conn.executescript(SCHEMA_SQL)
    # 事件 (run_id, seq) 唯一索引兜底：历史脏数据存在重复 seq 时跳过（仅告警不阻断启动）
    try:
        with get_conn() as conn:
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_events_run_seq ON events(run_id, seq)"
            )
    except sqlite3.OperationalError:
        pass


def wipe_data() -> None:
    """清空全部业务数据（保留表结构与内置工具）。"""
    tables = ("approvals", "events", "steps", "runs", "tools", "settings")
    with get_conn() as conn:
        for t in tables:
            conn.execute(f"DELETE FROM {t}")

def clear_runs() -> int:
    """清空全部任务业务数据（runs/steps/events/approvals），保留工具与设置。返回删除的任务数。"""
    with get_conn() as conn:
        total = conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
        conn.execute("DELETE FROM approvals")
        conn.execute("DELETE FROM events")
        conn.execute("DELETE FROM steps")
        conn.execute("DELETE FROM runs")
        return int(total)



# ---------------------------------------------------------------- runs

def create_run(title: str, input_text: str, created_at: str) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO runs(title, input_text, status, created_at, updated_at) VALUES(?,?,'pending',?,?)",
            (title, input_text, created_at, created_at),
        )
        return int(cur.lastrowid)


def get_run(run_id: int) -> sqlite3.Row | None:
    with get_conn() as conn:
        return conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()


def list_runs(status: str = "", query: str = "", page: int = 1, page_size: int = 20) -> tuple[list[sqlite3.Row], int]:
    where = "WHERE 1=1"
    params: list[Any] = []
    if status:
        where += " AND status = ?"
        params.append(status)
    if query:
        where += " AND (title LIKE ? OR input_text LIKE ?)"
        params += [f"%{query}%", f"%{query}%"]
    with get_conn() as conn:
        total = conn.execute(f"SELECT COUNT(*) FROM runs {where}", params).fetchone()[0]
        rows = conn.execute(
            f"SELECT * FROM runs {where} ORDER BY id DESC LIMIT ? OFFSET ?",
            params + [page_size, (page - 1) * page_size],
        ).fetchall()
        return list(rows), int(total)


def update_run(run_id: int, **fields: Any) -> None:
    if not fields:
        return
    keys = ", ".join(f"{k}=?" for k in fields)
    with get_conn() as conn:
        conn.execute(f"UPDATE runs SET {keys}, updated_at=? WHERE id=?", list(fields.values()) + [now_iso(), run_id])


def delete_run(run_id: int) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM runs WHERE id=?", (run_id,))


def fail_stale_runs() -> None:
    """服务启动时把遗留进行中任务/步骤标记为失败。"""
    with get_conn() as conn:
        conn.execute(
            "UPDATE runs SET status='failed', error='服务重启，任务中断', updated_at=?, finished_at=? "
            "WHERE status IN ('pending','planning','running','waiting_approval')",
            (now_iso(), now_iso()),
        )
        conn.execute(
            "UPDATE steps SET status='failed', error='服务重启，任务中断', finished_at=? "
            "WHERE status IN ('running','waiting_approval')",
            (now_iso(),),
        )


# ---------------------------------------------------------------- steps

def insert_steps(steps: list[dict[str, Any]]) -> None:
    with get_conn() as conn:
        conn.executemany(
            """INSERT INTO steps(run_id, step_key, seq, name, role, kind, tool_key, prompt,
               depends_on, status, created_at, updated_at)
               VALUES(:run_id,:step_key,:seq,:name,:role,:kind,:tool_key,:prompt,
               :depends_on,'pending',:created_at,:created_at)""",
            steps,
        )


def list_steps(run_id: int) -> list[sqlite3.Row]:
    with get_conn() as conn:
        return list(conn.execute("SELECT * FROM steps WHERE run_id=? ORDER BY seq", (run_id,)))


def get_step_by_key(run_id: int, step_key: str) -> sqlite3.Row | None:
    with get_conn() as conn:
        return conn.execute("SELECT * FROM steps WHERE run_id=? AND step_key=?", (run_id, step_key)).fetchone()


def get_step(step_id: int) -> sqlite3.Row | None:
    with get_conn() as conn:
        return conn.execute("SELECT * FROM steps WHERE id=?", (step_id,)).fetchone()


def update_step(step_id: int, **fields: Any) -> None:
    if not fields:
        return
    keys = ", ".join(f"{k}=?" for k in fields)
    with get_conn() as conn:
        conn.execute(f"UPDATE steps SET {keys}, updated_at=? WHERE id=?", list(fields.values()) + [now_iso(), step_id])


# ---------------------------------------------------------------- events

def insert_event(run_id: int, type: str, payload: dict[str, Any] | None = None, step_id: int | None = None) -> int:
    # 并行步骤线程会并发写事件：seq 计算与插入必须原子，否则 MAX+1 会撞号
    with _EVENT_SEQ_LOCK, get_conn() as conn:
        seq = conn.execute("SELECT COALESCE(MAX(seq),0)+1 FROM events WHERE run_id=?", (run_id,)).fetchone()[0]
        cur = conn.execute(
            "INSERT INTO events(run_id, step_id, seq, type, payload_json, created_at) VALUES(?,?,?,?,?,?)",
            (run_id, step_id, int(seq), type, jdumps(payload or {}), now_iso()),
        )
        return int(cur.lastrowid)


def list_events(run_id: int, after: int = 0, limit: int = 500) -> list[sqlite3.Row]:
    with get_conn() as conn:
        return list(conn.execute(
            "SELECT * FROM events WHERE run_id=? AND seq>? ORDER BY seq LIMIT ?",
            (run_id, after, limit),
        ))


# ---------------------------------------------------------------- tools

BUILTIN_TOOLS = [
    {"key": "web_search", "name": "网页检索", "description": "检索公开网页信息（演示模式返回样例数据）",
     "params": {"query": {"type": "string", "required": True}}, "sensitive": False},
    {"key": "sql_query", "name": "SQL 查询", "description": "查询内置样例数据库（只读）",
     "params": {"sql": {"type": "string", "required": True}}, "sensitive": False},
    {"key": "http_request", "name": "HTTP 请求", "description": "GET 请求白名单域名",
     "params": {"url": {"type": "string", "required": True}}, "sensitive": True},
    {"key": "summarize", "name": "文本摘要", "description": "对输入文本生成要点摘要",
     "params": {"text": {"type": "string", "required": True}}, "sensitive": False},
    {"key": "code_review", "name": "代码审查", "description": "多维代码审查（正确性/安全/性能/可维护性/风格），输入 PR URL 或 diff 文本",
     "params": {
         "diff": {"type": "string", "required": True, "description": "PR URL 或 diff 文本（传 sample 使用内置样例）"},
         "language": {"type": "string", "required": False, "description": "代码语言"},
         "focus": {"type": "array", "required": False, "description": "审查重点，如 [正确性, 安全]"},
     }, "sensitive": False},
    {"key": "approve", "name": "人工审批", "description": "暂停执行等待人工确认",
     "params": {"reason": {"type": "string", "required": True}}, "sensitive": True},
]


def seed_builtin_tools() -> None:
    with get_conn() as conn:
        for t in BUILTIN_TOOLS:
            conn.execute(
                """INSERT INTO tools(key, name, description, params_json, sensitive, is_builtin, created_at)
                   VALUES(?,?,?,?,?,1,?)
                   ON CONFLICT(key) DO UPDATE SET name=excluded.name, description=excluded.description""",
                (t["key"], t["name"], t["description"], jdumps(t["params"]), 1 if t["sensitive"] else 0, now_iso()),
            )


def list_tools() -> list[sqlite3.Row]:
    with get_conn() as conn:
        return list(conn.execute("SELECT * FROM tools ORDER BY is_builtin DESC, id"))


def get_tool_by_key(key: str) -> sqlite3.Row | None:
    with get_conn() as conn:
        return conn.execute("SELECT * FROM tools WHERE key=?", (key,)).fetchone()


def create_tool(key: str, name: str, description: str, params: dict[str, Any], sensitive: bool) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO tools(key, name, description, params_json, sensitive, is_builtin, created_at) VALUES(?,?,?,?,?,0,?)",
            (key, name, description, jdumps(params), 1 if sensitive else 0, now_iso()),
        )
        return int(cur.lastrowid)


def update_tool(key: str, name: str, description: str, params: dict[str, Any], sensitive: bool) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE tools SET name=?, description=?, params_json=?, sensitive=? WHERE key=?",
            (name, description, jdumps(params), 1 if sensitive else 0, key),
        )


def delete_tool(key: str) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM tools WHERE key=?", (key,))


# ---------------------------------------------------------------- approvals

def create_approval(run_id: int, step_id: int, action: str, reason: str) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO approvals(run_id, step_id, action, reason, created_at) VALUES(?,?,?,?,?)",
            (run_id, step_id, action, reason, now_iso()),
        )
        return int(cur.lastrowid)


def list_approvals(run_id: int) -> list[sqlite3.Row]:
    with get_conn() as conn:
        return list(conn.execute("SELECT * FROM approvals WHERE run_id=? ORDER BY id", (run_id,)))


# ---------------------------------------------------------------- settings

def get_setting(key: str, default: Any = None) -> Any:
    with get_conn() as conn:
        row = conn.execute("SELECT value_json FROM settings WHERE key=?", (key,)).fetchone()
        return jloads(row["value_json"], default) if row else default


def set_setting(key: str, value: Any) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO settings(key, value_json) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json",
            (key, jdumps(value)),
        )


def get_all_settings() -> dict[str, Any]:
    with get_conn() as conn:
        rows = conn.execute("SELECT key, value_json FROM settings").fetchall()
        return {r["key"]: jloads(r["value_json"]) for r in rows}
