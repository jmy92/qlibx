import { createRouter, createWebHistory } from 'vue-router'
import MainLayout from '../layouts/MainLayout.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      component: MainLayout,
      children: [
        { path: '', name: 'new-experiment', component: () => import('../views/NewExperiment.vue') },
        { path: 'running/:id', name: 'running', component: () => import('../views/RunningExperiment.vue') },
        { path: 'report/:id', name: 'report', component: () => import('../views/Report.vue') },
        { path: 'history', name: 'history', component: () => import('../views/History.vue') },
        { path: 'data', name: 'data-manage', component: () => import('../views/DataManage.vue') }
      ]
    }
  ]
})

export default router
