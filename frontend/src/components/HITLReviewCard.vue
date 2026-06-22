<script setup lang="ts">
import { ref, computed } from 'vue'
import type { PauseContext, InterventionPayload } from '../types'

const props = defineProps<{
  context: PauseContext
  taskId: string | null
}>()

const emit = defineEmits<{
  action: [payload: InterventionPayload]
  dismiss: []
}>()

const extraUrls = ref('')
const showUrlInput = ref(false)

const scorePct = computed(() => Math.round((props.context.score || 0) * 100))
const scoreColor = computed(() => {
  if (scorePct.value >= 70) return 'text-emerald-400'
  if (scorePct.value >= 55) return 'text-amber-400'
  return 'text-red-400'
})

const hasMissingDimensions = computed(() =>
  (props.context.missing_dimensions || []).length > 0
)

const criticalIssues = computed(() =>
  (props.context.issues || []).filter(i => i.severity === 'critical')
)

function emitAction(action: string) {
  const urls = extraUrls.value
    .split(/[\n,]/)
    .map(u => u.trim())
    .filter(u => u.startsWith('http'))
  extraUrls.value = ''
  showUrlInput.value = false
  emit('action', { action: action as any, urls: urls.length ? urls : undefined })
}
</script>

<template>
  <Teleport to="body">
    <div class="fixed inset-0 z-50 flex items-center justify-center" style="background: rgba(2,6,23,0.6); backdrop-filter: blur(4px);" @click.self="$emit('dismiss')">
      <div class="mx-4 w-full max-w-lg rounded-2xl border shadow-2xl overflow-hidden" style="background: rgba(15,23,42,0.95); border-color: rgba(99,102,241,0.3); box-shadow: 0 0 40px rgba(99,102,241,0.15);">
        <!-- Header -->
        <div class="px-6 py-4 border-b" style="border-color: rgba(99,102,241,0.2);">
          <div class="flex items-center justify-between">
            <div class="flex items-center gap-3">
              <span class="text-2xl">🛡️</span>
              <div>
                <div class="text-white text-sm font-semibold">QA 审核 — 第 {{ context.iteration }} 轮</div>
                <div class="text-xs text-slate-400 mt-0.5">管道暂停，等待人工决策</div>
              </div>
            </div>
            <div class="text-right">
              <div :class="['text-2xl font-bold', scoreColor]">{{ scorePct }}%</div>
              <div class="text-[10px] text-slate-500">QA 评分</div>
            </div>
          </div>
        </div>

        <!-- Body -->
        <div class="px-6 py-4 space-y-4 max-h-[50vh] overflow-y-auto">
          <!-- 缺失维度 -->
          <div v-if="hasMissingDimensions">
            <div class="text-xs font-medium text-slate-400 mb-2">缺失 / 不足维度</div>
            <div class="flex flex-wrap gap-1.5">
              <span
                v-for="dim in context.missing_dimensions"
                :key="dim"
                class="px-2.5 py-1 rounded text-[11px] font-medium"
                style="background: rgba(239,68,68,0.12); color: #fca5a5; border: 1px solid rgba(239,68,68,0.2);"
              >❌ {{ dim }}</span>
            </div>
          </div>

          <!-- 关键问题 -->
          <div v-if="criticalIssues.length">
            <div class="text-xs font-medium text-red-400 mb-2">严重问题 ({{ criticalIssues.length }})</div>
            <div class="space-y-1.5">
              <div v-for="(issue, i) in criticalIssues.slice(0, 3)" :key="i"
                class="text-[11px] text-slate-300 px-2.5 py-1.5 rounded"
                style="background: rgba(239,68,68,0.06); border-left: 2px solid rgba(239,68,68,0.4);"
              >
                <span class="text-red-400 font-medium">{{ issue.field_label || issue.field_path }}</span>
                <span class="text-slate-500"> — {{ issue.description }}</span>
              </div>
            </div>
          </div>

          <!-- 打回目标 -->
          <div v-if="context.target_agent" class="flex items-center gap-2 text-xs">
            <span class="text-slate-500">打回目标:</span>
            <span class="px-2 py-0.5 rounded font-medium text-[11px]" style="background: rgba(250,204,21,0.12); color: #fde047; border: 1px solid rgba(250,204,21,0.2);">
              {{ context.target_agent }}
            </span>
            <span v-if="context.iterations_left !== undefined" class="text-slate-500 ml-auto">
              剩余 {{ context.iterations_left }} 轮
            </span>
          </div>

          <!-- 补充 URL 输入 -->
          <div v-if="showUrlInput" class="space-y-2">
            <div class="text-xs font-medium text-slate-400">补充采集 URL（每行一个）</div>
            <textarea
              v-model="extraUrls"
              rows="3"
              class="w-full rounded-lg border px-3 py-2 text-xs text-white bg-transparent resize-none focus:outline-none focus:ring-1"
              style="border-color: rgba(99,102,241,0.3); background: rgba(99,102,241,0.06);"
              placeholder="https://example.com/pricing&#10;https://example.com/features"
            ></textarea>
          </div>

          <!-- 已解决 / 退化 -->
          <div v-if="context.resolved_fields?.length || context.regressed_fields?.length" class="flex gap-4 text-[11px]">
            <span v-if="context.resolved_fields?.length" class="text-emerald-400">✅ 已修复: {{ context.resolved_fields.join(', ') }}</span>
            <span v-if="context.regressed_fields?.length" class="text-red-400">⚠️ 退化: {{ context.regressed_fields.join(', ') }}</span>
          </div>

          <!-- 建议策略 -->
          <div v-if="context.suggested_strategy" class="text-[11px] text-amber-400 px-3 py-2 rounded"
            style="background: rgba(250,204,21,0.06); border: 1px solid rgba(250,204,21,0.15);">
            💡 建议: {{ context.suggested_strategy === 'open_search' ? '切换为开放搜索模式，扩大数据采集范围' : context.suggested_strategy }}
          </div>
        </div>

        <!-- Actions -->
        <div class="px-6 py-4 border-t flex items-center gap-3" style="border-color: rgba(99,102,241,0.2);">
          <button
            v-if="!showUrlInput"
            class="px-3 py-2 rounded-lg text-xs font-medium border transition-all active:scale-95"
            style="border-color: rgba(99,102,241,0.3); color: #a5b4fc;"
            @click="showUrlInput = true"
          >+ 补充 URL</button>
          <button
            class="flex-1 px-4 py-2 rounded-lg text-xs font-medium transition-all active:scale-95"
            style="background: rgba(99,102,241,0.2); color: #c7d2fe; border: 1px solid rgba(99,102,241,0.3);"
            @click="emitAction('continue')"
          >
            {{ extraUrls ? '补充并继续' : '继续迭代' }}
          </button>
          <button
            class="px-4 py-2 rounded-lg text-xs font-medium transition-all active:scale-95"
            style="background: rgba(16,185,129,0.15); color: #6ee7b7; border: 1px solid rgba(16,185,129,0.2);"
            @click="emitAction('force_pass')"
          >批准发布</button>
          <button
            class="px-3 py-2 rounded-lg text-xs font-medium transition-all active:scale-95"
            style="background: transparent; color: #94a3b8; border: 1px solid rgba(148,163,184,0.2);"
            @click="emitAction('abort')"
          >终止</button>
        </div>
      </div>
    </div>
  </Teleport>
</template>
