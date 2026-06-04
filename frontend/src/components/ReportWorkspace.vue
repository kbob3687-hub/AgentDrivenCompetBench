<script setup lang="ts">
import { computed } from 'vue'
import { marked } from 'marked'
import type { PauseContext, SSEComplete } from '../types'

const props = defineProps<{
  result: SSEComplete | null
  pauseContext: PauseContext | null
  status: 'idle' | 'running' | 'completed' | 'failed' | 'paused'
}>()

const reportMarkdown = computed(() => {
  if (props.result?.report_markdown) return props.result.report_markdown
  return props.pauseContext?.report_preview || ''
})

const renderedReport = computed(() => marked.parse(reportMarkdown.value || '') as string)

const sourceLinks = computed(() => {
  const links: Array<{ label: string; url: string }> = []
  const seen = new Set<string>()
  const markdown = reportMarkdown.value
  const regex = /\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g
  let match: RegExpExecArray | null
  while ((match = regex.exec(markdown)) !== null) {
    const url = match[2]
    if (seen.has(url)) continue
    seen.add(url)
    links.push({ label: match[1], url })
  }
  return links.slice(0, 12)
})

const scoreText = computed(() => {
  if (props.result) return `${(props.result.qa_score * 100).toFixed(0)}%`
  if (props.pauseContext) return `${(props.pauseContext.score * 100).toFixed(0)}%`
  return '—'
})

const statusLabel = computed(() => {
  if (props.status === 'completed') return '最终报告'
  if (props.status === 'paused') return '当前草稿'
  if (props.status === 'running') return '实时产物'
  if (props.status === 'failed') return '任务失败'
  return '等待分析'
})

function handleLinkClick(e: MouseEvent) {
  const target = (e.target as HTMLElement).closest('a') as HTMLAnchorElement | null
  if (!target) return
  const href = target.getAttribute('href')
  if (!href || href.startsWith('#')) return
  e.preventDefault()
  window.open(href, '_blank', 'noopener,noreferrer')
}

function downloadMarkdown() {
  if (!reportMarkdown.value) return
  const blob = new Blob([reportMarkdown.value], { type: 'text/markdown;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = 'competitive-analysis-report.md'
  a.click()
  URL.revokeObjectURL(url)
}
</script>

<template>
  <section class="h-full min-h-[520px] rounded-lg border border-slate-200 bg-white shadow-sm overflow-hidden flex flex-col">
    <div class="flex items-center justify-between gap-3 border-b border-slate-200 px-4 py-3">
      <div class="min-w-0">
        <div class="text-sm font-semibold text-slate-800">{{ statusLabel }}</div>
        <div class="mt-0.5 flex items-center gap-3 text-xs text-slate-500">
          <span>QA 评分 <span class="font-mono text-slate-700">{{ scoreText }}</span></span>
          <span v-if="sourceLinks.length">来源 <span class="font-mono text-slate-700">{{ sourceLinks.length }}</span></span>
        </div>
      </div>
      <button
        :disabled="!reportMarkdown"
        class="shrink-0 rounded border border-slate-300 px-3 py-1.5 text-xs font-medium text-slate-600 transition-colors hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-40"
        @click="downloadMarkdown"
      >
        导出
      </button>
    </div>

    <div v-if="reportMarkdown" class="min-h-0 flex-1 overflow-y-auto px-5 py-4 report-preview" @click="handleLinkClick">
      <div
        class="prose prose-sm max-w-none prose-headings:text-slate-800 prose-headings:font-semibold prose-h1:text-xl prose-h2:text-base prose-h3:text-sm prose-p:text-slate-600 prose-p:leading-relaxed prose-strong:text-slate-800 prose-code:text-blue-600 prose-table:text-xs prose-th:bg-slate-100 prose-th:px-2 prose-th:py-1 prose-td:px-2 prose-td:py-1 prose-li:text-slate-600 prose-a:text-blue-600 prose-hr:border-slate-200"
        v-html="renderedReport"
      ></div>
    </div>

    <div v-else class="flex min-h-0 flex-1 flex-col items-center justify-center px-8 text-center">
      <div class="text-sm font-medium text-slate-700">报告会显示在这里</div>
      <p class="mt-2 max-w-sm text-xs leading-relaxed text-slate-500">
        左侧展示 Agent 执行过程；当 Writer 产出草稿或任务完成后，右侧会固定展示报告和可点击来源。
      </p>
    </div>

    <div v-if="sourceLinks.length" class="border-t border-slate-200 bg-slate-50 px-4 py-3">
      <div class="mb-2 text-xs font-medium text-slate-600">可查来源</div>
      <div class="flex max-h-[96px] flex-wrap gap-2 overflow-y-auto">
        <a
          v-for="source in sourceLinks"
          :key="source.url"
          :href="source.url"
          target="_blank"
          rel="noopener noreferrer"
          class="max-w-full truncate rounded border border-slate-200 bg-white px-2 py-1 text-[11px] text-blue-700 hover:border-blue-300 hover:bg-blue-50"
        >
          {{ source.label }}
        </a>
      </div>
    </div>
  </section>
</template>

<style scoped>
.report-preview :deep(table) {
  display: block;
  width: 100%;
  overflow-x: auto;
  border-collapse: collapse;
}

.report-preview :deep(th),
.report-preview :deep(td) {
  border: 1px solid rgb(226 232 240);
}
</style>
