<script setup lang="ts">
import { computed, ref } from 'vue'
import type { PlaygroundNode, VisionImageMeta } from '@/types/playground'

const props = defineProps<{
  imageUrl: string
  imageMeta?: VisionImageMeta
  nodes: PlaygroundNode[]
  selectedNodeId: string | null
  hoveredNodeId: string | null
}>()

const emit = defineEmits<{
  select: [id: string]
  hover: [id: string | null]
}>()

const imageSize = ref({ width: 0, height: 0 })

const baseWidth = computed(() => props.imageMeta?.context_width || imageSize.value.width || 1)
const baseHeight = computed(() => props.imageMeta?.context_height || imageSize.value.height || 1)

function onImageLoad(event: Event) {
  const image = event.target as HTMLImageElement
  imageSize.value = {
    width: image.naturalWidth,
    height: image.naturalHeight,
  }
}

function boxStyle(node: PlaygroundNode) {
  if (!node.bbox) {
    return {}
  }

  return {
    left: `${(node.bbox.left / baseWidth.value) * 100}%`,
    top: `${(node.bbox.top / baseHeight.value) * 100}%`,
    width: `${(node.bbox.width / baseWidth.value) * 100}%`,
    height: `${(node.bbox.height / baseHeight.value) * 100}%`,
  }
}

function nodeClass(node: PlaygroundNode) {
  const style = (node.attributes as Record<string, unknown> | undefined)?.style as string | undefined
  return {
    'stage__box--label': node.nodeRole === 'label',
    'stage__box--selected': node.id === props.selectedNodeId,
    'stage__box--hovered': node.id === props.hoveredNodeId,
    'stage__box--candidate': style === 'candidate',
    'stage__box--primary': style === 'primary',
    'stage__box--fallback': style === 'fallback',
    'stage__box--cropwindow': style === 'crop_window',
  }
}
</script>

<template>
  <section class="stage">
    <div class="stage__header">
      <div>
        <h2>截图标注</h2>
        <p>在截图上查看识别框，点击任意框可以联动详情面板。</p>
      </div>
      <span>{{ nodes.length }} 个可见节点</span>
    </div>

    <div v-if="!imageUrl" class="stage__empty">
      <p>先导入一张截图，再导入 `vision` JSON。</p>
      <small>当前页面仅保留最小查看能力，不包含时间线和多来源对比。</small>
    </div>

    <div v-else class="stage__canvas">
      <div class="stage__wrap">
        <img class="stage__image" :src="imageUrl" alt="识别截图" @load="onImageLoad">

        <button
          v-for="node in nodes"
          :key="node.id"
          class="stage__box"
          :class="nodeClass(node)"
          :style="boxStyle(node)"
          type="button"
          @click="emit('select', node.id)"
          @mouseenter="emit('hover', node.id)"
          @mouseleave="emit('hover', null)"
        >
          <span class="stage__tag">{{ node.id }}</span>
        </button>
      </div>
    </div>
  </section>
</template>

<style scoped>
.stage {
  display: grid;
  grid-template-rows: auto 1fr;
  min-height: 0;
  gap: 16px;
  padding: 18px;
  border: 1px solid var(--border);
  border-radius: 24px;
  background: var(--panel);
}

.stage__header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.stage__header h2,
.stage__header p {
  margin: 0;
}

.stage__header p,
.stage__header span,
.stage__empty small {
  color: var(--muted);
}

.stage__empty {
  display: grid;
  place-items: center;
  gap: 10px;
  min-height: 420px;
  padding: 32px;
  border: 1px dashed var(--border);
  border-radius: 20px;
  color: var(--text);
  text-align: center;
}

.stage__empty p {
  margin: 0;
  font-size: 16px;
}

.stage__canvas {
  position: relative;
  display: grid;
  place-items: center;
  overflow: hidden;
  min-height: 0;
  padding: 16px;
  background: var(--panel-soft);
}

.stage__wrap {
  position: relative;
  display: inline-block;
  width: fit-content;
  max-width: 100%;
  max-height: 100%;
}

.stage__image {
  display: block;
  width: auto;
  height: auto;
  max-width: 100%;
  max-height: 100%;
}

.stage__box {
  position: absolute;
  border: 2px solid color-mix(in srgb, var(--accent) 70%, transparent);
  border-radius: 14px;
  background: color-mix(in srgb, var(--accent) 12%, transparent);
  cursor: pointer;
  transition: 0.16s ease;
}

.stage__box--label {
  border-style: dashed;
  border-color: color-mix(in srgb, var(--accent-2) 68%, transparent);
  background: color-mix(in srgb, var(--accent-2) 10%, transparent);
}

.stage__box:hover,
.stage__box--hovered {
  box-shadow: 0 0 0 2px rgba(151, 223, 255, 0.18);
}

.stage__box--selected {
  border-color: color-mix(in srgb, var(--highlight) 70%, transparent);
  background: color-mix(in srgb, var(--highlight) 12%, transparent);
}

.stage__box--candidate {
  border-color: #f59e0b;
  background: color-mix(in srgb, #f59e0b 10%, transparent);
}

.stage__box--primary {
  border-color: #10b981;
  background: color-mix(in srgb, #10b981 12%, transparent);
}

.stage__box--fallback {
  border-color: #ef4444;
  border-style: dashed;
  background: color-mix(in srgb, #ef4444 8%, transparent);
}

.stage__box--cropwindow {
  border-color: #eab308;
  border-style: dashed;
  background: transparent;
}

.stage__tag {
  position: absolute;
  left: 0;
  top: -30px;
  max-width: 220px;
  padding: 4px 8px;
  border-radius: 999px;
  background: color-mix(in srgb, var(--panel) 92%, transparent);
  color: var(--text);
  font-size: 12px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
</style>
