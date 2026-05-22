<script setup lang="ts">
import { computed } from 'vue'
import { Handle, Position } from '@vue-flow/core'
import type { NodeStatus } from '../types'

const props = defineProps<{
  data: { label: string; status: NodeStatus }
}>()

const statusClasses = computed(() => {
  switch (props.data.status) {
    case 'running':
      return 'bg-blue-600 border-blue-400 animate-pulse'
    case 'done':
      return 'bg-green-700 border-green-500'
    case 'error':
      return 'bg-red-700 border-red-500'
    case 'revise':
      return 'bg-orange-600 border-orange-400'
    default:
      return 'bg-slate-700 border-slate-500'
  }
})

const statusIcon = computed(() => {
  switch (props.data.status) {
    case 'running': return '⟳'
    case 'done': return '✓'
    case 'error': return '✗'
    case 'revise': return '↺'
    default: return '○'
  }
})
</script>

<template>
  <div
    :class="[
      'w-[120px] px-3 py-3 rounded-lg border-2 text-center transition-all duration-300',
      statusClasses
    ]"
  >
    <Handle type="target" :position="Position.Left" class="!bg-slate-400" />
    <div class="text-lg mb-1">{{ statusIcon }}</div>
    <div class="text-sm font-semibold text-white">{{ data.label }}</div>
    <div class="text-xs text-slate-200 mt-1 capitalize">{{ data.status }}</div>
    <Handle type="source" :position="Position.Right" class="!bg-slate-400" />
  </div>
</template>
