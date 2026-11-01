<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { FileText, ImageUp, Info, Moon, MousePointer2, Sun, Trash2 } from 'lucide-vue-next'
import WorkbenchImageStage from '@/components/workbench/WorkbenchImageStage.vue'
import WorkbenchPanelDetect from '@/components/workbench/WorkbenchPanelDetect.vue'
import WorkbenchPanelInfo from '@/components/workbench/WorkbenchPanelInfo.vue'
import { useTheme } from '@/composables/useTheme'
import { useVisionPlaygroundStore } from '@/stores/visionPlayground'
import type {
  PlaygroundGuideLines,
  PlaygroundSnapshotContextStep,
  PlaygroundNode,
  PlaygroundSnapshotPayload,
  PlaygroundWsMessage,
  VisionControlExportResult,
} from '@/types/playground'
import { parseVisionPayload } from '@/composables/usePlaygroundData'

type WorkbenchTab = 'detect' | 'info'

const store = useVisionPlaygroundStore()
const {
  imageUrl,
  imageMeta,
  visibleNodes,
  selectedNode,
  selectedNodeId,
  hoveredNodeId,
  rawVisionData,
  query,
  minConfidence,
} = storeToRefs(store)

const tab = ref<WorkbenchTab>('detect')
const imageInputRef = ref<HTMLInputElement | null>(null)
const visionInputRef = ref<HTMLInputElement | null>(null)
const visionImageBindInputRef = ref<HTMLInputElement | null>(null)
const errorMessage = ref('')
const noticeMessage = ref('')
const noticeTone = ref<'success' | 'warning'>('success')
const localObjectUrl = ref<string | null>(null)
const locateNodeId = ref<string | null>(null)
const currentImageHash = ref<string | null>(null)
const guideLines = ref<PlaygroundGuideLines>({ vertical: [], horizontal: [] })
const referenceLinesEnabled = ref(false)
const debugEnabled = ref(false)
const debugLoading = ref(false)
const debugSteps = ref<PlaygroundSnapshotContextStep[]>([])
const selectedDebugStepIndex = ref(-1)
const debugPayload = ref<PlaygroundSnapshotPayload | null>(null)
const debugLogs = ref<string[]>([])
const debugBodyRef = ref<HTMLElement | null>(null)
const isGenerating = ref(false)
const pendingVisionPayload = ref<VisionControlExportResult | null>(null)
const pendingVisionFileName = ref('')
const wsConnection = ref<WebSocket | null>(null)
const wsConnected = ref(false)
const { theme, toggleTheme, isDark } = useTheme()

const controls = computed(() =>
  visibleNodes.value.filter((item) => item.nodeRole === 'control'),
)
const stageNodes = computed(() => {
  if (!debugEnabled.value || !debugPayload.value) {
    return visibleNodes.value
  }

  const debugNodes: PlaygroundNode[] = []
  const nameSet = new Set<string>()

  debugPayload.value.regions.forEach((region, index) => {
    const bbox = Array.isArray(region.bbox) ? region.bbox : []
    if (bbox.length !== 4) {
      return
    }

    const left = Number(bbox[0])
    const top = Number(bbox[1])
    const right = Number(bbox[2])
    const bottom = Number(bbox[3])
    if (![left, top, right, bottom].every((value) => Number.isFinite(value))) {
      return
    }

    let label = String(region.name || '').trim()
    if (!label) {
      label = String(region.id || '').trim() || `region-${index + 1}`
    }
    if (nameSet.has(label)) {
      label = `${label}-${index + 1}`
    }
    nameSet.add(label)

    debugNodes.push({
      id: label,
      source: 'debug',
      nodeRole: 'label',
      name: String(region.name || region.id || label),
      text: String(region.description || ''),
      bbox: {
        left,
        top,
        right,
        bottom,
        width: Math.max(0, right - left),
        height: Math.max(0, bottom - top),
      },
      raw: region,
    })
  })

  const hintBBox = debugPayload.value.target_hint?.intersect_bbox || debugPayload.value.target_hint?.target_grid_bbox
  if (Array.isArray(hintBBox) && hintBBox.length === 4) {
    const left = Number(hintBBox[0])
    const top = Number(hintBBox[1])
    const right = Number(hintBBox[2])
    const bottom = Number(hintBBox[3])
    if ([left, top, right, bottom].every((value) => Number.isFinite(value))) {
      debugNodes.push({
        id: '定位目标',
        source: 'debug',
        nodeRole: 'control',
        name: '定位目标',
        bbox: {
          left,
          top,
          right,
          bottom,
          width: Math.max(0, right - left),
          height: Math.max(0, bottom - top),
        },
        raw: debugPayload.value.target_hint,
      })
    }
  }

  return [...visibleNodes.value, ...debugNodes]
})

function appendDebugLog(message: string) {
  const timestamp = new Date().toLocaleTimeString('zh-CN', { hour12: false })
  debugLogs.value = [`[${timestamp}] ${message}`, ...debugLogs.value].slice(0, 80)
}

function clearDebugLogs() {
  debugLogs.value = []
  appendDebugLog('调试日志已清空。')
}

async function scrollDebugLogsToLatest() {
  await nextTick()
  if (!debugBodyRef.value) {
    return
  }
  debugBodyRef.value.scrollTop = 0
}

function openImageImport() {
  imageInputRef.value?.click()
}

function openVisionImport() {
  visionInputRef.value?.click()
}

function openVisionImageBindImport() {
  visionImageBindInputRef.value?.click()
}

function resetDebugSteps() {
  debugSteps.value = []
  selectedDebugStepIndex.value = -1
  debugPayload.value = null
}

function resetDebugState() {
  debugEnabled.value = false
  debugLoading.value = false
  resetDebugSteps()
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
  tab.value = 'detect'
  errorMessage.value = ''
  noticeMessage.value = ''
  currentImageHash.value = null
  guideLines.value = { vertical: [], horizontal: [] }
  referenceLinesEnabled.value = false
  resetDebugState()
  isGenerating.value = false
  appendDebugLog('已清空当前图片、识别结果与参考线。')
}

function syncDebugSteps(payload: PlaygroundSnapshotPayload) {
  const steps = Array.isArray(payload.context?.steps) ? payload.context.steps : []
  debugPayload.value = payload
  debugSteps.value = steps
    .filter((item) => item && typeof item.name === 'string')
    .map((item) => ({
      name: item.name,
      description: item.description || '',
      input: item.input,
      output: item.output,
    }))

  if (!debugSteps.value.length) {
    selectedDebugStepIndex.value = -1
    return
  }

  if (selectedDebugStepIndex.value < 0 || selectedDebugStepIndex.value >= debugSteps.value.length) {
    selectedDebugStepIndex.value = 0
  }
}

function formatDebugValue(value: unknown): string {
  if (value == null) {
    return '暂无数据'
  }
  if (typeof value === 'string') {
    return value || '暂无数据'
  }
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}

function selectDebugStep(index: number) {
  selectedDebugStepIndex.value = index
  const step = debugSteps.value[index]
  if (!step) {
    return
  }

  const order = `T${String(index + 1).padStart(2, '0')}`
  const parts = [
    `Debug Step ${order}: ${step.name}`,
    step.description ? `描述: ${step.description}` : '',
    `输入:\n${formatDebugValue(step.input)}`,
    `输出:\n${formatDebugValue(step.output)}`,
  ].filter(Boolean)
  appendDebugLog(parts.join('\n'))
}

function isDebugOverlayNode(nodeId: string | null) {
  if (!nodeId) {
    return false
  }
  return nodeId === '定位目标' || debugPayload.value?.regions.some((region) => String(region.name || region.id || '').trim() === nodeId)
}

async function toggleDebugMode() {
  if (debugLoading.value) {
    return
  }

  if (debugEnabled.value) {
    debugEnabled.value = false
    resetDebugSteps()
    errorMessage.value = ''
    noticeTone.value = 'success'
    noticeMessage.value = '已关闭 Debug 回看。'
    appendDebugLog('Debug 回看已关闭。')
    return
  }

  try {
    debugLoading.value = true
    const payload = await requestCurrentPreprocess()
    if (!payload) {
      throw new Error('当前没有可加载 Debug 的图片')
    }
    syncDebugSteps(payload)
    debugEnabled.value = true
    errorMessage.value = ''
    noticeTone.value = 'success'
    noticeMessage.value = debugSteps.value.length
      ? `已开启 Debug，共 ${debugSteps.value.length} 个 step。`
      : '已开启 Debug，但当前没有可展示的 step 数据。'
    appendDebugLog(`Debug 已开启：steps=${debugSteps.value.length}。`)
  } catch (error) {
    resetDebugState()
    errorMessage.value = error instanceof Error ? error.message : '加载 Debug 失败'
    appendDebugLog(`Debug 加载失败：${errorMessage.value}`)
  } finally {
    debugLoading.value = false
  }
}

function resolvePlaygroundWsUrl(): string {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${protocol}//${window.location.host}/ws/playground/image`
}

function resolveServerHttpBaseUrl(): string {
  const protocol = window.location.protocol
  const host = window.location.hostname
  const currentPort = window.location.port
  const serverPort = currentPort === '5173' || currentPort === '4173' ? '8000' : currentPort
  return `${protocol}//${host}${serverPort ? `:${serverPort}` : ''}`
}

async function requestCurrentPreprocess(): Promise<PlaygroundSnapshotPayload | null> {
  const response = await fetch(`${resolveServerHttpBaseUrl()}/api/v1/playground/current/preprocess`)
  if (response.status === 404) {
    return null
  }

  const payload = (await response.json().catch(() => null)) as
    | PlaygroundSnapshotPayload
    | { detail?: string }
    | null

  if (!response.ok) {
    throw new Error(payload && 'detail' in payload && payload.detail ? payload.detail : '加载当前预处理结果失败')
  }

  const parsed = parseVisionPayload(payload)
  if (!parsed) {
    throw new Error('当前预处理结果结构无效')
  }

  return payload as PlaygroundSnapshotPayload
}

function extractGuideLines(payload: PlaygroundSnapshotPayload): PlaygroundGuideLines {
  const matrix = payload.matrix?.refer_line_matrix?.absolute_matrix || []
  const verticalSet = new Set<number>()
  const horizontalSet = new Set<number>()

  matrix.forEach((row) => {
    row.forEach((cell) => {
      const leftTop = Array.isArray(cell?.[0]) ? cell[0] : null
      const rightBottom = Array.isArray(cell?.[1]) ? cell[1] : null
      if (!leftTop || !rightBottom) {
        return
      }
      verticalSet.add(Number(leftTop[0]))
      verticalSet.add(Number(rightBottom[0]))
      horizontalSet.add(Number(leftTop[1]))
      horizontalSet.add(Number(rightBottom[1]))
    })
  })

  const rawWidth = payload.image?.raw_width ?? payload.image?.width ?? 0
  const rawHeight = payload.image?.raw_height ?? payload.image?.height ?? 0

  return {
    vertical: Array.from(verticalSet)
      .filter((value) => Number.isFinite(value) && value > 0 && value < rawWidth)
      .sort((a, b) => a - b),
    horizontal: Array.from(horizontalSet)
      .filter((value) => Number.isFinite(value) && value > 0 && value < rawHeight)
      .sort((a, b) => a - b),
  }
}

async function loadReferenceLines() {
  try {
    if (referenceLinesEnabled.value) {
      guideLines.value = { vertical: [], horizontal: [] }
      referenceLinesEnabled.value = false
      errorMessage.value = ''
      noticeTone.value = 'success'
      noticeMessage.value = '已关闭参考线显示。'
      appendDebugLog('参考线已关闭。')
      return
    }

    const payload = await requestCurrentPreprocess()
    if (!payload) {
      throw new Error('当前没有可加载参考线的图片')
    }

    cleanupObjectUrl()
    currentImageHash.value = payload.image?.image_hash ?? null
    locateNodeId.value = null
    guideLines.value = extractGuideLines(payload)
    referenceLinesEnabled.value = true
    if (debugEnabled.value) {
      syncDebugSteps(payload)
    }
    if (payload.image?.image_url) {
      store.setImageUrl(payload.image.image_url)
    }
    errorMessage.value = ''
    noticeTone.value = 'success'
    noticeMessage.value =
      `已加载参考线，共 ${guideLines.value.vertical.length} 条竖线、${guideLines.value.horizontal.length} 条横线。`
    appendDebugLog(
      `参考线加载完成：imageHash=${currentImageHash.value || '-'}，vertical=${guideLines.value.vertical.length}，horizontal=${guideLines.value.horizontal.length}。`,
    )
  } catch (error) {
    referenceLinesEnabled.value = false
    errorMessage.value = error instanceof Error ? error.message : '加载参考线失败'
    appendDebugLog(`参考线加载失败：${errorMessage.value}`)
  }
}

async function applyStreamFrame(message: Extract<PlaygroundWsMessage, { type: 'image.frame' }>) {
  const sameImageAsCurrent = Boolean(currentImageHash.value && currentImageHash.value.startsWith(message.frame_id))
  cleanupObjectUrl()
  currentImageHash.value = sameImageAsCurrent ? currentImageHash.value : null
  locateNodeId.value = null
  if (!sameImageAsCurrent) {
    store.clearRecognitionData()
    guideLines.value = { vertical: [], horizontal: [] }
    referenceLinesEnabled.value = false
    resetDebugState()
  }
  store.setImageUrl(message.image_url)
  errorMessage.value = ''
  noticeTone.value = 'success'
  noticeMessage.value = `已收到服务端图片帧 ${message.frame_id}，并更新到工作台显示。`
  appendDebugLog(`收到图片流帧：frameId=${message.frame_id}。`)
}

async function handleImageStreamMessage(raw: string) {
  const message = JSON.parse(raw) as PlaygroundWsMessage
  if (message.type === 'connected') {
    wsConnected.value = true
    errorMessage.value = ''
    appendDebugLog(`图片流已连接：在线客户端 ${message.client_count}。`)
    if (!store.imageUrl) {
      noticeTone.value = 'success'
      noticeMessage.value = `图片流已连接，当前在线 ${message.client_count} 个客户端。`
    }
    return
  }
  if (message.type === 'image.frame') {
    await applyStreamFrame(message)
  }
}

function connectImageStream() {
  if (wsConnection.value) {
    return
  }

  const socket = new WebSocket(resolvePlaygroundWsUrl())
  wsConnection.value = socket

  socket.addEventListener('message', async (event) => {
    try {
      await handleImageStreamMessage(String(event.data || ''))
    } catch (error) {
      errorMessage.value = error instanceof Error ? error.message : '解析图片流消息失败'
    }
  })

  socket.addEventListener('close', () => {
    wsConnection.value = null
    wsConnected.value = false
    appendDebugLog('图片流连接已关闭。')
  })

  socket.addEventListener('error', () => {
    errorMessage.value = '连接图片流失败，请确认 packages/server 已启动。'
    appendDebugLog('图片流连接失败。')
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

async function loadEmbeddedVisionData(data: VisionControlExportResult) {
  if (currentImageHash.value) {
    const expectedHash = data.source?.image_hash?.trim().toLowerCase()
    if (expectedHash && expectedHash !== currentImageHash.value.toLowerCase()) {
      throw new Error('当前图片与导入的 control.json 不匹配，请选择对应产物')
    }
  }

  const embeddedImageUrl = resolveImageUrl(data)
  if (!currentImageHash.value && embeddedImageUrl) {
    cleanupObjectUrl()
    store.setImageUrl(embeddedImageUrl)
  }
  store.loadVisionData(data)
  errorMessage.value = ''
}

function needsExternalImageBinding(data: VisionControlExportResult): boolean {
  if (currentImageHash.value || store.imageUrl) {
    return false
  }
  return !resolveImageUrl(data)
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

async function loadDemoData() {
  try {
    cleanupObjectUrl()
    currentImageHash.value = null
    locateNodeId.value = null
    guideLines.value = { vertical: [], horizontal: [] }
    referenceLinesEnabled.value = false
    resetDebugState()
    store.clearAll()
    tab.value = 'detect'
    noticeMessage.value = ''
    const response = await fetch('/demo/control.json')
    if (!response.ok) {
      throw new Error('项目示例 control.json 加载失败')
    }
    const parsed = (await response.json()) as unknown
    const payload = parseVisionPayload(parsed)
    if (!payload) {
      throw new Error('项目示例 control.json 结构无效')
    }
    await loadEmbeddedVisionData(payload)
    updateVisionNotice('示例数据已加载', payload)
  } catch (error) {
    errorMessage.value =
      error instanceof Error ? error.message : '项目示例数据加载失败'
  }
}

async function handleImageChange(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return

  try {
    cleanupObjectUrl()
    store.clearRecognitionData()
    guideLines.value = { vertical: [], horizontal: [] }
    referenceLinesEnabled.value = false
    resetDebugState()
    currentImageHash.value = await computeFileSha256(file)
    const objectUrl = URL.createObjectURL(file)
    localObjectUrl.value = objectUrl
    store.setImageUrl(objectUrl)
    locateNodeId.value = null
    tab.value = 'detect'
    errorMessage.value = ''
    noticeMessage.value = ''
    isGenerating.value = true

    const result = await requestVisionFromCore(file)
    await loadEmbeddedVisionData(result)
    requestImageStreamRefresh()
    updateVisionNotice('调用 core 成功', result)
    appendDebugLog(
      `截图识别完成：controls=${result.controls.length}，labels=${result.labels.length}，imageHash=${currentImageHash.value || '-'}`,
    )
  } catch (error) {
    errorMessage.value =
      error instanceof Error ? error.message : '调用 core 生成 control.json 失败'
    appendDebugLog(`截图识别失败：${errorMessage.value}`)
  } finally {
    isGenerating.value = false
    input.value = ''
  }
}

async function handleVisionChange(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return

  try {
    noticeMessage.value = ''
    const content = await file.text()
    const parsed = JSON.parse(content) as unknown
    const payload = parseVisionPayload(parsed)
    if (!payload) {
      throw new Error('文件结构不是有效的 vision 导出结果')
    }
    if (needsExternalImageBinding(payload)) {
      pendingVisionPayload.value = payload
      pendingVisionFileName.value = file.name
      errorMessage.value = ''
      noticeTone.value = 'warning'
      noticeMessage.value = '该 JSON 不包含截图，请继续选择一张对应图片后再渲染 bbox。'
      appendDebugLog(`JSON 已加载但缺少底图：file=${file.name}，等待绑定图片。`)
      openVisionImageBindImport()
      return
    }
    await loadEmbeddedVisionData(payload)
    pendingVisionPayload.value = null
    pendingVisionFileName.value = ''
    updateVisionNotice('control.json 已加载', payload)
    appendDebugLog(
      `JSON 已加载：controls=${payload.controls.length}，labels=${payload.labels.length}。`,
    )
  } catch (error) {
    errorMessage.value =
      error instanceof Error ? error.message : 'JSON 解析失败，请检查文件内容'
    appendDebugLog(`JSON 加载失败：${errorMessage.value}`)
  } finally {
    input.value = ''
  }
}

async function handleVisionImageBindChange(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return

  try {
    const payload = pendingVisionPayload.value
    if (!payload) {
      throw new Error('当前没有等待绑定图片的 JSON')
    }

    cleanupObjectUrl()
    currentImageHash.value = await computeFileSha256(file)
    const objectUrl = URL.createObjectURL(file)
    localObjectUrl.value = objectUrl
    store.setImageUrl(objectUrl)
    locateNodeId.value = null
    tab.value = 'detect'

    await loadEmbeddedVisionData(payload)
    updateVisionNotice(`${pendingVisionFileName.value || 'control.json'} 已加载`, payload)
    noticeTone.value = 'success'
    noticeMessage.value = `${pendingVisionFileName.value || 'control.json'} 已绑定图片并渲染 bbox。`
    appendDebugLog(
      `JSON 已绑定图片：file=${pendingVisionFileName.value || '-'}，image=${file.name}，controls=${payload.controls.length}，labels=${payload.labels.length}。`,
    )
    pendingVisionPayload.value = null
    pendingVisionFileName.value = ''
    errorMessage.value = ''
  } catch (error) {
    errorMessage.value =
      error instanceof Error ? error.message : '绑定图片失败，请检查图片与 JSON 是否匹配'
    appendDebugLog(`JSON 绑定图片失败：${errorMessage.value}`)
  } finally {
    input.value = ''
  }
}

function handleLocate(nodeId: string) {
  store.setSelectedNodeId(nodeId)
  locateNodeId.value = nodeId
  tab.value = 'info'
}

function handleStageSelect(nodeId: string) {
  if (debugEnabled.value && isDebugOverlayNode(nodeId)) {
    return
  }
  store.setSelectedNodeId(nodeId)
  if (tab.value === 'info') {
    tab.value = 'info'
  }
}

function handleStageOpen(nodeId: string) {
  if (debugEnabled.value && isDebugOverlayNode(nodeId)) {
    return
  }
  store.setSelectedNodeId(nodeId)
  tab.value = 'info'
}

function handleStageHover(nodeId: string | null) {
  if (debugEnabled.value && isDebugOverlayNode(nodeId)) {
    store.setHoveredNodeId(null)
    return
  }
  store.setHoveredNodeId(nodeId)
}

function handleLocateConsumed() {
  locateNodeId.value = null
}

onBeforeUnmount(() => {
  cleanupObjectUrl()
  wsConnection.value?.close()
})

onMounted(() => {
  connectImageStream()
})

watch(
  () => debugLogs.value.length,
  async (nextLength, previousLength) => {
    if (nextLength <= 0 || nextLength === previousLength) {
      return
    }
    await scrollDebugLogsToLatest()
  },
)
</script>

<template>
  <div class="workbench">
    <input
      ref="imageInputRef"
      class="workbench__hidden-input"
      type="file"
      accept="image/*"
      @change="handleImageChange"
    >
    <input
      ref="visionInputRef"
      class="workbench__hidden-input"
      type="file"
      accept=".json,application/json"
      @change="handleVisionChange"
    >
    <input
      ref="visionImageBindInputRef"
      class="workbench__hidden-input"
      type="file"
      accept="image/*"
      @change="handleVisionImageBindChange"
    >

    <section class="workbench__stage">
      <WorkbenchImageStage
        :image-url="imageUrl"
        :image-meta="imageMeta"
        :nodes="stageNodes"
        :guide-lines="guideLines"
        :selected-node-id="selectedNodeId"
        :hovered-node-id="hoveredNodeId"
        :locate-node-id="locateNodeId"
        @select="handleStageSelect"
        @open="handleStageOpen"
        @hover="handleStageHover"
        @locate-consumed="handleLocateConsumed"
      />
    </section>

    <aside class="workbench__panel" :class="{ 'workbench__panel--debug': debugEnabled }">
      <header class="workbench__panel-header">
        <div class="workbench__panel-row">
          <div class="workbench__seg">
            <button
              type="button"
              class="workbench__seg-btn"
              :class="{ 'workbench__seg-btn--active': tab === 'detect' }"
              @click="tab = 'detect'"
            >
              <MousePointer2 :size="16" />
              <span>识别</span>
            </button>
            <button
              type="button"
              class="workbench__seg-btn"
              :class="{ 'workbench__seg-btn--active': tab === 'info' }"
              @click="tab = 'info'"
            >
              <Info :size="16" />
              <span>信息</span>
            </button>
          </div>

          <button type="button" class="workbench__icon-btn" @click="toggleTheme" :title="theme">
            <Moon v-if="!isDark" :size="16" />
            <Sun v-else :size="16" />
          </button>
        </div>

        <div class="workbench__panel-tools">
          <button
            type="button"
            class="workbench__panel-btn"
            :class="{ 'workbench__panel-btn--active': debugEnabled }"
            :disabled="debugLoading"
            @click="toggleDebugMode"
          >
            {{ debugLoading ? 'Debug 加载中' : debugEnabled ? 'Debug 已开启' : 'Debug 已关闭' }}
          </button>
        </div>

        <div class="workbench__panel-actions">
          <button
            type="button"
            class="workbench__panel-btn"
            :class="{ 'workbench__panel-btn--active': referenceLinesEnabled }"
            @click="loadReferenceLines"
          >
            参考线
          </button>
          <button type="button" class="workbench__panel-btn" @click="openImageImport">
            <ImageUp :size="16" />
            截图
          </button>
          <button type="button" class="workbench__panel-btn" @click="openVisionImport">
            <FileText :size="16" />
            JSON
          </button>
          <button type="button" class="workbench__panel-btn workbench__panel-btn--ghost" @click="clearAll">
            <Trash2 :size="16" />
            清空
          </button>
        </div>
      </header>

      <p v-if="errorMessage" class="workbench__error">
        {{ errorMessage }}
      </p>
      <p v-else-if="isGenerating" class="workbench__status">
        正在调用 core 生成 control.json 并渲染控件标识...
      </p>
      <p
        v-else-if="noticeMessage"
        class="workbench__status"
        :class="{
          'workbench__status--success': noticeTone === 'success',
          'workbench__status--warning': noticeTone === 'warning',
        }"
      >
        {{ noticeMessage }}
      </p>

      <div class="workbench__panel-body">
        <WorkbenchPanelDetect
          v-if="tab === 'detect'"
          :controls="controls"
          :selected-node-id="selectedNodeId"
          :hovered-node-id="hoveredNodeId"
          :query="query"
          :min-confidence="minConfidence"
          @update:query="store.setQuery"
          @update:min-confidence="store.setMinConfidence"
          @select="store.setSelectedNodeId"
          @hover="store.setHoveredNodeId"
          @locate="handleLocate"
        />

        <WorkbenchPanelInfo
          v-else
          :node="selectedNode"
          :raw-vision-data="rawVisionData"
        />
      </div>

      <section v-if="debugEnabled" class="workbench__steps">
        <div class="workbench__steps-header">
          <span class="workbench__steps-title">Debug Steps</span>
          <span class="workbench__steps-meta">按流程顺序</span>
        </div>
        <div class="workbench__steps-body">
          <p v-if="!debugSteps.length" class="workbench__steps-empty">
            当前没有可展示的 step 数据。
          </p>
          <button
            v-for="(step, index) in debugSteps"
            v-else
            :key="`${index}-${step.name}`"
            type="button"
            class="workbench__steps-item"
            :class="{ 'workbench__steps-item--active': index === selectedDebugStepIndex }"
            @click="selectDebugStep(index)"
          >
            <span class="workbench__steps-order">
              {{ `T${String(index + 1).padStart(2, '0')}` }}
            </span>
            <span class="workbench__steps-main">
              <span class="workbench__steps-name">{{ step.name }}</span>
              <span class="workbench__steps-desc">{{ step.description || '当前步骤暂无描述。' }}</span>
            </span>
          </button>
        </div>
      </section>

      <section class="workbench__debug">
        <div class="workbench__debug-header">
          <span class="workbench__debug-title">调试日志</span>
          <div class="workbench__debug-actions">
            <span class="workbench__debug-meta">
              {{ wsConnected ? 'WS 已连接' : 'WS 未连接' }}
            </span>
            <button type="button" class="workbench__debug-clear" @click="clearDebugLogs">
              清空日志
            </button>
          </div>
        </div>
        <div ref="debugBodyRef" class="workbench__debug-body">
          <p v-if="!debugLogs.length" class="workbench__debug-empty">
            当前暂无调试日志。
          </p>
          <p
            v-for="(item, index) in debugLogs"
            v-else
            :key="`${index}-${item}`"
            class="workbench__debug-line"
          >
            {{ item }}
          </p>
        </div>
      </section>
    </aside>
  </div>
</template>

<style scoped>
.workbench {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 312px;
  gap: 18px;
  height: 100vh;
  min-height: 100vh;
  overflow: hidden;
}

.workbench__hidden-input {
  display: none;
}

.workbench__stage {
  position: relative;
  display: grid;
  align-items: center;
  min-height: 0;
  overflow: hidden;
  padding: 12px;
  border: 1px solid color-mix(in srgb, var(--accent) 22%, var(--border));
  background: color-mix(in srgb, var(--panel-soft) 86%, #0f172a 14%);
}

.workbench__panel {
  position: sticky;
  top: 0;
  align-self: start;
  height: 100vh;
  min-height: 100vh;
  display: grid;
  grid-template-rows: auto auto minmax(0, 1fr) minmax(140px, 20vh);
  gap: 16px;
  padding: 18px 18px 20px;
  border: 1px solid var(--border);
  border-radius: 0;
  background: var(--panel);
}

.workbench__panel--debug {
  grid-template-rows: auto auto minmax(0, 1fr) minmax(180px, 26vh) minmax(140px, 20vh);
}

.workbench__panel-header {
  display: grid;
  gap: 14px;
}

.workbench__panel-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.workbench__seg {
  display: grid;
  grid-template-columns: 1fr 1fr;
  flex: 1;
  padding: 4px;
  border-radius: 0;
  border: 1px solid var(--border);
  background: var(--panel-soft);
}

.workbench__seg-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  min-height: 34px;
  border-radius: 0;
  border: 1px solid transparent;
  background: transparent;
  color: var(--muted);
  cursor: pointer;
  transition: 0.18s ease;
}

.workbench__seg-btn:hover {
  color: var(--text);
}

.workbench__seg-btn--active {
  border-color: color-mix(in srgb, var(--accent) 42%, transparent);
  background: color-mix(in srgb, var(--panel) 85%, transparent);
  color: var(--text);
}

.workbench__seg-btn span {
  font-size: 12px;
  line-height: 1.1;
}

.workbench__icon-btn {
  flex: none;
  width: 40px;
  height: 40px;
  border-radius: 0;
  border: 1px solid var(--border);
  background: var(--panel-soft);
  color: var(--text);
  cursor: pointer;
  display: grid;
  place-items: center;
  transition: 0.18s ease;
}

.workbench__icon-btn:hover {
  border-color: color-mix(in srgb, var(--accent) 44%, var(--border));
}

.workbench__panel-actions {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

.workbench__panel-tools {
  display: grid;
  grid-template-columns: 1fr;
}

.workbench__panel-btn {
  flex: 1;
  min-height: 38px;
  border-radius: 0;
  padding: 0 10px;
  background: var(--panel-soft);
  border: 1px solid var(--border);
  color: var(--text);
  cursor: pointer;
  transition: 0.18s ease;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  font-size: 12px;
}

.workbench__panel-btn:hover {
  border-color: color-mix(in srgb, var(--accent) 44%, var(--border));
  transform: translateY(-1px);
}

.workbench__panel-btn:disabled {
  opacity: 0.6;
  cursor: wait;
  transform: none;
}

.workbench__panel-btn--active {
  border-color: color-mix(in srgb, var(--accent) 56%, transparent);
  background: color-mix(in srgb, var(--accent) 16%, var(--panel-soft));
  color: var(--text);
  box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--accent) 18%, transparent);
}

.workbench__panel-btn--ghost {
  background: color-mix(in srgb, var(--panel) 70%, transparent);
  color: var(--muted);
}

.workbench__panel-body {
  min-height: 0;
  overflow: auto;
}

.workbench__steps {
  min-height: 0;
  display: grid;
  grid-template-rows: auto 1fr;
  border: 1px solid color-mix(in srgb, var(--accent) 18%, var(--border));
  background: color-mix(in srgb, var(--panel-soft) 90%, transparent);
}

.workbench__steps-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 10px 12px;
  border-bottom: 1px solid color-mix(in srgb, var(--border) 88%, transparent);
}

.workbench__steps-title {
  font-size: 12px;
  font-weight: 600;
}

.workbench__steps-meta {
  color: var(--muted);
  font-size: 11px;
}

.workbench__steps-body {
  min-height: 0;
  overflow: auto;
  padding: 8px;
  display: grid;
  gap: 8px;
  align-content: start;
}

.workbench__steps-empty {
  margin: 0;
  padding: 8px;
  color: var(--muted);
  font-size: 11px;
}

.workbench__steps-item {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  gap: 10px;
  align-items: start;
  padding: 10px;
  border: 1px solid var(--border);
  background: var(--panel);
  color: var(--text);
  text-align: left;
  cursor: pointer;
  transition: 0.18s ease;
}

.workbench__steps-item:hover {
  border-color: color-mix(in srgb, var(--accent) 40%, var(--border));
}

.workbench__steps-item--active {
  border-color: color-mix(in srgb, var(--accent) 56%, transparent);
  background: color-mix(in srgb, var(--accent) 10%, var(--panel));
  box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--accent) 18%, transparent);
}

.workbench__steps-order {
  min-width: 32px;
  color: var(--muted);
  font-size: 11px;
  line-height: 1.6;
}

.workbench__steps-main {
  min-width: 0;
  display: grid;
  gap: 4px;
}

.workbench__steps-name {
  font-size: 12px;
  font-weight: 600;
  line-height: 1.4;
}

.workbench__steps-desc {
  color: var(--muted);
  font-size: 11px;
  line-height: 1.45;
}

.workbench__debug {
  min-height: 0;
  display: grid;
  grid-template-rows: auto 1fr;
  border: 1px solid color-mix(in srgb, var(--accent) 18%, var(--border));
  background: #0b1220;
  box-shadow: inset 0 1px 0 color-mix(in srgb, #ffffff 4%, transparent);
}

.workbench__debug-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 10px 12px;
  border-bottom: 1px solid color-mix(in srgb, #94a3b8 16%, transparent);
  background: color-mix(in srgb, #111827 90%, #020617 10%);
  color: #dbe4f0;
  font-size: 12px;
}

.workbench__debug-title {
  font-weight: 600;
  letter-spacing: 0.02em;
}

.workbench__debug-actions {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}

.workbench__debug-meta {
  color: #94a3b8;
  font-size: 11px;
}

.workbench__debug-clear {
  min-height: 24px;
  padding: 0 8px;
  border: 1px solid color-mix(in srgb, #94a3b8 20%, transparent);
  background: color-mix(in srgb, #0f172a 86%, transparent);
  color: #cbd5e1;
  font-size: 11px;
  cursor: pointer;
  transition: 0.18s ease;
}

.workbench__debug-clear:hover {
  border-color: color-mix(in srgb, var(--accent) 40%, #94a3b8);
  color: #f8fafc;
}

.workbench__debug-body {
  min-height: 0;
  overflow: auto;
  padding: 10px 12px;
  background:
    linear-gradient(to bottom, color-mix(in srgb, #0f172a 96%, transparent), #020617);
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
}

.workbench__debug-empty {
  margin: 0;
  color: #64748b;
  font-size: 11px;
}

.workbench__debug-line {
  margin: 0 0 8px;
  color: #dbe4f0;
  font-size: 10.5px;
  line-height: 1.55;
  word-break: break-word;
  white-space: pre-wrap;
}

.workbench__debug-line:last-child {
  margin-bottom: 0;
}

.workbench__error {
  margin: 0;
  padding: 10px 12px;
  border: 1px solid color-mix(in srgb, var(--danger) 28%, var(--border));
  border-radius: 0;
  background: var(--danger-bg);
  color: var(--danger);
  font-size: 12px;
}

.workbench__status {
  margin: 0;
  padding: 10px 12px;
  border: 1px solid color-mix(in srgb, var(--accent) 24%, var(--border));
  border-radius: 0;
  background: color-mix(in srgb, var(--accent) 10%, var(--panel));
  color: var(--text);
  font-size: 12px;
}

.workbench__status--success {
  border-color: color-mix(in srgb, #2fb36d 30%, var(--border));
  background: color-mix(in srgb, #2fb36d 12%, var(--panel));
}

.workbench__status--warning {
  border-color: color-mix(in srgb, #d29b2d 32%, var(--border));
  background: color-mix(in srgb, #d29b2d 12%, var(--panel));
}

:deep(.panel__search),
:deep(.panel__range),
:deep(.panel__empty),
:deep(.panel__item),
:deep(.panel__locate),
:deep(.detail),
:deep(.detail__empty),
:deep(.detail__card),
:deep(.detail__json) {
  border-radius: 0 !important;
}

@media (max-width: 1280px) {
  .workbench {
    grid-template-columns: minmax(0, 1fr) 288px;
  }
}

@media (max-width: 1100px) {
  .workbench {
    grid-template-columns: 1fr;
    height: 100vh;
  }

  .workbench__panel {
    position: static;
    height: auto;
    min-height: unset;
  }
}
</style>
