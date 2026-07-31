// Markdown 渲染（A8）：步骤标题锚点 #step-N + 引用链接改写 + 新窗口外链
import { marked } from 'marked'

class AgentFlowRenderer extends marked.Renderer {
  // marked v12 回调签名：heading(text, level, raw) / link(href, title, text)
  heading(text, level) {
    const m = text.match(/^步骤\s*(\d+)[.．、]?/)
    const id = m ? ' id="step-' + m[1] + '"' : ''
    const tag = ['', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6'][level] || 'h3'
    return '<' + tag + id + '>' + text + '</' + tag + '>\n'
  }
  link(href, title, text) {
    const m = href.match(/^#步骤-(\d+)$/)
    const finalHref = m ? '#step-' + m[1] : href
    const attrs = href.startsWith('#') ? ' class="citation"' : ' target="_blank" rel="noopener"'
    return '<a href="' + finalHref + '"' + attrs + (title ? ' title="' + title + '"' : '') + '>' + text + '</a>'
  }
}

export function renderMarkdown(md) {
  return marked.parse(md || '', { renderer: new AgentFlowRenderer(), gfm: true, breaks: true })
}
