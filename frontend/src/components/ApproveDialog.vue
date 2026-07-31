<script setup>
import { computed, ref } from 'vue'

const props = defineProps({ step: { type: Object, default: null } })
const emit = defineEmits(['close', 'submit'])
const action = ref('approve')
const reason = ref('')

const title = computed(() => (props.step ? `审批：${props.step.name}` : '审批'))
const sensitive = computed(() => props.step?.tool_key === 'http_request')

function submit() {
  if (action.value === 'reject' && !reason.value.trim()) return
  emit('submit', action.value, reason.value.trim())
}
</script>

<template>
  <div v-if="step" class="modal-mask" @click.self="emit('close')">
    <div class="modal">
      <h3 class="modal-title">{{ title }}</h3>
      <div class="muted" style="font-size:12px">步骤 #{{ step.seq }} · {{ step.role }} · {{ step.kind }}</div>
      <div v-if="step.prompt" class="ctx">
        <div class="label">步骤上下文</div>
        <div class="ctx-text">{{ step.prompt }}</div>
      </div>
      <div v-if="sensitive" class="risk">
        ⚠️ 该步骤使用敏感工具（{{ step.tool_key }}），涉及外部请求，请确认风险后再通过。
      </div>
      <div class="label">审批动作</div>
      <div class="radio-row">
        <label><input type="radio" value="approve" v-model="action" /> 通过</label>
        <label><input type="radio" value="reject" v-model="action" /> 拒绝</label>
      </div>
      <div class="label">理由（拒绝时必填）</div>
      <textarea class="textarea" v-model="reason" placeholder="填写审批理由…" :rows="3"></textarea>
      <div class="modal-actions">
        <button class="btn" @click="emit('close')">取消</button>
        <button class="btn" :class="action === 'approve' ? 'success' : 'danger'" @click="submit" :disabled="action === 'reject' && !reason.trim()">
          {{ action === 'approve' ? '确认通过' : '确认拒绝' }}
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.ctx { margin: 10px 0; }
.ctx-text { background: var(--bg-panel2); border: 1px solid var(--border); border-radius: 8px; padding: 10px; font-size: 13px; white-space: pre-wrap; }
.risk { margin: 12px 0; background: #3d1f00; color: var(--orange); border: 1px solid #6b4e00; border-radius: 8px; padding: 10px 12px; font-size: 13px; }
.radio-row { display: flex; gap: 18px; }
.radio-row label { display: flex; align-items: center; gap: 6px; cursor: pointer; }
</style>
