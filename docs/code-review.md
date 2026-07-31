# AgentFlow 代码审查复盘（v1.0.0）

> 审查时间：2026-08-01 · 审查范围：backend/（FastAPI + SQLite）与 frontend/（Vue 3 + Vite）全部代码 · 结论：通过，可发布

## 1. 交付概览

| 里程碑 | 内容 | 验证 |
|---|---|---|
| A1 | 工程骨架：FastAPI + SQLite + DAO + 统一异常 + 设置/健康检查 | pytest 全绿 |
| A2 | 规划引擎：规则模板 + LLM 规划 JSON 校验降级 + DAG 环检测 | 16 用例 |
| A3 | 执行引擎：DAG 并行调度 / 重试退避 / 超时 / 审批挂起唤醒 / 重启恢复 / 事件流 | 12 用例 |
| A4 | 内置工具注册表 + 只读样例库 + http_request 白名单 + 敏感工具审批前置 | 28 用例 |
| A5 | SSE 事件流：增量 / 断线续传（Last-Event-ID）/ 并发 seq 加锁 + 唯一索引兜底 | runs 用例覆盖 |
| A6 | 报告汇总与导出：步骤索引 + 引用跳转 + GET /api/reports/{id} + .md 下载 | 5 用例 |
| A7 | code_review 内置工具：多维规则审查 + 内置样例 diff + PR URL 模式 | 5 用例 |
| A8 | 前端：Dashboard / 详情（DAG + SSE 实时流）/ 审批 / 工具 / 设置 / 报告 | 9 vitest + build |
| A9 | Docker Compose + Nginx 同源（SPA 回退 + SSE 反代）+ CI（仅测试）+ 截图 | 浏览器端到端冒烟 |

## 2. 测试统计（提交 40753db 时）

- 后端 pytest：**88 passed**（85 个测试函数 + 参数化展开），覆盖 planner 16 / executor 12 / runs 14 / tools 28 / reports 5 / code_review 5 / settings 4 / health 1
- 后端 ruff check：**All checks passed**
- 前端 vitest：**9 passed**（dag 5 + markdown 4）；生产构建通过，manualChunks 拆分后无 >500KB 警告（vue 92KB / echarts 436KB / marked 35KB / index 36KB，gzip 后主依赖均 <150KB）
- CI（GitHub Actions）：backend（pytest + ruff）+ frontend（vitest + build）双 Job

## 3. 关键设计审查

### 3.1 并发安全
- 步骤级事件写入使用全局锁串行化 seq 分配，events 表对 (run_id, seq) 建唯一索引兜底，杜绝并发撞号（A5 曾发现并修复）。
- 执行器工作线程池 + 共享状态读取走 DB 快照，取消通过 run.status 轮询 + threading.Event 唤醒，无共享可变内存竞态。

### 3.2 状态机一致性
- run：pending → planning → running → succeeded / failed / cancelled（A3 统一语义：规划后保持 pending，真正执行才 running）。
- 步骤：pending → running → succeeded / failed / skipped；依赖失败级联 skip；审批中 waiting_approval 不阻塞其他就绪步骤。

### 3.3 可靠性
- 步骤重试：指数退避（retry_base * 2^(attempt-1)），步级超时（默认 120s）。
- 重启恢复：启动时把遗留 processing/running 标记为 failed，不留僵尸状态。
- 审批超时轮询 + 取消守卫：审批期间任务被取消时步骤抛 CancelledError 干净退出。

### 3.4 安全边界
- http_request 白名单（默认仅内网/演示域名），SQL 工具只读（SELECT 白名单 + 行数上限 + 超时）。
- 敏感工具强制审批前置：未经审批不得执行；审批记录含决策人与理由。
- demo_mode 下无 LLM Key：规则规划器 + 模拟执行器，接口与真实模式完全一致（可平滑切换）。

### 3.5 前端
- EventSource 消费 SSE（默认 message 事件，后端不发送 event: 行；保留 id 供断线续传）。
- 路由级懒加载 + manualChunks 拆分，构建产物可控。
- 审批/取消操作有乐观反馈与错误态；演示模式横幅常驻提示。

## 4. 端到端验证记录（Docker Compose 全栈）

浏览器（Playwright + Chrome）走通：Dashboard → 新建任务（示例 2，含审批）→ 详情页实时事件流 14 条（开始规划×1 → 规划完成×1 → 开始执行×1 → 步骤开始×4 → 步骤成功×4 → 请求审批×1 → 审批完成×1 → 任务成功×1）→ API 审批 → succeeded → 报告页渲染 + .md 下载。
SSE 经 Nginx 反代（proxy_buffering off + X-Accel-Buffering no）实时到达前端。

## 5. 失败场景演练清单（A10 验收项）

| 场景 | 预期 | 覆盖 |
|---|---|---|
| LLM 规划返回非法 JSON | 自动降级规则规划器，任务仍可执行 | test_planner |
| LLM 规划超时/异常 | 降级 + 错误事件落库 | test_planner |
| 步骤执行失败 | 指数退避重试 → 最终 failed → 报告记录错误 | test_executor |
| 步骤超时 | 标记超时并按重试策略处理 | test_executor |
| 审批拒绝 | 步骤 failed，任务失败，理由入库 | test_runs |
| 审批中取消任务 | 步骤 CancelledError 干净退出 | test_runs |
| 排队/执行中取消 | 状态 cancelled，不再调度新步骤 | test_runs |
| 服务重启遗留 running | 启动扫描标记 failed | test_executor |
| 非法 SQL（写操作/无 WHERE 全表） | 拦截拒绝 | test_tools |
| 敏感工具未审批调用 | 拒绝执行 | test_tools |
| http_request 非白名单地址 | 拒绝 | test_tools |
| 并发事件写入 | seq 不撞号（锁 + 唯一索引兜底） | test_runs |
| SSE 断线续传 | 客户端带 Last-Event-ID 重连只收增量 | test_runs |
| 无 Key 全流程 | 规则规划 + 模拟执行，演示可跑通 | 冒烟验证 |
| 前端取消/审批后状态刷新 | 状态徽章与事件流一致 | vitest + 冒烟 |

## 6. 结论

功能与质量门禁全部达标（测试 88 + 9、ruff clean、build 通过、Docker 全栈冒烟通过）。遗留问题均不阻塞发布，见 docs/known-issues.md，按优先级排入后续版本。
