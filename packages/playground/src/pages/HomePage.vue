<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { storeToRefs } from 'pinia'
import PlaygroundDetailPanel from '@/components/playground/PlaygroundDetailPanel.vue'
import PlaygroundNodeList from '@/components/playground/PlaygroundNodeList.vue'
import PlaygroundStage from '@/components/playground/PlaygroundStage.vue'
import PlaygroundToolbar from '@/components/playground/PlaygroundToolbar.vue'
import { useVisionPlaygroundStore } from '@/stores/visionPlayground'
import type { PlaygroundWsMessage, VisionControlExportResult } from '@/types/playground'
import { parseVisionPayload } from '@/composables/usePlaygroundData'

const store = useVisionPlaygroundStore()

const {
  imageUrl,
  imageMeta,
  query,
  minConfidence,
  visibleNodes,
  selectedNode,
  selectedNodeId,
  hoveredNodeId,
  rawVisionData,
} = storeToRefs(store)

const imageInputRef = ref<HTMLInputElement | null>(null)
const visionInputRef = ref<HTMLInputElement | null>(null)
const errorMessage = ref('')
const noticeMessage = ref('')
const noticeTone = ref<'success' | 'warning'>('success')
const localObjectUrl = ref<string | null>(null)
const currentImageHash = ref<string | null>(null)
const isGenerating = ref(false)
const wsConnection = ref<WebSocket | null>(null)
const wsConnected = ref(false)

const totalCount = computed(() => visibleNodes.value.length)
const controlCount = computed(
  () => visibleNodes.value.filter((item) => item.nodeRole === 'control').length,
)
const labelCount = computed(
  () => visibleNodes.value.filter((item) => item.nodeRole === 'label').length,
)

function openImageImport() {
  imageInputRef.value?.click()
}

function openVisionImport() {
  visionInputRef.value?.click()
}

function cleanupObjectUrl() {
  if (localObjectUrl.value) {
    URL.revokeObjectURL(localObjectUrl.value)
    localObjectUrl.value = null
  }
}

function clearAll() {
  cleanupObjectUrl()
  store.clearAll()
  errorMessage.value = ''
  noticeMessage.value = ''
  currentImageHash.value = null
  isGenerating.value = false
}

function resolvePlaygroundWsUrl(): string {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${protocol}//${window.location.host}/ws/playground/image`
}

function closeImageStream(options?: { keepNotice?: boolean }) {
  const keepNotice = options?.keepNotice ?? true
  const socket = wsConnection.value
  wsConnection.value = null
  wsConnected.value = false
  if (socket) {
    socket.close()
  }
  if (!keepNotice) {
    return
  }
  noticeTone.value = 'warning'
  noticeMessage.value = '图片流已断开。'
}

function applyStreamFrame(message: Extract<PlaygroundWsMessage, { type: 'image.frame' }>) {
  cleanupObjectUrl()
  currentImageHash.value = null
  store.clearRecognitionData()
  store.setImageUrl(message.image_url)
  errorMessage.value = ''
  noticeTone.value = 'success'
  noticeMessage.value = `已收到服务端图片帧 ${message.frame_id}，并更新到舞台显示。`
}

function handleImageStreamMessage(raw: string) {
  const message = JSON.parse(raw) as PlaygroundWsMessage
  if (message.type === 'connected') {
    wsConnected.value = true
    errorMessage.value = ''
    noticeTone.value = 'success'
    noticeMessage.value = `图片流已连接，当前在线 ${message.client_count} 个客户端。`
    return
  }
  if (message.type === 'image.frame') {
    applyStreamFrame(message)
  }
}

function connectImageStream() {
  if (wsConnection.value) {
    return
  }

  errorMessage.value = ''
  noticeTone.value = 'warning'
  noticeMessage.value = '正在连接服务端图片流...'
  const socket = new WebSocket(resolvePlaygroundWsUrl())
  wsConnection.value = socket

  socket.addEventListener('message', (event) => {
    try {
      handleImageStreamMessage(String(event.data || ''))
    } catch (error) {
      errorMessage.value = error instanceof Error ? error.message : '解析图片流消息失败'
    }
  })

  socket.addEventListener('close', () => {
    const wasConnected = wsConnected.value
    wsConnection.value = null
    wsConnected.value = false
    if (wasConnected) {
      noticeTone.value = 'warning'
      noticeMessage.value = '图片流连接已关闭。'
    }
  })

  socket.addEventListener('error', () => {
    errorMessage.value = '连接图片流失败，请确认 packages/server 已启动。'
  })
}

function requestImageStreamRefresh() {
  const socket = wsConnection.value
  if (!socket) {
    connectImageStream()
    return
  }
  if (socket.readyState === WebSocket.OPEN) {
    socket.send(JSON.stringify({ type: 'ping' }))
  }
}

function toggleImageStream() {
  if (wsConnection.value) {
    closeImageStream()
    return
  }
  connectImageStream()
}

async function computeFileSha256(file: File): Promise<string> {
  const buffer = await file.arrayBuffer()
  const digest = await crypto.subtle.digest('SHA-256', buffer)
  return Array.from(new Uint8Array(digest))
    .map((item) => item.toString(16).padStart(2, '0'))
    .join('')
}

async function fileToDataUrl(file: File): Promise<string> {
  return await new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result || ''))
    reader.onerror = () => reject(new Error('图片读取失败'))
    reader.readAsDataURL(file)
  })
}

async function requestVisionFromCore(file: File): Promise<VisionControlExportResult> {
  const imageBase64 = await fileToDataUrl(file)
  const response = await fetch('/api/vision/extract', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      fileName: file.name,
      imageBase64,
    }),
  })

  const payload = (await response.json().catch(() => null)) as
    | VisionControlExportResult
    | { error?: string }
    | null

  if (!response.ok) {
    throw new Error(payload && 'error' in payload && payload.error ? payload.error : '调用 core 生成 control.json 失败')
  }

  if (!parseVisionPayload(payload)) {
    throw new Error('core 返回的 control.json 结构无效')
  }

  return payload as VisionControlExportResult
}

function resolveImageUrl(data: VisionControlExportResult): string | null {
  const uri = data.source?.uri?.trim()
  if (!uri) {
    return null
  }
  if (
    uri.startsWith('/') ||
    uri.startsWith('http://') ||
    uri.startsWith('https://') ||
    uri.startsWith('data:image/')
  ) {
    return uri
  }
  return null
}

function loadVisionDataWithLink(data: VisionControlExportResult) {
  if (currentImageHash.value) {
    const expectedHash = data.source?.image_hash?.trim().toLowerCase()
    if (expectedHash && expectedHash !== currentImageHash.value.toLowerCase()) {
      throw new Error('当前图片与导入的 control.json 不匹配，请选择对应产物')
    }
  } else {
    const embeddedImageUrl = resolveImageUrl(data)
    if (embeddedImageUrl) {
      cleanupObjectUrl()
      store.setImageUrl(embeddedImageUrl)
    }
  }

  store.loadVisionData(data)
  errorMessage.value = ''
}

function updateVisionNotice(actionLabel: string, data: VisionControlExportResult) {
  const controlBoxCount = data.controls.filter((item) => item.bbox_context).length
  const labelBoxCount = data.labels.filter((item) => item.bbox_context).length
  const totalBoxCount = controlBoxCount + labelBoxCount

  if (totalBoxCount > 0) {
    noticeTone.value = 'success'
    noticeMessage.value =
      `${actionLabel}，已识别 ${data.controls.length} 个控件、${data.labels.length} 个标签，并渲染 ${totalBoxCount} 个 bbox。`
    return
  }

  noticeTone.value = 'warning'
  noticeMessage.value = `${actionLabel}，但当前结果里没有可渲染的 bbox。`
}

async function handleImageChange(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) {
    return
  }

  try {
    cleanupObjectUrl()
    store.clearRecognitionData()
    currentImageHash.value = await computeFileSha256(file)
    const objectUrl = URL.createObjectURL(file)
    localObjectUrl.value = objectUrl
    store.setImageUrl(objectUrl)
    errorMessage.value = ''
    noticeMessage.value = ''
    isGenerating.value = true

    const result = await requestVisionFromCore(file)
    loadVisionDataWithLink(result)
    requestImageStreamRefresh()
    updateVisionNotice('调用 core 成功', result)
  } catch (error) {
    errorMessage.value =
      error instanceof Error ? error.message : '调用 core 生成 control.json 失败'
  } finally {
    isGenerating.value = false
    input.value = ''
  }
}

async function handleVisionChange(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) {
    return
  }

  try {
    noticeMessage.value = ''
    const content = await file.text()
    const parsed = JSON.parse(content) as unknown
    const payload = parseVisionPayload(parsed)
    if (!payload) {
      throw new Error('文件结构不是有效的 vision 导出结果')
    }
    loadVisionDataWithLink(payload)
    updateVisionNotice('control.json 已加载', payload)
  } catch (error) {
    errorMessage.value =
      error instanceof Error ? error.message : 'JSON 解析失败，请检查文件内容'
  } finally {
    input.value = ''
  }
}

onMounted(() => {
  connectImageStream()
})

onBeforeUnmount(() => {
  cleanupObjectUrl()
  closeImageStream({ keepNotice: false })
})
</script>

<template>
  <div class="page">
    <input
      ref="imageInputRef"
      class="page__hidden-input"
      type="file"
      accept="image/*"
      @change="handleImageChange"
    >
    <input
      ref="visionInputRef"
      class="page__hidden-input"
      type="file"
      accept=".json,application/json"
      @change="handleVisionChange"
    >

    <PlaygroundToolbar
      :query="query"
      :min-confidence="minConfidence"
      :total-count="totalCount"
      :control-count="controlCount"
      :label-count="labelCount"
      :ws-connected="wsConnected"
      @update:query="store.setQuery"
      @update:min-confidence="store.setMinConfidence"
      @image-import="openImageImport"
      @vision-import="openVisionImport"
      @toggle-stream="toggleImageStream"
      @clear="clearAll"
    />

    <p v-if="errorMessage" class="page__error">
      {{ errorMessage }}
    </p>
    <p v-else-if="isGenerating" class="page__status">
      正在调用 core 生成 control.json 并渲染控件标识...
    </p>
    <p
      v-else-if="noticeMessage"
      class="page__status"
      :class="{
        'page__status--success': noticeTone === 'success',
        'page__status--warning': noticeTone === 'warning',
      }"
    >
      {{ noticeMessage }}
    </p>

    <section class="page__workspace">
      <PlaygroundNodeList
        :nodes="visibleNodes"
        :selected-node-id="selectedNodeId"
        :hovered-node-id="hoveredNodeId"
        @select="store.setSelectedNodeId"
        @hover="store.setHoveredNodeId"
      />

      <PlaygroundStage
        :image-url="imageUrl"
        :image-meta="imageMeta"
        :nodes="visibleNodes"
        :selected-node-id="selectedNodeId"
        :hovered-node-id="hoveredNodeId"
        @select="store.setSelectedNodeId"
        @hover="store.setHoveredNodeId"
      />

      <PlaygroundDetailPanel
        :node="selectedNode"
        :raw-vision-data="rawVisionData"
      />
    </section>
  </div>
</template>

<style scoped>
.page {
  display: grid;
  gap: 20px;
}

.page__hidden-input {
  display: none;
}

.page__error {
  margin: 0;
  padding: 14px 16px;
  border: 1px solid rgba(255, 111, 111, 0.2);
  border-radius: 16px;
  background: rgba(86, 18, 28, 0.55);
  color: #ffc2c2;
}

.page__status {
  margin: 0;
  padding: 14px 16px;
  border: 1px solid rgba(73, 121, 255, 0.24);
  border-radius: 16px;
  background: rgba(41, 68, 143, 0.18);
  color: #dbe7ff;
}

.page__status--success {
  border-color: rgba(47, 179, 109, 0.28);
  background: rgba(47, 179, 109, 0.14);
  color: #dff7ea;
}

.page__status--warning {
  border-color: rgba(210, 155, 45, 0.3);
  background: rgba(210, 155, 45, 0.14);
  color: #fff0c9;
}

.page__workspace {
  display: grid;
  grid-template-columns: 320px minmax(0, 1fr) 360px;
  gap: 20px;
  min-height: calc(100vh - 280px);
}

@media (max-width: 1380px) {
  .page__workspace {
    grid-template-columns: 280px minmax(0, 1fr);
  }
}

@media (max-width: 1100px) {
  .page__workspace {
    grid-template-columns: 1fr;
    min-height: auto;
  }
}
</style>
