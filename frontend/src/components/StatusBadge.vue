<script setup>
import { computed } from 'vue'
const props = defineProps({ status: { type: String, default: 'pending' } })
const label = computed(() => ({
  pending: '待执行',
  planning: '规划中',
  running: '执行中',
  waiting_approval: '待审批',
  succeeded: '成功',
  failed: '失败',
  cancelled: '已取消',
  skipped: '已跳过',
}[props.status] || props.status))
</script>

<template>
  <span class="badge" :class="status">{{ label }}</span>
</template>
