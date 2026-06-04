<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import AnalysisForm from './components/AnalysisForm.vue'
import DagView from './components/DagView.vue'
import LogStream from './components/LogStream.vue'
import ResultPanel from './components/ResultPanel.vue'
import IterationTimeline from './components/IterationTimeline.vue'
import CompareView from './components/CompareView.vue'
import ReportWorkspace from './components/ReportWorkspace.vue'
import { useAnalysis } from './composables/useAnalysis'
import type { InterventionAction, InterventionPayload } from './types'

const { state, startAnalysis, restoreFromHash, intervene } = useAnalysis()

const viewMode = ref<'analysis' | 'compare'>('analysis')

const isRunning = computed(() => state.status === 'running')
const isCompleted = computed(() => state.status === 'completed')
const isPaused = computed(() => state.status === 'paused')

function handleSubmit(payload: { competitorName: string; dimensions: string[]; industry: string; targetUrls: string[] }) {
  startAnalysis(payload.competitorName, payload.dimensions, payload.industry, payload.targetUrls)
}

function handleIntervene(payload: InterventionAction | InterventionPayload) {
  intervene(payload)
}

onMounted(() => {
  restoreFromHash()
})
</script>

<template>
  <div class="min-h-screen bg-slate-50 text-slate-800">
    <!-- Header -->
    <header class="border-b border-slate-200 bg-white px-6 py-4 shadow-sm">
      <div class="max-w-7xl mx-auto flex items-center justify-between">
        <div class="flex items-center gap-3">
          <div class="w-8 h-8 bg-gradient-to-br from-blue-500 to-indigo-600 rounded-lg flex items-center justify-center text-sm font-bold text-white shadow-sm">
            CA
          </div>
          <h1 class="text-lg font-semibold text-slate-800">竞品分析 Agent</h1>
        </div>
        <div class="flex items-center gap-2 text-sm text-slate-500">
          <button
            :class="[
              'px-3 py-1.5 text-xs font-medium rounded transition-colors',
              viewMode === 'compare'
                ? 'bg-indigo-100 text-indigo-700'
                : 'border border-slate-300 text-slate-600 hover:bg-slate-50'
            ]"
            @click="viewMode = viewMode === 'compare' ? 'analysis' : 'compare'"
          >
            {{ viewMode === 'compare' ? '返回分析' : '多竞品对比' }}
          </button>
          <span
            :class="[
              'w-2 h-2 rounded-full',
              isRunning ? 'bg-blue-500 animate-pulse' : isPaused ? 'bg-orange-500 animate-pulse' : isCompleted ? 'bg-emerald-500' : 'bg-slate-400'
            ]"
          ></span>
          <span>{{ state.status === 'idle' ? '就绪' : state.status === 'running' ? '分析中...' : state.status === 'paused' ? '等待审核' : state.status === 'completed' ? '已完成' : '失败' }}</span>
          <span v-if="state.currentIteration > 0" class="text-slate-500">
            | 第 {{ state.currentIteration }} 轮
          </span>
        </div>
      </div>
    </header>

    <main class="mx-auto max-w-[1800px] px-4 py-5 sm:px-6">
      <!-- Compare View -->
      <CompareView v-if="viewMode === 'compare'" @close="viewMode = 'analysis'" />

      <!-- Analysis View -->
      <template v-else>
        <div class="grid gap-5 xl:grid-cols-[minmax(680px,48%)_minmax(0,1fr)] xl:items-start">
          <div class="space-y-5 min-w-0">
            <AnalysisForm :disabled="isRunning" @submit="handleSubmit" />

            <div v-if="state.status !== 'idle'" class="grid gap-4">
              <div class="h-[360px] min-h-0 overflow-hidden">
                <DagView :node-states="state.nodeStates" :sub-agents="state.subAgents" />
              </div>
              <div class="h-[260px] min-h-0 overflow-hidden">
                <LogStream :logs="state.logs" />
              </div>
            </div>

            <IterationTimeline
              v-if="state.status !== 'idle' && (state.iterations.length > 0 || state.currentIteration > 0)"
              class="relative z-10"
              :iterations="state.iterations"
              :current-iteration="state.currentIteration"
              :is-running="isRunning"
              :is-paused="isPaused"
              :pause-verdict="state.pauseVerdict"
              :pause-context="state.pauseContext"
              @intervene="handleIntervene"
            />

            <ResultPanel
              v-if="isCompleted && state.result"
              class="xl:hidden"
              :result="state.result"
              :task-id="state.taskId"
            />
          </div>

          <div class="min-w-0 xl:sticky xl:top-5 xl:h-[calc(100vh-104px)]">
            <ReportWorkspace
              :result="state.result"
              :pause-context="state.pauseContext"
              :status="state.status"
            />
          </div>
        </div>
      </template>
    </main>
  </div>
</template>
