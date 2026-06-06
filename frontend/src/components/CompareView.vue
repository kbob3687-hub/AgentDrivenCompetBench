<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'

interface HistoryItem {
  task_id: string
  competitor_name: string
  industry: string
  status: string
  qa_score: number | null
  qa_verdict: string | null
  iteration: number
  report_length: number
  sources_fetched: number
  started_at: string | null
  completed_at: string | null
}

interface PricingTier {
  name: string
  price: string
}

interface FeatureNode {
  name: string
  category: string | null
  maturity: string | null
}

interface UserPersona {
  segment: string
  usage_scenarios: string[]
}

interface CompareCompetitor {
  task_id: string
  company_name: string
  product_name: string
  industry: string
  qa_score: number
  profile: {
    one_liner: string | null
    pricing: {
      model_type: string
      tiers: PricingTier[]
      currency: string
    } | null
    feature_tree: FeatureNode[]
    swot: {
      strength: string[]
      weakness: string[]
      opportunity: string[]
      threat: string[]
    }
    user_personas: UserPersona[]
    extensions: Record<string, any>
  }
}

interface CompareExtensionField {
  field_name: string
  label: string
  field_type: string
  required: boolean
  description: string
}

interface CompareResponse {
  competitors: CompareCompetitor[]
  dimensions: string[]
  common_industry: string | null
  mixed_industries: boolean
  extension_fields: CompareExtensionField[]
}

const emit = defineEmits<{ close: [] }>()

// State
const historyItems = ref<HistoryItem[]>([])
const selectedIds = ref<Set<string>>(new Set())
const loadingHistory = ref(false)
const loadingCompare = ref(false)
const compareResult = ref<CompareResponse | null>(null)
const errorMsg = ref('')

const completedItems = computed(() =>
  historyItems.value.filter(item => item.status === 'completed')
)

const canCompare = computed(() => {
  const count = selectedIds.value.size
  return count >= 2 && count <= 4
})

const selectionHint = computed(() => {
  const count = selectedIds.value.size
  if (count < 2) return '至少选择2个已完成的分析任务'
  if (count > 4) return '最多选择4个任务进行对比'
  return ''
})

// Fetch history on mount
onMounted(async () => {
  await fetchHistory()
})

async function fetchHistory() {
  loadingHistory.value = true
  errorMsg.value = ''
  try {
    const res = await fetch('/api/analyze/history?page_size=50')
    if (!res.ok) throw new Error(`请求失败: ${res.status}`)
    const data = await res.json()
    historyItems.value = Array.isArray(data) ? data : data.items || []
  } catch (e: any) {
    errorMsg.value = e.message || '获取历史记录失败'
  } finally {
    loadingHistory.value = false
  }
}

function toggleSelect(taskId: string) {
  const s = new Set(selectedIds.value)
  if (s.has(taskId)) {
    s.delete(taskId)
  } else {
    if (s.size >= 4) return
    s.add(taskId)
  }
  selectedIds.value = s
}

function isSelected(taskId: string): boolean {
  return selectedIds.value.has(taskId)
}

async function runCompare() {
  if (!canCompare.value) return
  loadingCompare.value = true
  errorMsg.value = ''
  compareResult.value = null
  try {
    const res = await fetch('/api/analyze/compare', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ task_ids: [...selectedIds.value] }),
    })
    if (!res.ok) throw new Error(`对比请求失败: ${res.status}`)
    compareResult.value = await res.json()
  } catch (e: any) {
    errorMsg.value = e.message || '对比分析失败'
  } finally {
    loadingCompare.value = false
  }
}

function formatDate(dateStr: string | null): string {
  if (!dateStr) return '—'
  const d = new Date(dateStr)
  return d.toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
}

function formatScore(score: number | null): string {
  if (score === null) return '—'
  return `${(score * 100).toFixed(0)}%`
}

function resetToSelection() {
  compareResult.value = null
}

function formatIndustry(industry: string | null): string {
  const labels: Record<string, string> = {
    saas: '项目管理/SaaS产品',
    consumer: '消费品',
    hardware: '硬件/智能设备',
  }
  return industry ? labels[industry] || industry : '公共'
}

function isBlankValue(value: any): boolean {
  return value === null || value === undefined || value === '' || (Array.isArray(value) && value.length === 0)
}

function formatExtensionValue(value: any): string {
  if (isBlankValue(value)) return '—'
  if (typeof value === 'string') return value.trim() || '—'
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)

  if (Array.isArray(value)) {
    const items = value
      .map(item => formatExtensionValue(item))
      .filter(item => item && item !== '—')
    return items.length ? items.slice(0, 8).join('；') : '—'
  }

  if (typeof value === 'object') {
    if ('claim' in value) return formatExtensionValue(value.claim)
    if ('value' in value && 'spec' in value) return `${value.spec}: ${formatExtensionValue(value.value)}`
    if ('value' in value) return formatExtensionValue(value.value)
    if ('summary' in value) return formatExtensionValue(value.summary)
    if ('items' in value) return formatExtensionValue(value.items)

    const compact = Object.entries(value)
      .filter(([key, val]) => !['sources', 'source', 'evidence', 'confidence', 'reasoning'].includes(key) && !isBlankValue(val))
      .map(([key, val]) => `${key}: ${formatExtensionValue(val)}`)
      .slice(0, 5)
    return compact.length ? compact.join('；') : '—'
  }

  return String(value)
}

function getExtensionSourceUrl(value: any): string | null {
  if (!value) return null
  if (Array.isArray(value)) {
    for (const item of value) {
      const url = getExtensionSourceUrl(item)
      if (url) return url
    }
    return null
  }
  if (typeof value !== 'object') return null
  if (typeof value.source_url === 'string') return value.source_url
  if (typeof value.url === 'string') return value.url
  if (Array.isArray(value.sources) && value.sources[0]?.url) return value.sources[0].url
  if (value.evidence) return getExtensionSourceUrl(value.evidence)
  return null
}
</script>

<template>
  <div class="bg-white rounded-lg border border-slate-200 shadow-sm overflow-hidden">
    <!-- Header -->
    <div class="flex items-center justify-between px-6 py-4 border-b border-slate-200">
      <h2 class="text-lg font-semibold text-slate-800">多竞品对比分析</h2>
      <button
        @click="emit('close')"
        class="px-3 py-1.5 text-sm font-medium rounded border border-slate-300 text-slate-600 hover:bg-slate-50 transition-colors"
      >
        返回
      </button>
    </div>

    <!-- Selection Panel (shown when no compare result) -->
    <div v-if="!compareResult" class="p-6">
      <!-- Loading state -->
      <div v-if="loadingHistory" class="flex items-center justify-center py-12">
        <svg class="animate-spin h-5 w-5 text-blue-500 mr-3" viewBox="0 0 24 24">
          <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" fill="none" />
          <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
        </svg>
        <span class="text-sm text-slate-500">加载历史记录...</span>
      </div>

      <!-- Empty state -->
      <div v-else-if="completedItems.length === 0" class="text-center py-12 text-sm text-slate-500">
        暂无已完成的分析任务
      </div>

      <!-- History list -->
      <div v-else>
        <p class="text-sm text-slate-500 mb-3">选择 2-4 个已完成的分析任务进行对比：</p>

        <!-- Scrollable selection table -->
        <div class="border border-slate-200 rounded-lg overflow-hidden max-h-[280px] overflow-y-auto">
          <table class="w-full text-sm text-left">
            <thead class="bg-slate-50 text-slate-500 sticky top-0">
              <tr>
                <th class="py-2 px-3 w-10"></th>
                <th class="py-2 px-3">竞品名称</th>
                <th class="py-2 px-3">行业</th>
                <th class="py-2 px-3">QA 评分</th>
                <th class="py-2 px-3">完成时间</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="item in completedItems"
                :key="item.task_id"
                :class="[
                  'border-b border-slate-100 cursor-pointer transition-colors',
                  isSelected(item.task_id) ? 'bg-blue-50' : 'hover:bg-slate-50'
                ]"
                @click="toggleSelect(item.task_id)"
              >
                <td class="py-2 px-3">
                  <input
                    type="checkbox"
                    :checked="isSelected(item.task_id)"
                    class="rounded border-slate-300 text-blue-600 focus:ring-blue-500"
                    @click.stop="toggleSelect(item.task_id)"
                  />
                </td>
                <td class="py-2 px-3 font-medium text-slate-800">{{ item.competitor_name }}</td>
                <td class="py-2 px-3 text-slate-600">{{ item.industry }}</td>
                <td class="py-2 px-3">
                  <span
                    v-if="item.qa_score !== null"
                    class="px-2 py-0.5 rounded text-xs font-medium bg-blue-100 text-blue-700"
                  >
                    {{ formatScore(item.qa_score) }}
                  </span>
                  <span v-else class="text-slate-400">—</span>
                </td>
                <td class="py-2 px-3 text-slate-500 text-xs">{{ formatDate(item.completed_at) }}</td>
              </tr>
            </tbody>
          </table>
        </div>

        <!-- Hint + Compare button -->
        <div class="mt-4 flex items-center justify-between">
          <span v-if="selectionHint" class="text-xs text-amber-600">{{ selectionHint }}</span>
          <span v-else class="text-xs text-slate-500">已选择 {{ selectedIds.size }} 个任务</span>
          <button
            :disabled="!canCompare || loadingCompare"
            :class="[
              'px-4 py-2 text-sm font-medium rounded transition-colors',
              canCompare && !loadingCompare
                ? 'bg-blue-600 text-white hover:bg-blue-700'
                : 'bg-slate-200 text-slate-400 cursor-not-allowed'
            ]"
            @click="runCompare"
          >
            <span v-if="loadingCompare" class="flex items-center gap-2">
              <svg class="animate-spin h-4 w-4" viewBox="0 0 24 24">
                <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" fill="none" />
                <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
              对比中...
            </span>
            <span v-else>对比分析</span>
          </button>
        </div>
      </div>

      <!-- Error message -->
      <div v-if="errorMsg" class="mt-3 px-3 py-2 rounded bg-red-50 text-red-700 text-sm">
        {{ errorMsg }}
      </div>
    </div>

    <!-- Compare Result Table -->
    <div v-if="compareResult" class="p-6">
      <!-- Back to selection -->
      <div class="flex items-center justify-between mb-4">
        <div>
          <h3 class="text-base font-semibold text-slate-800">
            对比结果（{{ compareResult.competitors.length }} 个竞品）
          </h3>
          <p class="mt-1 text-xs text-slate-500">
            <template v-if="compareResult.mixed_industries">
              混选行业，只展示公共字段。
            </template>
            <template v-else-if="compareResult.extension_fields.length">
              已启用{{ formatIndustry(compareResult.common_industry) }}模板字段（{{ compareResult.extension_fields.length }} 项）。
            </template>
            <template v-else>
              当前任务没有可展开的行业模板字段。
            </template>
          </p>
        </div>
        <button
          @click="resetToSelection"
          class="px-3 py-1.5 text-xs font-medium rounded border border-slate-300 text-slate-600 hover:bg-slate-50 transition-colors"
        >
          重新选择
        </button>
      </div>

      <!-- Comparison table -->
      <div class="border border-slate-200 rounded-lg overflow-x-auto">
        <table class="w-full text-sm text-left min-w-[600px]">
          <thead class="bg-slate-50 border-b border-slate-200">
            <tr>
              <th class="py-3 px-4 text-slate-500 font-medium w-[140px]">维度</th>
              <th
                v-for="comp in compareResult.competitors"
                :key="comp.task_id"
                class="py-3 px-4 text-slate-800 font-semibold"
              >
                <div>{{ comp.company_name }}</div>
                <div class="text-xs font-normal text-slate-500">{{ comp.product_name }}</div>
                <div class="mt-1">
                  <span class="px-1.5 py-0.5 rounded text-xs bg-blue-100 text-blue-700">
                    {{ (comp.qa_score * 100).toFixed(0) }}%
                  </span>
                </div>
              </th>
            </tr>
          </thead>
          <tbody>
            <!-- One-liner -->
            <tr class="border-b border-slate-100">
              <td class="py-3 px-4 font-medium text-slate-700 bg-slate-50">一句话定位</td>
              <td
                v-for="comp in compareResult.competitors"
                :key="comp.task_id"
                class="py-3 px-4 text-slate-600"
              >
                {{ comp.profile.one_liner || '—' }}
              </td>
            </tr>

            <!-- Pricing -->
            <tr class="border-b border-slate-100">
              <td class="py-3 px-4 font-medium text-slate-700 bg-slate-50">定价模型</td>
              <td
                v-for="comp in compareResult.competitors"
                :key="comp.task_id"
                class="py-3 px-4 text-slate-600"
              >
                <template v-if="comp.profile.pricing">
                  <div class="text-xs font-medium text-slate-700 mb-1">
                    {{ comp.profile.pricing.model_type }}
                    <span class="text-slate-400">({{ comp.profile.pricing.currency }})</span>
                  </div>
                  <ul class="space-y-0.5">
                    <li
                      v-for="tier in comp.profile.pricing.tiers"
                      :key="tier.name"
                      class="text-xs text-slate-500"
                    >
                      <span class="font-medium text-slate-600">{{ tier.name }}</span>: {{ tier.price }}
                    </li>
                  </ul>
                </template>
                <span v-else class="text-slate-400">—</span>
              </td>
            </tr>

            <!-- Features -->
            <tr class="border-b border-slate-100">
              <td class="py-3 px-4 font-medium text-slate-700 bg-slate-50">功能特性</td>
              <td
                v-for="comp in compareResult.competitors"
                :key="comp.task_id"
                class="py-3 px-4 text-slate-600"
              >
                <div v-if="comp.profile.feature_tree.length" class="space-y-1 max-h-[200px] overflow-y-auto">
                  <div
                    v-for="feat in comp.profile.feature_tree"
                    :key="feat.name"
                    class="text-xs flex items-center gap-1.5"
                  >
                    <span
                      v-if="feat.maturity"
                      :class="[
                        'inline-block w-1.5 h-1.5 rounded-full',
                        feat.maturity === 'mature' ? 'bg-emerald-500' :
                        feat.maturity === 'growing' ? 'bg-amber-500' : 'bg-slate-400'
                      ]"
                    ></span>
                    <span class="text-slate-700">{{ feat.name }}</span>
                    <span v-if="feat.category" class="text-slate-400 text-[10px]">({{ feat.category }})</span>
                  </div>
                </div>
                <span v-else class="text-slate-400">—</span>
              </td>
            </tr>

            <!-- User Personas -->
            <tr class="border-b border-slate-100">
              <td class="py-3 px-4 font-medium text-slate-700 bg-slate-50">用户画像</td>
              <td
                v-for="comp in compareResult.competitors"
                :key="comp.task_id"
                class="py-3 px-4 text-slate-600"
              >
                <div v-if="comp.profile.user_personas.length" class="space-y-1.5">
                  <div
                    v-for="persona in comp.profile.user_personas"
                    :key="persona.segment"
                    class="text-xs"
                  >
                    <span class="font-medium text-slate-700">{{ persona.segment }}</span>
                    <span class="text-slate-400 ml-1">{{ persona.usage_scenarios.join(', ') }}</span>
                  </div>
                </div>
                <span v-else class="text-slate-400">—</span>
              </td>
            </tr>

            <!-- Dynamic industry fields -->
            <tr
              v-for="field in compareResult.extension_fields"
              :key="field.field_name"
              class="border-b border-slate-100"
            >
              <td class="py-3 px-4 font-medium text-slate-700 bg-slate-50 align-top">
                <div>{{ field.label }}</div>
                <div class="mt-1 flex flex-wrap items-center gap-1.5">
                  <span class="text-[10px] font-normal text-slate-400">{{ field.field_type }}</span>
                  <span
                    v-if="field.required"
                    class="px-1.5 py-0.5 rounded text-[10px] font-medium bg-amber-50 text-amber-700"
                  >
                    必填
                  </span>
                </div>
              </td>
              <td
                v-for="comp in compareResult.competitors"
                :key="comp.task_id"
                class="py-3 px-4 text-slate-600 align-top"
              >
                <div class="text-xs leading-5 text-slate-700 whitespace-pre-wrap break-words">
                  {{ formatExtensionValue(comp.profile.extensions?.[field.field_name]) }}
                </div>
                <a
                  v-if="getExtensionSourceUrl(comp.profile.extensions?.[field.field_name])"
                  :href="getExtensionSourceUrl(comp.profile.extensions?.[field.field_name]) || undefined"
                  target="_blank"
                  rel="noreferrer"
                  class="mt-1 inline-block max-w-full truncate text-[11px] text-blue-600 hover:text-blue-700"
                >
                  查看来源
                </a>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>
