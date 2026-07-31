"""pytest 全局夹具：临时数据目录 + 清库测试客户端。"""
from __future__ import annotations

import os
import tempfile

os.environ["AGENTFLOW_DATA_DIR"] = tempfile.mkdtemp(prefix="agentflow-test-")
os.environ["AGENTFLOW_API_KEY"] = ""
# 测试套件请求量大，关闭限流干扰
os.environ["AGENTFLOW_RATE_LIMIT"] = "1000000"

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.seed import ensure_seed_tools
from app.storage import db


@pytest.fixture(autouse=True)
def db_env():
    """每个测试独立初始化数据库（执行引擎测试不经过 HTTP 客户端也需要）。"""
    db.init_db()
    db.wipe_data()
    ensure_seed_tools()
    yield


@pytest.fixture()
def client(db_env):
    with TestClient(app) as c:
        db.wipe_data()
        ensure_seed_tools()
        yield c
