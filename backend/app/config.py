"""AgentFlow 全局配置：所有路径与默认值集中于此。"""
from __future__ import annotations

import os
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BACKEND_DIR.parent

# 数据目录（测试通过 AGENTFLOW_DATA_DIR 重定向）
DATA_DIR = Path(os.environ.get("AGENTFLOW_DATA_DIR", PROJECT_ROOT / "data"))
DB_PATH = DATA_DIR / "agentflow.db"

# 模型默认值（settings 表可覆盖；环境变量便于无 UI 配置）
DEFAULT_MODEL = os.environ.get("AGENTFLOW_MODEL", "deepseek-chat")
DEFAULT_BASE_URL = os.environ.get("AGENTFLOW_BASE_URL", "https://api.deepseek.com/v1")
DEFAULT_API_KEY = os.environ.get("AGENTFLOW_API_KEY", "")
DEFAULT_TEMPERATURE = 0.3
DEFAULT_MAX_TOKENS = 4096

# 执行引擎默认值
DEFAULT_PARALLEL = 4
DEFAULT_STEP_TIMEOUT_SECONDS = 120
DEFAULT_MAX_ATTEMPTS = 3

# 限流：默认 60 req/min/IP
RATE_LIMIT_PER_MINUTE = int(os.environ.get("AGENTFLOW_RATE_LIMIT", "60"))

# 任务文本限制
TASK_TEXT_MAX = 4000
TASK_TITLE_MAX = 64


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
