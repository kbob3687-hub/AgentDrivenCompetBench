<script setup lang="ts">
import { ref, watch, nextTick } from 'vue'
import type { LogEntry, AgentName } from '../types'

const props = defineProps<{
  logs: LogEntry[]
}>()

const container = ref<HTMLElement | null>(null)

watch(
  () => props.logs.length,
  async () => {
    await nextTick()
    if (container.value) {
      container.value.scrollTop = container.value.scrollHeight
    }
  }
)

function formatTime(ts: number): string {
  const d = new Date(ts)
  return d.toLocaleTimeString('zh-CN', { hour12: false })
}

function agentColor(agent?: AgentName): string {
  switch (agent) {
    case 'collector': return 'bg-purple-600'
    case 'analyst': return 'bg-cyan-600'
    case 'writer': return 'bg-emerald-600'
    case 'qa': return 'bg-amber-600'
    default: return 'bg-slate-600'
  }
}

function typeColor(type: LogEntry['type']): string {
  switch (type) {
    case 'success': return 'text-green-400'
    case 'warning': return 'text-yellow-400'
    case 'error': return 'text-red-400'
    default: return 'text-slate-300'
  }
}
</script>

<template>
  <div
    ref="container"
    class="h-full overflow-y-auto bg-slate-900 rounded-lg border border-slate-700 p-3 font-mono text-xs space-y-1"
  >
    <div v-if="logs.length === 0" class="text-slate-500 text-center py-8">
      等待分析开始...
    </div>
    <div
      v-for="(log, idx) in logs"
      :key="idx"
      class="flex items-start gap-2 py-0.5"
    >
      <span class="text-slate-500 shrink-0">{{ formatTime(log.timestamp) }}</span>
      <span
        v-if="log.agent"
        :class="['px-1.5 py-0.5 rounded text-[10px] font-bold text-white shrink-0', agentColor(log.agent)]"
      >
        {{ log.agent }}
      </span>
      <span :class="typeColor(log.type)">{{ log.message }}</span>
    </div>
  </div>
</template>
