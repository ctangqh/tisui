import type {
  PlaygroundNode,
  PlaygroundRelation,
  PlaygroundBBox,
  PlaygroundSnapshotPayload,
  PlaygroundSnapshotRegion,
  VisionControlExportResult,
  VisionControlItem,
  VisionLabelItem,
  VisionRelationItem,
  UITreeDebugPayload,
  GoogleVisionExportResult,
  GoogleVisionElement,
  LocatorElementsExportResult,
  LocatorElement,
  LocatorElementRegion,
  LocatorInputImageMeta,
  RegionIdentifyExportResult,
  RegionIdentifyItem,
} from '@/types/playground'

function normalizeBBox(bbox: Partial<PlaygroundBBox>): PlaygroundBBox {
  const left = bbox.left ?? 0
  const top = bbox.top ?? 0
  const width = bbox.width ?? (bbox.right ? bbox.right - left : 0)
  const height = bbox.height ?? (bbox.bottom ? bbox.bottom - top : 0)
  const right = bbox.right ?? left + width
  const bottom = bbox.bottom ?? top + height
  return { left, top, width, height, right, bottom }
}

export function convertVisionData(data: VisionControlExportResult): {
  nodes: PlaygroundNode[]
  relations: PlaygroundRelation[]
} {
  const nodes: PlaygroundNode[] = []

  // Convert controls
  data.controls.forEach((control: VisionControlItem) => {
    nodes.push({
      id: control.id,
      source: 'vision-control',
      nodeRole: 'control',
      name: control.text || control.id,
      text: control.text,
      type: control.type,
      controlType: control.control_type,
      confidence: control.confidence,
      bbox: control.bbox_context ? normalizeBBox(control.bbox_context) : undefined,
      center: control.center_context,
      path: control.path,
      depth: control.depth,
      actionCapabilities: control.action_capabilities
        ? { ...control.action_capabilities }
        : undefined,
      attributes: control.attributes,
      locatorCandidates: control.locator_candidates,
      raw: control
    })
  })

  // Convert labels
  data.labels.forEach((label: VisionLabelItem) => {
    nodes.push({
      id: label.id,
      source: 'vision-label',
      nodeRole: 'label',
      name: label.text || label.id,
      text: label.text,
      confidence: label.confidence,
      bbox: label.bbox_context ? normalizeBBox(label.bbox_context) : undefined,
      center: label.center_context,
      path: label.path,
      depth: label.depth,
      raw: label
    })
  })

  const relations: PlaygroundRelation[] = data.relations.map(
    (relation: VisionRelationItem, index: number) => ({
      id: `relation-${index}`,
      kind: relation.kind,
      fromId: relation.from_id,
      toId: relation.to_id,
      confidence: relation.confidence,
      meta: relation.meta,
      raw: relation
    })
  )

  return { nodes, relations }
}

function isVisionControlExportResult(value: unknown): value is VisionControlExportResult {
  const data = value as Partial<VisionControlExportResult>
  return Boolean(
    data &&
      Array.isArray(data.controls) &&
      Array.isArray(data.labels) &&
      Array.isArray(data.relations) &&
      data.image,
  )
}

function isGoogleVisionExportResult(value: unknown): value is GoogleVisionExportResult {
  const data = value as Partial<GoogleVisionExportResult>
  const image = data && typeof data === 'object' ? (data as any).image : undefined
  return Boolean(
    data &&
      Array.isArray(data.elements) &&
      image &&
      typeof image.width === 'number' &&
      typeof image.height === 'number',
  )
}

function isLocatorElementsExportResult(value: unknown): value is LocatorElementsExportResult {
  const data = value as Partial<LocatorElementsExportResult>
  const inputImage = data && typeof data === 'object' ? (data as any).input_image : undefined
  return Boolean(
    data &&
      Array.isArray(data.elements) &&
      inputImage &&
      typeof inputImage.width === 'number' &&
      typeof inputImage.height === 'number',
  )
}

function isRegionIdentifyExportResult(value: unknown): value is RegionIdentifyExportResult {
  const data = value as Partial<RegionIdentifyExportResult>
  const image = data && typeof data === 'object' ? (data as any).image : undefined
  return Boolean(
    data &&
      Array.isArray(data.regions) &&
      image &&
      typeof image.width === 'number' &&
      typeof image.height === 'number',
  )
}

function isPlaygroundSnapshotPayload(value: unknown): value is PlaygroundSnapshotPayload {
  const data = value as Partial<PlaygroundSnapshotPayload>
  return Boolean(
    data &&
      data.type === 'playground.snapshot' &&
      Array.isArray(data.regions) &&
      data.image &&
      typeof data.image.image_url === 'string' &&
      typeof data.image.raw_width === 'number' &&
      typeof data.image.raw_height === 'number',
  )
}

function toBBoxFromLTRB(left: number, top: number, right: number, bottom: number): PlaygroundBBox {
  return normalizeBBox({ left, top, right, bottom })
}

function toBBoxFromRelativeBBox(relative: number[], width: number, height: number): PlaygroundBBox {
  return toBBoxFromLTRB(
    Number(relative[0]) * width,
    Number(relative[1]) * height,
    Number(relative[2]) * width,
    Number(relative[3]) * height,
  )
}

function toActionCapabilities(raw: unknown): Record<string, boolean> | undefined {
  if (!Array.isArray(raw)) return undefined
  const supported = new Set([
    'click',
    'input',
    'select',
    'toggle',
    'scroll',
    'hover',
    'drag',
    'long_press',
  ])
  const result: Record<string, boolean> = {}
  raw.forEach((item) => {
    if (typeof item !== 'string') return
    const key = item.trim()
    if (!key || !supported.has(key)) return
    result[key] = true
  })
  return Object.keys(result).length ? result : undefined
}

function tryParseJsonObject(raw: unknown): Record<string, unknown> | null {
  if (typeof raw !== 'string') return null

  let candidate = raw.trim()
  if (!candidate) return null

  if (candidate.startsWith('```')) {
    let lines = candidate.split(/\r?\n/)
    if (lines.length && lines[0].startsWith('```')) {
      lines = lines.slice(1)
    }
    if (lines.length && lines[0].trim().toLowerCase() === 'json') {
      lines = lines.slice(1)
    }
    if (lines.length && lines[lines.length - 1].trim().startsWith('```')) {
      lines = lines.slice(0, -1)
    }
    candidate = lines.join('\n').trim()
  }

  const start = candidate.indexOf('{')
  if (start < 0) return null

  let depth = 0
  let inString = false
  let escape = false
  let extracted = candidate

  for (let index = start; index < candidate.length; index += 1) {
    const char = candidate[index]
    if (inString) {
      if (escape) {
        escape = false
      } else if (char === '\\') {
        escape = true
      } else if (char === '"') {
        inString = false
      }
      continue
    }

    if (char === '"') {
      inString = true
      continue
    }
    if (char === '{') {
      depth += 1
      continue
    }
    if (char === '}') {
      depth -= 1
      if (depth === 0) {
        extracted = candidate.slice(start, index + 1)
        break
      }
    }
  }

  const attempts = [
    extracted,
    extracted.replace(/,\s*([}\]])/g, '$1'),
  ]

  for (const attempt of attempts) {
    try {
      const parsed = JSON.parse(attempt) as unknown
      if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
        return parsed as Record<string, unknown>
      }
    } catch {
      // Ignore parse failure and try the next sanitized candidate.
    }
  }

  return null
}

function recoverLocatorElementsPayload(
  data: LocatorElementsExportResult,
): LocatorElementsExportResult {
  if (Array.isArray(data.elements) && data.elements.length > 0) {
    return data
  }

  const rawModelResponse =
    data && typeof data === 'object' && data.raw_model_response && typeof data.raw_model_response === 'object'
      ? (data.raw_model_response as Record<string, unknown>)
      : null
  const recovered = tryParseJsonObject(rawModelResponse?.content)
  if (!recovered) {
    return data
  }

  const recoveredElements = Array.isArray(recovered.elements) ? recovered.elements : null
  if (!recoveredElements?.length) {
    return data
  }

  const recoveredInputImage =
    recovered.input_image && typeof recovered.input_image === 'object'
      ? (recovered.input_image as Record<string, unknown>)
      : null

  // 确保 input_image 至少有 width 和 height
  const finalInputImage = recoveredInputImage ?? data.input_image
  const safeInputImage: LocatorInputImageMeta = {
    width: Number(finalInputImage.width) || Number(data.input_image.width) || 0,
    height: Number(finalInputImage.height) || Number(data.input_image.height) || 0,
    ...finalInputImage,
  }

  return {
    ...data,
    ...recovered,
    input_image: safeInputImage,
    elements: recoveredElements as LocatorElement[],
    raw_model_response: data.raw_model_response ?? recovered.raw_model_response,
    errors: Array.isArray(data.errors) && data.errors.length ? data.errors : recovered.errors,
  }
}

function toLocatorRegion(raw: unknown): LocatorElementRegion | null {
  if (!raw) return null
  if (Array.isArray(raw) && raw.length && typeof raw[0] === 'object' && raw[0]) {
    return raw[0] as any
  }
  if (typeof raw === 'object') return raw as any
  return null
}

function adaptLocatorElementToControl(
  element: LocatorElement,
  index: number,
  imageWidth: number,
  imageHeight: number,
): VisionControlItem | null {
  const actionRegion = toLocatorRegion((element as any).action_regions)
  const region = actionRegion || toLocatorRegion((element as any).regions)
  if (!region) return null

  const absoluteBBox = (region as any).absolute_bbox
  const relativeBBox = (region as any).relative_bbox

  let bboxContext: PlaygroundBBox | undefined
  if (Array.isArray(absoluteBBox) && absoluteBBox.length === 4) {
    bboxContext = toBBoxFromLTRB(
      Number(absoluteBBox[0]),
      Number(absoluteBBox[1]),
      Number(absoluteBBox[2]),
      Number(absoluteBBox[3]),
    )
  }

  if (!bboxContext && Array.isArray(relativeBBox) && relativeBBox.length === 4) {
    if (imageWidth > 0 && imageHeight > 0) {
      bboxContext = toBBoxFromRelativeBBox(relativeBBox as any, imageWidth, imageHeight)
    }
  }

  if (!bboxContext) return null

  const center = {
    x: bboxContext.left + bboxContext.width / 2,
    y: bboxContext.top + bboxContext.height / 2,
  }

  const elementAttributes =
    typeof (element as any).attributes === 'object' && (element as any).attributes
      ? ((element as any).attributes as Record<string, unknown>)
      : {}
  const attributes: Record<string, unknown> = {
    ...elementAttributes,
    element_id: (element as any).element_id,
    refine_type: (element as any).refine_type,
  }
  if (region) {
    attributes.region = region
  }

  const textFromAttributes = typeof elementAttributes.text === 'string' ? elementAttributes.text.trim() : ''
  const labelFromAttributes = typeof elementAttributes.label === 'string' ? elementAttributes.label.trim() : ''
  const text = textFromAttributes || labelFromAttributes || String((element as any).refine_type || (element as any).element_id || `element-${index}`)

  const confidenceValue = (region as any).confidence
  const confidence =
    typeof confidenceValue === 'number' && Number.isFinite(confidenceValue) ? confidenceValue : 1

  const capabilities = (elementAttributes as any).capabilities

  return {
    id: String((element as any).element_id || `element-${index}`),
    node_role: 'control',
    text,
    confidence,
    bbox_context: bboxContext,
    bbox_logical: bboxContext,
    center_context: center,
    center_logical: center,
    source: { kind: 'locator' },
    type: typeof (element as any).type === 'string' ? (element as any).type : undefined,
    control_type:
      typeof (element as any).refine_type === 'string' ? (element as any).refine_type : undefined,
    action_capabilities: toActionCapabilities(capabilities) as any,
    attributes,
  }
}

export function adaptLocatorElementsPayload(
  data: LocatorElementsExportResult,
): VisionControlExportResult {
  const payload = recoverLocatorElementsPayload(data)
  const inputImage = (payload as any).input_image || {}
  const originalWidth = Number((inputImage as any).original_width || 0)
  const originalHeight = Number((inputImage as any).original_height || 0)
  const resizeWidth = Number((inputImage as any).width || 0)
  const resizeHeight = Number((inputImage as any).height || 0)

  const hasOriginalSize = originalWidth > 0 && originalHeight > 0
  const imageWidth = hasOriginalSize ? originalWidth : resizeWidth
  const imageHeight = hasOriginalSize ? originalHeight : resizeHeight

  const controls: VisionControlItem[] = []
  payload.elements.forEach((item, index) => {
    const control = adaptLocatorElementToControl(item, index, imageWidth, imageHeight)
    if (control) controls.push(control)
  })

  return {
    version: 'locator-elements-1',
    generated_at: new Date().toISOString(),
    platform: 'web',
    image: {
      raw_width: imageWidth,
      raw_height: imageHeight,
      context_width: imageWidth,
      context_height: imageHeight,
      screenshot_shrink_factor: 1,
      raw_to_context_ratio: 1,
      context_to_logical_ratio: 1,
    },
    source: {
      kind: 'external',
      uri: '',
      image_hash: '',
    },
    controls,
    labels: [],
    relations: [],
  }
}

function adaptGoogleElementToControl(
  element: GoogleVisionElement,
  index: number,
): VisionControlItem | null {
  const id = `element-${index}`
  const bbox = element.bbox
  const relative = element.relative_bbox

  let bboxContext: PlaygroundBBox | undefined
  if (Array.isArray(bbox) && bbox.length === 4) {
    bboxContext = toBBoxFromLTRB(
      Number(bbox[0]),
      Number(bbox[1]),
      Number(bbox[2]),
      Number(bbox[3]),
    )
  }

  if (!bboxContext && Array.isArray(relative) && relative.length === 4) {
    return null
  }

  if (!bboxContext) {
    return null
  }

  const center = {
    x: bboxContext.left + bboxContext.width / 2,
    y: bboxContext.top + bboxContext.height / 2,
  }

  const attributes: Record<string, unknown> = {
    ...(typeof element.attributes === 'object' && element.attributes ? element.attributes : {}),
  }
  if (typeof element.color_name === 'string' && element.color_name.trim()) {
    attributes.color_name = element.color_name.trim()
  }
  if (Array.isArray(element.relative_bbox) && element.relative_bbox.length === 4) {
    attributes.relative_bbox = [...element.relative_bbox]
  }
  if (Array.isArray(element.bbox) && element.bbox.length === 4) {
    attributes.bbox = [...element.bbox]
  }
  if (Array.isArray(element.action_capablilities) && element.action_capablilities.length) {
    attributes.action_capablilities = [...element.action_capablilities]
  }

  return {
    id,
    node_role: 'control',
    text: String(element.text || ''),
    confidence: 1,
    bbox_context: bboxContext,
    bbox_logical: bboxContext,
    center_context: center,
    center_logical: center,
    source: { kind: 'vision' },
    type: typeof element.type === 'string' ? element.type : undefined,
    control_type:
      typeof element.control_type === 'string' ? element.control_type : undefined,
    action_capabilities: toActionCapabilities(element.action_capablilities) as any,
    attributes,
  }
}

export function adaptGoogleVisionPayload(data: GoogleVisionExportResult): VisionControlExportResult {
  const width = data.image.width
  const height = data.image.height
  const controls: VisionControlItem[] = []
  data.elements.forEach((item, index) => {
    const control = adaptGoogleElementToControl(item, index)
    if (control) controls.push(control)
  })

  return {
    version: 'google-json-1',
    generated_at: new Date().toISOString(),
    platform: 'web',
    image: {
      raw_width: width,
      raw_height: height,
      context_width: width,
      context_height: height,
      screenshot_shrink_factor: 1,
      raw_to_context_ratio: 1,
      context_to_logical_ratio: 1,
    },
    source: {
      kind: 'external',
      uri: '',
      image_hash: '',
    },
    controls,
    labels: [],
    relations: [],
  }
}

function adaptRegionItemToControl(
  region: RegionIdentifyItem,
  index: number,
): VisionControlItem | null {
  const bbox = region.bbox
  const relative = region.relative_bbox

  let bboxContext: PlaygroundBBox | undefined
  if (Array.isArray(bbox) && bbox.length === 4) {
    bboxContext = toBBoxFromLTRB(
      Number(bbox[0]),
      Number(bbox[1]),
      Number(bbox[2]),
      Number(bbox[3]),
    )
  }

  if (!bboxContext && Array.isArray(relative) && relative.length === 4) {
    return null
  }

  if (!bboxContext) {
    return null
  }

  const center = {
    x: bboxContext.left + bboxContext.width / 2,
    y: bboxContext.top + bboxContext.height / 2,
  }
  const name = typeof region.name === 'string' && region.name.trim()
    ? region.name.trim()
    : `region-${index + 1}`
  const description = typeof region.description === 'string' ? region.description.trim() : ''
  const attributes: Record<string, unknown> = {}

  if (description) {
    attributes.description = description
  }
  if (Array.isArray(region.relative_bbox) && region.relative_bbox.length === 4) {
    attributes.relative_bbox = [...region.relative_bbox]
  }
  if (Array.isArray(region.bbox) && region.bbox.length === 4) {
    attributes.bbox = [...region.bbox]
  }

  return {
    id: `region-${index}`,
    node_role: 'control',
    text: name,
    confidence: 1,
    bbox_context: bboxContext,
    bbox_logical: bboxContext,
    center_context: center,
    center_logical: center,
    source: { kind: 'vision' },
    type: 'region',
    control_type: 'region',
    attributes,
  }
}

export function adaptRegionIdentifyPayload(data: RegionIdentifyExportResult): VisionControlExportResult {
  const width = data.image.width
  const height = data.image.height
  const controls: VisionControlItem[] = []
  data.regions.forEach((item, index) => {
    const control = adaptRegionItemToControl(item, index)
    if (control) controls.push(control)
  })

  return {
    version: 'regions-identify-1',
    generated_at: new Date().toISOString(),
    platform: 'web',
    image: {
      raw_width: width,
      raw_height: height,
      context_width: width,
      context_height: height,
      screenshot_shrink_factor: 1,
      raw_to_context_ratio: 1,
      context_to_logical_ratio: 1,
    },
    source: {
      kind: 'external',
      uri: '',
      image_hash: '',
    },
    controls,
    labels: [],
    relations: [],
  }
}

function adaptPlaygroundRegionToControl(
  region: PlaygroundSnapshotRegion,
  index: number,
): VisionControlItem | null {
  const bbox = region.bbox
  if (!Array.isArray(bbox) || bbox.length !== 4) {
    return null
  }

  const bboxContext = toBBoxFromLTRB(
    Number(bbox[0]),
    Number(bbox[1]),
    Number(bbox[2]),
    Number(bbox[3]),
  )
  const center = {
    x: bboxContext.left + bboxContext.width / 2,
    y: bboxContext.top + bboxContext.height / 2,
  }

  return {
    id: region.id || `preprocess-region-${index}`,
    node_role: 'control',
    text: region.name || `region-${index + 1}`,
    confidence: 1,
    bbox_context: bboxContext,
    bbox_logical: bboxContext,
    center_context: center,
    center_logical: center,
    source: { kind: 'preprocess' },
    type: 'region',
    control_type: 'region',
    attributes: {
      description: region.description,
      z_index: region.z_index,
      page_grid_position: region.page_grid_position,
      anchors: region.anchors,
      raw: region.raw,
      bbox_resized: region.bbox_resized,
      relative_bbox: region.relative_bbox,
    },
  }
}

export function adaptPlaygroundSnapshotPayload(data: PlaygroundSnapshotPayload): VisionControlExportResult {
  const image = data.image
  const controls: VisionControlItem[] = []

  data.regions.forEach((item, index) => {
    const control = adaptPlaygroundRegionToControl(item, index)
    if (control) controls.push(control)
  })

  return {
    version: 'playground-snapshot-1',
    generated_at: new Date().toISOString(),
    platform: 'web',
    image: {
      raw_width: image?.raw_width ?? 0,
      raw_height: image?.raw_height ?? 0,
      context_width: image?.width ?? image?.raw_width ?? 0,
      context_height: image?.height ?? image?.raw_height ?? 0,
      screenshot_shrink_factor:
        image && image.raw_width > 0 && image.width > 0 ? image.width / image.raw_width : 1,
      raw_to_context_ratio:
        image && image.raw_width > 0 && image.width > 0 ? image.width / image.raw_width : 1,
      context_to_logical_ratio: 1,
    },
    source: {
      kind: 'preprocess',
      uri: image?.image_url || '',
      image_hash: image?.image_hash || '',
    },
    controls,
    labels: [],
    relations: [],
  }
}

export function parseVisionPayload(value: unknown): VisionControlExportResult | null {
  if (isVisionControlExportResult(value)) return value
  if (isGoogleVisionExportResult(value)) return adaptGoogleVisionPayload(value)
  if (isLocatorElementsExportResult(value)) return adaptLocatorElementsPayload(value)
  if (isRegionIdentifyExportResult(value)) return adaptRegionIdentifyPayload(value)
  if (isPlaygroundSnapshotPayload(value)) return adaptPlaygroundSnapshotPayload(value)
  return null
}

export function convertUITreeData(data: UITreeDebugPayload): PlaygroundNode[] {
  const nodes: PlaygroundNode[] = []

  data.annotations.forEach((anno, index) => {
    nodes.push({
      id: `uitree-${index}`,
      source: 'uitree',
      nodeRole: 'tree-node',
      name: anno.label || `Node ${index}`,
      bbox: normalizeBBox(anno.rect),
      raw: anno
    })
  })

  return nodes
}
