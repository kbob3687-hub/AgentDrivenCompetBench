<script setup lang="ts">
import { ref, computed } from 'vue'
import { marked } from 'marked'
import type { SSEComplete } from '../types'

const props = defineProps<{
  result: SSEComplete
}>()

const activeTab = ref<'report' | 'feedback'>('report')

const renderedMarkdown = computed(() => {
  return marked.parse(props.result.report_markdown || '') as string
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
    <div v-if="activeTab === 'report'" class="p-6 max-h-[700px] overflow-y-auto report-content">
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
