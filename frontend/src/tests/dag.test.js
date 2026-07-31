// DAG 工具纯函数测试（A8）
import { describe, expect, it } from 'vitest'
import { buildDag, layoutLevels, toEChartsGraph } from '../utils/dag'

const steps = [
  { step_key: 'a', name: '检索 A', role: '调研', kind: 'tool', status: 'succeeded', depends_on: [], seq: 1 },
  { step_key: 'b', name: '检索 B', role: '调研', kind: 'tool', status: 'succeeded', depends_on: [], seq: 2 },
  { step_key: 'c', name: '分析', role: '分析', kind: 'llm', status: 'running', depends_on: ['a', 'b'], seq: 3 },
  { step_key: 'd', name: '报告', role: '报告', kind: 'report', status: 'pending', depends_on: ['c'], seq: 4 },
]

describe('buildDag', () => {
  it('构建节点与去重边', () => {
    const { nodes, edges } = buildDag(steps)
    expect(nodes).toHaveLength(4)
    expect(nodes[0]).toMatchObject({ id: 'a', name: '检索 A', status: 'succeeded' })
    expect(edges).toEqual([
      { source: 'a', target: 'c' },
      { source: 'b', target: 'c' },
      { source: 'c', target: 'd' },
    ])
  })

  it('忽略不存在的依赖与重复边', () => {
    const { edges } = buildDag([
      { step_key: 'x', name: 'X', role: 'r', kind: 'llm', status: 'pending', depends_on: ['ghost', 'x'], seq: 1 },
      { step_key: 'y', name: 'Y', role: 'r', kind: 'llm', status: 'pending', depends_on: ['x', 'x'], seq: 2 },
    ])
    expect(edges).toEqual([{ source: 'x', target: 'y' }])
  })
})

describe('layoutLevels', () => {
  it('按依赖深度分层', () => {
    const level = layoutLevels(steps)
    expect(level.get('a')).toBe(0)
    expect(level.get('b')).toBe(0)
    expect(level.get('c')).toBe(1)
    expect(level.get('d')).toBe(2)
  })
})

describe('toEChartsGraph', () => {
  it('输出 ECharts 图数据（节点坐标 + 状态色）', () => {
    const g = toEChartsGraph(steps)
    expect(g.nodes).toHaveLength(4)
    expect(g.links).toHaveLength(3)
    const d = g.nodes.find((n) => n.id === 'd')
    expect(d.x).toBeGreaterThan(g.nodes.find((n) => n.id === 'a').x) // 层级越深 x 越大
    const a = g.nodes.find((n) => n.id === 'a')
    expect(a.itemStyle.color).toBe('#3fb950') // succeeded 绿
    const c = g.nodes.find((n) => n.id === 'c')
    expect(c.itemStyle.color).toBe('#58a6ff') // running 蓝
    expect(d.symbolSize).toBe(34) // report 节点更大
  })

  it('空步骤安全', () => {
    const g = toEChartsGraph([])
    expect(g.nodes).toEqual([])
    expect(g.links).toEqual([])
  })
})
