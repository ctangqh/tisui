import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type {
  VisionPlaygroundState,
  PlaygroundNode,
  PlaygroundRelation,
  PlaygroundBBox,
  VisionControlExportResult,
  UITreeDebugPayload,
  StageDebugImage,
  StageDebugBbox,
} from '@/types/playground'
import { convertVisionData, convertUITreeData } from '@/composables/usePlaygroundData'

export const useVisionPlaygroundStore = defineStore('visionPlayground', () => {
  // State
  const imageUrl = ref<string>('')
  const imageMeta = ref<VisionPlaygroundState['imageMeta']>()
  const stage = ref<VisionPlaygroundState['stage']>('input')
  const nodes = ref<PlaygroundNode[]>([])
  const relations = ref<PlaygroundRelation[]>([])
  const selectedNodeId = ref<string | null>(null)
  const hoveredNodeId = ref<string | null>(null)
  const query = ref<string>('')
  const minConfidence = ref<number>(0)
  const visibleSources = ref<string[]>(['vision-control', 'vision-label', 'uitree', 'debug'])
  const visibleNodeRoles = ref<string[]>(['control', 'label', 'tree-node'])
  const showRelations = ref<boolean>(true)
  const showLabels = ref<boolean>(true)
  const showDebugOverlay = ref<boolean>(true)
  const scale = ref<number>(1)
  const offsetX = ref<number>(0)
  const offsetY = ref<number>(0)
  const rawVisionData = ref<VisionControlExportResult>()
  const rawUITreeData = ref<UITreeDebugPayload>()

  // ---- 三阶段管道 Debug ----
  const debugStages = ref<StageDebugImage[]>([])
  const activeStageIndex = ref(0)
  const debugMode = ref(false)

  // ---- Computed ----
  const filteredNodes = computed(() => {
    return nodes.value.filter((node) => {
      if (!visibleSources.value.includes(node.source)) return false
      if (!visibleNodeRoles.value.includes(node.nodeRole)) return false
      if (node.confidence !== undefined && node.confidence < minConfidence.value) return false
      if (query.value) {
        const q = query.value.toLowerCase()
        return (
          node.name.toLowerCase().includes(q) ||
          (node.text && node.text.toLowerCase().includes(q)) ||
          (node.id.toLowerCase().includes(q))
        )
      }
      return true
    })
  })

  const visibleNodes = computed(() => {
    let result = filteredNodes.value
    if (!showLabels.value) {
      result = result.filter((node) => node.nodeRole !== 'label')
    }
    return result
  })

  const visibleRelations = computed(() => {
    if (!showRelations.value) return []
    const nodeIds = new Set(visibleNodes.value.map((n) => n.id))
    return relations.value.filter(
      (rel) => nodeIds.has(rel.fromId) && nodeIds.has(rel.toId)
    )
  })

  const selectedNode = computed(() =>
    nodes.value.find((n) => n.id === selectedNodeId.value)
  )

  const hoveredNode = computed(() =>
    nodes.value.find((n) => n.id === hoveredNodeId.value)
  )

  // ---- Debug Computed ----
  const currentStage = computed<StageDebugImage | null>(() =>
    debugStages.value[activeStageIndex.value] ?? null
  )

  const activeStageImage = computed(() => {
    const stage = currentStage.value
    if (!stage) return imageUrl.value
    if (stage.image_base64) return stage.image_base64
    return imageUrl.value
  })

  const activeStageMeta = computed(() => {
    const stage = currentStage.value
    if (!stage) return imageMeta.value
    return {
      raw_width: stage.image_width,
      raw_height: stage.image_height,
      context_width: stage.image_width,
      context_height: stage.image_height,
      screenshot_shrink_factor: 1,
      raw_to_context_ratio: 1,
      context_to_logical_ratio: 1,
    }
  })

  const activeStageNodes = computed<PlaygroundNode[]>(() => {
    const stage = currentStage.value
    if (!stage) return debugMode.value ? [] : visibleNodes.value
    return stage.bboxes.map((item: StageDebugBbox, index: number) => {
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
  })

  // Actions
  function setImageUrl(url: string) {
    imageUrl.value = url
  }

  function setStage(newStage: VisionPlaygroundState['stage']) {
    stage.value = newStage
  }

  function setQuery(q: string) {
    query.value = q
  }

  function setMinConfidence(c: number) {
    minConfidence.value = c
  }

  function setSelectedNodeId(id: string | null) {
    selectedNodeId.value = id
  }

  function setHoveredNodeId(id: string | null) {
    hoveredNodeId.value = id
  }

  function setScale(s: number) {
    scale.value = Math.max(0.1, Math.min(10, s))
  }

  function setOffset(x: number, y: number) {
    offsetX.value = x
    offsetY.value = y
  }

  function resetView() {
    scale.value = 1
    offsetX.value = 0
    offsetY.value = 0
  }

  function loadVisionData(data: VisionControlExportResult) {
    rawVisionData.value = data
    imageMeta.value = data.image
    const converted = convertVisionData(data)
    nodes.value = converted.nodes
    relations.value = converted.relations
    selectedNodeId.value = null
    hoveredNodeId.value = null
    if (stage.value === 'input') {
      stage.value = 'vision'
    }
  }

  function loadUITreeData(data: UITreeDebugPayload) {
    rawUITreeData.value = data
    const uitreeNodes = convertUITreeData(data)
    const existingIds = new Set(nodes.value.map((n) => n.id))
    const newNodes = [...nodes.value]
    uitreeNodes.forEach((node) => {
      if (!existingIds.has(node.id)) {
        newNodes.push(node)
      }
    })
    nodes.value = newNodes
  }

  function clearRecognitionData() {
    imageMeta.value = undefined
    stage.value = 'input'
    nodes.value = []
    relations.value = []
    selectedNodeId.value = null
    hoveredNodeId.value = null
    rawVisionData.value = undefined
    rawUITreeData.value = undefined
    resetView()
  }

  function clearAll() {
    imageUrl.value = ''
    clearRecognitionData()
    query.value = ''
    minConfidence.value = 0
    exitDebugView()
  }

  // ---- Debug Actions ----
  function loadDebugStages(stages: StageDebugImage[]) {
    debugStages.value = stages
    activeStageIndex.value = 0
    debugMode.value = true
  }

  function setActiveStageIndex(index: number) {
    if (index >= 0 && index < debugStages.value.length) {
      activeStageIndex.value = index
    }
  }

  function exitDebugView() {
    debugMode.value = false
    debugStages.value = []
    activeStageIndex.value = 0
  }

  return {
    // State
    imageUrl,
    imageMeta,
    stage,
    nodes,
    relations,
    selectedNodeId,
    hoveredNodeId,
    query,
    minConfidence,
    visibleSources,
    visibleNodeRoles,
    showRelations,
    showLabels,
    showDebugOverlay,
    scale,
    offsetX,
    offsetY,
    rawVisionData,
    rawUITreeData,
    // Debug
    debugStages,
    activeStageIndex,
    debugMode,
    currentStage,
    activeStageImage,
    activeStageMeta,
    activeStageNodes,
    // Computed
    filteredNodes,
    visibleNodes,
    visibleRelations,
    selectedNode,
    hoveredNode,
    // Actions
    setImageUrl,
    setStage,
    setQuery,
    setMinConfidence,
    setSelectedNodeId,
    setHoveredNodeId,
    setScale,
    setOffset,
    resetView,
    loadVisionData,
    loadUITreeData,
    clearRecognitionData,
    clearAll,
    // Debug Actions
    loadDebugStages,
    setActiveStageIndex,
    exitDebugView,
  }
})