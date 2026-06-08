<script setup lang="ts">
import { ref } from 'vue'
import { marked } from 'marked'

const competitorName = ref('')
const industry = ref('saas')
const focus = ref('')
const loading = ref(false)
const error = ref('')
const activeTab = ref<'questionnaire' | 'interview'>('questionnaire')

const result = ref<{ competitor_name: string; questionnaire: string; interview_guide: string } | null>(null)

async function generate() {
  if (!competitorName.value.trim()) return
  loading.value = true
  error.value = ''
  result.value = null
  try {
    const res = await fetch('/api/survey', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        competitor_name: competitorName.value.trim(),
        industry: industry.value,
        focus: focus.value.trim(),
      }),
    })
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    result.value = await res.json()
  } catch (e: any) {
    error.value = e.message || '生成失败'
  } finally {
    loading.value = false
  }
}

function download() {
  if (!result.value) return
  const content = activeTab.value === 'questionnaire'
    ? result.value.questionnaire
    : result.value.interview_guide
  const filename = activeTab.value === 'questionnaire'
    ? `${result.value.competitor_name}-调研问卷.md`
    : `${result.value.competitor_name}-访谈提纲.md`
  const blob = new Blob([content], { type: 'text/markdown;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url; a.download = filename; a.click()
  URL.revokeObjectURL(url)
}
</script>

<template>
  <div class="rounded-lg border border-slate-200 bg-white shadow-sm overflow-hidden">
    <div class="border-b border-slate-200 px-4 py-3 flex items-center justify-between">
      <div>
        <div class="text-sm font-semibold text-slate-800">用户调研工具</div>
        <div class="text-xs text-slate-500 mt-0.5">自动生成调研问卷 + 访谈提纲</div>
      </div>
    </div>

    <div class="p-4 space-y-3">
      <div class="flex gap-2">
        <input
          v-model="competitorName"
          placeholder="竞品名称，如 ClickUp"
          class="flex-1 rounded border border-slate-300 px-3 py-1.5 text-sm focus:border-blue-400 focus:outline-none"
          @keyup.enter="generate"
        />
        <input
          v-model="focus"
          placeholder="聚焦方向（选填）"
          class="w-36 rounded border border-slate-300 px-3 py-1.5 text-sm focus:border-blue-400 focus:outline-none"
        />
        <button
          :disabled="loading || !competitorName.trim()"
          class="px-4 py-1.5 rounded bg-blue-600 text-white text-sm font-medium hover:bg-blue-500 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          @click="generate"
        >
          {{ loading ? '生成中...' : '生成' }}
        </button>
      </div>

      <div v-if="error" class="text-xs text-red-600 px-1">{{ error }}</div>

      <template v-if="result">
        <div class="flex items-center gap-2 border-b border-slate-200">
          <button
            :class="['px-3 py-1.5 text-xs font-medium transition-colors', activeTab === 'questionnaire' ? 'border-b-2 border-blue-500 text-blue-700' : 'text-slate-500 hover:text-slate-700']"
            @click="activeTab = 'questionnaire'"
          >调研问卷</button>
          <button
            :class="['px-3 py-1.5 text-xs font-medium transition-colors', activeTab === 'interview' ? 'border-b-2 border-blue-500 text-blue-700' : 'text-slate-500 hover:text-slate-700']"
            @click="activeTab = 'interview'"
          >访谈提纲</button>
          <div class="ml-auto">
            <button
              class="px-3 py-1 text-xs rounded border border-slate-300 text-slate-600 hover:bg-slate-50"
              @click="download"
            >导出 .md</button>
          </div>
        </div>

        <div class="max-h-[520px] overflow-y-auto prose prose-sm max-w-none prose-headings:text-slate-800 prose-headings:font-semibold prose-p:text-slate-600 prose-li:text-slate-600 prose-strong:text-slate-800">
          <div v-if="activeTab === 'questionnaire'" v-html="marked(result.questionnaire)" />
          <div v-else v-html="marked(result.interview_guide)" />
        </div>
      </template>
    </div>
  </div>
</template>
