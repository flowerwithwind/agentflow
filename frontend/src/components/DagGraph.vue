<script setup>
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts/core'
import { GraphChart } from 'echarts/charts'
import { TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { toEChartsGraph } from '../utils/dag'

echarts.use([GraphChart, TooltipComponent, CanvasRenderer])

const props = defineProps({ steps: { type: Array, default: () => [] } })
const el = ref(null)
let chart = null

function render() {
  if (!chart || !props.steps.length) return
  const { nodes, links } = toEChartsGraph(props.steps)
  chart.setOption({
    backgroundColor: 'transparent',
    tooltip: { trigger: 'item', formatter: (p) => `<b>${p.data.name}</b><br/>状态：${p.data.category}<br/>类型：${p.data.kind}` },
    series: [{
      type: 'graph',
      layout: 'none',
      data: nodes,
      links,
      roam: true,
      draggable: true,
      edgeSymbol: ['none', 'arrow'],
      edgeSymbolSize: 7,
      label: { color: '#e6edf3' },
      emphasis: { focus: 'adjacency', lineStyle: { width: 3 } },
    }],
  }, true)
}

onMounted(() => {
  chart = echarts.init(el.value)
  render()
  window.addEventListener('resize', resize)
})
function resize() { chart && chart.resize() }
watch(() => props.steps, render, { deep: true })
onBeforeUnmount(() => {
  window.removeEventListener('resize', resize)
  chart && chart.dispose()
})
</script>

<template>
  <div ref="el" class="dag-box"></div>
</template>

<style scoped>
.dag-box { width: 100%; height: 400px; }
</style>
