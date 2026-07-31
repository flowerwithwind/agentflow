<script setup>
defineProps({ demo: { type: Boolean, default: false } })
</script>

<template>
  <div v-if="demo" class="banner">
    <span>🔬 演示模式：未配置 LLM API Key，使用规则规划器 + 模拟执行（接口与真实模式完全一致）。</span>
    <RouterLink to="/settings">去配置</RouterLink>
  </div>
</template>
