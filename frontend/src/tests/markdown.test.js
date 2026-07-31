// Markdown 渲染测试（A8）：步骤标题锚点 + 引用链接改写
import { describe, expect, it } from 'vitest'
import { renderMarkdown } from '../utils/markdown'

describe('renderMarkdown', () => {
  it('步骤标题生成 #step-N 锚点', () => {
    const html = renderMarkdown('### 步骤 1. 竞品动态检索（调研员）')
    expect(html).toContain('<h3 id="step-1">步骤 1. 竞品动态检索（调研员）</h3>')
  })

  it('引用链接 #步骤-N 改写为页内锚点 #step-N', () => {
    const html = renderMarkdown('[步骤 1：竞品动态检索](#步骤-1)')
    expect(html).toContain('href="#step-1"')
    expect(html).toContain('class="citation"')
    expect(html).not.toContain('#步骤-')
  })

  it('外链添加新窗口属性', () => {
    const html = renderMarkdown('[官网](https://example.com)')
    expect(html).toContain('target="_blank"')
    expect(html).toContain('rel="noopener"')
  })

  it('空文本安全', () => {
    expect(renderMarkdown('')).toBe('')
    expect(renderMarkdown(undefined)).toBe('')
  })
})
