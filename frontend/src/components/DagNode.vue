<script setup lang="ts">
import { computed } from 'vue'
import { Handle, Position } from '@vue-flow/core'
import type { NodeStatus } from '../types'

const props = defineProps<{
  data: { label: string; status: NodeStatus }
}>()

// Ring progress: running=75%, done=100%, else=0%
const ringProgress = computed(() => {
  if (props.data.status === 'done') return 100
  if (props.data.status === 'running') return 75
  return 0
})

const circumference = 2 * Math.PI * 22 // r=22
const strokeDashoffset = computed(() =>
  circumference - (ringProgress.value / 100) * circumference
)

const ringColor = computed(() => {
  switch (props.data.status) {
    case 'running': return '#60a5fa'  // blue-400
    case 'done':    return '#34d399'  // emerald-400
    case 'error':   return '#f87171'  // red-400
    case 'revise':  return '#fb923c'  // orange-400
    default:        return '#475569'  // slate-600
  }
})

const glowColor = computed(() => {
  switch (props.data.status) {
    case 'running': return '0 0 16px 3px rgba(96,165,250,0.55)'
    case 'done':    return '0 0 14px 2px rgba(52,211,153,0.5)'
    case 'error':   return '0 0 14px 2px rgba(248,113,113,0.5)'
    case 'revise':  return '0 0 14px 2px rgba(251,146,60,0.5)'
    default:        return 'none'
  }
})

const statusIcon = computed(() => {
  switch (props.data.status) {
    case 'running': return '⟳'
    case 'done':    return '✓'
    case 'error':   return '✗'
    case 'revise':  return '↺'
    default:        return '○'
  }
})

const statusLabel = computed(() => {
  switch (props.data.status) {
    case 'running': return 'running'
    case 'done':    return 'done'
    case 'error':   return 'error'
    case 'revise':  return 'revise'
    default:        return 'idle'
  }
})
</script>

<template>
  <div
    class="relative flex items-center justify-center"
    style="width: 96px; height: 96px;"
  >
    <Handle type="target" :position="Position.Left" class="!bg-slate-500 !border-slate-600" />

    <!-- SVG ring -->
    <svg
      width="96" height="96"
      class="absolute inset-0"
      style="transform: rotate(-90deg);"
    >
      <!-- track -->
      <circle
        cx="48" cy="48" r="44"
        fill="none"
        stroke="#1e293b"
        stroke-width="4"
      />
      <!-- progress arc -->
      <circle
        v-if="ringProgress > 0"
        cx="48" cy="48" r="44"
        fill="none"
        :stroke="ringColor"
        stroke-width="4"
        stroke-linecap="round"
        :stroke-dasharray="circumference"
        :stroke-dashoffset="strokeDashoffset"
        :class="data.status === 'running' ? 'ring-spin' : ''"
        style="transition: stroke-dashoffset 0.6s ease;"
      />
    </svg>

    <!-- inner card -->
    <div
      class="relative z-10 flex flex-col items-center justify-center rounded-xl text-center transition-all duration-300"
      style="width: 72px; height: 72px; background: #0f172a; border: 1.5px solid #1e293b;"
      :style="{ boxShadow: glowColor }"
    >
      <div class="text-base leading-none mb-1" :style="{ color: ringColor }">{{ statusIcon }}</div>
      <div class="text-[11px] font-semibold text-slate-100 leading-tight">{{ data.label }}</div>
      <div class="text-[9px] mt-0.5" :style="{ color: ringColor }">{{ data.sub || statusLabel }}</div>
    </div>

    <Handle type="source" :position="Position.Right" class="!bg-slate-500 !border-slate-600" />
  </div>
</template>

<style scoped>
.ring-spin {
  animation: ring-rotate 1.6s linear infinite;
  transform-origin: 48px 48px;
}
@keyframes ring-rotate {
  from { stroke-dashoffset: v-bind(circumference); }
  to   { stroke-dashoffset: 0; }
}
</style>
