<script setup>
import { onMounted, reactive, ref } from 'vue'
import { api } from '../api'

const tools = ref([])
const loading = ref(false)
const error = ref('')
const notice = ref('')
const showModal = ref(false)
const editing = ref(null)   // null=新建；对象=编辑中的自定义工具
const saving = ref(false)

const form = reactive({ key: '', name: '', description: '', params_text: '{}', sensitive: false })

async function load() {
  loading.value = true
  try {
    tools.value = await api.listTools()
    error.value = ''
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}

function openCreate() {
  editing.value = null
  form.key = ''
  form.name = ''
  form.description = ''
  form.params_text = '{}'
  form.sensitive = false
  showModal.value = true
}

function openEdit(tool) {
  editing.value = tool
  form.key = tool.key
  form.name = tool.name
  form.description = tool.description || ''
  form.params_text = JSON.stringify(tool.params || {}, null, 2)
  form.sensitive = !!tool.sensitive
  showModal.value = true
}

function parseParams() {
  let params = {}
  try {
    params = JSON.parse(form.params_text || '{}')
  } catch (e) {
    throw new Error('参数定义不是合法 JSON：' + e.message)
  }
  if (typeof params !== 'object' || params === null || Array.isArray(params)) {
    throw new Error('参数定义必须是 JSON 对象')
  }
  return params
}

async function save() {
  if (!/^[a-z][a-z0-9_]*$/.test(form.key)) {
    error.value = '工具 key 必须以小写字母开头，仅含小写字母 / 数字 / 下划线'
    return
  }
  if (!form.name.trim()) { error.value = '请填写工具名称'; return }
  let params
  try { params = parseParams() } catch (e) { error.value = e.message; return }
  saving.value = true
  try {
    const body = { key: form.key, name: form.name.trim(), description: form.description.trim(), params, sensitive: form.sensitive }
    if (editing.value) {
      await api.updateTool(editing.value.key, body)
      flash('已更新工具 @' + form.key)
    } else {
      await api.createTool(body)
      flash('已注册工具 @' + form.key)
    }
    showModal.value = false
    await load()
  } catch (e) {
    error.value = e.message
  } finally {
    saving.value = false
  }
}

async function removeTool(tool) {
  if (!window.confirm('确认删除自定义工具 @' + tool.key + '？')) return
  try {
    await api.deleteTool(tool.key)
    flash('已删除 @' + tool.key)
    await load()
  } catch (e) {
    error.value = e.message
  }
}

function paramsSummary(tool) {
  const keys = Object.keys(tool.params || {})
  if (!keys.length) return '无参数'
  return keys.map((k) => k + (tool.params[k] && tool.params[k].required ? '*' : '')).join(', ')
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
        <h1 class="page-title">工具管理</h1>
        <div class="page-sub">内置工具不可修改；注册自定义工具后即可在规划步骤中引用</div>
      </div>
      <button class="btn primary" @click="openCreate">＋ 注册自定义工具</button>
    </div>

    <div v-if="notice" class="toast">{{ notice }}</div>
    <div v-if="error" class="error-box">{{ error }}</div>

    <div class="card">
      <table class="table">
        <thead>
          <tr><th>Key</th><th>名称</th><th>说明</th><th>参数</th><th>类型</th><th>操作</th></tr>
        </thead>
        <tbody>
          <tr v-for="t in tools" :key="t.id">
            <td class="mono">@{{ t.key }}</td>
            <td class="tool-name">{{ t.name }}</td>
            <td class="muted tool-desc">{{ t.description }}</td>
            <td class="mono">{{ paramsSummary(t) }}</td>
            <td>
              <span class="tag" :class="t.sensitive ? 'tag-warn' : ''">{{ t.sensitive ? '敏感' : '普通' }}</span>
              <span v-if="t.is_builtin" class="tag">内置</span>
            </td>
            <td class="col-ops">
              <button v-if="!t.is_builtin" class="btn sm" @click="openEdit(t)">编辑</button>
              <button v-if="!t.is_builtin" class="btn sm danger" @click="removeTool(t)">删除</button>
              <span v-else class="muted small">—</span>
            </td>
          </tr>
        </tbody>
      </table>
      <div v-if="!tools.length && !loading" class="empty">暂无工具</div>
    </div>

    <div v-if="showModal" class="modal-mask" @click.self="showModal = false">
      <div class="modal">
        <h3 class="modal-title">{{ editing ? '编辑工具 @' + editing.key : '注册自定义工具' }}</h3>

        <div class="label">工具 Key（{{ editing ? '不可修改' : '小写字母开头，如 my_analyze' }}）</div>
        <input class="input" v-model="form.key" :disabled="!!editing" placeholder="my_analyze" />

        <div class="label">名称</div>
        <input class="input" v-model="form.name" placeholder="自定义分析" />

        <div class="label">说明</div>
        <input class="input" v-model="form.description" placeholder="工具用途描述" />

        <div class="label">参数定义（JSON Schema 风格，示例：{"text": {"type": "string", "required": true}}）</div>
        <textarea class="textarea code-input" v-model="form.params_text" rows="6" spellcheck="false"></textarea>

        <div class="label">敏感工具</div>
        <label class="check"><input type="checkbox" v-model="form.sensitive" /> 敏感工具调用前必须经过人工审批</label>

        <div class="modal-actions">
          <button class="btn" @click="showModal = false">取消</button>
          <button class="btn primary" @click="save" :disabled="saving">{{ saving ? '保存中…' : '保存' }}</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.tool-name { font-weight: 600; }
.tool-desc { font-size: 12px; max-width: 320px; }
.col-ops .btn { margin-right: 6px; }
.tag-warn { color: var(--orange); border-color: var(--orange); }
.small { font-size: 12px; }
.code-input { font-family: 'SFMono-Regular', Consolas, monospace; font-size: 12px; }
.check { display: flex; align-items: center; gap: 6px; font-size: 13px; cursor: pointer; }
.toast {
  position: fixed; top: 20px; left: 50%; transform: translateX(-50%); z-index: 100;
  background: #12301c; color: var(--green); border: 1px solid var(--green); border-radius: 999px;
  padding: 8px 18px; font-size: 13px; box-shadow: 0 4px 18px rgba(0,0,0,.4);
}
</style>
