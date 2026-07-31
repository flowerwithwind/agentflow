// AgentFlow 前端 API 封装（A8）：统一 fetch + JSON + 错误提取
const BASE = '/api'

async function request(path, options = {}) {
  const init = { ...options, headers: { 'Content-Type': 'application/json', ...(options.headers || {}) } }
  if (init.body && typeof init.body !== 'string') init.body = JSON.stringify(init.body)
  const resp = await fetch(BASE + path, init)
  if (!resp.ok) {
    let detail = `HTTP ${resp.status}`
    try {
      const data = await resp.json()
      if (data.detail) detail = typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail)
    } catch { /* 非 JSON 错误体 */ }
    throw new Error(detail)
  }
  const ct = resp.headers.get('content-type') || ''
  return ct.includes('application/json') ? resp.json() : resp.text()
}

export const api = {
  health: () => request('/health'),
  // 任务
  listRuns: (params = {}) => {
    const qs = new URLSearchParams()
    for (const [k, v] of Object.entries(params)) {
      if (v !== undefined && v !== null && v !== '') qs.set(k, v)
    }
    return request(`/runs?${qs.toString()}`)
  },
  getRun: (id) => request(`/runs/${id}`),
  createRun: (body) => request('/runs', { method: 'POST', body }),
  cancelRun: (id) => request(`/runs/${id}/cancel`, { method: 'POST' }),
  deleteRun: (id) => request(`/runs/${id}`, { method: 'DELETE' }),
  approve: (stepId, action, reason) =>
    request(`/runs/steps/${stepId}/approve`, { method: 'POST', body: { action, reason } }),
  listEvents: (id, after = 0) => request(`/runs/${id}/events?after=${after}`),
  // 报告
  report: (id) => request(`/reports/${id}`),
  reportDownloadUrl: (id) => `${BASE}/reports/${id}/download`,
  // 工具注册表
  listTools: () => request('/tools'),
  createTool: (body) => request('/tools', { method: 'POST', body }),
  updateTool: (key, body) => request(`/tools/${key}`, { method: 'PUT', body }),
  deleteTool: (key) => request(`/tools/${key}`, { method: 'DELETE' }),
  // 设置
  settings: () => request('/settings'),
  saveSettings: (body) => request('/settings', { method: 'PUT', body }),
  clearData: () => request('/settings/clear-data', { method: 'POST' }),
}
