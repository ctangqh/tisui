<script setup lang="ts">
import { computed } from 'vue'
import { LocateFixed, Search, SlidersHorizontal } from 'lucide-vue-next'
import type { PlaygroundNode } from '@/types/playground'

const props = defineProps<{
  controls: PlaygroundNode[]
  selectedNodeId: string | null
  hoveredNodeId: string | null
  query: string
  minConfidence: number
}>()

const emit = defineEmits<{
  'update:query': [value: string]
  'update:minConfidence': [value: number]
  select: [id: string]
  hover: [id: string | null]
  locate: [id: string]
}>()

const filteredControls = computed(() => props.controls)
</script>

<template>
  <section class="panel">
    <div class="panel__filters">
      <label class="panel__search">
        <Search :size="16" />
        <input
          :value="query"
          type="search"
          placeholder="搜索控件"
          @input="emit('update:query', ($event.target as HTMLInputElement).value)"
        >
      </label>

      <label class="panel__range">
        <SlidersHorizontal :size="16" />
        <span>{{ minConfidence.toFixed(2) }}</span>
        <input
          :value="minConfidence"
          type="range"
          min="0"
          max="1"
          step="0.05"
          @input="emit('update:minConfidence', Number(($event.target as HTMLInputElement).value))"
        >
      </label>
    </div>

    <div class="panel__list">
      <div v-if="filteredControls.length === 0" class="panel__empty">
        上传截图后会自动调用 `core`。
        如果调用成功但没有识别到控件，这里会保持为空。
      </div>

      <button
        v-for="node in filteredControls"
        :key="node.id"
        class="panel__item"
        :class="{
          'panel__item--selected': node.id === selectedNodeId,
          'panel__item--hovered': node.id === hoveredNodeId,
        }"
        type="button"
        @click="emit('select', node.id)"
        @mouseenter="emit('hover', node.id)"
        @mouseleave="emit('hover', null)"
      >
        <div class="panel__item-main">
          <strong>{{ node.name || node.id }}</strong>
          <span>{{ node.confidence === undefined ? '-' : node.confidence.toFixed(2) }}</span>
        </div>
        <div class="panel__item-meta">
          <span>{{ node.controlType || node.type || 'control' }}</span>
          <span class="panel__id">{{ node.id }}</span>
        </div>
        <div class="panel__item-actions">
          <button
            class="panel__locate"
            type="button"
            @click.stop="emit('locate', node.id)"
          >
            <LocateFixed :size="16" />
            定位
          </button>
        </div>
      </button>
    </div>
  </section>
</template>

<style scoped>
.panel {
  display: grid;
  gap: 14px;
  min-height: 0;
}

.panel__filters {
  display: grid;
  gap: 10px;
}

.panel__search,
.panel__range {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  border-radius: 16px;
  border: 1px solid var(--border);
  background: var(--panel-soft);
  color: var(--muted);
}

.panel__search input {
  width: 100%;
  border: none;
  outline: none;
  background: transparent;
  color: var(--text);
}

.panel__search input::placeholder {
  color: var(--muted);
}

.panel__range span {
  width: 44px;
  text-align: right;
  color: var(--text);
  font-variant-numeric: tabular-nums;
}

.panel__range input {
  flex: 1;
}

.panel__list {
  display: grid;
  gap: 10px;
  overflow: auto;
  min-height: 0;
  padding-right: 4px;
}

.panel__empty {
  padding: 18px;
  border-radius: 18px;
  border: 1px dashed var(--border);
  color: var(--muted);
  text-align: center;
}

.panel__item {
  display: grid;
  gap: 8px;
  padding: 12px 12px 10px;
  border-radius: 18px;
  border: 1px solid var(--border);
  background: var(--panel-soft);
  color: var(--text);
  text-align: left;
  cursor: pointer;
  transition: 0.18s ease;
}

.panel__item:hover,
.panel__item--hovered {
  transform: translateY(-1px);
  border-color: color-mix(in srgb, var(--accent) 38%, var(--border));
}

.panel__item--selected {
  border-color: color-mix(in srgb, var(--accent) 62%, var(--border));
  box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--accent) 28%, transparent);
}

.panel__item-main,
.panel__item-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.panel__item-main span {
  color: var(--muted);
  font-size: 12px;
  font-variant-numeric: tabular-nums;
}

.panel__item-meta {
  color: var(--muted);
  font-size: 12px;
}

.panel__id {
  max-width: 120px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.panel__item-actions {
  display: flex;
  justify-content: flex-end;
}

.panel__locate {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  min-height: 36px;
  padding: 0 12px;
  border-radius: 999px;
  border: 1px solid color-mix(in srgb, var(--accent) 28%, var(--border));
  background: color-mix(in srgb, var(--accent) 14%, transparent);
  color: var(--text);
  cursor: pointer;
  transition: 0.18s ease;
}

.panel__locate:hover {
  background: color-mix(in srgb, var(--accent) 22%, transparent);
}
</style>
