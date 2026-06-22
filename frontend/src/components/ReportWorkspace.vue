<script setup lang="ts">
import { ref, computed } from 'vue'
import { marked } from 'marked'
import type { PauseContext, SSEComplete } from '../types'

const props = defineProps<{
  result: SSEComplete | null
  pauseContext: PauseContext | null
  status: 'idle' | 'running' | 'completed' | 'failed' | 'paused'
}>()

interface ReportSource {
  id: string
  title: string
  url: string
}

const reportMarkdown = computed(() => {
  if (props.result?.report_markdown) return props.result.report_markdown
  return props.pauseContext?.report_preview || ''
})

function normalizeSourceTitle(value: string): string {
  return value
    .replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g, '$1')
    .replace(/\s*[-:：]\s*$/g, '')
    .replace(/^\s*[-*]\s*/g, '')
    .trim()
}

function normalizeSourceUrl(value: string): string {
  const markdownLink = value.match(/\((https?:\/\/[^)\s]+)\)/)
  const bareUrl = value.match(/https?:\/\/[^\s)<|]+/)
  return (markdownLink?.[1] || bareUrl?.[0] || '').replace(/[.,;，。；]+$/g, '')
}

function parseSourceLine(line: string): ReportSource | null {
  const tableMatch = line.match(/^\|\s*\[(\d+)\]\s*\|\s*(.*?)\s*\|\s*(.*?)\s*\|?\s*$/)
  if (tableMatch) {
    const url = normalizeSourceUrl(tableMatch[3])
    if (!url) return null
    return {
      id: tableMatch[1],
      title: normalizeSourceTitle(tableMatch[2]) || `来源 ${tableMatch[1]}`,
      url,
    }
  }

  const listMatch = line.match(/^\s*(?:[-*]\s*)?\[(\d+)\]\s+(.+)$/)
  if (!listMatch) return null

  const id = listMatch[1]
  const rest = listMatch[2]
  const url = normalizeSourceUrl(rest)
  if (!url) return null

  const urlIndex = rest.indexOf(url)
  const titlePart = urlIndex >= 0 ? rest.slice(0, urlIndex) : rest
  return {
    id,
    title: normalizeSourceTitle(titlePart.replace(/\[[^\]]+\]\(\s*$/g, '')) || `来源 ${id}`,
    url,
  }
}

function addSourceAnchors(markdown: string): string {
  return markdown
    .replace(
      /^(\|\s*)\[(\d+)\]/gm,
      '$1<span id="source-$2" class="source-anchor"></span><span class="source-index">[$2]</span>'
    )
    .replace(
      /^(\s*(?:[-*]\s*)?)\[(\d+)\]/gm,
      '$1<span id="source-$2" class="source-anchor"></span><span class="source-index">[$2]</span>'
    )
}

// ---- 脚注溯源映射：从附录解析 [N] → { title, url } ----
const sourceMap = computed<Record<string, ReportSource>>(() => {
  const map: Record<string, ReportSource> = {}
  for (const line of reportMarkdown.value.split('\n')) {
    const source = parseSourceLine(line)
    if (source) map[source.id] = source
  }
  return map
})

const sourceEntries = computed(() =>
  Object.values(sourceMap.value).sort((a, b) => Number(a.id) - Number(b.id))
)

const renderedReport = computed(() => {
  const md = reportMarkdown.value || ''
  if (!md) return ''

  // 从附录标题处切分正文与附录
  const appendixMatch = md.match(/^#{2,3}\s+.*(?:附录|数据来源|参考来源|来源)/m)
  let bodyMd = md
  let appendixMd = ''

  if (appendixMatch && appendixMatch.index !== undefined) {
    bodyMd = md.substring(0, appendixMatch.index)
    appendixMd = md.substring(appendixMatch.index)
  }

  let bodyHtml = marked.parse(bodyMd) as string
  let appendixHtml = marked.parse(addSourceAnchors(appendixMd)) as string

  // 正文 [N] → 可点击脚注（去掉 href，靠 JS 拦截滚动）
  bodyHtml = bodyHtml.replace(
    /\[(\d+)\]/g,
    '<sup class="footnote-ref" data-source-id="$1"><button type="button" data-source="$1" title="查看来源 $1">[$1]</button></sup>'
  )

  return bodyHtml + (appendixHtml ? '\n<hr class="source-divider">\n' + appendixHtml : '')
})

const sourceLinks = computed(() => {
  const links: Array<{ label: string; url: string }> = []
  const seen = new Set<string>()
  for (const source of sourceEntries.value) {
    if (seen.has(source.url)) continue
    seen.add(source.url)
    links.push({ label: `[${source.id}] ${source.title}`, url: source.url })
  }
  return links.slice(0, 12)
})

const scoreText = computed(() => {
  const fmt = (v: number | null | undefined) => Number(v) ? `${(Number(v) * 100).toFixed(0)}%` : '—'
  if (props.result) return fmt(props.result.qa_score)
  if (props.pauseContext) return fmt(props.pauseContext.score)
  return '—'
})

const statusLabel = computed(() => {
  if (props.status === 'completed') return '最终报告'
  if (props.status === 'paused') return '当前草稿'
  if (props.status === 'running') return '实时产物'
  if (props.status === 'failed') return '任务失败'
  return '等待分析'
})

// ---- 脚注 hover 溯源浮窗 ----
const tooltip = ref<{ show: boolean; x: number; y: number; id: string; title: string; url: string }>({
  show: false, x: 0, y: 0, id: '', title: '', url: '',
})

function onReportMouseOver(e: MouseEvent) {
  const ref = (e.target as HTMLElement).closest('.footnote-ref') as HTMLElement | null
  if (!ref) { tooltip.value.show = false; return }
  const id = ref.dataset.sourceId || ''
  const src = sourceMap.value[id]
  if (!src) { tooltip.value.show = false; return }
  const rect = ref.getBoundingClientRect()
  const container = (e.currentTarget as HTMLElement)?.closest('.report-scroll')
  const cRect = container?.getBoundingClientRect()
  tooltip.value = {
    show: true,
    x: (cRect ? rect.left - cRect.left : rect.left) + rect.width / 2,
    y: (cRect ? rect.top - cRect.top : rect.top) - 8,
    id,
    title: src.title,
    url: src.url,
  }
}

function onReportMouseLeave() {
  tooltip.value.show = false
}

function handleReportClick(e: MouseEvent) {
  const target = e.target as HTMLElement
  const sourceButton = target.closest('[data-source]') as HTMLElement | null

  // 脚注链接：手动滚动到附录锚点
  const sourceId = sourceButton?.getAttribute('data-source')
  if (sourceButton && sourceId) {
    e.preventDefault()
    const container = sourceButton.closest('.report-scroll')
    const el = container?.querySelector(`#source-${CSS.escape(sourceId)}`)
    if (el) {
      el.scrollIntoView({ behavior: 'smooth', block: 'center' })
      el.classList.add('source-flash')
      setTimeout(() => el.classList.remove('source-flash'), 1500)
    }
    return
  }

  // 外部链接新窗口打开
  const anchor = target.closest('a') as HTMLAnchorElement | null
  if (!anchor) return
  const href = anchor.getAttribute('href')
  if (href) {
    e.preventDefault()
    window.open(href, '_blank', 'noopener,noreferrer')
  }
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
        class="shrink-0 rounded border border-slate-300 px-3 py-1.5 text-xs font-medium text-slate-600 transition-colors hover:-translate-y-px hover:bg-slate-50 active:translate-y-0 disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:translate-y-0"
        @click="downloadMarkdown"
      >
        导出
      </button>
    </div>

    <div
      v-if="reportMarkdown"
      class="min-h-0 flex-1 overflow-y-auto px-5 py-4 report-preview report-scroll relative"
      @click="handleReportClick"
      @mouseover="onReportMouseOver"
      @mouseleave="onReportMouseLeave"
    >
      <div
        class="prose prose-sm max-w-none prose-headings:text-slate-800 prose-headings:font-semibold prose-h1:text-xl prose-h2:text-base prose-h3:text-sm prose-p:text-slate-600 prose-p:leading-relaxed prose-strong:text-slate-800 prose-code:text-blue-600 prose-table:text-xs prose-th:bg-slate-100 prose-th:px-2 prose-th:py-1 prose-td:px-2 prose-td:py-1 prose-li:text-slate-600 prose-a:text-blue-600 prose-hr:border-slate-200"
        v-html="renderedReport"
      ></div>

      <!-- 脚注溯源浮窗 -->
      <Transition name="tip-fade">
        <div
          v-if="tooltip.show"
          class="absolute z-30 px-3 py-2 rounded-lg border border-indigo-200 bg-white shadow-lg pointer-events-none"
          :style="{ left: tooltip.x + 'px', top: tooltip.y + 'px', transform: 'translate(-50%, -100%)' }"
        >
          <div class="text-[11px] font-medium text-slate-700 mb-0.5 max-w-[240px] truncate">{{ tooltip.title }}</div>
          <div class="text-[10px] text-blue-600 font-mono max-w-[240px] truncate">{{ tooltip.url }}</div>
          <div class="absolute left-1/2 bottom-0 -translate-x-1/2 translate-y-full w-0 h-0 border-l-[5px] border-l-transparent border-r-[5px] border-r-transparent border-t-[5px] border-t-indigo-200"></div>
        </div>
      </Transition>
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
          class="max-w-full truncate rounded border border-slate-200 bg-white px-2 py-1 text-[11px] text-blue-700 transition-colors hover:-translate-y-px hover:border-blue-300 hover:bg-blue-50"
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

/* 脚注链接 */
.report-preview :deep(.footnote-ref button) {
  appearance: none;
  border: 0;
  background: transparent;
  color: #6366f1;
  cursor: pointer;
  text-decoration: none;
  font-weight: 600;
  font-size: 0.7em;
  padding: 0 1px;
  transition: color 0.15s, transform 0.15s;
}
.report-preview :deep(.footnote-ref button:hover) {
  color: #4f46e5;
  text-decoration: underline;
  transform: translateY(-1px);
}

/* 附录锚点偏移（避免被固定 header 遮挡） */
.report-preview :deep(.source-anchor) {
  scroll-margin-top: 20px;
}

.report-preview :deep(.source-index) {
  color: #475569;
  font-weight: 700;
}

.report-preview :deep(td:has(.source-anchor)),
.report-preview :deep(li:has(.source-anchor)),
.report-preview :deep(p:has(.source-anchor)) {
  transition: background-color 0.2s ease;
}

/* 正文-附录分隔线 */
.report-preview :deep(.source-divider) {
  margin-top: 2rem;
  border-color: #e2e8f0;
}

/* 工具提示淡入淡出 */
.tip-fade-enter-active { transition: opacity 0.15s ease, transform 0.15s ease; }
.tip-fade-leave-active { transition: opacity 0.1s ease; }
.tip-fade-enter-from { opacity: 0; transform: translate(-50%, -100%) translateY(4px); }
.tip-fade-leave-to   { opacity: 0; }

/* 脚注跳转高亮闪烁 */
.report-preview :deep(.source-flash) {
  animation: flash-highlight 0.6s ease-in-out 2;
}
@keyframes flash-highlight {
  0%, 100% { background-color: transparent; }
  50%      { background-color: rgba(99, 102, 241, 0.15); border-radius: 4px; }
}
</style>
