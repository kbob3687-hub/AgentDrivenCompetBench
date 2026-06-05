<script setup lang="ts">
import { computed, ref } from 'vue'
import AgentTracePanel from './AgentTracePanel.vue'
import IterationTimeline from './IterationTimeline.vue'
import MetricsPanel from './MetricsPanel.vue'
import type { FeedbackRecord, InterventionAction, InterventionPayload, PauseContext, SSEComplete } from '../types'

const props = defineProps<{
  result: SSEComplete | null
  taskId: string | null
  iterations: FeedbackRecord[]
  currentIteration: number
  isRunning: boolean
  isPaused: boolean
  pauseVerdict: 'pass' | 'revise' | null
  pauseContext: PauseContext | null
}>()

const emit = defineEmits<{
  intervene: [payload: InterventionAction | InterventionPayload]
}>()

const activeTab = ref<'qa' | 'trace' | 'metrics'>('qa')

const traces = computed(() => props.result?.agent_traces || [])
const showMetrics = computed(() => Boolean(props.taskId && props.result))

function handleIntervene(payload: InterventionAction | InterventionPayload) {
  emit('intervene', payload)
}
</script>

<template>
  <section class="overflow-hidden rounded-lg border border-slate-200 bg-white shadow-sm">
    <div class="flex items-center justify-between gap-3 border-b border-slate-200 bg-white px-4 py-2">
      <div class="flex min-w-0 items-center gap-1 overflow-x-auto">
        <button
          :class="[
            'whitespace-nowrap rounded px-3 py-1.5 text-xs font-medium transition-colors',
            activeTab === 'qa'
              ? 'bg-blue-100 text-blue-700'
              : 'text-slate-500 hover:bg-slate-100 hover:text-slate-700'
          ]"
          @click="activeTab = 'qa'"
        >
          QA 反馈循环
        </button>
        <button
          :class="[
            'whitespace-nowrap rounded px-3 py-1.5 text-xs font-medium transition-colors',
            activeTab === 'trace'
              ? 'bg-purple-100 text-purple-700'
              : 'text-slate-500 hover:bg-slate-100 hover:text-slate-700'
          ]"
          @click="activeTab = 'trace'"
        >
          Agent Trace
          <span v-if="traces.length" class="ml-1 font-mono text-[11px] opacity-70">{{ traces.length }}</span>
        </button>
        <button
          :disabled="!showMetrics"
          :class="[
            'whitespace-nowrap rounded px-3 py-1.5 text-xs font-medium transition-colors',
            activeTab === 'metrics'
              ? 'bg-emerald-100 text-emerald-700'
              : showMetrics
                ? 'text-slate-500 hover:bg-slate-100 hover:text-slate-700'
                : 'cursor-not-allowed text-slate-300'
          ]"
          @click="showMetrics && (activeTab = 'metrics')"
        >
          观测指标
        </button>
      </div>
      <div class="hidden shrink-0 text-[11px] text-slate-400 sm:block">
        过程证明与运行观测
      </div>
    </div>

    <div class="max-h-[560px] overflow-y-auto">
      <div v-show="activeTab === 'qa'">
        <IterationTimeline
          :iterations="iterations"
          :current-iteration="currentIteration"
          :is-running="isRunning"
          :is-paused="isPaused"
          :pause-verdict="pauseVerdict"
          :pause-context="pauseContext"
          embedded
          @intervene="handleIntervene"
        />
      </div>

      <div v-show="activeTab === 'trace'" class="p-4">
        <AgentTracePanel :traces="traces" :trace-id="result?.trace_id || taskId" />
      </div>

      <div v-show="activeTab === 'metrics'" class="p-4">
        <MetricsPanel v-if="showMetrics && taskId" :task-id="taskId" embedded />
        <div v-else class="flex items-center justify-center py-10 text-sm text-slate-500">
          任务完成后显示观测指标。
        </div>
      </div>
    </div>
  </section>
</template>
