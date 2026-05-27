<script setup lang="ts">
import { ref, computed } from 'vue'
import type { FeedbackRecord, PauseContext, QAIssueDetail } from '../types'

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
const reportExpanded = ref(false)

function handleIntervene(action: 'force_pass' | 'abort' | 'continue') {
  if (submitting.value) return
  submitting.value = true
  emit('intervene', action)
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
  if (delta > 0) return 'text-emerald-600'
  if (delta < 0) return 'text-red-600'
  return 'text-slate-500'
}

function issuesDelta(index: number): number | null {
  if (index === 0) return null
  return props.iterations[index].issues_count - props.iterations[index - 1].issues_count
}

function severityDot(severity: string): string {
  if (severity === 'critical') return 'bg-red-500'
  if (severity === 'major') return 'bg-orange-400'
  return 'bg-slate-400'
}

function severityLabel(severity: string): string {
  if (severity === 'critical') return '严重'
  if (severity === 'major') return '主要'
  return '次要'
}

const sortedIssues = computed<QAIssueDetail[]>(() => {
  const list = props.pauseContext?.issues || []
  const order: Record<string, number> = { critical: 0, major: 1, minor: 2 }
  return [...list].sort((a, b) => (order[a.severity] ?? 9) - (order[b.severity] ?? 9))
})

const trendText = computed(() => {
  const t = props.pauseContext?.score_trend || []
  if (t.length === 0) return ''
  const pcts = t.map(s => `${(s * 100).toFixed(0)}%`)
  return pcts.join(' → ')
})

const trendDelta = computed(() => {
  const t = props.pauseContext?.score_trend || []
  if (t.length < 2) return null
  return t[t.length - 1] - t[0]
})

const continueHint = computed(() => {
  const ctx = props.pauseContext
  if (!ctx) return ''
  if (ctx.iterations_left <= 0) return '已达最大迭代上限，再迭代将不再执行'
  const critical = sortedIssues.value.filter(i => i.severity === 'critical').length
  const tail = ctx.suggested_strategy && ctx.suggested_strategy !== ctx.current_strategy
    ? `（下一轮将切换数据源 → ${ctx.suggested_strategy}）`
    : ''
  return `再跑 1 轮（剩 ${ctx.iterations_left} 轮）。预期解决 ${critical} 个严重问题${tail}`
})

const forcePassHint = computed(() => {
  const ctx = props.pauseContext
  if (!ctx) return ''
  if (props.pauseVerdict === 'pass') return '当前报告将作为最终结果发布'
  return `跳过修复，直接发布当前报告（仍含 ${ctx.issues.length} 个未解决问题）`
})
</script>

<template>
  <div class="bg-white rounded-lg border border-slate-200 p-4 shadow-sm">
    <h3 class="text-sm font-medium text-slate-600 mb-3">QA 反馈循环</h3>
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
          <span v-if="issuesDelta(idx) !== null && issuesDelta(idx)! < 0" class="text-[10px] text-emerald-600">
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
      <span class="text-xs text-slate-300">|</span>
      <span class="text-xs text-slate-700">
        问题数 {{ iterations[0].issues_count }} → {{ iterations[iterations.length - 1].issues_count }}
      </span>
      <span class="text-xs text-slate-300">|</span>
      <span class="text-xs text-slate-700">
        共 {{ iterations.length }} 轮迭代
      </span>
    </div>

    <!-- 人工介入面板 -->
    <div
      v-if="isPaused"
      class="mt-3 rounded-md bg-orange-50 border border-orange-200 overflow-hidden"
    >
      <!-- 顶部状态条 -->
      <div class="px-4 py-2 bg-orange-100/60 border-b border-orange-200 flex items-center justify-between text-xs">
        <span class="text-orange-700 font-medium">
          {{ pauseVerdict === 'pass' ? '✓ QA 已通过，等待人工确认发布' : '⚠ QA 打回，等待人工审核决策' }}
        </span>
        <span v-if="pauseContext" class="text-slate-600">
          剩余可迭代轮数: <span class="font-mono font-medium">{{ pauseContext.iterations_left }}</span>
        </span>
      </div>

      <div v-if="pauseContext" class="p-4 space-y-3">
        <!-- 关键指标行 -->
        <div class="flex flex-wrap items-center gap-4 text-xs">
          <!-- 评分趋势 -->
          <div class="flex items-center gap-1.5">
            <span class="text-slate-500">评分趋势:</span>
            <span class="font-mono text-slate-700">{{ trendText }}</span>
            <span v-if="trendDelta !== null" :class="['font-bold', deltaColor(trendDelta)]">
              ({{ deltaText(trendDelta) }}%)
            </span>
          </div>
          <!-- 当前轮 -->
          <div class="flex items-center gap-1.5">
            <span class="text-slate-500">本轮:</span>
            <span class="font-mono text-slate-700">第 {{ pauseContext.iteration }} 轮</span>
          </div>
          <!-- 路由目标 -->
          <div v-if="pauseVerdict !== 'pass' && pauseContext.target_agent" class="flex items-center gap-1.5">
            <span class="text-slate-500">QA 路由:</span>
            <span class="px-1.5 py-0.5 rounded bg-blue-100 text-blue-700 font-mono">{{ pauseContext.target_agent }}</span>
          </div>
          <!-- 缺失维度 -->
          <div v-if="pauseContext.missing_dimensions.length" class="flex items-center gap-1.5">
            <span class="text-slate-500">缺失维度:</span>
            <span
              v-for="dim in pauseContext.missing_dimensions"
              :key="dim"
              class="px-1.5 py-0.5 rounded bg-red-100 text-red-600"
            >
              {{ dim }}
            </span>
          </div>
        </div>

        <!-- 策略降级提示 -->
        <div
          v-if="pauseContext.suggested_strategy && pauseContext.suggested_strategy !== pauseContext.current_strategy"
          class="px-3 py-2 rounded bg-blue-50 border border-blue-200 text-xs text-blue-700"
        >
          <span class="font-medium">↻ QA 已建议策略降级:</span>
          <span class="font-mono">{{ pauseContext.current_strategy }}</span>
          →
          <span class="font-mono font-bold">{{ pauseContext.suggested_strategy }}</span>
          <span class="text-blue-600">（继续迭代将自动换数据源）</span>
        </div>

        <!-- 字段级 diff（已解决 / 新出现） -->
        <div v-if="pauseContext.resolved_fields.length || pauseContext.regressed_fields.length" class="flex flex-wrap items-center gap-3 text-xs">
          <div v-if="pauseContext.resolved_fields.length" class="flex items-center gap-1.5">
            <span class="text-emerald-600 font-medium">✓ 已解决:</span>
            <span
              v-for="f in pauseContext.resolved_fields"
              :key="f"
              class="px-1.5 py-0.5 rounded bg-emerald-100 text-emerald-700 font-mono"
            >{{ f }}</span>
          </div>
          <div v-if="pauseContext.regressed_fields.length" class="flex items-center gap-1.5">
            <span class="text-red-600 font-medium">↑ 新增问题:</span>
            <span
              v-for="f in pauseContext.regressed_fields"
              :key="f"
              class="px-1.5 py-0.5 rounded bg-red-100 text-red-700 font-mono"
            >{{ f }}</span>
          </div>
        </div>

        <!-- Issue 明细列表 -->
        <div v-if="sortedIssues.length" class="border border-slate-200 rounded bg-white">
          <div class="px-3 py-1.5 bg-slate-50 border-b border-slate-200 text-xs text-slate-600 font-medium">
            待修复问题 ({{ sortedIssues.length }} 个)
          </div>
          <ul class="divide-y divide-slate-100 max-h-[180px] overflow-y-auto">
            <li v-for="(issue, idx) in sortedIssues" :key="idx" class="px-3 py-2 text-xs flex items-start gap-2">
              <span :class="['mt-1 w-2 h-2 rounded-full flex-shrink-0', severityDot(issue.severity)]" :title="severityLabel(issue.severity)"></span>
              <div class="flex-1 min-w-0">
                <div class="flex items-center gap-2 mb-0.5">
                  <span class="font-mono text-slate-700">{{ issue.field_path || '(全局)' }}</span>
                  <span class="text-[10px] px-1 rounded bg-slate-100 text-slate-500">{{ issue.issue_type }}</span>
                </div>
                <div class="text-slate-600">{{ issue.description }}</div>
                <div v-if="issue.suggestion" class="text-slate-500 mt-0.5">
                  <span class="text-slate-400">建议:</span> {{ issue.suggestion }}
                </div>
              </div>
            </li>
          </ul>
        </div>

        <!-- 报告预览（折叠） -->
        <div v-if="pauseContext.report_preview" class="border border-slate-200 rounded bg-white">
          <button
            @click="reportExpanded = !reportExpanded"
            class="w-full px-3 py-1.5 bg-slate-50 border-b border-slate-200 text-xs text-slate-600 font-medium flex items-center justify-between hover:bg-slate-100"
          >
            <span>报告预览（前 800 字）</span>
            <span class="text-slate-400">{{ reportExpanded ? '▲ 收起' : '▼ 展开' }}</span>
          </button>
          <pre v-if="reportExpanded" class="px-3 py-2 text-xs text-slate-700 whitespace-pre-wrap max-h-[200px] overflow-y-auto leading-relaxed">{{ pauseContext.report_preview }}</pre>
        </div>
      </div>

      <!-- 操作按钮 -->
      <div class="px-4 py-3 bg-white border-t border-orange-200 space-y-2">
        <template v-if="pauseVerdict === 'pass'">
          <div class="flex items-center gap-3 flex-wrap">
            <button
              :disabled="submitting"
              class="px-3 py-1.5 text-xs font-medium rounded bg-green-700 text-green-100 hover:bg-green-600 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
              @click="handleIntervene('force_pass')"
            >
              {{ submitting ? '提交中...' : '✓ 确认发布' }}
            </button>
            <span class="text-xs text-slate-500">{{ forcePassHint }}</span>
          </div>
          <div class="flex items-center gap-3 flex-wrap">
            <button
              :disabled="submitting"
              class="px-3 py-1.5 text-xs font-medium rounded bg-blue-700 text-blue-100 hover:bg-blue-600 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
              @click="handleIntervene('continue')"
            >
              ↻ 打回重跑
            </button>
            <span class="text-xs text-slate-500">{{ continueHint }}</span>
          </div>
          <div class="flex items-center gap-3 flex-wrap">
            <button
              :disabled="submitting"
              class="px-3 py-1.5 text-xs font-medium rounded bg-red-700 text-red-100 hover:bg-red-600 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
              @click="handleIntervene('abort')"
            >
              ✕ 终止任务
            </button>
            <span class="text-xs text-slate-500">丢弃当前结果，不发布报告</span>
          </div>
        </template>
        <template v-else>
          <div class="flex items-center gap-3 flex-wrap">
            <button
              :disabled="submitting || (pauseContext?.iterations_left ?? 0) <= 0"
              class="px-3 py-1.5 text-xs font-medium rounded bg-blue-700 text-blue-100 hover:bg-blue-600 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
              @click="handleIntervene('continue')"
            >
              {{ submitting ? '提交中...' : '↻ 继续迭代' }}
            </button>
            <span class="text-xs text-slate-500">{{ continueHint }}</span>
          </div>
          <div class="flex items-center gap-3 flex-wrap">
            <button
              :disabled="submitting"
              class="px-3 py-1.5 text-xs font-medium rounded bg-green-700 text-green-100 hover:bg-green-600 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
              @click="handleIntervene('force_pass')"
            >
              ⚡ 强制通过
            </button>
            <span class="text-xs text-slate-500">{{ forcePassHint }}</span>
          </div>
          <div class="flex items-center gap-3 flex-wrap">
            <button
              :disabled="submitting"
              class="px-3 py-1.5 text-xs font-medium rounded bg-red-700 text-red-100 hover:bg-red-600 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
              @click="handleIntervene('abort')"
            >
              ✕ 终止任务
            </button>
            <span class="text-xs text-slate-500">丢弃当前结果，不发布报告</span>
          </div>
        </template>
      </div>
    </div>
  </div>
</template>
