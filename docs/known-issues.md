# AgentFlow 已知问题（Known Issues）

> 建档时间：2026-08-01（v1.0.0 发布）· 格式：KN-xx [P1/P2/P3] 描述 / 影响 / 处理

## P2（下版本优先）

- **KN-01 [P2] SSE 标签页休眠断线**：浏览器标签页进入后台/休眠时 EventSource 可能断线。服务端已支持 Last-Event-ID 增量续传，但前端未展示"重连中"状态。
  影响：演示时切标签页可能短暂丢事件（自动恢复）。处理：前端增加连接状态指示与手动重连按钮（已列 B 类优化）。
- **KN-02 [P2] clear-data 不可恢复**：设置页"清空任务数据"直接删除全部 runs/steps/events/approvals，无回收站。
  影响：误操作导致演示数据丢失。处理：增加二次确认 + 删除前自动备份 data/agentflow.db（建议 v1.1）。

## P3（低优先）

- **KN-03 [P3] 模拟执行器 token 恒为 0**：demo_mode 下执行器为模拟实现，token/耗时统计不真实（耗时真实）。
  影响：演示页面 Token 列显示 0，属预期降级行为。处理：无（配置真实 LLM Key 后即为真实统计）。
- **KN-04 [P3] http_request 默认白名单过窄**：默认仅放行 localhost/内网与演示域名，真实公网调用需自行修改配置。
  影响：开箱即用的工具调用受限（安全优先的设计取舍）。处理：文档说明 + 设置页可配置（建议）。
- **KN-05 [P3] ECharts 整包引入**：manualChunks 已把 echarts 拆为独立 chunk（gzip 147KB），但仍是全量引入。
  影响：首屏多加载约 147KB gzip。处理：按需引入 echarts/core + 图表组件（v1.1 优化）。
- **KN-06 [P3] SQLite 单写者**：任务库与样例库均为 SQLite，多实例/多进程部署会锁竞争。
  影响：单机演示/小并发无碍；高并发部署需换 PostgreSQL。处理：文档注明部署边界（不阻塞求职演示）。

## 已关闭（Close）

- ~~并发事件 seq 撞号~~：A5 以全局锁 + 唯一索引兜底修复（test_runs 覆盖）。
- ~~SSE 浏览器不显示事件~~：A8 移除 event: 行（EventSource.onmessage 兼容），实测 14 条事件实时显示。
- ~~vite build 在 node:20-alpine SIGTRAP~~：Dockerfile 改用 node:20-slim（musl 兼容问题）。
