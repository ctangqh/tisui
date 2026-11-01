<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import type { PlaygroundGuideLines, PlaygroundNode, VisionImageMeta } from '@/types/playground'

const props = defineProps<{
  imageUrl: string
  imageMeta?: VisionImageMeta
  nodes: PlaygroundNode[]
  guideLines?: PlaygroundGuideLines
  selectedNodeId: string | null
  hoveredNodeId: string | null
  locateNodeId: string | null
}>()

const emit = defineEmits<{
  select: [id: string]
  open: [id: string]
  hover: [id: string | null]
  locateConsumed: []
}>()

const imageSize = ref({ width: 0, height: 0 })
const pulseNodeId = ref<string | null>(null)
const pulseTimer = ref<number | null>(null)
const boxRefs = ref<Record<string, HTMLElement | null>>({})

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
  if (!node.bbox) return {}

  return {
    left: `${(node.bbox.left / baseWidth.value) * 100}%`,
    top: `${(node.bbox.top / baseHeight.value) * 100}%`,
    width: `${(node.bbox.width / baseWidth.value) * 100}%`,
    height: `${(node.bbox.height / baseHeight.value) * 100}%`,
  }
}

const verticalGuideStyles = computed(() =>
  (props.guideLines?.vertical || []).map((value) => ({
    left: `${(value / baseWidth.value) * 100}%`,
  })),
)

const horizontalGuideStyles = computed(() =>
  (props.guideLines?.horizontal || []).map((value) => ({
    top: `${(value / baseHeight.value) * 100}%`,
  })),
)

function nodeClass(node: PlaygroundNode) {
  return {
    'stage__box--label': node.nodeRole === 'label',
    'stage__box--selected': node.id === props.selectedNodeId,
    'stage__box--hovered': node.id === props.hoveredNodeId,
    'stage__box--pulse': node.id === pulseNodeId.value,
  }
}

function registerBoxRef(nodeId: string, el: unknown) {
  const resolved = (el as { $el?: unknown } | null)?.$el ?? el
  boxRefs.value[nodeId] = (resolved as HTMLElement | null) ?? null
}

function clearPulse() {
  if (pulseTimer.value) {
    window.clearTimeout(pulseTimer.value)
    pulseTimer.value = null
  }
  pulseNodeId.value = null
}

async function runLocate(nodeId: string) {
  await nextTick()
  const target = boxRefs.value[nodeId]
  if (!target) return

  target.scrollIntoView({ behavior: 'smooth', block: 'center', inline: 'center' })
  pulseNodeId.value = nodeId
  if (pulseTimer.value) {
    window.clearTimeout(pulseTimer.value)
  }
  pulseTimer.value = window.setTimeout(() => {
    pulseNodeId.value = null
    pulseTimer.value = null
  }, 1200)
}

watch(
  () => props.locateNodeId,
  async (value) => {
    if (!value) return
    await runLocate(value)
    emit('locateConsumed')
  },
)

onBeforeUnmount(() => {
  clearPulse()
})
</script>

<template>
  <div v-if="!imageUrl" class="stage__empty">
    <p>先导入一张截图，再导入 `vision` JSON。</p>
  </div>

  <div v-else class="stage__canvas">
    <div class="stage__wrap">
      <img class="stage__image" :src="imageUrl" alt="识别截图" @load="onImageLoad">

        <div
          v-for="(style, index) in verticalGuideStyles"
          :key="`guide-v-${index}`"
          class="stage__guide stage__guide--vertical"
          :style="style"
        />
        <div
          v-for="(style, index) in horizontalGuideStyles"
          :key="`guide-h-${index}`"
          class="stage__guide stage__guide--horizontal"
          :style="style"
        />

      <button
        v-for="node in nodes"
        :key="node.id"
        class="stage__box"
        :class="nodeClass(node)"
        :style="boxStyle(node)"
        type="button"
        :ref="(el) => registerBoxRef(node.id, el)"
        @click="emit('select', node.id)"
        @dblclick="emit('open', node.id)"
        @mouseenter="emit('hover', node.id)"
        @mouseleave="emit('hover', null)"
      >
        <span class="stage__tag">{{ node.id }}</span>
      </button>
    </div>
  </div>
</template>

<style scoped>
.stage__empty {
  display: grid;
  place-items: center;
  padding: 24px 0;
  color: var(--muted);
  text-align: center;
  min-height: calc(100vh - 96px);
}

.stage__canvas {
  position: relative;
  display: grid;
  place-items: center;
  overflow: hidden;
  min-height: calc(100vh - 96px);
}

.stage__wrap {
  position: relative;
  display: inline-block;
  width: fit-content;
  max-width: 100%;
  max-height: calc(100vh - 96px);
}

.stage__image {
  display: block;
  width: auto;
  height: auto;
  max-width: 100%;
  max-height: calc(100vh - 96px);
}

.stage__guide {
  position: absolute;
  pointer-events: none;
  opacity: 0.75;
  z-index: 1;
}

.stage__guide--vertical {
  top: 0;
  bottom: 0;
  border-left: 1px dashed color-mix(in srgb, var(--text) 22%, transparent);
}

.stage__guide--horizontal {
  left: 0;
  right: 0;
  border-top: 1px dashed color-mix(in srgb, var(--text) 22%, transparent);
}

.stage__box {
  position: absolute;
  border: 2px solid color-mix(in srgb, var(--accent) 72%, transparent);
  border-radius: 0;
  background: color-mix(in srgb, var(--accent) 12%, transparent);
  cursor: pointer;
  transition: 0.16s ease;
  z-index: 2;
}

.stage__box--label {
  border-style: dashed;
  border-color: color-mix(in srgb, var(--accent-2) 70%, transparent);
  background: color-mix(in srgb, var(--accent-2) 10%, transparent);
}

.stage__box:hover,
.stage__box--hovered {
  box-shadow: 0 0 0 2px color-mix(in srgb, var(--accent) 18%, transparent);
}

.stage__box--selected {
  border-color: color-mix(in srgb, var(--highlight) 72%, transparent);
  background: color-mix(in srgb, var(--highlight) 14%, transparent);
}

.stage__box--pulse {
  animation: pulse-highlight 1.2s ease;
}

.stage__tag {
  position: absolute;
  left: 0;
  top: -26px;
  max-width: 240px;
  height: 24px;
  padding: 0 8px;
  border-radius: 0;
  border: 1px solid color-mix(in srgb, var(--border) 92%, transparent);
  background: color-mix(in srgb, var(--panel) 96%, transparent);
  color: var(--text);
  font-size: 11px;
  line-height: 22px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  box-sizing: border-box;
}

@keyframes pulse-highlight {
  0% {
    box-shadow: 0 0 0 0 color-mix(in srgb, var(--highlight) 35%, transparent);
  }
  50% {
    box-shadow: 0 0 0 6px color-mix(in srgb, var(--highlight) 25%, transparent);
  }
  100% {
    box-shadow: 0 0 0 0 color-mix(in srgb, var(--highlight) 0%, transparent);
  }
}
</style>
