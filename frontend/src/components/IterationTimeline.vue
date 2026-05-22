<script setup lang="ts">
import type { FeedbackRecord } from '../types'

const props = defineProps<{
  iterations: FeedbackRecord[]
  currentIteration: number
  isRunning: boolean
}>()

function scoreColor(score: number): string {
  if (score >= 0.7) return 'bg-green-600'
  if (score >= 0.55) return 'bg-orange-500'
  return 'bg-red-600'
}

function verdictClass(verdict: string): string {
  if (verdict === 'pass') return 'bg-green-700 text-green-100'
  if (verdict === 'revise') return 'bg-orange-700 text-orange-100'
  return 'bg-red-700 text-red-100'
}

function scoreDelta(index: number): number | null {
  if (index === 0) return null
  const prev = props.iterations[index - 1]
  const curr = props.iterations[index]
  return curr.score - prev.score
}

function deltaText(delta: number): string {
  const pct = (delta * 100).toFixed(0)
  return delta > 0 ? `+${pct}` : `${pct}`
}

function deltaColor(delta: number): string {
  if (delta > 0) return 'text-green-400'
  if (delta < 0) return 'text-red-400'
  return 'text-slate-400'
}

function issuesDelta(index: number): number | null {
  if (index === 0) return null
  return props.iterations[index].issues_count - props.iterations[index - 1].issues_count
}
</script>

<template>
  <div class="bg-slate-800 rounded-lg border border-slate-700 p-4">
    <h3 class="text-sm font-medium text-slate-300 mb-3">QA 反馈循环</h3>
    <div class="flex items-start gap-2 overflow-x-auto pb-2">
      <!-- Completed iterations with delta arrows -->
      <template v-for="(iter, idx) in iterations" :key="iter.iteration">
        <!-- Delta arrow between cards -->
        <div v-if="idx > 0" class="flex-shrink-0 flex flex-col items-center justify-center w-[48px] self-center">
          <svg class="w-4 h-4 text-slate-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7"/>
          </svg>
          <span :class="['text-[11px] font-bold', deltaColor(scoreDelta(idx)!)]">
            {{ deltaText(scoreDelta(idx)!) }}%
          </span>
          <span v-if="issuesDelta(idx) !== null && issuesDelta(idx)! < 0" class="text-[10px] text-green-400">
            {{ issuesDelta(idx) }} 问题
          </span>
        </div>

        <!-- Iteration card -->
        <div class="flex-shrink-0 w-[200px] rounded-lg border border-slate-600 bg-slate-900 p-3">
          <div class="flex items-center justify-between mb-2">
            <span class="text-xs text-slate-400">第 {{ iter.iteration }} 轮</span>
            <span
              :class="['px-1.5 py-0.5 rounded text-[10px] font-medium', verdictClass(iter.verdict)]"
            >
              {{ iter.verdict.toUpperCase() }}
            </span>
          </div>
          <div class="flex items-center gap-2 mb-2">
            <div
              :class="['w-8 h-8 rounded-full flex items-center justify-center text-xs font-bold text-white', scoreColor(iter.score)]"
            >
              {{ (iter.score * 100).toFixed(0) }}
            </div>
            <div class="text-xs text-slate-400">
              <div>{{ iter.issues_count }} 问题</div>
              <div v-if="iter.critical_issues">{{ iter.critical_issues }} 严重</div>
            </div>
          </div>
          <div class="text-[11px] text-slate-400 leading-tight">
            <div v-if="iter.action_taken" class="mb-1 text-slate-300 font-medium">{{ iter.action_taken }}</div>
            <div class="line-clamp-2">{{ iter.feedback_summary || '—' }}</div>
          </div>
        </div>
      </template>

      <!-- Current in-progress iteration -->
      <div
        v-if="isRunning && currentIteration > iterations.length"
        class="flex-shrink-0 w-[200px] rounded-lg border border-blue-500/50 bg-slate-900 p-3 animate-pulse"
      >
        <div class="flex items-center justify-between mb-2">
          <span class="text-xs text-slate-400">第 {{ currentIteration }} 轮</span>
          <span class="px-1.5 py-0.5 rounded text-[10px] font-medium bg-blue-700 text-blue-100">
            RUNNING
          </span>
        </div>
        <div class="h-8 bg-slate-700 rounded animate-pulse mb-2"></div>
        <div class="h-3 bg-slate-700 rounded w-3/4"></div>
      </div>

      <!-- Empty state -->
      <template v-if="iterations.length === 0 && !isRunning">
        <div class="flex items-center justify-center text-slate-500 text-sm w-full py-4">
          等待 QA 反馈...
        </div>
      </template>
    </div>

    <!-- Overall improvement summary -->
    <div v-if="iterations.length >= 2" class="mt-3 px-3 py-2 rounded-md bg-slate-900 border border-slate-700 flex items-center gap-4">
      <span class="text-xs text-slate-400">反馈闭环效果:</span>
      <span class="text-xs font-medium" :class="deltaColor(iterations[iterations.length - 1].score - iterations[0].score)">
        分数 {{ (iterations[0].score * 100).toFixed(0) }}%
        → {{ (iterations[iterations.length - 1].score * 100).toFixed(0) }}%
        ({{ deltaText(iterations[iterations.length - 1].score - iterations[0].score) }}%)
      </span>
      <span class="text-xs text-slate-400">|</span>
      <span class="text-xs text-slate-300">
        问题数 {{ iterations[0].issues_count }} → {{ iterations[iterations.length - 1].issues_count }}
      </span>
      <span class="text-xs text-slate-400">|</span>
      <span class="text-xs text-slate-300">
        共 {{ iterations.length }} 轮迭代
      </span>
    </div>
  </div>
</template>
