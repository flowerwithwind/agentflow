// DAG 工具（A8）：步骤依赖 → ECharts 图数据 + 分层布局
export function buildDag(steps = []) {
  const byKey = new Map(steps.map((s) => [s.step_key, s]))
  const nodes = steps.map((s) => ({
    id: s.step_key,
    name: s.name,
    role: s.role,
    kind: s.kind,
    status: s.status,
    seq: s.seq,
    tool: s.tool_key || null,
  }))
  const edges = []
  const seen = new Set()
  for (const s of steps) {
    for (const dep of s.depends_on || []) {
      if (!byKey.has(dep) || dep === s.step_key) continue // 忽略不存在依赖与自身环
      const key = dep + '->' + s.step_key
      if (seen.has(key)) continue
      seen.add(key)
      edges.push({ source: dep, target: s.step_key })
    }
  }
  return { nodes, edges }
}

export function layoutLevels(steps = []) {
  const byKey = new Map(steps.map((s) => [s.step_key, s]))
  const level = new Map()
  const compute = (key) => {
    if (level.has(key)) return level.get(key)
    const s = byKey.get(key)
    if (!s) return 0
    let lv = 0
    for (const d of s.depends_on || []) {
      if (byKey.has(d)) lv = Math.max(lv, compute(d) + 1)
    }
    level.set(key, lv)
    return lv
  }
  steps.forEach((s) => compute(s.step_key))
  return level
}

export const STATUS_COLORS = {
  pending: '#8b949e',
  planning: '#d29922',
  running: '#58a6ff',
  waiting_approval: '#f0883e',
  succeeded: '#3fb950',
  failed: '#f85149',
  skipped: '#6e7681',
}

export function toEChartsGraph(steps = []) {
  const { nodes, edges } = buildDag(steps)
  const level = layoutLevels(steps)
  // 分层坐标：x 按层级，y 按层内序号
  const perLevel = new Map()
  nodes.forEach((n) => {
    const lv = level.get(n.id) ?? 0
    if (!perLevel.has(lv)) perLevel.set(lv, [])
    perLevel.get(lv).push(n)
  })
  const levels = [...perLevel.keys()].sort((a, b) => a - b)
  const W = 720
  const H = 380
  nodes.forEach((n) => {
    const lv = level.get(n.id) ?? 0
    const list = perLevel.get(lv)
    const idx = list.indexOf(n)
    n.x = levels.length <= 1 ? W / 2 : 60 + (lv / (levels.length - 1)) * (W - 120)
    n.y = list.length <= 1 ? H / 2 : 50 + (idx / (list.length - 1)) * (H - 100)
  })
  return {
    nodes: nodes.map((n) => ({
      id: n.id,
      name: `${n.name}`,
      value: n.id,
      x: n.x,
      y: n.y,
      symbolSize: n.kind === 'report' ? 34 : n.kind === 'approval' ? 40 : 30,
      itemStyle: { color: STATUS_COLORS[n.status] || STATUS_COLORS.pending },
      label: { show: true, formatter: `${n.name}\n[${n.status}]`, fontSize: 11 },
      category: n.status || 'pending',
    })),
    links: edges.map((e) => ({ source: e.source, target: e.target, lineStyle: { color: '#6e7681', width: 1.5, curveness: 0.15 } })),
  }
}
