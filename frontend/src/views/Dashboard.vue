<script setup>
import { onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { api } from '../api'
import StatusBadge from '../components/StatusBadge.vue'
import DemoBanner from '../components/DemoBanner.vue'

const TERMINAL = ['succeeded', 'failed', 'cancelled']
const STATUS_OPTIONS = [
  { value: '', label: '全部状态' },
  { value: 'pending', label: '待执行' },
  { value: 'planning', label: '规划中' },
  { value: 'running', label: '执行中' },
  { value: 'waiting_approval', label: '待审批' },
  { value: 'succeeded', label: '成功' },
  { value: 'failed', label: '失败' },
  { value: 'cancelled', label: '已取消' },
]

const runs = ref([])
const total = ref(0)
const loading = ref(false)
const error = ref('')
const page = ref(1)
const pageSize = ref(10)
const status = ref('')
const query = ref('')
const demo = ref(false)
const notice = ref('')
const showCreate = ref(false)
const submitting = ref(false)

const examples = [
  {
    title: '竞品分析：AI 编程助手',
    text: '对比 Cursor、GitHub Copilot 与 AgentFlow 三类 AI 编程助手的功能差异、定价与社区口碑，输出结构化竞品分析报告。',
  },
  {
    title: '开发者沙龙活动策划（含审批）',
    text: '策划一场 30 人规模的 AI 应用开发者线下沙龙：拆解活动目标与受众、设计流程与物料、评估预算与风险，方案需经人工审批后输出完整策划案。',
  },
  {
    title: '线上 502 故障排查',
    text: '线上服务偶发 502 报错且高峰期明显：收集日志与网关特征、定位根因、验证数据并输出修复建议报告。',
  },
  {
    title: '订单数据核对',
    text: '核对本月订单报表与支付流水的一致性，输出差异清单、口径说明与修正建议。',
  },
]

const form = reactive({ title: '', input_text: '', parallel: 4, allow_sensitive: false })
let timer = null

async function load() {
  try {
    const data = await api.listRuns({ status: status.value, query: query.value, page: page.value, page_size: pageSize.value })
    runs.value = data.items
    total.value = data.total
    error.value = ''
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}

function applyExample(i) {
  form.title = examples[i].title
  form.input_text = examples[i].text
  form.parallel = 4
  form.allow_sensitive = false
}

async function createRun() {
  if (!form.title.trim() || !form.input_text.trim()) return
  submitting.value = true
  try {
    const run = await api.createRun({ ...form, title: form.title.trim(), input_text: form.input_text.trim() })
    showCreate.value = false
    form.title = ''
    form.input_text = ''
    flash('已创建任务 #' + run.id + '，后台开始规划执行')
    await load()
  } catch (e) {
    error.value = e.message
  } finally {
    submitting.value = false
  }
}

async function removeRun(run) {
  if (!window.confirm('确认删除任务 #' + run.id + '？该操作不可恢复。')) return
  try {
    await api.deleteRun(run.id)
    flash('已删除任务 #' + run.id)
    await load()
  } catch (e) {
    error.value = e.message
  }
}

function fmtDuration(ms) {
  if (ms == null) return '—'
  if (ms < 1000) return ms + 'ms'
  const s = ms / 1000
  if (s < 60) return s.toFixed(1) + 's'
  return Math.floor(s / 60) + 'm' + Math.round(s % 60) + 's'
}

function flash(msg) {
  notice.value = msg
  clearTimeout(flash._t)
  flash._t = setTimeout(() => (notice.value = ''), 3000)
}

function totalPages() {
  return Math.max(1, Math.ceil(total.value / pageSize.value))
}

function hasActive() {
  return runs.value.some((r) => !TERMINAL.includes(r.status))
}

onMounted(async () => {
  await load()
  try {
    const h = await api.health()
    demo.value = !!(h.capabilities && h.capabilities.demo_mode)
  } catch { /* 后端不可用时忽略 */ }
  timer = setInterval(async () => {
    if (document.hidden) return
    const before = hasActive()
    await load()
    // 有活跃任务才持续刷新；全部终态后停止轮询
    if (before && !hasActive()) flash('任务已全部结束')
  }, 5000)
})

onBeforeUnmount(() => { if (timer) clearInterval(timer) })
</script>

<template>
  <div class="page">
    <div class="page-head">
      <div>
        <h1 class="page-title">任务工作台</h1>
        <div class="page-sub">创建多智能体任务，查看规划 DAG、实时执行与汇总报告</div>
      </div>
      <div class="head-actions">
        <button class="btn" @click="load" :disabled="loading">⟳ 刷新</button>
        <button class="btn primary" @click="showCreate = true">＋ 新建任务</button>
      </div>
    </div>

    <DemoBanner :demo="demo" />

    <div v-if="notice" class="toast">{{ notice }}</div>
    <div v-if="error" class="error-box">{{ error }}</div>

    <div class="card filter-bar">
      <input class="input search" v-model="query" placeholder="搜索标题 / 任务内容…" @keyup.enter="page = 1; load()" />
      <select class="select status-select" v-model="status" @change="page = 1; load()">
        <option v-for="o in STATUS_OPTIONS" :key="o.value" :value="o.value">{{ o.label }}</option>
      </select>
      <span class="muted count">共 {{ total }} 条</span>
    </div>

    <div class="card">
      <div v-if="!runs.length && !loading" class="empty">暂无任务，点击「新建任务」或从示例一键加载开始</div>
      <table v-else class="table">
        <thead>
          <tr>
            <th>#</th><th>任务</th><th>状态</th><th>Token</th><th>耗时</th><th>创建时间</th><th class="col-ops">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="r in runs" :key="r.id" class="run-row">
            <td class="mono muted">{{ r.id }}</td>
            <td>
              <RouterLink :to="{ name: 'run-detail', params: { id: r.id } }" class="run-title">{{ r.title }}</RouterLink>
              <div class="muted run-desc">{{ (r.input_text || '').slice(0, 60) }}</div>
            </td>
            <td><StatusBadge :status="r.status" /></td>
            <td class="mono">{{ r.total_tokens || 0 }}</td>
            <td class="mono">{{ fmtDuration(r.total_duration_ms) }}</td>
            <td class="muted">{{ r.created_at.slice(5, 16) }}</td>
            <td class="col-ops">
              <RouterLink class="btn sm" :to="{ name: 'run-detail', params: { id: r.id } }">详情</RouterLink>
              <RouterLink v-if="r.status === 'succeeded'" class="btn sm success" :to="{ name: 'run-report', params: { id: r.id } }">报告</RouterLink>
              <button class="btn sm danger" @click="removeRun(r)">删除</button>
            </td>
          </tr>
        </tbody>
      </table>
      <div class="pager">
        <button class="btn sm" :disabled="page <= 1" @click="page--; load()">‹ 上一页</button>
        <span class="muted">{{ page }} / {{ totalPages() }}</span>
        <button class="btn sm" :disabled="page >= totalPages()" @click="page++; load()">下一页 ›</button>
      </div>
    </div>

    <div v-if="showCreate" class="modal-mask" @click.self="showCreate = false">
      <div class="modal">
        <h3 class="modal-title">新建任务</h3>
        <div class="label">示例任务（一键加载）</div>
        <div class="example-grid">
          <button v-for="(ex, i) in examples" :key="ex.title" class="btn example" @click="applyExample(i)">
            {{ ex.title }}
          </button>
        </div>
        <div class="label">任务标题</div>
        <input class="input" v-model="form.title" placeholder="例如：竞品分析：AI 编程助手" maxlength="64" />
        <div class="label">任务内容</div>
        <textarea class="textarea" v-model="form.input_text" placeholder="描述任务目标、范围与交付要求…" maxlength="4000"></textarea>
        <div class="form-row">
          <div class="field">
            <div class="label">并行度（1-16）</div>
            <input class="input" type="number" min="1" max="16" v-model.number="form.parallel" />
          </div>
          <div class="field">
            <div class="label">敏感工具</div>
            <label class="check"><input type="checkbox" v-model="form.allow_sensitive" /> 允许敏感工具（HTTP 请求等）</label>
          </div>
        </div>
        <div class="modal-actions">
          <button class="btn" @click="showCreate = false">取消</button>
          <button class="btn primary" @click="createRun" :disabled="submitting || !form.title.trim() || !form.input_text.trim()">
            {{ submitting ? '创建中…' : '创建并执行' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.head-actions { display: flex; gap: 8px; }
.filter-bar { display: flex; align-items: center; gap: 10px; margin-bottom: 12px; padding: 12px; }
.search { max-width: 340px; }
.status-select { width: 140px; flex: none; }
.count { flex: 1; text-align: right; }
.run-title { font-weight: 600; }
.run-desc { font-size: 11px; margin-top: 2px; max-width: 380px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.col-ops { white-space: nowrap; }
.col-ops .btn { margin-right: 6px; }
.pager { display: flex; align-items: center; justify-content: center; gap: 14px; padding-top: 14px; }
.example-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
.example { justify-content: flex-start; text-align: left; font-size: 12px; }
.form-row { display: flex; gap: 16px; }
.field { flex: 1; }
.check { display: flex; align-items: center; gap: 6px; font-size: 13px; cursor: pointer; padding-top: 8px; }
.toast {
  position: fixed; top: 20px; left: 50%; transform: translateX(-50%); z-index: 100;
  background: #12301c; color: var(--green); border: 1px solid var(--green); border-radius: 999px;
  padding: 8px 18px; font-size: 13px; box-shadow: 0 4px 18px rgba(0,0,0,.4);
}
@media (max-width: 700px) { .example-grid, .form-row { grid-template-columns: 1fr; flex-direction: column; } }
</style>
