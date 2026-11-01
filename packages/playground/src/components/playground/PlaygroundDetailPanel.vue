<script setup lang="ts">
import { computed } from 'vue'
import type { PlaygroundNode, VisionControlExportResult } from '@/types/playground'

const props = defineProps<{
  node: PlaygroundNode | undefined
  rawVisionData?: VisionControlExportResult
}>()

const rawText = computed(() => {
  if (!props.node?.raw) {
    return props.rawVisionData ? JSON.stringify(props.rawVisionData, null, 2) : ''
  }
  return JSON.stringify(props.node.raw, null, 2)
})

function formatNumber(value: number) {
  if (Number.isFinite(value) && Number.isInteger(value)) return String(value)
  if (!Number.isFinite(value)) return String(value)
  return value.toFixed(2)
}

const bboxLTRBText = computed(() => {
  const bbox = props.node?.bbox
  if (!bbox) return ''
  return `[${formatNumber(bbox.left)}, ${formatNumber(bbox.top)}, ${formatNumber(bbox.right)}, ${formatNumber(bbox.bottom)}]`
})

const actions = computed(() => {
  const capabilities = props.node?.actionCapabilities
  if (!capabilities) return []
  return Object.entries(capabilities)
    .filter(([, enabled]) => Boolean(enabled))
    .map(([name]) => name)
})

const colorName = computed(() => {
  const value = props.node?.attributes?.color_name
  if (typeof value !== 'string') return ''
  return value.trim()
})

const colorHex = computed(() => {
  const value = props.node?.attributes?.color
  if (typeof value !== 'string') return ''
  return value.trim()
})

const resolvedColor = computed(() => {
  const value = colorHex.value
  if (!value) return ''
  if (/^#([0-9a-f]{3}|[0-9a-f]{6}|[0-9a-f]{8})$/i.test(value)) return value
  return ''
})

const googleExtra = computed(() => {
  const attributes = props.node?.attributes
  if (!attributes) return []
  const entries: Array<[string, string]> = []

  if (colorName.value) {
    entries.push(['color_name', colorName.value])
  }

  const relativeBBox = attributes.relative_bbox
  if (Array.isArray(relativeBBox) && relativeBBox.length === 4) {
    entries.push(['relative_bbox', JSON.stringify(relativeBBox)])
  }

  const ltrbBBox = attributes.bbox
  if (Array.isArray(ltrbBBox) && ltrbBBox.length === 4) {
    entries.push(['bbox(LTRB)', JSON.stringify(ltrbBBox)])
  }

  const rawActions = attributes.action_capablilities
  if (Array.isArray(rawActions) && rawActions.length) {
    entries.push(['action_capablilities', JSON.stringify(rawActions)])
  }

  return entries
})
</script>

<template>
  <aside class="detail">
    <div class="detail__header">
      <h2>节点详情</h2>
      <span v-if="node">{{ node.id }}</span>
    </div>

    <div v-if="!node" class="detail__empty">
      <p>还没有选中的节点。</p>
      <small>点击左侧列表项，或双击截图上的框，即可查看详细信息。</small>
    </div>

    <div v-else class="detail__content">
      <section class="detail__card">
        <h3>基础信息</h3>
        <table class="detail__table">
          <tbody>
            <tr>
              <th>名称</th>
              <td>{{ node.id }}</td>
            </tr>
            <tr>
              <th>角色</th>
              <td>{{ node.nodeRole }}</td>
            </tr>
            <tr>
              <th>类型</th>
              <td>{{ node.controlType || node.type || '-' }}</td>
            </tr>
            <tr v-if="colorName || colorHex">
              <th>颜色</th>
              <td>
                <div class="detail__color">
                  <span
                    v-if="resolvedColor"
                    class="detail__color-swatch"
                    :style="{ background: resolvedColor }"
                  />
                  <span v-if="colorHex" class="detail__color-hex">{{ colorHex }}</span>
                  <span v-if="colorName" class="detail__color-name">{{ colorName }}</span>
                </div>
              </td>
            </tr>
            <tr>
              <th>文本</th>
              <td>{{ node.text || '-' }}</td>
            </tr>
            <tr>
              <th>置信度</th>
              <td>{{ node.confidence === undefined ? '-' : node.confidence.toFixed(2) }}</td>
            </tr>
            <tr>
              <th>交互能力</th>
              <td>{{ actions.length ? actions.join(', ') : '' }}</td>
            </tr>
          </tbody>
        </table>
      </section>

      <section v-if="bboxLTRBText" class="detail__card">
        <h3>几何信息</h3>
        <table class="detail__table">
          <tbody>
            <tr>
              <th>坐标[左,上,右,下]</th>
              <td>{{ bboxLTRBText }}</td>
            </tr>
          </tbody>
        </table>
      </section>

      <section v-if="googleExtra.length" class="detail__card">
        <h3>Google 补充</h3>
        <dl class="detail__list">
          <div v-for="[label, value] in googleExtra" :key="label">
            <dt>{{ label }}</dt>
            <dd>{{ value }}</dd>
          </div>
        </dl>
      </section>

      <section v-if="node.attributes && Object.keys(node.attributes).length" class="detail__card">
        <h3>属性</h3>
        <pre class="detail__json">{{ JSON.stringify(node.attributes, null, 2) }}</pre>
      </section>

      <section class="detail__card">
        <h3>原始 JSON</h3>
        <pre class="detail__json">{{ rawText }}</pre>
      </section>
    </div>
  </aside>
</template>

<style scoped>
.detail {
  display: grid;
  grid-template-rows: auto 1fr;
  min-height: 0;
  padding: 0;
  border: none;
  background: transparent;
}

.detail__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 4px 2px 12px;
  border-bottom: 1px solid var(--border);
  margin-bottom: 0;
}

.detail__header h2 {
  margin: 0;
}

.detail__header span,
.detail__empty small,
.detail__list dt {
  color: var(--muted);
}

.detail__empty {
  display: grid;
  place-items: center;
  gap: 10px;
  min-height: 220px;
  padding: 28px 20px;
  border: 1px dashed var(--border);
  border-radius: 0;
  color: var(--text);
  text-align: center;
}

.detail__empty p {
  margin: 0;
}

.detail__content {
  display: grid;
  gap: 18px;
  overflow: auto;
  padding: 18px 2px 2px;
}

.detail__card {
  display: grid;
  gap: 12px;
  padding: 0 0 18px;
  border: none;
  border-bottom: 1px solid var(--border);
  background: transparent;
}

.detail__card:last-of-type {
  border-bottom: none;
  padding-bottom: 0;
}

.detail__card h3 {
  margin: 0;
  font-size: 15px;
  color: var(--text);
}

.detail__table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}

.detail__table th,
.detail__table td {
  padding: 8px 10px;
  border: 1px solid var(--border);
  vertical-align: top;
}

.detail__table th {
  width: 92px;
  text-align: left;
  color: var(--muted);
  font-weight: 500;
  background: color-mix(in srgb, var(--panel) 60%, transparent);
}

.detail__table td {
  color: var(--text);
}

.detail__color {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  line-height: 1.2;
}

.detail__color-swatch {
  width: 12px;
  height: 12px;
  border-radius: 2px;
  border: 1px solid color-mix(in srgb, var(--border) 80%, transparent);
  box-sizing: border-box;
}

.detail__color-hex,
.detail__color-name {
  font-variant-numeric: tabular-nums;
}

.detail__list {
  display: grid;
  gap: 10px;
  margin: 0;
}

.detail__list div {
  display: grid;
  gap: 4px;
}

.detail__list dd {
  margin: 0;
  color: var(--text);
}

.detail__json {
  margin: 0;
  padding: 16px;
  border-radius: 0;
  background: color-mix(in srgb, var(--panel) 70%, black);
  color: color-mix(in srgb, var(--text) 90%, white);
  font-size: 12px;
  line-height: 1.6;
  overflow: auto;
}
</style>
