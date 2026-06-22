<script setup lang="ts">
import { computed } from 'vue'
import { Handle, Position } from '@vue-flow/core'
import type { NodeStatus } from '../types'

const props = defineProps<{
  data: { label: string; sub?: string; status: NodeStatus; role?: string }
}>()

// ---- 角色 Emoji 映射 ----
const roleEmoji = computed(() => {
  const map: Record<string, string> = {
    discovery: '🔍',
    collector: '📡',
    analyst: '🧠',
    writer: '✍️',
    qa: '🛡️',
  }
  return map[props.data.role || ''] || '🔹'
})

// Ring progress: running=80%, done=100%, else=0%
const ringProgress = computed(() => {
  if (props.data.status === 'done') return 100
  if (props.data.status === 'running') return 80
  return 0
})

const circumference = 2 * Math.PI * 37
const strokeDashoffset = computed(() =>
  circumference - (ringProgress.value / 100) * circumference
)

const ringColor = computed(() => {
  switch (props.data.status) {
    case 'running': return '#818cf8'  // indigo-400
    case 'done':    return '#34d399'  // emerald-400
    case 'error':   return '#f87171'  // red-400
    case 'revise':  return '#fb923c'  // orange-400
    default:        return '#475569'  // slate-600
  }
})

const glowColor = computed(() => {
  switch (props.data.status) {
    case 'running': return '0 0 20px 4px rgba(129,140,248,0.6), 0 0 40px 2px rgba(129,140,248,0.2)'
    case 'done':    return '0 0 16px 3px rgba(52,211,153,0.5)'
    case 'error':   return '0 0 18px 3px rgba(248,113,113,0.6)'
    case 'revise':  return '0 0 18px 3px rgba(251,146,60,0.6)'
    default:        return 'none'
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
    style="width: 82px; height: 82px;"
  >
    <Handle type="target" :position="Position.Left" class="!bg-slate-500 !border-slate-600" />

    <!-- SVG ring -->
    <svg
      width="82" height="82"
      class="absolute inset-0"
      style="transform: rotate(-90deg);"
    >
      <!-- track -->
      <circle
        cx="41" cy="41" r="37"
        fill="none"
        stroke="#1e293b"
        stroke-width="3"
      />
      <!-- progress arc -->
      <circle
        v-if="ringProgress > 0"
        cx="41" cy="41" r="37"
        fill="none"
        :stroke="ringColor"
        stroke-width="3"
        stroke-linecap="round"
        :stroke-dasharray="circumference"
        :stroke-dashoffset="strokeDashoffset"
        :class="data.status === 'running' ? 'ring-spin' : ''"
        style="transition: stroke-dashoffset 0.6s ease;"
      />
    </svg>

    <!-- inner card -->
    <div
      class="relative z-10 flex flex-col items-center justify-center rounded-lg text-center transition-all duration-300"
      :class="{ 'node-pulse': data.status === 'running' }"
      style="width: 62px; height: 62px; background: #0f172a; border: 1.5px solid #1e293b;"
      :style="{ boxShadow: glowColor }"
    >
      <div class="text-base leading-none mb-0.5">{{ roleEmoji }}</div>
      <div class="text-[11px] font-semibold text-slate-100 leading-tight">{{ data.label }}</div>
      <div class="text-[9px] mt-0.5" :style="{ color: ringColor }">{{ data.sub || statusLabel }}</div>
    </div>

    <Handle type="source" :position="Position.Right" class="!bg-slate-500 !border-slate-600" />
  </div>
</template>

<style scoped>
.ring-spin {
  animation: ring-rotate 2s linear infinite;
  transform-origin: 41px 41px;
}
@keyframes ring-rotate {
  from { stroke-dashoffset: v-bind(circumference); }
  to   { stroke-dashoffset: 0; }
}

.node-pulse {
  animation: node-breathe 1.8s ease-in-out infinite;
}
@keyframes node-breathe {
  0%, 100% { box-shadow: 0 0 20px 4px rgba(129,140,248,0.6), 0 0 40px 2px rgba(129,140,248,0.2); }
  50%      { box-shadow: 0 0 30px 8px rgba(129,140,248,0.85), 0 0 60px 4px rgba(129,140,248,0.35); }
}
</style>
