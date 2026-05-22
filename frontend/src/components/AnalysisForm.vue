<script setup lang="ts">
import { ref } from 'vue'

const emit = defineEmits<{
  submit: [payload: { competitorName: string; dimensions: string[] }]
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

function toggleDimension(id: string) {
  const idx = selectedDimensions.value.indexOf(id)
  if (idx >= 0) {
    selectedDimensions.value.splice(idx, 1)
  } else {
    selectedDimensions.value.push(id)
  }
}

function handleSubmit() {
  if (!competitorName.value.trim() || selectedDimensions.value.length === 0) return
  emit('submit', {
    competitorName: competitorName.value.trim(),
    dimensions: [...selectedDimensions.value]
  })
}
</script>

<template>
  <div class="bg-slate-800 rounded-lg p-6 border border-slate-700">
    <div class="flex flex-wrap items-end gap-4">
      <div class="flex-1 min-w-[200px]">
        <label class="block text-sm font-medium text-slate-300 mb-1">竞品名称</label>
        <input
          v-model="competitorName"
          type="text"
          :disabled="disabled"
          class="w-full px-3 py-2 bg-slate-900 border border-slate-600 rounded-md text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent disabled:opacity-50"
          placeholder="输入竞品名称..."
        />
      </div>
      <div class="flex-1 min-w-[300px]">
        <label class="block text-sm font-medium text-slate-300 mb-1">分析维度</label>
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
                : 'bg-slate-700 text-slate-300 hover:bg-slate-600'
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
  </div>
</template>
