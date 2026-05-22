<script setup lang="ts">
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { marked } from 'marked'
import type { SSEComplete, AgentTrace } from '../types'

const props = defineProps<{
  result: SSEComplete
}>()

const activeTab = ref<'report' | 'feedback' | 'trace'>('report')

const renderedMarkdown = computed(() => {
  return marked.parse(props.result.report_markdown || '') as string
})

const totalTokens = computed(() => {
  const traces = props.result.agent_traces || []
  return traces.reduce((sum, t) => sum + t.input_tokens + t.output_tokens, 0)
})

const totalDuration = computed(() => {
  const traces = props.result.agent_traces || []
  return traces.reduce((sum, t) => sum + t.duration_ms, 0)
})

const estimatedCost = computed(() => {
  const traces = props.result.agent_traces || []
  let cost = 0
  for (const t of traces) {
    if (t.model?.includes('deepseek')) {
      cost += t.input_tokens * 0.0000001 + t.output_tokens * 0.0000002
    } else {
      cost += t.input_tokens * 0.000003 + t.output_tokens * 0.000015
    }
  }
  return cost
})

const langfuseUrl = computed(() => {
  const traceId = props.result.trace_id
  if (!traceId) return ''
  const cleanId = traceId.replace(/-/g, '').slice(0, 32)
  return `https://cloud.langfuse.com/trace/${cleanId}`
})

function agentColor(agent: string): string {
  const colors: Record<string, string> = {
    collector: 'border-blue-500 bg-blue-500/10',
    analyst: 'border-purple-500 bg-purple-500/10',
    writer: 'border-green-500 bg-green-500/10',
    qa: 'border-orange-500 bg-orange-500/10',
  }
  return colors[agent] || 'border-slate-500 bg-slate-500/10'
}

function agentDotColor(agent: string): string {
  const colors: Record<string, string> = {
    collector: 'bg-blue-500',
    analyst: 'bg-purple-500',
    writer: 'bg-green-500',
    qa: 'bg-orange-500',
  }
  return colors[agent] || 'bg-slate-500'
}

function handleLinkClick(e: MouseEvent) {
  const target = e.target as HTMLElement
  const anchor = target.closest('a') as HTMLAnchorElement | null
  if (!anchor) return
  const href = anchor.getAttribute('href')
  if (!href || href.startsWith('#')) return
  e.preventDefault()
  window.open(href, '_blank', 'noopener,noreferrer')
}

const reportEl = ref<HTMLElement | null>(null)

onMounted(() => {
  reportEl.value?.addEventListener('click', handleLinkClick)
})

onBeforeUnmount(() => {
  reportEl.value?.removeEventListener('click', handleLinkClick)
})
</script>

<template>
  <div class="bg-slate-800 rounded-lg border border-slate-700 overflow-hidden">
    <!-- Tabs -->
    <div class="flex border-b border-slate-700">
      <button
        :class="[
          'px-6 py-3 text-sm font-medium transition-colors',
          activeTab === 'report'
            ? 'text-blue-400 border-b-2 border-blue-400 bg-slate-800'
            : 'text-slate-400 hover:text-slate-200'
        ]"
        @click="activeTab = 'report'"
      >
        分析报告
      </button>
      <button
        :class="[
          'px-6 py-3 text-sm font-medium transition-colors',
          activeTab === 'trace'
            ? 'text-blue-400 border-b-2 border-blue-400 bg-slate-800'
            : 'text-slate-400 hover:text-slate-200'
        ]"
        @click="activeTab = 'trace'"
      >
        Agent Trace
      </button>
      <button
        :class="[
          'px-6 py-3 text-sm font-medium transition-colors',
          activeTab === 'feedback'
            ? 'text-blue-400 border-b-2 border-blue-400 bg-slate-800'
            : 'text-slate-400 hover:text-slate-200'
        ]"
        @click="activeTab = 'feedback'"
      >
        反馈历史 ({{ result.feedback_history?.length || 0 }} 轮)
      </button>
    </div>

    <!-- Report Tab -->
    <div v-if="activeTab === 'report'" ref="reportEl" class="p-6 max-h-[700px] overflow-y-auto report-content">
      <div class="flex items-center gap-3 mb-6">
        <span class="text-sm text-slate-400">最终状态:</span>
        <span class="px-2 py-0.5 rounded bg-green-700 text-green-100 text-sm font-medium">
          {{ result.final_status }}
        </span>
        <span class="text-sm text-slate-400">QA 评分:</span>
        <span class="px-2 py-0.5 rounded bg-blue-700 text-blue-100 text-sm font-medium">
          {{ (result.qa_score * 100).toFixed(0) }}%
        </span>
      </div>
      <div
        class="prose prose-invert max-w-none prose-headings:text-slate-100 prose-headings:font-semibold prose-h1:text-2xl prose-h1:border-b prose-h1:border-slate-700 prose-h1:pb-3 prose-h2:text-xl prose-h2:mt-8 prose-h3:text-base prose-p:text-slate-300 prose-p:leading-relaxed prose-strong:text-slate-100 prose-code:text-blue-300 prose-table:text-sm prose-th:bg-slate-700/50 prose-th:px-3 prose-th:py-2 prose-td:px-3 prose-td:py-2 prose-td:border-slate-700 prose-tr:border-slate-700 prose-li:text-slate-300 prose-a:text-blue-400 prose-hr:border-slate-700"
        v-html="renderedMarkdown"
      ></div>
    </div>

    <!-- Agent Trace Tab -->
    <div v-if="activeTab === 'trace'" class="p-6 max-h-[700px] overflow-y-auto">
      <!-- Summary cards -->
      <div class="grid grid-cols-4 gap-3 mb-6">
        <div class="bg-slate-900 rounded-lg p-3 border border-slate-700">
          <div class="text-xs text-slate-400 mb-1">总耗时</div>
          <div class="text-lg font-bold text-slate-100">{{ (totalDuration / 1000).toFixed(1) }}s</div>
        </div>
        <div class="bg-slate-900 rounded-lg p-3 border border-slate-700">
          <div class="text-xs text-slate-400 mb-1">总 Token</div>
          <div class="text-lg font-bold text-slate-100">{{ totalTokens.toLocaleString() }}</div>
        </div>
        <div class="bg-slate-900 rounded-lg p-3 border border-slate-700">
          <div class="text-xs text-slate-400 mb-1">预估成本</div>
          <div class="text-lg font-bold text-slate-100">${{ estimatedCost.toFixed(4) }}</div>
        </div>
        <div class="bg-slate-900 rounded-lg p-3 border border-slate-700">
          <div class="text-xs text-slate-400 mb-1">Agent 调用</div>
          <div class="text-lg font-bold text-slate-100">{{ (result.agent_traces || []).length }} 次</div>
        </div>
      </div>

      <!-- Timeline -->
      <div class="space-y-3">
        <div
          v-for="(trace, idx) in (result.agent_traces || [])"
          :key="idx"
          :class="['rounded-lg border-l-4 p-4 bg-slate-900', agentColor(trace.agent)]"
        >
          <div class="flex items-center justify-between mb-2">
            <div class="flex items-center gap-2">
              <span :class="['w-2.5 h-2.5 rounded-full', agentDotColor(trace.agent)]"></span>
              <span class="text-sm font-medium text-slate-200 capitalize">{{ trace.agent }}</span>
              <span class="text-xs text-slate-500">iter {{ trace.iteration }}</span>
            </div>
            <div class="flex items-center gap-3 text-xs text-slate-400">
              <span>{{ trace.model }}</span>
              <span class="font-mono">{{ (trace.duration_ms / 1000).toFixed(1) }}s</span>
            </div>
          </div>
          <div class="flex items-center gap-4 text-xs text-slate-400 mb-2">
            <span>Input: <span class="text-slate-300 font-mono">{{ trace.input_tokens.toLocaleString() }}</span> tokens</span>
            <span>Output: <span class="text-slate-300 font-mono">{{ trace.output_tokens.toLocaleString() }}</span> tokens</span>
          </div>
          <div v-if="trace.prompt_preview" class="text-xs text-slate-500 mb-1">
            <span class="text-slate-400">Prompt:</span> {{ trace.prompt_preview }}
          </div>
          <div v-if="trace.output_preview" class="text-xs text-slate-500">
            <span class="text-slate-400">Output:</span> {{ trace.output_preview }}
          </div>
        </div>
      </div>

      <!-- Langfuse deep link -->
      <div v-if="langfuseUrl" class="mt-6 pt-4 border-t border-slate-700 flex items-center justify-between">
        <span class="text-xs text-slate-500">完整 Trace 详情（Prompt / 输入 / 输出 / Token 明细）</span>
        <a
          :href="langfuseUrl"
          target="_blank"
          rel="noopener noreferrer"
          class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-slate-700 text-xs text-slate-300 hover:bg-slate-600 transition-colors"
        >
          <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14"/>
          </svg>
          在 Langfuse 中查看
        </a>
      </div>
    </div>

    <!-- Feedback History Tab -->
    <div v-if="activeTab === 'feedback'" class="p-6 max-h-[600px] overflow-y-auto">
      <table class="w-full text-sm text-left">
        <thead class="text-slate-400 border-b border-slate-700">
          <tr>
            <th class="py-2 px-3">轮次</th>
            <th class="py-2 px-3">判定</th>
            <th class="py-2 px-3">评分</th>
            <th class="py-2 px-3">问题数</th>
            <th class="py-2 px-3">关键问题</th>
            <th class="py-2 px-3">动作</th>
            <th class="py-2 px-3">反馈摘要</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="record in result.feedback_history"
            :key="record.iteration"
            class="border-b border-slate-700/50 text-slate-300"
          >
            <td class="py-2 px-3 font-mono">{{ record.iteration }}</td>
            <td class="py-2 px-3">
              <span
                :class="[
                  'px-2 py-0.5 rounded text-xs font-medium',
                  record.verdict === 'pass' ? 'bg-green-700 text-green-100' : 'bg-orange-700 text-orange-100'
                ]"
              >
                {{ record.verdict }}
              </span>
            </td>
            <td class="py-2 px-3 font-mono">{{ record.score }}</td>
            <td class="py-2 px-3 font-mono">{{ record.issues_count }}</td>
            <td class="py-2 px-3 font-mono">{{ record.critical_issues }}</td>
            <td class="py-2 px-3">{{ record.action_taken }}</td>
            <td class="py-2 px-3 text-xs text-slate-400 max-w-[200px] truncate">
              {{ record.feedback_summary }}
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<style scoped>
.report-content :deep(table) {
  border-collapse: collapse;
  width: 100%;
  font-size: 0.875rem;
}

.report-content :deep(table th) {
  background-color: rgb(51 65 85 / 0.5);
  font-weight: 600;
  text-align: left;
  white-space: nowrap;
}

.report-content :deep(table td),
.report-content :deep(table th) {
  border: 1px solid rgb(51 65 85);
  padding: 0.5rem 0.75rem;
}

.report-content :deep(table tr:nth-child(even)) {
  background-color: rgb(30 41 59 / 0.3);
}

.report-content :deep(hr) {
  border-color: rgb(51 65 85);
  margin: 2rem 0;
}

.report-content :deep(h1) {
  font-size: 1.5rem;
  margin-bottom: 1.5rem;
}

.report-content :deep(h2) {
  margin-top: 2rem;
  padding-bottom: 0.5rem;
  border-bottom: 1px solid rgb(51 65 85 / 0.5);
}

.report-content :deep(ul) {
  padding-left: 1.25rem;
}

.report-content :deep(li) {
  margin-bottom: 0.25rem;
}

.report-content :deep(strong) {
  color: rgb(226 232 240);
}
</style>
