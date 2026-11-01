<script setup lang="ts">
import { computed, ref } from 'vue'
import type {
  PlaygroundBBox,
  PlaygroundNode,
  VisionImageMeta,
  PipelineLocateResult,
  PipelineLocateElement,
  StageDebugImage,
} from '@/types/playground'
import StageTimeline from '@/components/playground/StageTimeline.vue'

interface OriginalImageSizeInput {
  width: string
  height: string
}

const imageInputRef = ref<HTMLInputElement | null>(null)
const imageUrl = ref('')
const imageName = ref('')
const imageMeta = ref<VisionImageMeta>()
const imageNaturalSize = ref({ width: 0, height: 0 })
const fileBase64 = ref('')
const actionText = ref('')
const selectedNodeId = ref<string | null>(null)
const hoveredNodeId = ref<string | null>(null)
const loading = ref(false)
const errorMessage = ref('')
const noticeMessage = ref('')
const responsePayload = ref<PipelineLocateResult | null>(null)

// ---- Debug 阶段视图 ----
const debugStages = ref<StageDebugImage[]>([])
const activeStageIndex = ref(0)
const debugMode = ref(false)

const currentStage = computed<StageDebugImage | null>(() =>
  debugStages.value[activeStageIndex.value] ?? null
)

const displayImageUrl = computed(() => {
  const stage = currentStage.value
  if (debugMode.value && stage && stage.image_base64) {
    return stage.image_base64
  }
  return imageUrl.value
})

const displayImageMeta = computed<VisionImageMeta>(() => {
  const stage = currentStage.value
  if (debugMode.value && stage) {
    return {
      raw_width: stage.image_width,
      raw_height: stage.image_height,
      context_width: stage.image_width,
      context_height: stage.image_height,
      screenshot_shrink_factor: 1,
      raw_to_context_ratio: 1,
      context_to_logical_ratio: 1,
    }
  }
  return imageMeta.value ?? {
    raw_width: imageNaturalSize.value.width,
    raw_height: imageNaturalSize.value.height,
    context_width: imageNaturalSize.value.width,
    context_height: imageNaturalSize.value.height,
    screenshot_shrink_factor: 1,
    raw_to_context_ratio: 1,
    context_to_logical_ratio: 1,
  }
})

const overlayNodes = computed<PlaygroundNode[]>(() => {
  console.log('DEBUG: overlayNodes computed called', {
    debugMode: debugMode.value,
    currentStage: currentStage.value,
    finalOverlayNodes: finalOverlayNodes.value
  })
  if (debugMode.value) {
    const stage = currentStage.value
    console.log('DEBUG: overlayNodes in debugMode, stage:', stage)
    if (!stage) {
      console.log('DEBUG: overlayNodes in debugMode, no stage, return []')
      return []
    }
    console.log('DEBUG: overlayNodes stage.bboxes:', stage.bboxes)
    if (!stage.bboxes || stage.bboxes.length === 0) {
      console.log('DEBUG: overlayNodes in debugMode, no bboxes, return []')
      return []
    }
    const nodes = stage.bboxes.map((item, index) => {
      const [left, top, right, bottom] = item.bbox
      const bbox: PlaygroundBBox = {
        left, top, right, bottom,
        width: Math.max(0, right - left),
        height: Math.max(0, bottom - top),
      }
      return {
        id: `debug-${stage.stage}-${index}`,
        source: 'debug',
        nodeRole: 'control',
        name: item.label,
        text: item.label,
        confidence: item.confidence,
        bbox,
        attributes: { style: item.style },
      } as PlaygroundNode
    })
    console.log('DEBUG: overlayNodes returning debug nodes:', nodes)
    return nodes
  }
  console.log('DEBUG: overlayNodes returning finalOverlayNodes:', finalOverlayNodes.value)
  return finalOverlayNodes.value
})

const finalOverlayNodes = ref<PlaygroundNode[]>([])

// 阶段切换时: 等图片过渡动画结束后再绘制 bbox 框,
// 避免动画进行中框卡在入场态 (opacity:0) 而不显示。
const stageImageReady = ref(true)
const visibleOverlayNodes = computed<PlaygroundNode[]>(() => {
  // 直接返回，移除限制，优先保证 bbox 显示！
  return overlayNodes.value
})

const hasImage = computed(() => Boolean(imageUrl.value))

// Debug: 打印所有关键状态
console.log('DEBUG: DebugLocatorPage loaded')
console.log('DEBUG: overlayNodes', overlayNodes)
console.log('DEBUG: visibleOverlayNodes', visibleOverlayNodes)
console.log('DEBUG: finalOverlayNodes', finalOverlayNodes)
console.log('DEBUG: responsePayload', responsePayload)

function openImageImport() {
  imageInputRef.value?.click()
}

function clearAll() {
  imageUrl.value = ''
  imageName.value = ''
  imageMeta.value = undefined
  imageNaturalSize.value = { width: 0, height: 0 }
  fileBase64.value = ''
  actionText.value = ''
  selectedNodeId.value = null
  hoveredNodeId.value = null
  responsePayload.value = null
  finalOverlayNodes.value = []
  debugStages.value = []
  activeStageIndex.value = 0
  debugMode.value = false
  errorMessage.value = ''
  noticeMessage.value = ''
}

function resolveServerHttpBaseUrl(): string {
  console.log('DEBUG: resolveServerHttpBaseUrl location:', window.location)
  
  // 生产环境下（直接访问 server）：用相对路径
  // dev 模式下（vite）：用 http://127.0.0.1:8000
  const protocol = window.location.protocol
  const host = window.location.hostname
  const currentPort = window.location.port
  
  let baseUrl
  if (currentPort.startsWith('5')) { // vite dev server: 5173
    baseUrl = 'http://127.0.0.1:8000'
  } else { // prod: 当前地址就是 server
    baseUrl = `${protocol}//${host}${currentPort ? `:${currentPort}` : ''}`
  }
  
  console.log('DEBUG: resolveServerHttpBaseUrl returning:', baseUrl)
  return baseUrl
}

function toBBoxFromAbsolute(bbox: number[]): PlaygroundBBox | null {
  if (!Array.isArray(bbox) || bbox.length !== 4) return null
  const left = Number(bbox[0])
  const top = Number(bbox[1])
  const right = Number(bbox[2])
  const bottom = Number(bbox[3])
  if (![left, top, right, bottom].every((v) => Number.isFinite(v))) return null
  return {
    left, top, right, bottom,
    width: Math.max(0, right - left),
    height: Math.max(0, bottom - top),
  }
}

function buildFinalNodes(elements: PipelineLocateElement[]): PlaygroundNode[] {
  return elements
    .map((elem, index) => {
      const bbox = toBBoxFromAbsolute(elem.bbox)
      if (!bbox) return null
      return {
        id: `final-${index}`,
        source: 'debug',
        nodeRole: 'control',
        name: `${elem.type} ${elem.text || ''}`.trim() || `element-${index}`,
        text: elem.text,
        type: elem.type,
        confidence: elem.confidence,
        bbox,
        attributes: {
          style: elem.is_fallback ? 'fallback' : elem.source === 'fine' ? 'primary' : 'candidate',
          source: elem.source,
          fallback_reason: elem.fallback_reason,
          refine_type: elem.refine_type,
          action_point: elem.action_point,
        },
      } as PlaygroundNode
    })
    .filter((n): n is PlaygroundNode => n !== null)
}

async function readFileAsDataUrl(file: File): Promise<string> {
  return await new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result || ''))
    reader.onerror = () => reject(new Error('图片读取失败'))
    reader.readAsDataURL(file)
  })
}

async function readImageSize(file: File): Promise<{ width: number; height: number }> {
  const objectUrl = URL.createObjectURL(file)
  try {
    const image = await new Promise<HTMLImageElement>((resolve, reject) => {
      const nextImage = new Image()
      nextImage.onload = () => resolve(nextImage)
      nextImage.onerror = () => reject(new Error('图片尺寸读取失败'))
      nextImage.src = objectUrl
    })
    return { width: image.naturalWidth, height: image.naturalHeight }
  } finally {
    URL.revokeObjectURL(objectUrl)
  }
}

async function requestPipelineDebug() {
  if (!fileBase64.value) throw new Error('请先加载图片')
  if (!actionText.value.trim()) throw new Error('请输入 action_text')

  console.log('DEBUG: requestPipelineDebug starting')
  console.log('DEBUG: actionText:', actionText.value.trim())

  try {
    // 直接用相对路径，这样 dev 和 prod 都能用！
    const response = await fetch('/locator/pipeline-debug', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        image: fileBase64.value,
        action_text: actionText.value.trim(),
      }),
    })

    console.log('DEBUG: response status:', response.status, response.statusText)
    console.log('DEBUG: response ok:', response.ok)

    const text = await response.text()
    console.log('DEBUG: response raw text:', text)

    let payload
    try {
      payload = JSON.parse(text)
      console.log('DEBUG: response parsed payload:', payload)
    } catch (e) {
      console.error('DEBUG: JSON parse error:', e)
      throw new Error('无法解析返回的 JSON')
    }

    if (!response.ok) {
      const detail = payload && 'detail' in payload && typeof payload.detail === 'string'
        ? payload.detail
        : `调用 /locator/pipeline-debug 失败 (status: ${response.status})`
      throw new Error(detail)
    }

    return payload as PipelineLocateResult
  } catch (error) {
    console.error('DEBUG: requestPipelineDebug error:', error)
    throw error
  }
}

async function handleImageChange(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return

  try {
    loading.value = true
    errorMessage.value = ''
    noticeMessage.value = ''

    const [dataUrl, naturalSize] = await Promise.all([
      readFileAsDataUrl(file),
      readImageSize(file),
    ])

    imageUrl.value = dataUrl
    imageName.value = file.name
    fileBase64.value = dataUrl
    imageNaturalSize.value = naturalSize
    imageMeta.value = {
      raw_width: naturalSize.width,
      raw_height: naturalSize.height,
      context_width: naturalSize.width,
      context_height: naturalSize.height,
      screenshot_shrink_factor: 1,
      raw_to_context_ratio: 1,
      context_to_logical_ratio: 1,
    }

    noticeMessage.value = `已加载图片 ${file.name} (${naturalSize.width}x${naturalSize.height})，请输入 action_text 后点击定位。`
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '加载图片失败'
  } finally {
    loading.value = false
    input.value = ''
  }
}

async function handleLocate() {
  if (!fileBase64.value) {
    errorMessage.value = '请先加载图片'
    return
  }
  if (!actionText.value.trim()) {
    errorMessage.value = '请输入 action_text'
    return
  }

  try {
    loading.value = true
    errorMessage.value = ''
    noticeMessage.value = ''

    const payload = await requestPipelineDebug()
    responsePayload.value = payload

    // 最终结果
    finalOverlayNodes.value = buildFinalNodes(payload.elements)

    // Debug 阶段
    if (payload.debug_stages && payload.debug_stages.length) {
      debugStages.value = payload.debug_stages
      activeStageIndex.value = 0
      debugMode.value = true
    } else {
      debugMode.value = false
    }

    selectedNodeId.value = finalOverlayNodes.value[0]?.id || null
    noticeMessage.value = `定位完成: status=${payload.status}, elements=${payload.elements.length}, total=${payload.total_duration_ms.toFixed(0)}ms`
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '定位请求失败'
    responsePayload.value = null
    finalOverlayNodes.value = []
    debugMode.value = false
  } finally {
    loading.value = false
  }
}

function selectStage(index: number) {
  if (index >= 0 && index < debugStages.value.length) {
    activeStageIndex.value = index
    selectedNodeId.value = null
  }
}

function exitDebugView() {
  debugMode.value = false
  activeStageIndex.value = 0
  selectedNodeId.value = finalOverlayNodes.value[0]?.id || null
}

function boxStyle(node: PlaygroundNode) {
  const meta = displayImageMeta.value
  if (!node.bbox || !meta) return {}
  const w = meta.context_width || 1
  const h = meta.context_height || 1
  return {
    left: `${(node.bbox.left / w) * 100}%`,
    top: `${(node.bbox.top / h) * 100}%`,
    width: `${(node.bbox.width / w) * 100}%`,
    height: `${(node.bbox.height / h) * 100}%`,
  }
}

function nodeClass(node: PlaygroundNode) {
  const style = (node.attributes as Record<string, unknown> | undefined)?.style as string | undefined
  return {
    'locator-debug__box--selected': node.id === selectedNodeId.value,
    'locator-debug__box--hovered': node.id === hoveredNodeId.value,
    'locator-debug__box--candidate': style === 'candidate',
    'locator-debug__box--primary': style === 'primary',
    'locator-debug__box--fallback': style === 'fallback',
    'locator-debug__box--cropwindow': style === 'crop_window',
  }
}
</script>

<template>
  <div class="locator-debug">
    <input
      ref="imageInputRef"
      class="locator-debug__hidden-input"
      type="file"
      accept="image/*"
      @change="handleImageChange"
    >

    <section class="locator-debug__stage-panel">

         <div v-if="!hasImage" class="locator-debug__empty">
        <p>先在右侧点击"加载图片"，输入 action_text，再点击"三阶段定位"。</p>
      </div>

      <div v-else class="locator-debug__stage-body">
        <!-- 时间线 -->
        <StageTimeline
          v-if="debugMode && debugStages.length"
          :stages="debugStages"
          :active-index="activeStageIndex"
          @select="selectStage"
        />

        <!-- 阶段信息 -->
        <div v-if="debugMode && currentStage" class="locator-debug__stage-info">
          <span><strong>{{ currentStage.stage }}</strong></span>
          <span>zoom: {{ currentStage.zoom_scale.toFixed(2) }}x</span>
          <span v-if="currentStage.crop_on_raw">
            crop: [{{ currentStage.crop_on_raw.join(', ') }}]
          </span>
          <span v-if="currentStage.decisions.length">
            {{ currentStage.decisions.join(' | ') }}
          </span>
          <button type="button" class="locator-debug__exit-btn" @click="exitDebugView">
            ✕ 退出阶段视图
          </button>
        </div>

        <!-- 图片 + bbox 叠加 -->
        <div class="locator-debug__stage-wrap">
          <Transition
            name="stage-image"
            mode="out-in"
            @before-leave="stageImageReady = false"
            @after-enter="stageImageReady = true"
            @enter-cancelled="stageImageReady = true"
          >
            <img
              :key="activeStageIndex"
              class="locator-debug__image"
              :src="displayImageUrl"
              alt="Locator Debug Image"
              @load="stageImageReady = true"
            >
          </Transition>

          <!-- 调试：不用 TransitonGroup，直接渲染 -->
          <div v-if="true">
            <button
              v-for="node in visibleOverlayNodes"
              :key="node.id"
              class="locator-debug__box"
              :class="nodeClass(node)"
              :style="boxStyle(node)"
              type="button"
              @click="selectedNodeId = node.id"
              @mouseenter="hoveredNodeId = node.id"
              @mouseleave="hoveredNodeId = null"
            >
              <span class="locator-debug__tag">{{ node.name }}</span>
            </button>
          </div>

          <!-- 原始代码 -->
          <TransitionGroup name="stage-box" v-else>
            <button
              v-for="node in visibleOverlayNodes"
              :key="node.id"
              class="locator-debug__box"
              :class="nodeClass(node)"
              :style="boxStyle(node)"
              type="button"
              @click="selectedNodeId = node.id"
              @mouseenter="hoveredNodeId = node.id"
              @mouseleave="hoveredNodeId = null"
            >
              <span class="locator-debug__tag">{{ node.name }}</span>
            </button>
          </TransitionGroup>
        </div>
      </div>
    </section>

    <aside class="locator-debug__panel">
      <header class="locator-debug__panel-header">
        <h1 class="locator-debug__title">Pipeline Debug</h1>
        <p class="locator-debug__subtitle">三阶段定位管道调试</p>
      </header>

      <div class="locator-debug__actions">
        <button type="button" class="locator-debug__button" :disabled="loading" @click="openImageImport">
          {{ loading ? '加载中' : '加载图片' }}
        </button>
        <button type="button" class="locator-debug__button locator-debug__button--ghost" @click="clearAll">
          清空
        </button>
      </div>

      <div class="locator-debug__group">
        <span class="locator-debug__group-title">Action Text</span>
        <label class="locator-debug__field">
          <input
            v-model="actionText"
            type="text"
            placeholder="例如：搜索 pymidscene"
            @keyup.enter="handleLocate"
          >
        </label>
      </div>

      <div class="locator-debug__actions">
        <button
          type="button"
          class="locator-debug__button locator-debug__button--primary"
          :disabled="loading || !hasImage"
          @click="handleLocate"
        >
          {{ loading ? '定位中...' : '三阶段定位' }}
        </button>
      </div>

      <div class="locator-debug__group">
        <span class="locator-debug__group-title">当前信息</span>
        <div class="locator-debug__meta">
          <p><strong>图片：</strong>{{ imageName || '-' }} ({{ imageNaturalSize.width || 0 }}x{{ imageNaturalSize.height || 0 }})</p>
          <p><strong>模式：</strong>{{ debugMode ? `阶段视图 (${currentStage?.stage || ''})` : '最终结果' }}</p>
          <p><strong>渲染数量：</strong>{{ overlayNodes.length }}</p>
          <p v-if="responsePayload"><strong>状态：</strong>{{ responsePayload.status }} | {{ responsePayload.total_duration_ms.toFixed(0) }}ms</p>
        </div>
      </div>

      <p v-if="errorMessage" class="locator-debug__message locator-debug__message--error">
        {{ errorMessage }}
      </p>
      <p v-else-if="noticeMessage" class="locator-debug__message locator-debug__message--notice">
        {{ noticeMessage }}
      </p>

      <div class="locator-debug__group locator-debug__group--result">
        <span class="locator-debug__group-title">返回结果</span>
        <pre class="locator-debug__json">{{ responsePayload ? JSON.stringify(responsePayload, null, 2) : '暂无返回结果' }}</pre>
      </div>
    </aside>
  </div>
</template>

<style scoped>
.locator-debug {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 340px;
  gap: 18px;
  height: 100vh;
  min-height: 100vh;
  overflow: hidden;
}

.locator-debug__hidden-input {
  display: none;
}

.locator-debug__stage-panel {
  position: relative;
  display: grid;
  align-items: flex-start;
  min-height: 0;
  overflow: hidden auto;
  padding: 12px;
  border: 1px solid color-mix(in srgb, var(--accent) 22%, var(--border));
  background: color-mix(in srgb, var(--panel-soft) 86%, #0f172a 14%);
}

.locator-debug__empty {
  display: grid;
  place-items: center;
  min-height: 100%;
  color: var(--muted);
  text-align: center;
}

.locator-debug__stage-body {
  display: grid;
  gap: 10px;
  width: 100%;
}

.locator-debug__stage-info {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 12px;
  padding: 6px 12px;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: var(--panel);
  font-size: 12px;
}

.locator-debug__exit-btn {
  margin-left: auto;
  padding: 2px 10px;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: var(--panel-soft);
  color: var(--muted);
  font-size: 11px;
  cursor: pointer;
}

.locator-debug__stage-wrap {
  position: relative;
  display: inline-block;
  width: fit-content;
  max-width: 100%;
  justify-self: center;
}

.locator-debug__image {
  display: block;
  width: auto;
  height: auto;
  max-width: 100%;
  max-height: calc(100vh - 180px);
}

.locator-debug__box {
  position: absolute;
  border: 1px solid color-mix(in srgb, var(--accent) 82%, transparent);
  background: transparent;
  cursor: pointer;
  z-index: 2;
}

.locator-debug__box--selected {
  border-color: color-mix(in srgb, var(--highlight) 82%, transparent);
}

.locator-debug__box--hovered {
  box-shadow: 0 0 0 1px color-mix(in srgb, var(--accent) 20%, transparent);
}

.locator-debug__box--candidate {
  border-color: #f59e0b;
  background: color-mix(in srgb, #f59e0b 8%, transparent);
}

.locator-debug__box--primary {
  border-color: #10b981;
  background: color-mix(in srgb, #10b981 10%, transparent);
}

.locator-debug__box--fallback {
  border-color: #ef4444;
  border-style: dashed;
  background: color-mix(in srgb, #ef4444 6%, transparent);
}

.locator-debug__box--cropwindow {
  border-color: #eab308;
  border-style: dashed;
  background: transparent;
}

.locator-debug__tag {
  position: absolute;
  left: 0;
  top: -22px;
  max-width: 220px;
  padding: 0 6px;
  border: 1px solid var(--border);
  background: color-mix(in srgb, var(--panel) 94%, transparent);
  color: var(--text);
  font-size: 10px;
  line-height: 18px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.locator-debug__panel {
  display: grid;
  grid-template-rows: auto auto auto auto auto auto 1fr;
  gap: 14px;
  height: 100vh;
  padding: 18px;
  padding-right: 22px;
  border: 1px solid var(--border);
  background: var(--panel);
  overflow: hidden;
  box-sizing: border-box;
  min-width: 0;
}

.locator-debug__panel-header {
  display: grid;
  gap: 6px;
}

.locator-debug__title {
  margin: 0;
  font-size: 20px;
  line-height: 1.2;
}

.locator-debug__subtitle {
  margin: 0;
  color: var(--muted);
  font-size: 12px;
}

.locator-debug__actions {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
}

.locator-debug__button {
  min-height: 38px;
  border: 1px solid var(--border);
  background: var(--panel-soft);
  color: var(--text);
  cursor: pointer;
}

.locator-debug__button:disabled {
  opacity: 0.6;
  cursor: wait;
}

.locator-debug__button--primary {
  border-color: var(--accent);
  background: color-mix(in srgb, var(--accent) 18%, var(--panel));
}

.locator-debug__button--ghost {
  color: var(--muted);
}

.locator-debug__group {
  display: grid;
  gap: 10px;
}

.locator-debug__group--result {
  min-height: 0;
  grid-template-rows: auto minmax(0, 1fr);
}

.locator-debug__group-title {
  font-size: 12px;
  font-weight: 600;
}

.locator-debug__field {
  display: grid;
  gap: 6px;
}

.locator-debug__field input {
  min-height: 34px;
  padding: 0 10px;
  border: 1px solid var(--border);
  background: var(--panel-soft);
  color: var(--text);
}

.locator-debug__meta {
  display: grid;
  gap: 6px;
  font-size: 12px;
}

.locator-debug__meta p {
  margin: 0;
}

.locator-debug__message {
  margin: 0;
  padding: 10px 12px;
  font-size: 12px;
}

.locator-debug__message--error {
  border: 1px solid color-mix(in srgb, var(--danger) 30%, var(--border));
  background: var(--danger-bg);
  color: var(--danger);
}

.locator-debug__message--notice {
  border: 1px solid color-mix(in srgb, var(--accent) 24%, var(--border));
  background: color-mix(in srgb, var(--accent) 10%, var(--panel));
  color: var(--text);
}

.locator-debug__json {
  margin: 0;
  min-height: 0;
  height: 100%;
  max-height: 100%;
  overflow: auto;
  padding: 12px;
  border: 1px solid var(--border);
  background: color-mix(in srgb, var(--panel-soft) 88%, transparent);
  color: var(--text);
  font-size: 11px;
  line-height: 1.55;
  white-space: pre-wrap;
  word-break: break-word;
}

/* ---- 阶段切换过渡动画 ---- */

/* 图片: 淡入淡出 */
.stage-image-enter-active,
.stage-image-leave-active {
  transition: opacity 0.3s ease;
}
.stage-image-enter-from,
.stage-image-leave-to {
  opacity: 0;
}

/* bbox: 缩放 + 淡入 */
.stage-box-enter-active {
  transition: opacity 0.35s ease, transform 0.35s ease;
}
.stage-box-leave-active {
  transition: opacity 0.2s ease, transform 0.2s ease;
}
.stage-box-enter-from {
  transform: scale(0.85);
}
.stage-box-leave-to {
  opacity: 0;
  transform: scale(0.9);
}
.stage-box-move {
  transition: transform 0.3s ease;
}

/* 阶段信息条: 下滑淡入 */
.locator-debug__stage-info {
  animation: stage-info-in 0.35s ease;
}
@keyframes stage-info-in {
  from {
    opacity: 0;
    transform: translateY(-8px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

@media (max-width: 1100px) {
  .locator-debug {
    grid-template-columns: 1fr;
    height: auto;
    min-height: 100vh;
  }
  .locator-debug__panel {
    height: auto;
    min-height: 520px;
  }
}
</style>