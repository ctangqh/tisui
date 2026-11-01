<script setup lang="ts">
import PlaygroundDetailPanel from '@/components/playground/PlaygroundDetailPanel.vue'
import type { PlaygroundNode, VisionControlExportResult } from '@/types/playground'

defineProps<{
  node: PlaygroundNode | undefined
  rawVisionData?: VisionControlExportResult
}>()
</script>

<template>
  <PlaygroundDetailPanel :node="node" :raw-vision-data="rawVisionData" />
</template>

