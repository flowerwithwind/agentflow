<script setup>
import { onMounted, reactive, ref } from 'vue'
import { api } from '../api'

const loading = ref(true)
const saving = ref(false)
const clearing = ref(false)
const error = ref('')
const notice = ref('')
const caps = ref(null)

const model = reactive({ model: '', base_url: '', api_key: '', temperature: 1.0, max_tokens: 4096 })
const exec = reactive({ parallel: 4, step_timeout_seconds: 120, max_attempts: 3, retry_base_seconds: 2 })
const API_KEY_SENTINEL = '***'

async function load() {
  loading.value = true
  try {
    const s = await api.settings()
    Object.assign(model, {
      model: s.model.model || '',
      base_url: s.model.base_url || '',
      api_key: s.model.api_key || '',
      temperature: s.model.temperature ?? 1.0,
      max_tokens: s.model.max_tokens ?? 4096,
    })
    Object.assign(exec, {
      parallel: s.execution.parallel ?? 4,
      step_timeout_seconds: s.execution.step_timeout_seconds ?? 120,
      max_attempts: s.execution.max_attempts ?? 3,
      retry_base_seconds: s.execution.retry_base_seconds ?? 2,
    })
    caps.value = s.capabilities
    error.value = ''
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}

async function save() {
  saving.value = true
  error.value = ''
  try {
    const body = {
      model: {
        model: model.model.trim(),
        base_url: model.base_url.trim(),
        api_key: model.api_key.trim(),
        temperature: Number(model.temperature),
        max_tokens: Number(model.max_tokens),
      },
      execution: {
        parallel: Number(exec.parallel),
        step_timeout_seconds: Number(exec.step_timeout_seconds),
        max_attempts: Number(exec.max_attempts),
        retry_base_seconds: Number(exec.retry_base_seconds),
      },
    }
    // 未修改的掩码 Key 交给后端保留原值
    if (body.model.api_key === API_KEY_SENTINEL) body.model.api_key = API_KEY_SENTINEL
    const s = await api.saveSettings(body)
    caps.value = s.capabilities
    flash('设置已保存')
    await load()
  } catch (e) {
    error.value = e.message
  } finally {
    saving.value = false
  }
}

async function clearData() {
  if (!window.confirm('确认清空全部任务数据？工具注册表与设置会保留，该操作不可恢复。')) return
  clearing.value = true
  try {
    const r = await api.clearData()
    flash('已清空 ' + r.count + ' 条任务数据')
  } catch (e) {
    error.value = e.message
  } finally {
    clearing.value = false
  }
}

function flash(msg) {
  notice.value = msg
  clearTimeout(flash._t)
  flash._t = setTimeout(() => (notice.value = ''), 3000)
}

onMounted(load)
</script>

<template>
  <div class="page">
    <div class="page-head">
      <div>
        <h1 class="page-title">设置</h1>
        <div class="page-sub">
          模型配置 · 执行参数 · 数据管理
          <span v-if="caps" class="caps-tag">
            <span class="dot" :class="caps.llm ? 'ok' : 'bad'"></span>
            {{ caps.demo_mode ? '演示模式（未配置 LLM）' : 'LLM 已就绪' }}
          </span>
        </div>
      </div>
    </div>

    <div v-if="notice" class="toast">{{ notice }}</div>
    <div v-if="error" class="error-box">{{ error }}</div>
    <div v-if="loading" class="empty">加载中…</div>

    <template v-else>
      <div class="card">
        <div class="card-title">模型配置</div>
        <div class="grid-2">
          <div>
            <div class="label">模型名称</div>
            <input class="input" v-model="model.model" placeholder="deepseek-chat" />
          </div>
          <div>
            <div class="label">Base URL（OpenAI 兼容）</div>
            <input class="input" v-model="model.base_url" placeholder="https://api.deepseek.com/v1" />
          </div>
        </div>
        <div class="grid-2">
          <div>
            <div class="label">API Key（已保存时显示 ***，留空则不修改）</div>
            <input class="input" v-model="model.api_key" type="password" placeholder="sk-…" autocomplete="off" />
          </div>
          <div class="grid-2 inner">
            <div>
              <div class="label">Temperature</div>
              <input class="input" type="number" step="0.1" min="0" max="2" v-model.number="model.temperature" />
            </div>
            <div>
              <div class="label">Max Tokens</div>
              <input class="input" type="number" min="1" max="128000" v-model.number="model.max_tokens" />
            </div>
          </div>
        </div>
      </div>

      <div class="card">
        <div class="card-title">执行参数</div>
        <div class="grid-2">
          <div>
            <div class="label">并行度（1-16）</div>
            <input class="input" type="number" min="1" max="16" v-model.number="exec.parallel" />
          </div>
          <div>
            <div class="label">步骤超时（秒）</div>
            <input class="input" type="number" min="5" max="3600" v-model.number="exec.step_timeout_seconds" />
          </div>
        </div>
        <div class="grid-2">
          <div>
            <div class="label">最大重试次数</div>
            <input class="input" type="number" min="0" max="10" v-model.number="exec.max_attempts" />
          </div>
          <div>
            <div class="label">重试退避基数（秒）</div>
            <input class="input" type="number" min="1" max="120" v-model.number="exec.retry_base_seconds" />
          </div>
        </div>
        <div class="save-row">
          <button class="btn primary" @click="save" :disabled="saving">{{ saving ? '保存中…' : '保存设置' }}</button>
        </div>
      </div>

      <div class="card danger-card">
        <div class="card-title">数据管理</div>
        <div class="danger-row">
          <div>
            <div class="danger-text">清空全部任务与步骤、事件、审批记录（保留工具注册表与模型/执行设置）。</div>
            <div class="muted small">用于演示前的数据重置。</div>
          </div>
          <button class="btn danger" @click="clearData" :disabled="clearing">{{ clearing ? '清空中…' : '清空任务数据' }}</button>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.card { margin-bottom: 14px; }
.card-title { font-weight: 600; margin-bottom: 6px; }
.grid-2.inner { gap: 12px; }
.caps-tag { display: inline-flex; align-items: center; gap: 6px; margin-left: 10px; font-size: 12px; color: var(--text-dim); }
.dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; }
.dot.ok { background: var(--green); }
.dot.bad { background: var(--yellow); }
.save-row { display: flex; justify-content: flex-end; margin-top: 16px; }
.danger-card { border-color: rgba(248, 81, 73, .4); }
.danger-row { display: flex; align-items: center; justify-content: space-between; gap: 16px; flex-wrap: wrap; }
.danger-text { font-size: 13px; }
.small { font-size: 12px; }
.toast {
  position: fixed; top: 20px; left: 50%; transform: translateX(-50%); z-index: 100;
  background: #12301c; color: var(--green); border: 1px solid var(--green); border-radius: 999px;
  padding: 8px 18px; font-size: 13px; box-shadow: 0 4px 18px rgba(0,0,0,.4);
}
</style>
