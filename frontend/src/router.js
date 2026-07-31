import { createRouter, createWebHistory } from 'vue-router'
import Dashboard from './views/Dashboard.vue'
import RunDetail from './views/RunDetail.vue'
import ReportView from './views/ReportView.vue'
import ToolsView from './views/ToolsView.vue'
import SettingsView from './views/SettingsView.vue'

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'dashboard', component: Dashboard },
    { path: '/runs/:id', name: 'run-detail', component: RunDetail, props: true },
    { path: '/runs/:id/report', name: 'run-report', component: ReportView, props: true },
    { path: '/tools', name: 'tools', component: ToolsView },
    { path: '/settings', name: 'settings', component: SettingsView },
  ],
})
