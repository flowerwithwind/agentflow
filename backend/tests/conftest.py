"""pytest 全局夹具：临时数据目录 + 清库测试客户端。"""
from __future__ import annotations

import os
import tempfile

os.environ["AGENTFLOW_DATA_DIR"] = tempfile.mkdtemp(prefix="agentflow-test-")
os.environ["AGENTFLOW_API_KEY"] = ""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.seed import ensure_seed_tools
from app.storage import db


@pytest.fixture()
def client():
    with TestClient(app) as c:
        db.wipe_data()
        ensure_seed_tools()
        yield c
