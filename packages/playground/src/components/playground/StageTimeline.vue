<script setup lang="ts">
import type { StageDebugImage } from '@/types/playground'

defineProps<{
  stages: StageDebugImage[]
  activeIndex: number
}>()

const emit = defineEmits<{
  select: [index: number]
}>()

const STAGE_LABELS: Record<string, string> = {
  position_inference: '位置推断',
  coarse: '粗定位',
  fine: '精定位',
  compensate: '补偿',
}

function formatMs(ms: number): string {
  if (ms >= 1000) return `${(ms / 1000).toFixed(1)}s`
  return `${ms.toFixed(0)}ms`
}

function modelLabel(calls: number, name: string): string {
  if (calls === 0) return '0 calls'
  return `${calls} ${name || 'VLM'}`
}
</script>

<template>
  <div v-if="stages.length" class="timeline">
    <button
      v-for="(stage, index) in stages"
      :key="stage.stage"
      class="timeline__node"
      :class="{ 'timeline__node--active': index === activeIndex }"
      type="button"
      @click="emit('select', index)"
    >
      <span class="timeline__dot" />
      <span class="timeline__label">{{ STAGE_LABELS[stage.stage] || stage.stage }}</span>
      <span class="timeline__duration">{{ formatMs(stage.duration_ms) }}</span>
      <span class="timeline__calls">{{ modelLabel(stage.model_calls, '') }}</span>
    </button>
  </div>
</template>

<style scoped>
.timeline {
  display: flex;
  gap: 0;
  padding: 12px 16px;
  border: 1px solid var(--border);
  border-radius: 16px;
  background: var(--panel);
  overflow-x: auto;
}

.timeline__node {
  position: relative;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  flex: 1;
  min-width: 90px;
  padding: 10px 8px 8px;
  border: none;
  background: transparent;
  color: var(--muted);
  cursor: pointer;
  transition: color 0.16s;
}

.timeline__node::before {
  content: '';
  position: absolute;
  top: 22px;
  left: 0;
  right: 50%;
  height: 2px;
  background: var(--border);
}

.timeline__node::after {
  content: '';
  position: absolute;
  top: 22px;
  left: 50%;
  right: 0;
  height: 2px;
  background: var(--border);
}

.timeline__node:first-child::before {
  display: none;
}

.timeline__node:last-child::after {
  display: none;
}

.timeline__node--active {
  color: var(--text);
}

.timeline__node--active::before,
.timeline__node--active::after {
  background: var(--accent);
  transition: background 0.3s ease;
}

.timeline__dot {
  width: 12px;
  height: 12px;
  border-radius: 50%;
  border: 2px solid var(--border);
  background: var(--panel);
  z-index: 1;
  transition: border-color 0.3s ease, background 0.3s ease, transform 0.3s ease, box-shadow 0.3s ease;
}

.timeline__node--active .timeline__dot {
  border-color: var(--accent);
  background: var(--accent);
  transform: scale(1.25);
  box-shadow: 0 0 0 4px color-mix(in srgb, var(--accent) 20%, transparent);
  animation: dot-pulse 1.5s ease-in-out infinite;
}

@keyframes dot-pulse {
  0%, 100% { box-shadow: 0 0 0 4px color-mix(in srgb, var(--accent) 20%, transparent); }
  50%      { box-shadow: 0 0 0 8px color-mix(in srgb, var(--accent) 8%, transparent); }
}

.timeline__label {
  font-size: 12px;
  font-weight: 600;
  white-space: nowrap;
}

.timeline__duration {
  font-size: 11px;
  opacity: 0.7;
}

.timeline__calls {
  font-size: 10px;
  opacity: 0.5;
}
</style>