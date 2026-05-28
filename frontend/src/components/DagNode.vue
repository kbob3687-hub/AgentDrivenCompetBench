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
      return 'bg-blue-50 border-blue-400 animate-pulse shadow-blue-100'
    case 'done':
      return 'bg-emerald-50 border-emerald-400 shadow-emerald-100'
    case 'error':
      return 'bg-red-50 border-red-400 shadow-red-100'
    case 'revise':
      return 'bg-orange-50 border-orange-400 shadow-orange-100'
    default:
      return 'bg-white border-slate-300 shadow-slate-100'
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
      'w-[120px] px-3 py-3 rounded-lg border-2 text-center transition-all duration-300 shadow-sm',
      statusClasses
    ]"
  >
    <Handle type="target" :position="Position.Left" class="!bg-slate-300" />
    <div class="text-lg mb-1">{{ statusIcon }}</div>
    <div class="text-sm font-semibold text-slate-700">{{ data.label }}</div>
    <div class="text-xs text-slate-500 mt-1 capitalize">{{ data.status }}</div>
    <Handle type="source" :position="Position.Right" class="!bg-slate-300" />
  </div>
</template>
