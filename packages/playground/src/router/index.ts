import { createRouter, createWebHistory } from 'vue-router'
import HomePage from '@/pages/HomePage.vue'
import DebugLocatorPage from '@/pages/DebugLocatorPage.vue'
import WorkbenchPage from '@/pages/WorkbenchPage.vue'

const routes = [
  {
    path: '/',
    name: 'home',
    component: WorkbenchPage,
  },
  {
    path: '/playground',
    name: 'playground',
    component: HomePage,
  },
  {
    path: '/debug/locator',
    name: 'debug-locator',
    component: DebugLocatorPage,
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

export default router
