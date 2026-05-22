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
</script>

<template>
  <div class="bg-slate-800 rounded-lg border border-slate-700 p-4">
    <h3 class="text-sm font-medium text-slate-300 mb-3">QA 反馈循环</h3>
    <div class="flex items-start gap-3 overflow-x-auto pb-2">
      <!-- Completed iterations -->
      <div
        v-for="iter in iterations"
        :key="iter.iteration"
        class="flex-shrink-0 w-[200px] rounded-lg border border-slate-600 bg-slate-900 p-3"
      >
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

      <!-- Arrow between cards -->
      <template v-if="iterations.length === 0 && !isRunning">
        <div class="flex items-center justify-center text-slate-500 text-sm w-full py-4">
          等待 QA 反馈...
        </div>
      </template>
    </div>
  </div>
</template>
