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
// 生产层 (y=120): Discovery → Collector → Analyst → Writer
// 审查层 (y=5):  QA（居中偏右位置）
const PROD_Y = 120
const QA_Y = 5

const agentNodes = computed(() => [
  { id: 'discovery', type: 'agent', position: { x: 10,  y: PROD_Y }, data: { label: 'Discovery', sub: 'URL 发现', status: props.nodeStates.discovery, role: 'discovery' }, sourcePosition: Position.Right, targetPosition: Position.Left },
  { id: 'collector',  type: 'agent', position: { x: 150, y: PROD_Y }, data: { label: 'Collector',  sub: '数据采集',   status: props.nodeStates.collector,  role: 'collector'  }, sourcePosition: Position.Right, targetPosition: Position.Left },
  { id: 'analyst',    type: 'agent', position: { x: 290, y: PROD_Y }, data: { label: 'Analyst',    sub: '结构化分析',  status: props.nodeStates.analyst,    role: 'analyst'    }, sourcePosition: Position.Right, targetPosition: Position.Left },
  { id: 'writer',     type: 'agent', position: { x: 430, y: PROD_Y }, data: { label: 'Writer',     sub: '报告撰写',   status: props.nodeStates.writer,     role: 'writer'     }, sourcePosition: Position.Right, targetPosition: Position.Left },
  // QA 审查层
  { id: 'qa',         type: 'agent', position: { x: 530, y: QA_Y },  data: { label: 'QA',         sub: '质量审查',   status: props.nodeStates.qa,         role: 'qa'         }, sourcePosition: Position.Bottom, targetPosition: Position.Left },
])

const subNodes = computed(() =>
  props.subAgents.slice(0, 4).map((sa, i) => ({
    id: `sub-${sa.sub_id}`,
    type: 'sub-agent',
    position: { x: 40 + i * 130, y: 230 },
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
    position: { x: 560, y: 230 },
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
    ? { stroke: '#818cf8', strokeWidth: 2.5 }
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
function qaEdge(id: string, target: AgentName, lx: number, ly: number, label: string, condition: string) {
  const isActive = props.nodeStates.qa === 'done'
    && (props.nodeStates[target] === 'revise' || props.nodeStates[target] === 'running')
    && props.qaTargetAgent === target
  const isReject = isActive && target === 'collector'
  return {
    id,
    source: 'qa', target,
    type: 'smoothstep',
    label: `${label}\n(${condition})`,
    labelX: lx, labelY: ly,
    style: {
      stroke: isReject ? '#ef4444' : isActive ? '#fb923c' : '#334155',
      strokeWidth: isActive ? 2.5 : 1,
      strokeDasharray: isActive ? 'none' : '5 5',
      filter: isReject ? 'drop-shadow(0 0 6px rgba(239,68,68,0.6))' : undefined,
    },
    labelStyle: {
      fill: isReject ? '#fca5a5' : isActive ? '#fb923c' : '#475569',
      fontWeight: 600, fontSize: 9,
    },
    labelBgStyle: { fill: '#0b1120', fillOpacity: 0.9 },
    animated: isActive,
  }
}

const qaEdges = computed(() => [
  qaEdge('e-qa-coll', 'collector', 220, 70, '数据问题', 'missing_source'),
  qaEdge('e-qa-anal', 'analyst',   340, 50, '分析问题', 'low_confidence'),
  qaEdge('e-qa-writ', 'writer',    460, 50, '报告问题', 'schema_violation'),
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
      :fit-view-options="{ padding: 0.12, minZoom: 0.35, maxZoom: 1 }"
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
  animation: flow-dash 0.9s linear infinite;
  stroke-dasharray: 12 6;
}
@keyframes flow-dash {
  from { stroke-dashoffset: 36; }
  to   { stroke-dashoffset: 0; }
}
</style>
