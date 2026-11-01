<script setup lang="ts">
import { MousePointer2, Info, Sun, Moon } from 'lucide-vue-next'
import { useTheme } from '@/composables/useTheme'

type WorkbenchTab = 'detect' | 'info'

defineProps<{
  activeTab: WorkbenchTab
}>()

const emit = defineEmits<{
  tabChange: [tab: WorkbenchTab]
}>()

const { theme, toggleTheme, isDark } = useTheme()
</script>

<template>
  <nav class="rail">
    <button
      class="rail__btn"
      :class="{ 'rail__btn--active': activeTab === 'detect' }"
      type="button"
      @click="emit('tabChange', 'detect')"
    >
      <MousePointer2 :size="18" />
      <span>控件识别</span>
    </button>

    <button
      class="rail__btn"
      :class="{ 'rail__btn--active': activeTab === 'info' }"
      type="button"
      @click="emit('tabChange', 'info')"
    >
      <Info :size="18" />
      <span>控件信息</span>
    </button>

    <div class="rail__spacer" />

    <button class="rail__btn rail__btn--theme" type="button" @click="toggleTheme">
      <Moon v-if="!isDark" :size="18" />
      <Sun v-else :size="18" />
      <span>{{ theme === 'dark' ? 'Dark' : 'Light' }}</span>
    </button>
  </nav>
</template>

<style scoped>
.rail {
  height: 100%;
  display: grid;
  grid-template-rows: repeat(2, auto) 1fr auto;
  gap: 10px;
  padding: 14px 12px;
  border: 1px solid var(--border);
  border-radius: 22px;
  background: var(--panel);
}

.rail__btn {
  display: grid;
  justify-items: center;
  gap: 8px;
  padding: 12px 10px;
  border-radius: 18px;
  border: 1px solid transparent;
  background: transparent;
  color: var(--muted);
  cursor: pointer;
  transition: 0.18s ease;
}

.rail__btn span {
  font-size: 11px;
  line-height: 1.2;
  text-align: center;
}

.rail__btn:hover {
  background: var(--panel-soft);
  color: var(--text);
}

.rail__btn--active {
  background: color-mix(in srgb, var(--accent) 18%, transparent);
  border-color: color-mix(in srgb, var(--accent) 38%, transparent);
  color: var(--text);
}

.rail__btn--theme {
  background: var(--panel-soft);
  color: var(--text);
}

.rail__spacer {
  min-height: 0;
}
</style>

