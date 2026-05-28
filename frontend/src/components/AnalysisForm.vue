<script setup lang="ts">
import { ref } from 'vue'

const emit = defineEmits<{
  submit: [payload: { competitorName: string; dimensions: string[]; industry: string; targetUrls: string[] }]
}>()

defineProps<{
  disabled: boolean
}>()

const competitorName = ref('Notion')
const allDimensions = [
  { id: 'pricing', label: '定价策略' },
  { id: 'features', label: '核心功能' },
  { id: 'integrations', label: '集成生态' },
  { id: 'ai_features', label: 'AI 能力' }
]
const selectedDimensions = ref<string[]>(['pricing', 'features', 'integrations', 'ai_features'])

const industries = [
  { id: 'saas', label: 'SaaS/项目管理' },
  { id: 'consumer', label: '消费品' },
  { id: 'hardware', label: '硬件/智能设备' }
]
const selectedIndustry = ref('saas')
const targetUrlsInput = ref('')
const showUrlInput = ref(false)

function toggleDimension(id: string) {
  const idx = selectedDimensions.value.indexOf(id)
  if (idx >= 0) {
    selectedDimensions.value.splice(idx, 1)
  } else {
    selectedDimensions.value.push(id)
  }
}

function parseUrls(): string[] {
  if (!targetUrlsInput.value.trim()) return []
  return targetUrlsInput.value
    .split('\n')
    .map(u => u.trim())
    .filter(u => u.length > 0 && u.startsWith('http'))
}

function handleSubmit() {
  if (!competitorName.value.trim() || selectedDimensions.value.length === 0) return
  emit('submit', {
    competitorName: competitorName.value.trim(),
    dimensions: [...selectedDimensions.value],
    industry: selectedIndustry.value,
    targetUrls: parseUrls()
  })
}
</script>

<template>
  <div class="bg-white rounded-lg p-6 border border-slate-200 shadow-sm">
    <div class="flex flex-wrap items-end gap-4">
      <div class="flex-1 min-w-[200px]">
        <label class="block text-sm font-medium text-slate-600 mb-1">竞品名称</label>
        <input
          v-model="competitorName"
          type="text"
          :disabled="disabled"
          class="w-full px-3 py-2 bg-white border border-slate-300 rounded-md text-slate-800 placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent disabled:opacity-50"
          placeholder="输入竞品名称..."
        />
      </div>
      <div class="min-w-[160px]">
        <label class="block text-sm font-medium text-slate-600 mb-1">行业模板</label>
        <div class="flex gap-1.5">
          <button
            v-for="ind in industries"
            :key="ind.id"
            type="button"
            :disabled="disabled"
            :class="[
              'px-2.5 py-1.5 rounded-md text-xs font-medium transition-colors',
              selectedIndustry === ind.id
                ? 'bg-purple-600 text-white'
                : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
            ]"
            @click="selectedIndustry = ind.id"
          >
            {{ ind.label }}
          </button>
        </div>
      </div>
      <div class="flex-1 min-w-[300px]">
        <label class="block text-sm font-medium text-slate-600 mb-1">分析维度</label>
        <div class="flex flex-wrap gap-2">
          <button
            v-for="dim in allDimensions"
            :key="dim.id"
            type="button"
            :disabled="disabled"
            :class="[
              'px-3 py-1.5 rounded-md text-sm font-medium transition-colors',
              selectedDimensions.includes(dim.id)
                ? 'bg-blue-600 text-white'
                : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
            ]"
            @click="toggleDimension(dim.id)"
          >
            {{ dim.label }}
          </button>
        </div>
      </div>
      <button
        :disabled="disabled || !competitorName.trim() || selectedDimensions.length === 0"
        class="px-6 py-2 bg-blue-600 text-white font-medium rounded-md hover:bg-blue-500 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        @click="handleSubmit"
      >
        {{ disabled ? '分析中...' : '开始分析' }}
      </button>
    </div>

    <!-- 种子URL输入（人工介入） -->
    <div class="mt-4 border-t border-slate-200 pt-3">
      <button
        type="button"
        class="text-xs text-slate-500 hover:text-slate-700 transition-colors"
        @click="showUrlInput = !showUrlInput"
      >
        {{ showUrlInput ? '收起' : '指定采集URL（可选）' }}
      </button>
      <div v-if="showUrlInput" class="mt-2">
        <textarea
          v-model="targetUrlsInput"
          :disabled="disabled"
          rows="3"
          class="w-full px-3 py-2 bg-white border border-slate-300 rounded-md text-slate-800 placeholder-slate-400 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:opacity-50"
          placeholder="每行一个URL，例如：&#10;https://notion.so/pricing&#10;https://notion.so/product"
        ></textarea>
        <p class="text-xs text-slate-500 mt-1">人工指定数据源，Agent将优先采集这些页面</p>
      </div>
    </div>
  </div>
</template>
