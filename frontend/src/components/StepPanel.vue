<script setup>
import { ref } from 'vue'
import StatusBadge from './StatusBadge.vue'

defineProps({
  steps: { type: Array, default: () => [] },
  pending: { type: Boolean, default: false },
})
const emit = defineEmits(['approve'])
const expanded = ref(new Set())

function toggle(key) {
  if (expanded.value.has(key)) expanded.value.delete(key)
  else expanded.value.add(key)
  expanded.value = new Set(expanded.value)
}
function fmtDuration(ms) { return ms == null ? '—' : ms < 1000 ? `${ms}ms` : `${(ms / 1000).toFixed(1)}s` }
function fmtOutput(out) {
  if (!out) return ''
  const { _tokens, ...rest } = out
  try { return JSON.stringify(rest, null, 2) } catch { return String(out) }
}
function kindLabel(k) { return { llm: 'LLM', tool: '工具', approval: '审批', report: '报告' }[k] || k }
</script>

<template>
  <div class="step-list">
    <div v-if="!steps.length && pending" class="skeleton">规划中，等待步骤生成…</div>
    <div v-for="s in steps" :key="s.step_key" class="step-card" :class="s.status">
      <div class="step-head" @click="toggle(s.step_key)">
        <span class="step-seq">{{ s.seq }}</span>
        <div class="step-main">
          <div class="step-name">
            {{ s.name }}
            <span class="tag">{{ kindLabel(s.kind) }}</span>
            <span v-if="s.tool_key" class="tag">@{{ s.tool_key }}</span>
          </div>
          <div class="step-meta muted">
            {{ s.role }} · 依赖：{{ (s.depends_on || []).join(', ') || '无' }}
            <template v-if="s.duration_ms != null"> · {{ fmtDuration(s.duration_ms) }}</template>
            <template v-if="s.tokens_in || s.tokens_out"> · tokens {{ s.tokens_in }}/{{ s.tokens_out }}</template>
            <template v-if="s.attempts > 1"> · 尝试 {{ s.attempts }} 次</template>
          </div>
        </div>
        <StatusBadge :status="s.status" />
      </div>
      <div v-if="expanded.has(s.step_key)" class="step-body">
        <div v-if="s.prompt" class="step-section"><div class="sec-title">任务</div><div class="sec-text">{{ s.prompt }}</div></div>
        <div v-if="s.error" class="error-box">{{ s.error }}</div>
        <div v-if="s.output" class="step-section">
          <div class="sec-title">输出</div>
          <pre class="code-block">{{ fmtOutput(s.output) }}</pre>
        </div>
        <div v-if="s.status === 'waiting_approval'" class="approve-bar">
          <span class="muted">该步骤需要人工审批</span>
          <button class="btn success sm" @click.stop="emit('approve', s, 'approve')">通过</button>
          <button class="btn danger sm" @click.stop="emit('approve', s, 'reject')">拒绝</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.step-list { display: flex; flex-direction: column; gap: 8px; }
.step-card { border: 1px solid var(--border); border-radius: 8px; background: var(--bg-panel2); overflow: hidden; }
.step-head { display: flex; align-items: center; gap: 10px; padding: 9px 12px; cursor: pointer; }
.step-head:hover { background: #21262d; }
.step-seq { width: 22px; height: 22px; border-radius: 50%; background: #30363d; color: var(--text-dim); display: flex; align-items: center; justify-content: center; font-size: 11px; flex: none; }
.step-main { flex: 1; min-width: 0; }
.step-name { font-weight: 600; display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }
.step-meta { font-size: 11px; margin-top: 2px; }
.step-body { border-top: 1px solid var(--border); padding: 10px 12px; }
.step-section { margin-bottom: 8px; }
.sec-title { font-size: 11px; color: var(--text-dim); margin-bottom: 4px; }
.sec-text { font-size: 12px; white-space: pre-wrap; }
.code-block { background: #0d1117; border: 1px solid var(--border); border-radius: 6px; padding: 8px; overflow: auto; max-height: 260px; margin: 0; font-size: 11px; }
.approve-bar { display: flex; align-items: center; gap: 10px; margin-top: 8px; }
.step-card.succeeded { border-left: 3px solid var(--green); }
.step-card.failed { border-left: 3px solid var(--red); }
.step-card.waiting_approval { border-left: 3px solid var(--orange); }
.step-card.skipped { opacity: .65; }
</style>
