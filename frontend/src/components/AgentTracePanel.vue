<script setup lang="ts">
import { computed } from 'vue'
import type { AgentTrace } from '../types'

const props = defineProps<{
  traces: AgentTrace[]
  traceId?: string | null
  traceUrl?: string | null
}>()

const totalTokens = computed(() =>
  props.traces.reduce((sum, t) => sum + t.input_tokens + t.output_tokens, 0)
)

const totalDuration = computed(() =>
  props.traces.reduce((sum, t) => sum + t.duration_ms, 0)
)

const estimatedCost = computed(() => {
  let cost = 0
  for (const t of props.traces) {
    if (t.model?.includes('deepseek')) {
      cost += t.input_tokens * 0.0000001 + t.output_tokens * 0.0000002
    } else {
      cost += t.input_tokens * 0.000003 + t.output_tokens * 0.000015
    }
  }
  return cost
})

const langfuseUrl = computed(() => {
  return props.traceUrl || ''
})

function agentColor(agent: string): string {
  const colors: Record<string, string> = {
    discovery: 'border-indigo-500 bg-indigo-50',
    collector: 'border-blue-500 bg-blue-50',
    analyst: 'border-purple-500 bg-purple-50',
    writer: 'border-green-500 bg-green-50',
    qa: 'border-orange-500 bg-orange-50',
  }
  return colors[agent] || 'border-slate-500 bg-slate-50'
}

function agentDotColor(agent: string): string {
  const colors: Record<string, string> = {
    discovery: 'bg-indigo-500',
    collector: 'bg-blue-500',
    analyst: 'bg-purple-500',
    writer: 'bg-green-500',
    qa: 'bg-orange-500',
  }
  return colors[agent] || 'bg-slate-500'
}
</script>

<template>
  <div>
    <div v-if="!traces.length" class="flex items-center justify-center py-10 text-sm text-slate-500">
      Agent Trace 会在任务完成后显示。
    </div>

    <template v-else>
      <div class="grid grid-cols-4 gap-3 mb-4">
        <div class="rounded-md border border-slate-200 bg-slate-50 p-3">
          <div class="mb-1 text-xs text-slate-500">总耗时</div>
          <div :key="totalDuration" class="metric-value text-lg font-bold text-slate-800">{{ (totalDuration / 1000).toFixed(1) }}s</div>
        </div>
        <div class="rounded-md border border-slate-200 bg-slate-50 p-3">
          <div class="mb-1 text-xs text-slate-500">总 Token</div>
          <div :key="totalTokens" class="metric-value text-lg font-bold text-slate-800">{{ totalTokens.toLocaleString() }}</div>
        </div>
        <div class="rounded-md border border-slate-200 bg-slate-50 p-3">
          <div class="mb-1 text-xs text-slate-500">预估成本</div>
          <div :key="estimatedCost" class="metric-value text-lg font-bold text-slate-800">${{ estimatedCost.toFixed(4) }}</div>
        </div>
        <div class="rounded-md border border-slate-200 bg-slate-50 p-3">
          <div class="mb-1 text-xs text-slate-500">Agent 调用</div>
          <div :key="traces.length" class="metric-value text-lg font-bold text-slate-800">{{ traces.length }} 次</div>
        </div>
      </div>

      <div class="space-y-3">
        <div
          v-for="(trace, idx) in traces"
          :key="`${trace.agent}-${trace.iteration}-${idx}`"
          :class="['rounded-md border border-slate-200 border-l-4 p-3', agentColor(trace.agent)]"
        >
          <div class="mb-2 flex items-center justify-between gap-3">
            <div class="flex items-center gap-2">
              <span :class="['h-2.5 w-2.5 rounded-full', agentDotColor(trace.agent)]"></span>
              <span class="text-sm font-medium capitalize text-slate-700">{{ trace.agent }}</span>
              <span class="text-xs text-slate-500">iter {{ trace.iteration }}</span>
            </div>
            <div class="flex items-center gap-3 text-xs text-slate-500">
              <span>{{ trace.model }}</span>
              <span class="font-mono">{{ (trace.duration_ms / 1000).toFixed(1) }}s</span>
            </div>
          </div>
          <div class="mb-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-slate-500">
            <span>Input <span class="font-mono text-slate-700">{{ trace.input_tokens.toLocaleString() }}</span></span>
            <span>Output <span class="font-mono text-slate-700">{{ trace.output_tokens.toLocaleString() }}</span></span>
          </div>
          <div v-if="trace.prompt_preview" class="mb-1 text-xs text-slate-600">
            <span class="text-slate-500">Prompt:</span> {{ trace.prompt_preview }}
          </div>
          <div v-if="trace.output_preview" class="text-xs text-slate-600">
            <span class="text-slate-500">Output:</span> {{ trace.output_preview }}
          </div>
        </div>
      </div>

      <div class="mt-4 flex items-center justify-between gap-3 border-t border-slate-200 pt-3">
        <span class="min-w-0 truncate text-xs text-slate-500">
          Langfuse Trace
          <span v-if="traceId" class="font-mono text-slate-600">{{ traceId }}</span>
          <span v-else>任务完成后生成</span>
        </span>
        <a
          v-if="langfuseUrl"
          :href="langfuseUrl"
          target="_blank"
          rel="noopener noreferrer"
          class="shrink-0 rounded-md bg-slate-100 px-3 py-1.5 text-xs text-slate-600 transition-colors hover:bg-slate-200"
        >
          在 Langfuse 中查看
        </a>
        <span v-else class="shrink-0 text-xs text-amber-600">
          未生成云端链接
        </span>
      </div>
    </template>
  </div>
</template>

<style scoped>
.metric-value {
  animation: metric-pop 0.22s ease-out;
}

@keyframes metric-pop {
  0% {
    transform: translateY(2px) scale(0.98);
    opacity: 0.75;
  }
  100% {
    transform: translateY(0) scale(1);
    opacity: 1;
  }
}
</style>
