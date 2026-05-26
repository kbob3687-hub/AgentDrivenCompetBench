<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'

const props = defineProps<{
  taskId: string
  embedded?: boolean
}>()

interface AgentBreakdown {
  duration_ms: number
  input_tokens: number
  output_tokens: number
  calls: number
}

interface BaselineComparison {
  time: { human: number; ai: number; human_label: string; ai_label: string; speedup: number }
  sources: { human: number; ai: number; improvement: string }
  structure: { human: string; ai: string; score: number }
  traceability: { human: string; ai: string; score: number }
  consistency: { human: string; ai: string; score: number }
}

interface Metrics {
  accuracy_rate: number
  coverage_rate: number
  revision_rate: number
  total_tokens: number
  total_duration_ms: number
  total_iterations: number
  agent_breakdown: Record<string, AgentBreakdown>
  qa_trend: { iteration: number; score: number }[]
  baseline_comparison: BaselineComparison
}

const metrics = ref<Metrics | null>(null)
const loading = ref(true)
const error = ref('')

onMounted(async () => {
  try {
    const res = await fetch(`/api/analyze/${props.taskId}/metrics`)
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    metrics.value = await res.json()
  } catch (e: any) {
    error.value = e.message
  } finally {
    loading.value = false
  }
})

const agentColors: Record<string, string> = {
  discovery: '#6366f1',
  collector: '#3b82f6',
  analyst: '#a855f7',
  writer: '#22c55e',
  qa: '#f97316',
}

const maxDuration = computed(() => {
  if (!metrics.value) return 1
  return Math.max(...Object.values(metrics.value.agent_breakdown).map(a => a.duration_ms), 1)
})

const maxTokens = computed(() => {
  if (!metrics.value) return 1
  return Math.max(...Object.values(metrics.value.agent_breakdown).map(a => a.input_tokens + a.output_tokens), 1)
})

const svgPath = computed(() => {
  if (!metrics.value || metrics.value.qa_trend.length === 0) return ''
  const points = metrics.value.qa_trend
  const w = 280, h = 80, pad = 4
  const xStep = points.length > 1 ? (w - pad * 2) / (points.length - 1) : 0
  return points.map((p, i) => {
    const x = pad + i * xStep
    const y = h - pad - (p.score * (h - pad * 2))
    return `${i === 0 ? 'M' : 'L'}${x},${y}`
  }).join(' ')
})

const svgDots = computed(() => {
  if (!metrics.value || metrics.value.qa_trend.length === 0) return []
  const points = metrics.value.qa_trend
  const w = 280, h = 80, pad = 4
  const xStep = points.length > 1 ? (w - pad * 2) / (points.length - 1) : 0
  return points.map((p, i) => ({
    x: pad + i * xStep,
    y: h - pad - (p.score * (h - pad * 2)),
    score: p.score,
    iteration: p.iteration,
  }))
})
</script>

<template>
  <div :class="embedded ? '' : 'bg-white rounded-lg border border-slate-200 p-6 shadow-sm'">
    <h3 v-if="!embedded" class="text-sm font-semibold text-slate-700 mb-4">观测面板</h3>

    <div v-if="loading" class="text-sm text-slate-500">加载中...</div>
    <div v-else-if="error" class="text-sm text-red-500">{{ error }}</div>
    <div v-else-if="metrics">
      <!-- KPI Cards -->
      <div class="grid grid-cols-4 gap-3 mb-6">
        <div class="bg-slate-50 rounded-lg p-3 border border-slate-200">
          <div class="text-xs text-slate-500 mb-1">准确率 (QA Score)</div>
          <div class="text-xl font-bold text-emerald-600">{{ (metrics.accuracy_rate * 100).toFixed(0) }}%</div>
        </div>
        <div class="bg-slate-50 rounded-lg p-3 border border-slate-200">
          <div class="text-xs text-slate-500 mb-1">覆盖率</div>
          <div class="text-xl font-bold text-blue-600">{{ (metrics.coverage_rate * 100).toFixed(0) }}%</div>
        </div>
        <div class="bg-slate-50 rounded-lg p-3 border border-slate-200">
          <div class="text-xs text-slate-500 mb-1">修订率</div>
          <div class="text-xl font-bold text-orange-500">{{ (metrics.revision_rate * 100).toFixed(0) }}%</div>
        </div>
        <div class="bg-slate-50 rounded-lg p-3 border border-slate-200">
          <div class="text-xs text-slate-500 mb-1">总 Token 消耗</div>
          <div class="text-xl font-bold text-slate-800">{{ metrics.total_tokens.toLocaleString() }}</div>
        </div>
      </div>

      <!-- Per-Agent Breakdown -->
      <div class="grid grid-cols-2 gap-6">
        <!-- Duration Bar Chart -->
        <div>
          <div class="text-xs text-slate-500 mb-3 font-medium">Agent 耗时 (ms)</div>
          <div class="space-y-2">
            <div v-for="(stat, agent) in metrics.agent_breakdown" :key="agent" class="flex items-center gap-2">
              <span class="text-xs text-slate-600 w-20 capitalize">{{ agent }}</span>
              <div class="flex-1 h-5 bg-slate-100 rounded overflow-hidden">
                <div
                  class="h-full rounded transition-all"
                  :style="{ width: (stat.duration_ms / maxDuration * 100) + '%', backgroundColor: agentColors[agent] || '#64748b' }"
                ></div>
              </div>
              <span class="text-xs text-slate-500 font-mono w-16 text-right">{{ (stat.duration_ms / 1000).toFixed(1) }}s</span>
            </div>
          </div>
        </div>

        <!-- Token Bar Chart -->
        <div>
          <div class="text-xs text-slate-500 mb-3 font-medium">Agent Token 消耗</div>
          <div class="space-y-2">
            <div v-for="(stat, agent) in metrics.agent_breakdown" :key="agent" class="flex items-center gap-2">
              <span class="text-xs text-slate-600 w-20 capitalize">{{ agent }}</span>
              <div class="flex-1 h-5 bg-slate-100 rounded overflow-hidden">
                <div
                  class="h-full rounded transition-all"
                  :style="{ width: ((stat.input_tokens + stat.output_tokens) / maxTokens * 100) + '%', backgroundColor: agentColors[agent] || '#64748b' }"
                ></div>
              </div>
              <span class="text-xs text-slate-500 font-mono w-16 text-right">{{ ((stat.input_tokens + stat.output_tokens) / 1000).toFixed(1) }}k</span>
            </div>
          </div>
        </div>
      </div>

      <!-- QA Score Trend -->
      <div v-if="metrics.qa_trend.length > 1" class="mt-6 pt-4 border-t border-slate-200">
        <div class="text-xs text-slate-500 mb-2 font-medium">QA 评分趋势</div>
        <svg viewBox="0 0 280 80" class="w-full h-20" preserveAspectRatio="none">
          <path :d="svgPath" fill="none" stroke="#3b82f6" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" />
          <circle
            v-for="dot in svgDots"
            :key="dot.iteration"
            :cx="dot.x" :cy="dot.y" r="3"
            fill="#3b82f6"
          />
        </svg>
        <div class="flex justify-between text-xs text-slate-400 mt-1">
          <span v-for="p in metrics.qa_trend" :key="p.iteration">
            R{{ p.iteration }}: {{ (p.score * 100).toFixed(0) }}%
          </span>
        </div>
      </div>

      <!-- Baseline Comparison: AI vs Human -->
      <div v-if="metrics.baseline_comparison" class="mt-6 pt-4 border-t border-slate-200">
        <div class="text-xs text-slate-500 mb-3 font-medium">AI Agent vs 人工分析 — 量化对比</div>
        <div class="grid grid-cols-5 gap-2">
          <div class="bg-emerald-50 rounded-lg p-3 border border-emerald-200 text-center">
            <div class="text-xs text-slate-500 mb-1">耗时</div>
            <div class="text-lg font-bold text-emerald-600">{{ metrics.baseline_comparison.time.speedup }}x</div>
            <div class="text-xs text-slate-400 mt-1">{{ metrics.baseline_comparison.time.human_label }} → {{ metrics.baseline_comparison.time.ai_label }}</div>
          </div>
          <div class="bg-emerald-50 rounded-lg p-3 border border-emerald-200 text-center">
            <div class="text-xs text-slate-500 mb-1">信息源</div>
            <div class="text-lg font-bold text-emerald-600">{{ metrics.baseline_comparison.sources.improvement }}</div>
            <div class="text-xs text-slate-400 mt-1">{{ metrics.baseline_comparison.sources.human }}个 → {{ metrics.baseline_comparison.sources.ai }}个</div>
          </div>
          <div class="bg-emerald-50 rounded-lg p-3 border border-emerald-200 text-center">
            <div class="text-xs text-slate-500 mb-1">结构化</div>
            <div class="text-lg font-bold text-emerald-600">Schema</div>
            <div class="text-xs text-slate-400 mt-1">Word → JSON</div>
          </div>
          <div class="bg-emerald-50 rounded-lg p-3 border border-emerald-200 text-center">
            <div class="text-xs text-slate-500 mb-1">溯源</div>
            <div class="text-lg font-bold text-emerald-600">100%</div>
            <div class="text-xs text-slate-400 mt-1">无 → 逐条URL</div>
          </div>
          <div class="bg-emerald-50 rounded-lg p-3 border border-emerald-200 text-center">
            <div class="text-xs text-slate-500 mb-1">一致性</div>
            <div class="text-lg font-bold text-emerald-600">100%</div>
            <div class="text-xs text-slate-400 mt-1">因人而异 → Schema约束</div>
          </div>
        </div>
      </div>

      <!-- Summary -->
      <div class="mt-4 pt-4 border-t border-slate-200 flex items-center gap-4 text-xs text-slate-500">
        <span>总耗时: {{ (metrics.total_duration_ms / 1000).toFixed(1) }}s</span>
        <span>迭代轮次: {{ metrics.total_iterations }}</span>
        <span>Agent 调用: {{ Object.values(metrics.agent_breakdown).reduce((s, a) => s + a.calls, 0) }} 次</span>
      </div>
    </div>
  </div>
</template>
