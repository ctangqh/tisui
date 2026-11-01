<script setup lang="ts">
import { computed } from 'vue'
import type { PlaygroundNode } from '@/types/playground'

const props = defineProps<{
  nodes: PlaygroundNode[]
  selectedNodeId: string | null
  hoveredNodeId: string | null
}>()

const emit = defineEmits<{
  select: [id: string]
  hover: [id: string | null]
}>()

const groupedNodes = computed(() => {
  const controls = props.nodes.filter((node) => node.nodeRole === 'control')
  const labels = props.nodes.filter((node) => node.nodeRole === 'label')
  return [
    { title: '控件', items: controls },
    { title: '标签', items: labels },
  ].filter((group) => group.items.length > 0)
})

function confidenceText(node: PlaygroundNode) {
  return node.confidence === undefined ? '-' : node.confidence.toFixed(2)
}

function typeText(node: PlaygroundNode) {
  return node.controlType || node.type || node.nodeRole
}
</script>

<template>
  <aside class="node-list">
    <div class="node-list__header">
      <h2>识别结果</h2>
      <span>{{ nodes.length }} 项</span>
    </div>

    <div v-if="nodes.length === 0" class="node-list__empty">
      导入 `vision` JSON 后，这里会显示控件和标签列表。
    </div>

    <div v-else class="node-list__groups">
      <section v-for="group in groupedNodes" :key="group.title" class="node-list__group">
        <div class="node-list__group-header">
          <h3>{{ group.title }}</h3>
          <span>{{ group.items.length }}</span>
        </div>

        <button
          v-for="node in group.items"
          :key="node.id"
          class="node-list__item"
          :class="{
            'node-list__item--selected': node.id === selectedNodeId,
            'node-list__item--hovered': node.id === hoveredNodeId,
          }"
          type="button"
          @click="emit('select', node.id)"
          @mouseenter="emit('hover', node.id)"
          @mouseleave="emit('hover', null)"
        >
          <div class="node-list__item-top">
            <strong>{{ node.name || '未命名节点' }}</strong>
            <span>{{ confidenceText(node) }}</span>
          </div>
          <div class="node-list__item-meta">
            <span>{{ typeText(node) }}</span>
            <span>{{ node.id }}</span>
          </div>
        </button>
      </section>
    </div>
  </aside>
</template>

<style scoped>
.node-list {
  display: grid;
  grid-template-rows: auto 1fr;
  min-height: 0;
  padding: 18px;
  border: 1px solid var(--border);
  border-radius: 24px;
  background: var(--panel);
}

.node-list__header,
.node-list__group-header,
.node-list__item-top,
.node-list__item-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.node-list__header {
  margin-bottom: 16px;
}

.node-list__header h2,
.node-list__group-header h3 {
  margin: 0;
}

.node-list__header span,
.node-list__group-header span,
.node-list__item-meta,
.node-list__item-top span {
  color: var(--muted);
  font-size: 12px;
}

.node-list__groups {
  display: grid;
  gap: 16px;
  overflow: auto;
  padding-right: 6px;
}

.node-list__group {
  display: grid;
  gap: 10px;
}

.node-list__item {
  display: grid;
  gap: 8px;
  width: 100%;
  padding: 14px;
  border: 1px solid var(--border);
  border-radius: 18px;
  background: var(--panel-soft);
  color: var(--text);
  text-align: left;
  cursor: pointer;
  transition: 0.18s ease;
}

.node-list__item:hover,
.node-list__item--hovered {
  border-color: color-mix(in srgb, var(--accent) 38%, var(--border));
  transform: translateY(-1px);
}

.node-list__item--selected {
  border-color: color-mix(in srgb, var(--accent) 62%, var(--border));
  box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--accent) 18%, transparent);
}

.node-list__empty {
  display: grid;
  place-items: center;
  min-height: 220px;
  padding: 20px;
  border: 1px dashed var(--border);
  border-radius: 20px;
  color: var(--muted);
  text-align: center;
}
</style>
