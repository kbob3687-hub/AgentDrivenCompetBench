<script setup lang="ts">
import { ref, computed, onMounted, watch, nextTick } from 'vue'
import AnalysisForm from './components/AnalysisForm.vue'
import DagView from './components/DagView.vue'
import LogStream from './components/LogStream.vue'
import CompareView from './components/CompareView.vue'
import ProcessObservabilityPanel from './components/ProcessObservabilityPanel.vue'
import ReportWorkspace from './components/ReportWorkspace.vue'
import SurveyPanel from './components/SurveyPanel.vue'
import HITLReviewCard from './components/HITLReviewCard.vue'
import { useAnalysis } from './composables/useAnalysis'
import { useDemoReplay } from './composables/useDemoReplay'
import type { InterventionAction, InterventionPayload } from './types'

const { state, startAnalysis, resetState, restoreFromHash, intervene, processEvent } = useAnalysis()
const { state: demo, start: startDemo, stop: stopDemo } = useDemoReplay(processEvent)

const showDemoOverlay = ref(false)
const demoHasPlayed = ref(false)
const demoStorageKey = 'competbench-demo-seen'

const viewMode = ref<'analysis' | 'compare' | 'survey'>('analysis')

const isRunning = computed(() => state.status === 'running' || demo.value.playing)
const isCompleted = computed(() => state.status === 'completed')
const isPaused = computed(() => state.status === 'paused')

function handleSubmit(payload: { competitorName: string; dimensions: string[]; industry: string; targetUrls: string[] }) {
  stopDemo()
  showDemoOverlay.value = false
  demoHasPlayed.value = true
  resetState()
  nextTick(() => {
    startAnalysis(payload.competitorName, payload.dimensions, payload.industry, payload.targetUrls)
  })
}

function handleIntervene(payload: InterventionAction | InterventionPayload) {
  intervene(payload)
}

function handleHITLAction(payload: { action: InterventionAction; reason?: string; urls?: string[] }) {
  intervene(payload)
}

function replayDemo() {
  stopDemo()
  showDemoOverlay.value = false
  demoHasPlayed.value = false
  resetState()
  startDemo()
}

function focusFormInput() {
  showDemoOverlay.value = false
  const input = document.querySelector<HTMLInputElement>('input')
  input?.focus()
}

onMounted(async () => {
  const restored = await restoreFromHash()
  if (!restored) {
    state.competitorName = 'Notion'
    state.industry = 'saas'
    const params = new URLSearchParams(window.location.search)
    const shouldPlayDemo = params.get('demo') === '1' || localStorage.getItem(demoStorageKey) !== 'true'
    if (shouldPlayDemo) {
      setTimeout(() => startDemo(), 500)
    }
  }
})

watch(() => demo.value.completed, (val) => {
  if (val && !demoHasPlayed.value) {
    demoHasPlayed.value = true
    localStorage.setItem(demoStorageKey, 'true')
    setTimeout(() => { showDemoOverlay.value = true }, 1200)
  }
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
          <button v-if="demo.completed"
            class="px-2.5 py-1 text-xs font-medium rounded border border-indigo-200 text-indigo-600 hover:bg-indigo-50 transition-colors"
            @click="replayDemo"
          >↻ 重播演示</button>
          <button
            :class="['px-3 py-1.5 text-xs font-medium rounded transition-colors', viewMode === 'survey' ? 'bg-emerald-100 text-emerald-700' : 'border border-slate-300 text-slate-600 hover:bg-slate-50']"
            @click="viewMode = viewMode === 'survey' ? 'analysis' : 'survey'"
          >{{ viewMode === 'survey' ? '返回分析' : '调研工具' }}</button>
          <button
            :class="['px-3 py-1.5 text-xs font-medium rounded transition-colors', viewMode === 'compare' ? 'bg-indigo-100 text-indigo-700' : 'border border-slate-300 text-slate-600 hover:bg-slate-50']"
            @click="viewMode = viewMode === 'compare' ? 'analysis' : 'compare'"
          >{{ viewMode === 'compare' ? '返回分析' : '多竞品对比' }}</button>
          <span
            :class="[
              'w-2 h-2 rounded-full',
              isRunning ? 'bg-blue-500 animate-pulse' : isPaused ? 'bg-orange-500 animate-pulse' : isCompleted ? 'bg-emerald-500' : demo.playing ? 'bg-indigo-500 animate-pulse' : 'bg-slate-400'
            ]"
          ></span>
          <span>{{ demo.playing ? '演示播放中...' : state.status === 'idle' ? '就绪' : state.status === 'running' ? '分析中...' : state.status === 'paused' ? '等待审核' : state.status === 'completed' ? '已完成' : '失败' }}</span>
          <span v-if="state.currentIteration > 0" class="text-slate-500">
            | 第 {{ state.currentIteration }} 轮
          </span>
          <span v-if="demo.playing" class="text-xs text-indigo-400 font-mono">
            {{ demo.currentIndex }}/{{ demo.totalEvents }}
          </span>
        </div>
      </div>
    </header>

    <main class="mx-auto max-w-[1800px] px-4 py-5 sm:px-6">
      <!-- Survey View -->
      <div v-if="viewMode === 'survey'" class="max-w-4xl mx-auto">
        <SurveyPanel />
      </div>

      <!-- Compare View -->
      <CompareView v-else-if="viewMode === 'compare'" @close="viewMode = 'analysis'" />

      <!-- Analysis View -->
      <template v-else>
        <div class="grid gap-5 xl:grid-cols-[minmax(680px,48%)_minmax(0,1fr)] xl:items-start">
          <div class="space-y-5 min-w-0">
            <AnalysisForm
              :disabled="isRunning"
              :competitor-name="state.competitorName"
              :industry="state.industry"
              @submit="handleSubmit"
            />

            <div v-if="state.status !== 'idle' || demo.playing" class="grid gap-4">
              <div class="relative h-[360px] min-h-0 overflow-hidden">
                <DagView :node-states="state.nodeStates" :sub-agents="state.subAgents" :qa-target-agent="state.qaTargetAgent" />
                <!-- Demo 完成后的引导浮层 -->
                <Transition name="overlay-fade">
                  <div v-if="showDemoOverlay && viewMode === 'analysis'" class="absolute inset-0 z-20 flex items-center justify-center backdrop-blur-sm" style="background: rgba(11,17,32,0.55)">
                    <div class="text-center px-8 py-6 rounded-2xl border border-indigo-500/30 shadow-2xl" style="background: rgba(15,23,42,0.92)">
                      <div class="text-3xl mb-3">🎯</div>
                      <div class="text-white text-base font-semibold mb-1">这就是竞品分析 Agent 的工作流程</div>
                      <div class="text-slate-400 text-sm mb-5">4 个 Agent 协作采集 → 分析 → 撰写 → 审核，全程自动化</div>
                      <button
                        class="px-6 py-2.5 bg-gradient-to-r from-indigo-500 to-blue-500 text-white text-sm font-medium rounded-lg shadow-lg shadow-indigo-500/30 hover:from-indigo-400 hover:to-blue-400 transition-all active:scale-95"
                        @click="focusFormInput()"
                      >开始你自己的分析 →</button>
                    </div>
                  </div>
                </Transition>
              </div>
              <div class="h-[260px] min-h-0 overflow-hidden">
                <LogStream :logs="state.logs" />
              </div>
            </div>

            <ProcessObservabilityPanel
              v-if="(state.status !== 'idle' || demo.playing) && (state.iterations.length > 0 || state.currentIteration > 0)"
              class="relative z-10"
              :result="state.result"
              :task-id="state.taskId"
              :iterations="state.iterations"
              :current-iteration="state.currentIteration"
              :is-running="isRunning"
              :is-paused="isPaused"
              :pause-verdict="state.pauseVerdict"
              :pause-context="state.pauseContext"
              @intervene="handleIntervene"
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

        <!-- HITL 审核卡片 -->
        <HITLReviewCard
          v-if="isPaused && state.pauseContext"
          :context="state.pauseContext"
          :task-id="state.taskId"
          @action="handleHITLAction"
          @dismiss="showDemoOverlay = false"
        />
      </template>
    </main>
  </div>
</template>

<style scoped>
.overlay-fade-enter-active {
  transition: opacity 0.5s ease;
}
.overlay-fade-leave-active {
  transition: opacity 0.25s ease;
}
.overlay-fade-enter-from,
.overlay-fade-leave-to {
  opacity: 0;
}
</style>
