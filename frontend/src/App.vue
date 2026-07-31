<script setup>
import { onMounted, ref } from 'vue'
import { api } from './api'

const health = ref(null)
const nav = [
  { to: '/', label: '任务工作台', icon: '▦' },
  { to: '/tools', label: '工具管理', icon: '⚙' },
  { to: '/settings', label: '设置', icon: '⚑' },
]

onMounted(async () => {
  try {
    health.value = await api.health()
  } catch { /* 后端不可用时不阻塞页面 */ }
})
</script>

<template>
  <div class="app-shell">
    <aside class="sidebar">
      <div class="brand">
        <span class="brand-mark">AF</span>
        <div>
          <div class="brand-name">AgentFlow</div>
          <div class="brand-sub">多智能体任务编排</div>
        </div>
      </div>
      <nav class="nav">
        <RouterLink v-for="item in nav" :key="item.to" :to="item.to" class="nav-item" active-class="active">
          <span class="nav-icon">{{ item.icon }}</span>{{ item.label }}
        </RouterLink>
      </nav>
      <div class="side-foot">
        <div v-if="health" class="health-line">
          <span class="dot" :class="health.status === 'ok' ? 'ok' : 'bad'"></span>
          v{{ health.version }}
          <span v-if="health.capabilities?.demo_mode" class="demo-tag">演示模式</span>
        </div>
      </div>
    </aside>
    <main class="main">
      <RouterView />
    </main>
  </div>
</template>
