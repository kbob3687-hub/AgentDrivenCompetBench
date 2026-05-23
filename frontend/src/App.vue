<script setup lang="ts">
import { computed, onMounted } from 'vue'
import AnalysisForm from './components/AnalysisForm.vue'
import DagView from './components/DagView.vue'
import LogStream from './components/LogStream.vue'
import ResultPanel from './components/ResultPanel.vue'
import IterationTimeline from './components/IterationTimeline.vue'
import { useAnalysis } from './composables/useAnalysis'

const { state, startAnalysis, restoreFromHash, intervene } = useAnalysis()

const isRunning = computed(() => state.status === 'running')
const isCompleted = computed(() => state.status === 'completed')

function handleSubmit(payload: { competitorName: string; dimensions: string[]; industry: string; targetUrls: string[] }) {
  startAnalysis(payload.competitorName, payload.dimensions, payload.industry, payload.targetUrls)
}

onMounted(() => {
  restoreFromHash()
})
</script>

<template>
  <div class="min-h-screen bg-slate-950 text-slate-100">
    <!-- Header -->
    <header class="border-b border-slate-800 px-6 py-4">
      <div class="max-w-7xl mx-auto flex items-center justify-between">
        <div class="flex items-center gap-3">
          <div class="w-8 h-8 bg-blue-600 rounded-lg flex items-center justify-center text-sm font-bold">
            CA
          </div>
          <h1 class="text-lg font-semibold text-slate-100">竞品分析 Agent</h1>
        </div>
        <div class="flex items-center gap-2 text-sm text-slate-400">
          <span
            :class="[
              'w-2 h-2 rounded-full',
              isRunning ? 'bg-blue-500 animate-pulse' : isCompleted ? 'bg-green-500' : 'bg-slate-600'
            ]"
          ></span>
          <span>{{ state.status === 'idle' ? '就绪' : state.status === 'running' ? '分析中...' : state.status === 'completed' ? '已完成' : '失败' }}</span>
          <span v-if="state.currentIteration > 0" class="text-slate-500">
            | 第 {{ state.currentIteration }} 轮
          </span>
        </div>
      </div>
    </header>

    <main class="max-w-7xl mx-auto px-6 py-6 space-y-6">
      <!-- Analysis Form -->
      <AnalysisForm :disabled="isRunning" @submit="handleSubmit" />

      <!-- DAG + Logs -->
      <div v-if="state.status !== 'idle'" class="grid grid-cols-5 gap-4 h-[350px]">
        <div class="col-span-3">
          <DagView :node-states="state.nodeStates" :sub-agents="state.subAgents" />
        </div>
        <div class="col-span-2">
          <LogStream :logs="state.logs" />
        </div>
      </div>

      <!-- Iteration Timeline -->
      <IterationTimeline
        v-if="state.status !== 'idle' && (state.iterations.length > 0 || state.currentIteration > 0)"
        :iterations="state.iterations"
        :current-iteration="state.currentIteration"
        :is-running="isRunning"
        @intervene="(action) => intervene(action)"
      />

      <!-- Result Panel -->
      <ResultPanel v-if="isCompleted && state.result" :result="state.result" />
    </main>
  </div>
</template>
