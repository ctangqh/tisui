import { createApp } from 'vue'
import { createPinia } from 'pinia'
import './style.css'
import App from './App.vue'
import router from './router'

// 自动移除 trae 悬浮小图标
function removeTraeBadge() {
  try {
    const badge = document.getElementById('trae-badge-plugin');
    if (badge) badge.remove();
    const style = document.getElementById('trae-badge-plugin-styles');
    if (style) style.remove();
  } catch (e) {
    console.warn('Failed to remove trae badge:', e);
  }
}

// 立即执行一次
removeTraeBadge();

// 监听 DOM 变化，防止它重新被添加
const observer = new MutationObserver(() => removeTraeBadge());
observer.observe(document.body, { childList: true, subtree: true });

// 创建 Vue 应用
const app = createApp(App)
const pinia = createPinia()

app.use(router)
app.use(pinia)
app.mount('#app')
