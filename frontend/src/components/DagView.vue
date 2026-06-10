<script setup lang="ts">
import { computed } from 'vue'
import { VueFlow, Position } from '@vue-flow/core'
import { Background, BackgroundVariant } from '@vue-flow/background'
import type { AgentName, NodeStatus, SubAgentState } from '../types'
import DagNode from './DagNode.vue'

const props = defineProps<{
  nodeStates: Record<AgentName, NodeStatus>
  subAgents: SubAgentState[]
  qaTargetAgent: AgentName | null
}>()

function getUrlLabel(rawUrl: string): string {
  try {
    const url = new URL(rawUrl)
    const host = url.hostname.replace('www.', '')
    const path = `${url.pathname}${url.search}` || '/'
    return `${host}${path}`
  } catch {
    return rawUrl
  }
}

// ---- 布局 ----
// 生产层 (y=140): Discovery → Collector → Analyst → Writer
// 审查层 (y=10):  QA（独立一行，在 Writer 上方）
const PROD_Y = 140
const QA_Y = 10

const agentNodes = computed(() => [
  { id: 'discovery', type: 'agent', position: { x: 10,  y: PROD_Y }, data: { label: 'Discovery', sub: 'URL 发现', status: props.nodeStates.discovery }, sourcePosition: Position.Right, targetPosition: Position.Left },
  { id: 'collector',  type: 'agent', position: { x: 140, y: PROD_Y }, data: { label: 'Collector',  sub: '数据采集',   status: props.nodeStates.collector  }, sourcePosition: Position.Right, targetPosition: Position.Left },
  { id: 'analyst',    type: 'agent', position: { x: 270, y: PROD_Y }, data: { label: 'Analyst',    sub: '结构化分析',  status: props.nodeStates.analyst    }, sourcePosition: Position.Right, targetPosition: Position.Left },
  { id: 'writer',     type: 'agent', position: { x: 400, y: PROD_Y }, data: { label: 'Writer',     sub: '报告撰写',   status: props.nodeStates.writer     }, sourcePosition: Position.Right, targetPosition: Position.Left },
  // QA 审查层 — 独立一行，不在生产层并排
  { id: 'qa',         type: 'agent', position: { x: 400, y: QA_Y },  data: { label: 'QA',         sub: '质量审查',   status: props.nodeStates.qa          }, sourcePosition: Position.Bottom, targetPosition: Position.Top },
])

const subNodes = computed(() =>
  props.subAgents.slice(0, 4).map((sa, i) => ({
    id: `sub-${sa.sub_id}`,
    type: 'sub-agent',
    position: { x: 30 + i * 120, y: 250 },
    data: { label: getUrlLabel(sa.url), status: sa.status, claims: sa.claims_count },
    sourcePosition: Position.Top,
    targetPosition: Position.Top,
  }))
)

const overflowNode = computed(() => {
  const hiddenCount = props.subAgents.length - 4
  if (hiddenCount <= 0) return []
  const failed = props.subAgents.filter(sa => sa.status === 'error').length
  const done   = props.subAgents.filter(sa => sa.status === 'done').length
  return [{
    id: 'sub-overflow',
    type: 'sub-agent',
    position: { x: 510, y: 250 },
    data: {
      label: `+${hiddenCount} sources`,
      status: failed ? 'error' : done ? 'done' : 'running',
      claims: props.subAgents.reduce((sum, sa) => sum + (sa.claims_count || 0), 0),
    },
    sourcePosition: Position.Top,
    targetPosition: Position.Top,
  }]
})

const nodes = computed(() => [...agentNodes.value, ...subNodes.value, ...overflowNode.value])

// ---- 边 ----

function edgeStyle(animated: boolean) {
  return animated
    ? { stroke: '#60a5fa', strokeWidth: 2 }
    : { stroke: '#334155', strokeWidth: 1.5 }
}

// 生产层线性边
const mainEdges = computed(() => [
  { id: 'e-disc-coll', source: 'discovery', target: 'collector', animated: props.nodeStates.discovery === 'running', style: edgeStyle(props.nodeStates.discovery === 'running') },
  { id: 'e-coll-anal', source: 'collector',  target: 'analyst',   animated: props.nodeStates.collector  === 'running', style: edgeStyle(props.nodeStates.collector  === 'running') },
  { id: 'e-anal-writ', source: 'analyst',    target: 'writer',    animated: props.nodeStates.analyst    === 'running', style: edgeStyle(props.nodeStates.analyst    === 'running') },
  // Writer 产出 → 提交 QA 审查
  {
    id: 'e-writ-qa',
    source: 'writer', target: 'qa',
    type: 'smoothstep',
    style: { stroke: '#818cf8', strokeWidth: 1.5 },
    animated: props.nodeStates.writer === 'running' || props.nodeStates.qa === 'running',
    label: '提交审查', labelStyle: { fill: '#a5b4fc', fontWeight: 600, fontSize: 10 }, labelBgStyle: { fill: '#0b1120', fillOpacity: 0.9 },
  },
])

// QA 三条回环边 — 按问题类型路由，只亮被触发的那条
// labelX/labelY 手动偏移，避免三條 label 挤在一起
function qaEdge(id: string, target: AgentName, lx: number, ly: number, label: string, condition: string) {
  const isActive = props.nodeStates.qa === 'done'
    && (props.nodeStates[target] === 'revise' || props.nodeStates[target] === 'running')
    && props.qaTargetAgent === target
  return {
    id,
    source: 'qa', target,
    type: 'smoothstep',
    label: `${label}\n(${condition})`,
    labelX: lx, labelY: ly,
    style: {
      stroke: isActive ? '#fb923c' : '#334155',
      strokeWidth: isActive ? 2 : 1,
      strokeDasharray: isActive ? 'none' : '5 5',
    },
    labelStyle: {
      fill: isActive ? '#fb923c' : '#475569',
      fontWeight: 600, fontSize: 9,
    },
    labelBgStyle: { fill: '#0b1120', fillOpacity: 0.9 },
    animated: isActive,
  }
}

const qaEdges = computed(() => [
  qaEdge('e-qa-coll', 'collector', 200, 80, '数据问题', 'missing_source / factual_error'),
  qaEdge('e-qa-anal', 'analyst',   320, 55, '分析问题', 'low_confidence / inconsistency'),
  qaEdge('e-qa-writ', 'writer',    420, 55, '报告问题', 'schema_violation'),
])

// 子节点边
const subEdges = computed(() => [
  ...props.subAgents.slice(0, 4).map(sa => ({
    id: `e-coll-${sa.sub_id}`,
    source: 'collector', target: `sub-${sa.sub_id}`,
    type: 'smoothstep',
    style: { stroke: sa.status === 'running' ? '#a78bfa' : '#334155', strokeWidth: 1.5 },
    animated: sa.status === 'running',
  })),
  ...overflowNode.value.map(node => ({
    id: 'e-coll-overflow',
    source: 'collector', target: node.id,
    type: 'smoothstep',
    style: { stroke: node.data.status === 'running' ? '#a78bfa' : '#334155', strokeWidth: 1.5 },
    animated: node.data.status === 'running',
  })),
])

const edges = computed(() => [...mainEdges.value, ...qaEdges.value, ...subEdges.value])
</script>

<template>
  <div class="h-full rounded-lg overflow-hidden shadow-sm" style="background: #0b1120; border: 1px solid #1e293b;">
    <VueFlow
      :nodes="nodes"
      :edges="edges"
      :fit-view-on-init="true"
      :fit-view-options="{ padding: 0.18, minZoom: 0.5, maxZoom: 1.2 }"
      :nodes-draggable="false"
      :nodes-connectable="false"
      :zoom-on-scroll="false"
      :pan-on-drag="false"
      class="dag-dark"
    >
      <template #node-agent="nodeProps">
        <DagNode :data="nodeProps.data" />
      </template>

      <template #node-sub-agent="nodeProps">
        <div
          class="px-2 py-1.5 rounded-lg text-center text-[10px] w-[118px] transition-all duration-300"
          :style="{
            background: '#0f172a',
            border: `1px solid ${nodeProps.data.status === 'running' ? '#7c3aed' : nodeProps.data.status === 'done' ? '#065f46' : '#7f1d1d'}`,
            boxShadow: nodeProps.data.status === 'running' ? '0 0 10px 2px rgba(124,58,237,0.4)' : 'none',
            color: nodeProps.data.status === 'running' ? '#c4b5fd' : nodeProps.data.status === 'done' ? '#6ee7b7' : '#fca5a5',
          }"
        >
          <div class="truncate font-medium" :title="nodeProps.data.label">{{ nodeProps.data.label }}</div>
          <div v-if="nodeProps.data.claims != null" class="text-[9px] opacity-60 mt-0.5">
            {{ nodeProps.data.claims }} claims
          </div>
        </div>
      </template>

      <Background :variant="BackgroundVariant.Dots" :gap="20" :size="0.8" color="#1e293b" />
    </VueFlow>
  </div>
</template>

<style>
.dag-dark {
  --vf-node-bg: transparent;
  --vf-node-text: #cbd5e1;
  background: transparent;
}
.dag-dark .vue-flow__edge-path {
  stroke: #334155;
  stroke-width: 1.5;
}
.dag-dark .vue-flow__edge.animated .vue-flow__edge-path {
  animation: flow-dash 1.4s linear infinite;
}
@keyframes flow-dash {
  from { stroke-dashoffset: 40; }
  to   { stroke-dashoffset: 0; }
}
</style>
