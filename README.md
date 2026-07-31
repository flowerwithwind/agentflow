# AgentFlow 多智能体任务编排工作台

把"一句话任务"变成"一组可追踪、可审批、可复盘的多智能体协作流水线"。
> 求职作品集主项目（AI 应用开发工程师）· 需求文档见 [docs/需求开发文档.md](docs/需求开发文档.md)

![CI](https://github.com/flowerwithwind/agentflow/actions/workflows/ci.yml/badge.svg)

## 核心能力

- **自然语言规划**：任务输入 → 规划器拆解为子任务 DAG（步骤、角色、依赖、工具）
- **多智能体执行**：规划 / 检索 / 分析 / 审核等角色化 Agent，步骤级重试、超时与并行调度
- **工具调用**：内置工具注册表（检索 / SQL / HTTP / 摘要）+ 可扩展注册，敏感工具需授权
- **人工审批闭环**：敏感节点进入待审批状态，浏览器一键通过 / 拒绝并记录理由
- **可观测复盘**：节点级流式事件、token 与耗时统计、结果溯源（引用），任务失败可回溯重跑
- **无 Key 可演示**：规则规划器 + 模拟执行器降级，内置示例任务，零配置完整体验流程

## 技术栈

Python · FastAPI · SQLite · Vue 3 · Vite · Element Plus · ECharts · Docker · GitHub Actions

## 里程碑

见 [docs/需求开发文档.md](docs/需求开发文档.md) §9：M1 骨架 → M2 编排引擎 → M3 审批与可观测 → M4 前端 → M5 演示与部署 → M6 质量门禁。
