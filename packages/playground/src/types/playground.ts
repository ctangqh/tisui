export interface PlaygroundBBox {
  left: number
  top: number
  width: number
  height: number
  right: number
  bottom: number
}

export interface PlaygroundNode {
  id: string
  source: 'vision-control' | 'vision-label' | 'uitree' | 'debug'
  nodeRole: 'control' | 'label' | 'tree-node'
  name: string
  text?: string
  type?: string
  controlType?: string
  confidence?: number
  bbox?: PlaygroundBBox
  center?: {
    x: number
    y: number
  }
  path?: string[]
  depth?: number
  actionCapabilities?: Record<string, boolean>
  attributes?: Record<string, unknown>
  locatorCandidates?: Array<Record<string, unknown>>
  raw?: unknown
}

export interface PlaygroundRelation {
  id: string
  kind: string
  fromId: string
  toId: string
  confidence?: number
  meta?: Record<string, unknown>
  raw?: unknown
}

export interface VisionImageMeta {
  raw_width: number
  raw_height: number
  context_width: number
  context_height: number
  screenshot_shrink_factor: number
  raw_to_context_ratio: number
  context_to_logical_ratio: number
}

export interface VisionModelMeta {
  provider: string
  name: string
  tiling_enabled: boolean
  tile_overlap_ratio: number
}

export interface VisionInputMeta {
  kind: string
  uri: string
  image_hash: string
}

export interface VisionActionCapabilities {
  click: boolean
  input: boolean
  select?: boolean
  toggle?: boolean
  scroll?: boolean
  hover?: boolean
  drag?: boolean
  long_press?: boolean
}

export interface VisionColor {
  primary?: string
  secondary?: string
  text?: string
  name?: string
  palette?: string[]
  confidence?: number
}

export interface VisionPositionHint {
  horizontal?: 'left' | 'center' | 'right'
  vertical?: 'top' | 'middle' | 'bottom'
  label?: string
}

export interface VisionSourceMeta {
  kind: string
  tile_index?: number
}

export interface VisionBaseNode {
  id: string
  node_role: string
  text: string
  confidence: number
  bbox_context: PlaygroundBBox
  bbox_logical: PlaygroundBBox
  center_context: { x: number; y: number }
  center_logical: { x: number; y: number }
  source: VisionSourceMeta
  platform?: string
  path?: string[]
  depth?: number
  tag?: string
  attributes?: Record<string, unknown>
}

export interface VisionControlItem extends VisionBaseNode {
  node_role: 'control'
  type?: string
  control_type?: string
  enabled?: boolean
  action_capabilities?: VisionActionCapabilities
  bbox_raw?: PlaygroundBBox
  center_raw?: { x: number; y: number }
  parent_id?: string
  class_name?: string
  color?: VisionColor
  position_hint?: VisionPositionHint
  element_ref?: Record<string, unknown>
  locator_candidates?: Array<Record<string, unknown>>
  preferred_action_ref?: Record<string, unknown>
}

export interface VisionLabelItem extends VisionBaseNode {
  node_role: 'label'
  bbox_raw?: PlaygroundBBox
  center_raw?: { x: number; y: number }
  parent_id?: string
}

export interface VisionRelationItem {
  kind: string
  from_id: string
  to_id: string
  confidence?: number
  meta?: Record<string, unknown>
}

export interface VisionControlExportResult {
  version: string
  generated_at: string
  platform: string
  image: VisionImageMeta
  model?: VisionModelMeta
  source: VisionInputMeta
  controls: VisionControlItem[]
  labels: VisionLabelItem[]
  relations: VisionRelationItem[]
  annotated_image_path?: string
}

export interface GoogleVisionImageMeta {
  width: number
  height: number
}

export interface GoogleVisionElement {
  type?: string
  control_type?: string
  relative_bbox?: [number, number, number, number]
  bbox?: [number, number, number, number]
  text?: string
  action_capablilities?: string[]
  color_name?: string
  attributes?: Record<string, unknown>
  [key: string]: unknown
}

export interface GoogleVisionExportResult {
  elements: GoogleVisionElement[]
  errors?: unknown
  image: GoogleVisionImageMeta
}

export interface LocatorInputImageMeta {
  start_coordinate?: number[]
  width: number
  height: number
  zoom_ratio?: number
  original_width?: number
  original_height?: number
  [key: string]: unknown
}

export interface LocatorElementRegion {
  relative_bbox?: number[]
  absolute_bbox?: number[]
  action_point?: number[]
  action?: string
  confidence?: number
  adopt_strategy?: string
  [key: string]: unknown
}

export interface LocatorElement {
  element_id?: string
  type?: string
  refine_type?: string
  regions?: LocatorElementRegion
  action_regions?: LocatorElementRegion | LocatorElementRegion[]
  attributes?: Record<string, unknown>
  [key: string]: unknown
}

export interface LocatorElementsExportResult {
  input_image: LocatorInputImageMeta
  elements: LocatorElement[]
  errors?: unknown
  [key: string]: unknown
}

export interface RegionIdentifyItem {
  name?: string
  description?: string
  relative_bbox?: [number, number, number, number]
  bbox?: [number, number, number, number]
  [key: string]: unknown
}

export interface RegionIdentifyExportResult {
  regions: RegionIdentifyItem[]
  errors?: unknown
  image: GoogleVisionImageMeta
}

export interface PlaygroundSnapshotImage {
  image_hash: string
  source_file_name?: string | null
  image_url: string
  image_variant: 'raw' | 'resized'
  width: number
  height: number
  raw_width: number
  raw_height: number
  resized_width: number
  resized_height: number
  resize_max_side: number
}

export interface PlaygroundSnapshotRegion {
  id: string
  name: string
  description: string
  z_index: number
  relative_bbox?: number[]
  bbox?: number[]
  bbox_resized?: number[]
  page_grid_position?: string | null
  anchors?: unknown[]
  raw?: Record<string, unknown>
}

export interface PlaygroundSnapshotTargetCandidate {
  region_id?: string | null
  region_name?: string | null
  grid_position?: string | null
  confidence?: number | null
  reason?: string | null
}

export interface PlaygroundSnapshotTargetHint {
  action_text: string
  target_region_id?: string | null
  target_region_name?: string | null
  target_grid_position?: string | null
  target_grid_index?: number | null
  target_grid_bbox?: number[] | null
  intersect_bbox?: number[] | null
  confidence?: number | null
  reasoning?: string | null
  candidates?: PlaygroundSnapshotTargetCandidate[]
  raw_llm_result?: Record<string, unknown>
  normalized_summary?: Record<string, unknown>
}

export type PlaygroundSnapshotAnchor = [[number, number], [number, number]]

export interface PlaygroundSnapshotMatrixGroup {
  absolute_matrix?: PlaygroundSnapshotAnchor[][]
  relative_matrix?: PlaygroundSnapshotAnchor[][]
}

export interface PlaygroundSnapshotMatrix {
  nine_matrix?: PlaygroundSnapshotMatrixGroup
  refer_line_matrix?: PlaygroundSnapshotMatrixGroup
}

export interface PlaygroundSnapshotContextStep {
  name: string
  description?: string
  input?: Record<string, unknown>
  output?: Record<string, unknown>
}

export interface PlaygroundSnapshotContext {
  action?: string
  meta?: Record<string, unknown>
  steps?: PlaygroundSnapshotContextStep[]
  [key: string]: unknown
}

export interface PlaygroundSnapshotPayload {
  type: 'playground.snapshot'
  stage: 'regions_identify' | 'action_regions' | 'action_target'
  image?: PlaygroundSnapshotImage | null
  regions: PlaygroundSnapshotRegion[]
  page_anchors?: unknown[]
  target_hint?: PlaygroundSnapshotTargetHint | null
  config?: Record<string, unknown>
  matrix?: PlaygroundSnapshotMatrix
  context?: PlaygroundSnapshotContext
  errors?: unknown[]
}

export interface PlaygroundGuideLines {
  vertical: number[]
  horizontal: number[]
}

export interface UITreeDebugPayload {
  description: string
  device_type?: string
  annotations: Array<{ rect: PlaygroundBBox; label: string }>
  tree?: unknown
}

export interface PlaygroundWsConnectedMessage {
  type: 'connected'
  channel: 'playground.image'
  client_id: string
  client_count: number
}

export interface PlaygroundWsPongMessage {
  type: 'pong'
}

export interface PlaygroundWsImageFrameMessage {
  type: 'image.frame'
  frame_id: string
  mime_type: string
  image_url: string
  width?: number
  height?: number
  sent_at: string
}

export type PlaygroundWsMessage =
  | PlaygroundWsConnectedMessage
  | PlaygroundWsPongMessage
  | PlaygroundWsImageFrameMessage

export interface VisionPlaygroundState {
  imageUrl: string
  imageMeta?: VisionImageMeta
  stage: 'input' | 'vision' | 'relations' | 'filtered' | 'uitree' | 'compare'
  nodes: PlaygroundNode[]
  relations: PlaygroundRelation[]
  selectedNodeId: string | null
  hoveredNodeId: string | null
  query: string
  minConfidence: number
  visibleSources: string[]
  visibleNodeRoles: string[]
  showRelations: boolean
  showLabels: boolean
  showDebugOverlay: boolean
  scale: number
  offsetX: number
  offsetY: number
  rawVisionData?: VisionControlExportResult
  rawUITreeData?: UITreeDebugPayload
}

// =============================================================================
// 三阶段定位管道 Debug 类型
// =============================================================================

export interface StageDebugBbox {
  bbox: [number, number, number, number]   // [left, top, right, bottom]
  label: string
  style: 'candidate' | 'primary' | 'fallback' | 'crop_window'
  confidence: number
}

export interface StageDebugImage {
  stage: string
  image_base64: string
  image_width: number
  image_height: number
  crop_on_raw: [number, number, number, number] | null
  bboxes: StageDebugBbox[]
  zoom_scale: number
  duration_ms: number
  model_calls: number
  decisions: string[]
}

export interface PipelineStageTrace {
  stage_name: string
  duration_ms: number
  model_calls: number
  model_name: string
  input_size: [number, number]
  output_count: number
  decisions: string[]
  errors: string[]
}

export interface PipelineLocateElement {
  type: string
  text: string
  description: string
  bbox: [number, number, number, number]
  relative_bbox: [number, number, number, number]
  action_point: [number, number]
  confidence: number
  enabled: boolean
  action_capabilities: string[]
  refine_type: string
  action_point_hint: string
  source: string
  is_fallback: boolean
  fallback_reason: string
  coarse_bbox: [number, number, number, number] | null
  coarse_confidence: number | null
}

export interface PipelineLocateResult {
  status: string
  error: string | null
  elements: PipelineLocateElement[]
  primary_index: number
  trace: PipelineStageTrace[]
  total_duration_ms: number
  quality_path_used: boolean
  debug_stages: StageDebugImage[]
}
