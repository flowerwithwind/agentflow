"""简易内存限流中间件（滑动窗口，按客户端 IP）。"""
from __future__ import annotations

import time
from collections import defaultdict, deque

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.config import RATE_LIMIT_PER_MINUTE


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, limit: int = RATE_LIMIT_PER_MINUTE):
        super().__init__(app)
        self.limit = limit
        self.windows: dict[str, deque[float]] = defaultdict(deque)

    async def dispatch(self, request: Request, call_next):
        if request.url.path.startswith("/api/"):
            ip = request.client.host if request.client else "unknown"
            now = time.monotonic()
            q = self.windows[ip]
            while q and now - q[0] > 60:
                q.popleft()
            if len(q) >= self.limit:
                return JSONResponse(
                    status_code=429,
                    content={"detail": "请求过于频繁，请稍后再试"},
                    headers={"Retry-After": "60"},
                )
            q.append(now)
        return await call_next(request)
