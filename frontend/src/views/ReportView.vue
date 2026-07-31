<script setup>
import { computed, ref } from 'vue'
import { api } from '../api'
import { renderMarkdown } from '../utils/markdown'

const props = defineProps({ id: { type: [Number, String], required: true } })

const report = ref(null)
const error = ref('')
const loading = ref(true)

async function load() {
  loading.value = true
  try {
    report.value = await api.report(props.id)
    error.value = ''
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}

const html = computed(() => (report.value ? renderMarkdown(report.value.report) : ''))

function fmtDuration(ms) {
  if (ms == null) return '—'
  if (ms < 1000) return ms + 'ms'
  const s = ms / 1000
  if (s < 60) return s.toFixed(1) + 's'
  return Math.floor(s / 60) + 'm' + Math.round(s % 60) + 's'
}

load()
</script>

<template>
  <div class="page">
    <div class="crumb">
      <RouterLink :to="{ name: 'run-detail', params: { id } }">← 返回任务详情</RouterLink>
    </div>

    <div v-if="error" class="error-box">{{ error }}</div>
    <div v-else-if="!report" class="empty">{{ loading ? '加载中…' : '暂无报告' }}</div>

    <template v-else>
      <div class="page-head">
        <div>
          <h1 class="page-title">汇总报告 · {{ report.title }}</h1>
          <div class="page-sub">
            任务 #{{ report.run_id }} · 成功 · Token {{ report.total_tokens }} · 耗时 {{ fmtDuration(report.total_duration_ms) }}
          </div>
        </div>
        <div class="head-actions">
          <a class="btn primary" :href="api.reportDownloadUrl(report.run_id)">⬇ 下载 Markdown</a>
        </div>
      </div>

      <div class="card report-card">
        <!-- eslint-disable-next-line vue/no-v-html -->
        <div class="markdown-body" v-html="html"></div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.crumb { margin-bottom: 12px; font-size: 13px; }
.head-actions { display: flex; gap: 8px; }
.report-card { padding: 28px 32px; }
.markdown-body :deep(h1), .markdown-body :deep(h2), .markdown-body :deep(h3) { margin: 18px 0 10px; }
.markdown-body :deep(h3) { border-left: 3px solid var(--accent); padding-left: 10px; }
.markdown-body :deep(blockquote) { border-left: 3px solid var(--border); margin: 10px 0; padding: 4px 12px; color: var(--text-dim); }
.markdown-body :deep(a.citation) { color: var(--green); }
.markdown-body :deep(ul), .markdown-body :deep(ol) { padding-left: 22px; line-height: 1.8; }
.markdown-body :deep(p) { line-height: 1.8; }
.markdown-body :deep(hr) { border-color: var(--border); margin: 16px 0; }
</style>
