<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { api } from '../api'
import StatusBadge from '../components/StatusBadge.vue'
import DagGraph from '../components/DagGraph.vue'
import StepPanel from '../components/StepPanel.vue'
import EventStream from '../components/EventStream.vue'
import ApproveDialog from '../components/ApproveDialog.vue'

const props = defineProps({ id: { type: [Number, String], required: true } })

const TERMINAL = ['succeeded', 'failed', 'cancelled']
const run = ref(null)
const steps = ref([])
const settingsExec = ref(null)
const loading = ref(true)
const error = ref('')
const notice = ref('')
const approveStep = ref(null)
let timer = null

const terminal = computed(() => !!run.value && TERMINAL.includes(run.value.status))

async function load() {
  if (!run.value || !TERMINAL.includes(run.value.status)) loading.value = false
  try {
    const data = await api.getRun(props.id)
    run.value = data.run
    steps.value = data.steps
    error.value = ''
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}

async function loadSettings() {
  try {
    const s = await api.settings()
    settingsExec.value = s.execution
  } catch { /* 非关键 */ }
}

async function cancelRun() {
  if (!window.confirm('确认取消该任务？')) return
  try {
    await api.cancelRun(props.id)
    flash('已请求取消')
    await load()
  } catch (e) {
    error.value = e.message
  }
}

async function submitApprove(action, reason) {
  const step = approveStep.value
  if (!step) return
  try {
    await api.approve(step.id, action, reason)
    approveStep.value = null
    flash(action === 'approve' ? '已通过审批' : '已拒绝审批')
    await load()
  } catch (e) {
    error.value = e.message
    approveStep.value = null
  }
}

function flash(msg) {
  notice.value = msg
  clearTimeout(flash._t)
  flash._t = setTimeout(() => (notice.value = ''), 3000)
}

function fmtDuration(ms) {
  if (ms == null) return '—'
  if (ms < 1000) return ms + 'ms'
  const s = ms / 1000
  if (s < 60) return s.toFixed(1) + 's'
  return Math.floor(s / 60) + 'm' + Math.round(s % 60) + 's'
}

function fmtTime(iso) { return iso ? iso.slice(5, 16).replace('T', ' ') : '—' }

onMounted(async () => {
  await load()
  loadSettings()
  timer = setInterval(() => {
    if (!document.hidden && !terminal.value) load()
  }, 3000)
})
onBeforeUnmount(() => { if (timer) clearInterval(timer) })
</script>

<template>
  <div class="page">
    <div class="crumb">
      <RouterLink to="/">← 返回工作台</RouterLink>
    </div>

    <div v-if="error" class="error-box">{{ error }}</div>
    <div v-else-if="!run" class="empty">{{ loading ? '加载中…' : '任务不存在' }}</div>

    <template v-else>
      <div v-if="notice" class="toast">{{ notice }}</div>

      <div class="card status-bar">
        <div class="sb-main">
          <div class="sb-title">
            #{{ run.id }} {{ run.title }}
            <StatusBadge :status="run.status" />
          </div>
          <div class="muted sb-sub">创建于 {{ fmtTime(run.created_at) }}<template v-if="run.finished_at"> · 结束于 {{ fmtTime(run.finished_at) }}</template></div>
        </div>
        <div class="sb-stats">
          <div class="stat"><div class="stat-v mono">{{ fmtDuration(run.total_duration_ms) }}</div><div class="stat-k">总耗时</div></div>
          <div class="stat"><div class="stat-v mono">{{ run.total_tokens }}</div><div class="stat-k">Token</div></div>
          <div class="stat"><div class="stat-v mono">{{ settingsExec ? settingsExec.parallel : '—' }}</div><div class="stat-k">并行度</div></div>
        </div>
        <div class="sb-actions">
          <button v-if="!terminal" class="btn danger" @click="cancelRun">取消任务</button>
          <RouterLink v-if="run.status === 'succeeded'" class="btn success" :to="{ name: 'run-report', params: { id: run.id } }">查看报告</RouterLink>
          <a v-if="run.status === 'succeeded'" class="btn" :href="api.reportDownloadUrl(run.id)">下载 .md</a>
        </div>
      </div>

      <div v-if="run.error" class="error-box">{{ run.error }}</div>

      <div class="detail-grid">
        <div class="col-left">
          <div class="card">
            <div class="card-title">执行 DAG</div>
            <DagGraph :steps="steps" />
          </div>
          <EventStream :run-id="run.id" :terminal="terminal" />
        </div>
        <div class="col-right">
          <div class="card steps-card">
            <div class="card-title">步骤面板（{{ steps.length }}）</div>
            <StepPanel :steps="steps" :pending="run.status === 'planning'" @approve="approveStep = $event" />
          </div>
        </div>
      </div>

      <ApproveDialog :step="approveStep" @close="approveStep = null" @submit="submitApprove" />
    </template>
  </div>
</template>

<style scoped>
.crumb { margin-bottom: 12px; font-size: 13px; }
.status-bar { display: flex; align-items: center; gap: 18px; margin-bottom: 14px; flex-wrap: wrap; }
.sb-main { flex: 1; min-width: 240px; }
.sb-title { font-size: 17px; font-weight: 700; display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.sb-sub { font-size: 12px; margin-top: 4px; }
.sb-stats { display: flex; gap: 22px; }
.stat { text-align: center; }
.stat-v { font-size: 16px; font-weight: 700; }
.stat-k { font-size: 11px; color: var(--text-dim); margin-top: 2px; }
.sb-actions { display: flex; gap: 8px; }
.detail-grid { display: grid; grid-template-columns: 1.25fr 1fr; gap: 14px; align-items: start; }
.col-left, .col-right { display: flex; flex-direction: column; gap: 14px; min-width: 0; }
.card-title { font-weight: 600; margin-bottom: 10px; }
.steps-card { max-height: 720px; overflow: auto; }
.toast {
  position: fixed; top: 20px; left: 50%; transform: translateX(-50%); z-index: 100;
  background: #12301c; color: var(--green); border: 1px solid var(--green); border-radius: 999px;
  padding: 8px 18px; font-size: 13px; box-shadow: 0 4px 18px rgba(0,0,0,.4);
}
@media (max-width: 960px) { .detail-grid { grid-template-columns: 1fr; } }
</style>
