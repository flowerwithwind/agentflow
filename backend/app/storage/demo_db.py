"""内置演示数据库（A4）：只读 SQLite 样例库。

- 首次启动自动建库并写入样例数据（订单 / 客户 / 产品）；
- 查询侧一律通过只读连接（mode=ro），杜绝写操作；
- 测试环境重定向 DATA_DIR 后自动在临时目录重建。
"""
from __future__ import annotations

import sqlite3

from app.config import DEMO_DB_PATH

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS orders (
  id INTEGER PRIMARY KEY,
  customer TEXT NOT NULL,
  amount REAL NOT NULL,
  status TEXT NOT NULL,
  date TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS customers (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  region TEXT NOT NULL,
  joined_date TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS products (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  category TEXT NOT NULL,
  price REAL NOT NULL,
  stock INTEGER NOT NULL
);
"""

SEED_ORDERS = [
    {"id": 1001, "customer": "华东商贸", "amount": 12800.0, "status": "paid", "date": "2026-07-01"},
    {"id": 1002, "customer": "华南实业", "amount": 8600.0, "status": "pending", "date": "2026-07-05"},
    {"id": 1003, "customer": "华北集团", "amount": 23400.0, "status": "paid", "date": "2026-07-12"},
    {"id": 1004, "customer": "西部电商", "amount": 5200.0, "status": "refunded", "date": "2026-07-18"},
    {"id": 1005, "customer": "中部零售", "amount": 15750.0, "status": "paid", "date": "2026-07-24"},
    {"id": 1006, "customer": "华东商贸", "amount": 9800.0, "status": "paid", "date": "2026-07-28"},
]

SEED_CUSTOMERS = [
    {"id": 1, "name": "华东商贸", "region": "华东", "joined_date": "2024-03-12"},
    {"id": 2, "name": "华南实业", "region": "华南", "joined_date": "2024-06-01"},
    {"id": 3, "name": "华北集团", "region": "华北", "joined_date": "2025-01-20"},
    {"id": 4, "name": "西部电商", "region": "西南", "joined_date": "2025-04-15"},
]

SEED_PRODUCTS = [
    {"id": 1, "name": "智能音箱", "category": "智能硬件", "price": 399.0, "stock": 120},
    {"id": 2, "name": "无线耳机", "category": "智能硬件", "price": 299.0, "stock": 80},
    {"id": 3, "name": "云主机", "category": "云服务", "price": 88.0, "stock": 500},
    {"id": 4, "name": "对象存储", "category": "云服务", "price": 0.12, "stock": 100000},
    {"id": 5, "name": "企业版 OCR", "category": "AI 服务", "price": 1999.0, "stock": 30},
]


def ensure_demo_db() -> None:
    """演示库不存在时创建并写入样例数据（幂等，已存在则跳过）。"""
    if DEMO_DB_PATH.exists():
        return
    DEMO_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DEMO_DB_PATH)
    try:
        conn.executescript(SCHEMA_SQL)
        conn.executemany(
            "INSERT INTO orders(id, customer, amount, status, date) VALUES(:id,:customer,:amount,:status,:date)",
            SEED_ORDERS,
        )
        conn.executemany(
            "INSERT INTO customers(id, name, region, joined_date) VALUES(:id,:name,:region,:joined_date)",
            SEED_CUSTOMERS,
        )
        conn.executemany(
            "INSERT INTO products(id, name, category, price, stock) VALUES(:id,:name,:category,:price,:stock)",
            SEED_PRODUCTS,
        )
        conn.commit()
    finally:
        conn.close()


def connect_readonly() -> sqlite3.Connection:
    """打开演示库只读连接（mode=ro），行工厂为 sqlite3.Row。"""
    ensure_demo_db()
    uri = f"file:{DEMO_DB_PATH.as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=5)
    conn.row_factory = sqlite3.Row
    return conn
