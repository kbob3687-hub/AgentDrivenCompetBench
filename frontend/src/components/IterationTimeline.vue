<script setup lang="ts">
import { ref } from 'vue'
import type { FeedbackRecord, PauseContext } from '../types'

const props = defineProps<{
  iterations: FeedbackRecord[]
  currentIteration: number
  isRunning: boolean
  isPaused: boolean
  pauseVerdict: 'pass' | 'revise' | null
  pauseContext: PauseContext | null
}>()

const emit = defineEmits<{
  intervene: [action: 'force_pass' | 'abort' | 'continue']
}>()

const submitting = ref(false)

function handleIntervene(action: 'force_pass' | 'abort' | 'continue') {
  if (submitting.value) return
  submitting.value = true
  emit('intervene', action)
  // 保底：5秒后自动解锁，防止按钮永久卡死
  setTimeout(() => { submitting.value = false }, 5000)
}

function scoreColor(score: number): string {
  if (score >= 0.7) return 'bg-emerald-500'
  if (score >= 0.55) return 'bg-orange-400'
  return 'bg-red-500'
}

function verdictClass(verdict: string): string {
  if (verdict === 'pass') return 'bg-emerald-100 text-emerald-700'
  if (verdict === 'revise') return 'bg-orange-100 text-orange-700'
  return 'bg-red-100 text-red-700'
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
  <div class="bg-white rounded-lg border border-slate-200 p-4 shadow-sm">
    <h3 class="text-sm font-medium text-slate-600 mb-3">QA 反馈循环</h3>
    <div class="flex items-start gap-2 overflow-x-auto pb-2">
      <!-- Completed iterations with delta arrows -->
      <template v-for="(iter, idx) in iterations" :key="iter.iteration">
        <!-- Delta arrow between cards -->
        <div v-if="idx > 0" class="flex-shrink-0 flex flex-col items-center justify-center w-[48px] self-center">
          <svg class="w-4 h-4 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
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
        <div class="flex-shrink-0 w-[200px] rounded-lg border border-slate-200 bg-slate-50 p-3">
          <div class="flex items-center justify-between mb-2">
            <span class="text-xs text-slate-500">第 {{ iter.iteration }} 轮</span>
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
            <div class="text-xs text-slate-500">
              <div>{{ iter.issues_count }} 问题</div>
              <div v-if="iter.critical_issues">{{ iter.critical_issues }} 严重</div>
            </div>
          </div>
          <div class="text-[11px] text-slate-500 leading-tight">
            <div v-if="iter.action_taken" class="mb-1 text-slate-600 font-medium">{{ iter.action_taken }}</div>
            <div class="line-clamp-2">{{ iter.feedback_summary || '—' }}</div>
          </div>
        </div>
      </template>

      <!-- Current in-progress iteration -->
      <div
        v-if="isRunning && currentIteration > iterations.length"
        class="flex-shrink-0 w-[200px] rounded-lg border border-blue-300 bg-blue-50 p-3 animate-pulse"
      >
        <div class="flex items-center justify-between mb-2">
          <span class="text-xs text-slate-500">第 {{ currentIteration }} 轮</span>
          <span class="px-1.5 py-0.5 rounded text-[10px] font-medium bg-blue-100 text-blue-700">
            RUNNING
          </span>
        </div>
        <div class="h-8 bg-blue-100 rounded animate-pulse mb-2"></div>
        <div class="h-3 bg-blue-100 rounded w-3/4"></div>
      </div>

      <!-- Empty state -->
      <template v-if="iterations.length === 0 && !isRunning">
        <div class="flex items-center justify-center text-slate-500 text-sm w-full py-4">
          等待 QA 反馈...
        </div>
      </template>
    </div>

    <!-- Overall improvement summary -->
    <div v-if="iterations.length >= 2" class="mt-3 px-3 py-2 rounded-md bg-slate-50 border border-slate-200 flex items-center gap-4">
      <span class="text-xs text-slate-500">反馈闭环效果:</span>
      <span class="text-xs font-medium" :class="deltaColor(iterations[iterations.length - 1].score - iterations[0].score)">
        分数 {{ (iterations[0].score * 100).toFixed(0) }}%
        → {{ (iterations[iterations.length - 1].score * 100).toFixed(0) }}%
        ({{ deltaText(iterations[iterations.length - 1].score - iterations[0].score) }}%)
      </span>
      <span class="text-xs text-slate-400">|</span>
      <span class="text-xs text-slate-600">
        问题数 {{ iterations[0].issues_count }} → {{ iterations[iterations.length - 1].issues_count }}
      </span>
      <span class="text-xs text-slate-400">|</span>
      <span class="text-xs text-slate-600">
        共 {{ iterations.length }} 轮迭代
      </span>
    </div>

    <!-- 人工介入按钮 -->
    <div
      v-if="isPaused"
      class="mt-3 px-4 py-3 rounded-md bg-orange-50 border border-orange-200"
    >
      <!-- 决策依据 -->
      <div v-if="pauseContext" class="mb-3 flex items-center gap-4 text-xs">
        <div class="flex items-center gap-1.5">
          <span class="text-slate-500">QA 评分:</span>
          <span
            :class="[
              'px-1.5 py-0.5 rounded font-bold',
              pauseContext.score >= 0.7 ? 'bg-emerald-100 text-emerald-700' : pauseContext.score >= 0.55 ? 'bg-orange-100 text-orange-700' : 'bg-red-100 text-red-700'
            ]"
          >
            {{ (pauseContext.score * 100).toFixed(0) }}%
          </span>
        </div>
        <div class="flex items-center gap-1.5">
          <span class="text-slate-500">轮次:</span>
          <span class="text-slate-700">第 {{ pauseContext.iteration }} 轮</span>
        </div>
        <div v-if="pauseContext.missing_dimensions.length" class="flex items-center gap-1.5">
          <span class="text-slate-500">缺失维度:</span>
          <span
            v-for="dim in pauseContext.missing_dimensions"
            :key="dim"
            class="px-1.5 py-0.5 rounded bg-red-100 text-red-600 text-[11px]"
          >
            {{ dim }}
          </span>
        </div>
        <div v-if="pauseContext.message" class="text-slate-500 truncate max-w-[200px]" :title="pauseContext.message">
          {{ pauseContext.message }}
        </div>
      </div>

      <!-- 操作按钮 -->
      <div class="flex items-center gap-3">
        <!-- QA pass: 确认发布 or 打回重跑 -->
        <template v-if="pauseVerdict === 'pass'">
          <span class="text-xs text-orange-600">QA 已通过，等待人工确认发布</span>
          <button
            :disabled="submitting"
            class="px-3 py-1 text-xs font-medium rounded bg-green-700 text-green-100 hover:bg-green-600 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            @click="handleIntervene('force_pass')"
          >
            {{ submitting ? '提交中...' : '确认发布' }}
          </button>
          <button
            :disabled="submitting"
            class="px-3 py-1 text-xs font-medium rounded bg-blue-700 text-blue-100 hover:bg-blue-600 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            @click="handleIntervene('continue')"
          >
            打回重跑
          </button>
          <button
            :disabled="submitting"
            class="px-3 py-1 text-xs font-medium rounded bg-red-700 text-red-100 hover:bg-red-600 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            @click="handleIntervene('abort')"
          >
            终止任务
          </button>
        </template>
        <!-- QA revise: 继续迭代 / 强制通过 / 终止 -->
        <template v-else>
          <span class="text-xs text-orange-600">QA 打回，等待人工审核决策</span>
          <button
            :disabled="submitting"
            class="px-3 py-1 text-xs font-medium rounded bg-blue-700 text-blue-100 hover:bg-blue-600 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            @click="handleIntervene('continue')"
          >
            {{ submitting ? '提交中...' : '继续迭代' }}
          </button>
          <button
            :disabled="submitting"
            class="px-3 py-1 text-xs font-medium rounded bg-green-700 text-green-100 hover:bg-green-600 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            @click="handleIntervene('force_pass')"
          >
            强制通过
          </button>
          <button
            :disabled="submitting"
            class="px-3 py-1 text-xs font-medium rounded bg-red-700 text-red-100 hover:bg-red-600 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            @click="handleIntervene('abort')"
          >
            终止任务
          </button>
        </template>
      </div>
    </div>
  </div>
</template>
