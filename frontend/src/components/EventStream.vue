<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'

const props = defineProps({
  runId: { type: [Number, String], required: true },
  terminal: { type: Boolean, default: false },
})
const events = ref([])
const connState = ref('connecting') // connecting / open / closed
const box = ref(null)

const EVENT_LABELS = {
  run_planning: '开始规划', run_planned: '规划完成', run_started: '开始执行',
  run_succeeded: '任务成功', run_failed: '任务失败', run_cancelled: '任务取消',
  step_started: '步骤开始', step_succeeded: '步骤成功', step_failed: '步骤失败',
  step_retry: '步骤重试', step_skipped: '步骤跳过', approval_requested: '请求审批',
  approval_resolved: '审批完成',
}

let es = null
function connect() {
  if (es) es.close()
  connState.value = 'connecting'
  es = new EventSource(`/api/runs/${props.runId}/events/stream`)
  es.onopen = () => { connState.value = 'open' }
  es.onmessage = (msg) => {
    try {
      const ev = JSON.parse(msg.data)
      events.value.push({
        seq: ev.seq,
        type: ev.type,
        label: EVENT_LABELS[ev.type] || ev.type,
        payload: ev.payload || {},
        created_at: ev.created_at,
      })
    } catch { /* 忽略非法事件 */ }
  }
  es.onerror = () => {
    // 任务终态后服务端关闭流 → 浏览器会重连；由父组件传入 terminal 后主动关闭
    if (!props.terminal) connState.value = 'connecting'
  }
}
function scrollBottom() {
  requestAnimationFrame(() => { if (box.value) box.value.scrollTop = box.value.scrollHeight })
}
watch(events, scrollBottom, { deep: true })
watch(() => props.terminal, (v) => {
  if (v) { connState.value = 'closed'; if (es) es.close() }
})
onMounted(() => connect())
onBeforeUnmount(() => { if (es) es.close() })

const summary = computed(() => {
  const m = {}
  for (const e of events.value) m[e.label] = (m[e.label] || 0) + 1
  return Object.entries(m).map(([k, v]) => `${k}×${v}`).join(' ')
})
</script>

<template>
  <div class="ev-card">
    <div class="ev-head">
      <span class="ev-title">实时事件流（SSE）</span>
      <span class="tag" :class="connState">{{ { connecting: '连接中…', open: '已连接', closed: '已结束' }[connState] }}</span>
      <span v-if="summary" class="muted ev-summary">{{ summary }}</span>
    </div>
    <div ref="box" class="ev-body">
      <div v-if="!events.length" class="empty">等待事件…</div>
      <div v-for="e in events" :key="e.seq" class="ev-row">
        <span class="ev-seq mono">#{{ e.seq }}</span>
        <span class="ev-type" :class="e.type">{{ e.label }}</span>
        <span v-if="e.payload.step_key" class="muted">{{ e.payload.step_key }}</span>
        <span v-if="e.payload.error" class="ev-err">{{ e.payload.error }}</span>
        <span v-if="e.payload.reason" class="muted">{{ e.payload.reason }}</span>
        <span class="muted ev-time">{{ e.created_at?.slice(11, 19) }}</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.ev-card { border: 1px solid var(--border); border-radius: 10px; background: var(--bg-panel); }
.ev-head { display: flex; align-items: center; gap: 10px; padding: 10px 14px; border-bottom: 1px solid var(--border); }
.ev-title { font-weight: 600; }
.ev-summary { font-size: 11px; }
.ev-body { max-height: 240px; overflow: auto; padding: 6px 14px; }
.ev-row { display: flex; align-items: center; gap: 8px; padding: 5px 0; font-size: 12px; border-bottom: 1px dashed #21262d; }
.ev-seq { color: var(--text-dim); }
.ev-type { font-weight: 600; color: var(--accent); }
.ev-type.run_succeeded { color: var(--green); }
.ev-type.run_failed { color: var(--red); }
.ev-type.approval_requested { color: var(--orange); }
.ev-err { color: var(--red); font-size: 11px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 320px; }
.ev-time { margin-left: auto; font-size: 11px; }
.tag.open { color: var(--green); border-color: var(--green); }
.tag.connecting { color: var(--yellow); }
.tag.closed { color: var(--text-dim); }
</style>
