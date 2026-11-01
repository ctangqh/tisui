<script setup lang="ts">
import { ImageUp, Search, SlidersHorizontal, Trash2, Wifi, WifiOff } from 'lucide-vue-next'

defineProps<{
  query: string
  minConfidence: number
  totalCount: number
  controlCount: number
  labelCount: number
  wsConnected: boolean
}>()

const emit = defineEmits<{
  'update:query': [value: string]
  'update:minConfidence': [value: number]
  imageImport: []
  visionImport: []
  toggleStream: []
  clear: []
}>()
</script>

<template>
  <section class="toolbar">
    <div class="toolbar__hero">
      <p class="toolbar__eyebrow">Vision Playground</p>
      <h1 class="toolbar__title">查看 UI 控件识别结果</h1>
      <p class="toolbar__desc">
        导入截图和 `vision` JSON，在同一页中查看控件框、标签列表和节点详情。
      </p>
    </div>

    <div class="toolbar__actions">
      <button class="toolbar__button toolbar__button--primary" type="button" @click="emit('imageImport')">
        <ImageUp :size="16" />
        <span>导入截图</span>
      </button>
      <button class="toolbar__button" type="button" @click="emit('visionImport')">
        <SlidersHorizontal :size="16" />
        <span>导入 Vision JSON</span>
      </button>
      <button class="toolbar__button" type="button" @click="emit('toggleStream')">
        <component :is="wsConnected ? WifiOff : Wifi" :size="16" />
        <span>{{ wsConnected ? '断开图片流' : '连接图片流' }}</span>
      </button>
      <button class="toolbar__button toolbar__button--ghost" type="button" @click="emit('clear')">
        <Trash2 :size="16" />
        <span>清空</span>
      </button>
    </div>

    <div class="toolbar__filters">
      <label class="toolbar__search">
        <Search :size="16" />
        <input
          :value="query"
          type="search"
          placeholder="搜索文本、类型或节点 ID"
          @input="emit('update:query', ($event.target as HTMLInputElement).value)"
        >
      </label>

      <label class="toolbar__range">
        <span>最低置信度</span>
        <input
          :value="minConfidence"
          type="range"
          min="0"
          max="1"
          step="0.05"
          @input="emit('update:minConfidence', Number(($event.target as HTMLInputElement).value))"
        >
        <strong>{{ minConfidence.toFixed(2) }}</strong>
      </label>
    </div>

    <div class="toolbar__stats">
      <div class="toolbar__stat">
        <span>可见节点</span>
        <strong>{{ totalCount }}</strong>
      </div>
      <div class="toolbar__stat">
        <span>控件</span>
        <strong>{{ controlCount }}</strong>
      </div>
      <div class="toolbar__stat">
        <span>标签</span>
        <strong>{{ labelCount }}</strong>
      </div>
      <div class="toolbar__stat">
        <span>图片流</span>
        <strong>{{ wsConnected ? '已连接' : '未连接' }}</strong>
      </div>
    </div>
  </section>
</template>

<style scoped>
.toolbar {
  display: grid;
  gap: 16px;
  padding: 24px;
  border: 1px solid var(--border);
  border-radius: 28px;
  background:
    radial-gradient(circle at top left, color-mix(in srgb, var(--accent) 18%, transparent), transparent 32%),
    var(--panel);
  box-shadow: var(--shadow);
}

.toolbar__hero {
  display: grid;
  gap: 6px;
}

.toolbar__eyebrow {
  margin: 0;
  font-size: 12px;
  letter-spacing: 0.16em;
  text-transform: uppercase;
  color: color-mix(in srgb, var(--accent) 70%, var(--text));
}

.toolbar__title {
  margin: 0;
  font-size: 28px;
  line-height: 1.15;
  color: var(--text);
}

.toolbar__desc {
  margin: 0;
  max-width: 680px;
  color: var(--muted);
}

.toolbar__actions,
.toolbar__filters,
.toolbar__stats {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
}

.toolbar__button {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  min-height: 44px;
  padding: 0 16px;
  border: 1px solid var(--border);
  border-radius: 14px;
  background: var(--panel-soft);
  color: var(--text);
  cursor: pointer;
  transition: 0.2s ease;
}

.toolbar__button:hover {
  border-color: color-mix(in srgb, var(--accent) 44%, var(--border));
  transform: translateY(-1px);
}

.toolbar__button--primary {
  background: linear-gradient(135deg, color-mix(in srgb, var(--accent) 88%, white), color-mix(in srgb, var(--accent-2) 70%, white));
  color: color-mix(in srgb, var(--text) 15%, black);
  border-color: transparent;
}

.toolbar__button--ghost {
  color: var(--muted);
}

.toolbar__search,
.toolbar__range,
.toolbar__stat {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  min-height: 44px;
  padding: 0 14px;
  border: 1px solid var(--border);
  border-radius: 14px;
  background: var(--panel-soft);
  color: var(--text);
}

.toolbar__search {
  min-width: min(420px, 100%);
  flex: 1 1 320px;
}

.toolbar__search input {
  width: 100%;
  border: none;
  outline: none;
  background: transparent;
  color: inherit;
}

.toolbar__search input::placeholder {
  color: var(--muted);
}

.toolbar__range input {
  width: 160px;
}

.toolbar__stat {
  flex-direction: column;
  align-items: flex-start;
  min-width: 108px;
  padding: 12px 14px;
}

.toolbar__stat span {
  font-size: 12px;
  color: var(--muted);
}

.toolbar__stat strong {
  font-size: 20px;
  color: var(--text);
}

@media (max-width: 1024px) {
  .toolbar {
    padding: 20px;
  }

  .toolbar__title {
    font-size: 24px;
  }

  .toolbar__range {
    width: 100%;
    justify-content: space-between;
  }

  .toolbar__range input {
    flex: 1;
  }
}
</style>
