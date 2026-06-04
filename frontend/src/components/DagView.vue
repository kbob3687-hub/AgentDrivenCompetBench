<script setup lang="ts">
import { computed } from 'vue'
import { VueFlow, Position } from '@vue-flow/core'
import { Background, BackgroundVariant } from '@vue-flow/background'
import { Controls } from '@vue-flow/controls'
import type { AgentName, NodeStatus, SubAgentState } from '../types'
import DagNode from './DagNode.vue'

const props = defineProps<{
  nodeStates: Record<AgentName, NodeStatus>
  subAgents: SubAgentState[]
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

const agentNodes = computed(() => [
  {
    id: 'discovery',
    type: 'agent',
    position: { x: 30, y: 110 },
    data: { label: 'Discovery', status: props.nodeStates.discovery },
    sourcePosition: Position.Right,
    targetPosition: Position.Left
  },
  {
    id: 'collector',
    type: 'agent',
    position: { x: 175, y: 110 },
    data: { label: 'Collector', status: props.nodeStates.collector },
    sourcePosition: Position.Right,
    targetPosition: Position.Left
  },
  {
    id: 'analyst',
    type: 'agent',
    position: { x: 320, y: 110 },
    data: { label: 'Analyst', status: props.nodeStates.analyst },
    sourcePosition: Position.Right,
    targetPosition: Position.Left
  },
  {
    id: 'writer',
    type: 'agent',
    position: { x: 465, y: 110 },
    data: { label: 'Writer', status: props.nodeStates.writer },
    sourcePosition: Position.Right,
    targetPosition: Position.Left
  },
  {
    id: 'qa',
    type: 'agent',
    position: { x: 610, y: 110 },
    data: { label: 'QA', status: props.nodeStates.qa },
    sourcePosition: Position.Right,
    targetPosition: Position.Left
  }
])

const subNodes = computed(() =>
  props.subAgents.slice(0, 4).map((sa, i) => ({
    id: `sub-${sa.sub_id}`,
    type: 'sub-agent',
    position: { x: 60 + i * 140, y: 245 },
    data: { label: getUrlLabel(sa.url), status: sa.status, claims: sa.claims_count },
    sourcePosition: Position.Top,
    targetPosition: Position.Top
  }))
)

const overflowNode = computed(() => {
  const hiddenCount = props.subAgents.length - 4
  if (hiddenCount <= 0) return []
  const failed = props.subAgents.filter(sa => sa.status === 'error').length
  const done = props.subAgents.filter(sa => sa.status === 'done').length
  return [{
    id: 'sub-overflow',
    type: 'sub-agent',
    position: { x: 620, y: 245 },
    data: {
      label: `+${hiddenCount} sources`,
      status: failed ? 'error' : done ? 'done' : 'running',
      claims: props.subAgents.reduce((sum, sa) => sum + (sa.claims_count || 0), 0),
    },
    sourcePosition: Position.Top,
    targetPosition: Position.Top
  }]
})

const nodes = computed(() => [...agentNodes.value, ...subNodes.value, ...overflowNode.value])

const mainEdges = computed(() => [
  {
    id: 'e-discovery-collector',
    source: 'discovery',
    target: 'collector',
    animated: props.nodeStates.discovery === 'running'
  },
  {
    id: 'e-collector-analyst',
    source: 'collector',
    target: 'analyst',
    animated: props.nodeStates.collector === 'running'
  },
  {
    id: 'e-analyst-writer',
    source: 'analyst',
    target: 'writer',
    animated: props.nodeStates.analyst === 'running'
  },
  {
    id: 'e-writer-qa',
    source: 'writer',
    target: 'qa',
    animated: props.nodeStates.writer === 'running'
  },
  {
    id: 'e-qa-collector',
    source: 'qa',
    target: 'collector',
    label: 'revise',
    type: 'smoothstep',
    style: { stroke: '#f97316', strokeDasharray: '5 5' },
    labelStyle: { fill: '#f97316', fontWeight: 600 },
    labelBgStyle: { fill: '#1e293b' },
    animated: props.nodeStates.qa === 'done' && props.nodeStates.collector === 'revise'
  }
])

const subEdges = computed(() =>
  props.subAgents.slice(0, 4).map(sa => ({
    id: `e-collector-${sa.sub_id}`,
    source: 'collector',
    target: `sub-${sa.sub_id}`,
    type: 'smoothstep',
    style: { stroke: '#a855f7', strokeWidth: 1.5 },
    animated: sa.status === 'running'
  })).concat(
    overflowNode.value.map(node => ({
      id: 'e-collector-overflow',
      source: 'collector',
      target: node.id,
      type: 'smoothstep',
      style: { stroke: '#a855f7', strokeWidth: 1.5 },
      animated: node.data.status === 'running'
    }))
  )
)

const edges = computed(() => [...mainEdges.value, ...subEdges.value])
</script>

<template>
  <div class="h-full bg-white rounded-lg border border-slate-200 overflow-hidden shadow-sm">
    <VueFlow
      :nodes="nodes"
      :edges="edges"
      :fit-view-on-init="true"
      :fit-view-options="{ padding: 0.18, minZoom: 0.55, maxZoom: 1 }"
      :nodes-draggable="false"
      :nodes-connectable="false"
      :zoom-on-scroll="false"
      :pan-on-drag="false"
      class="vue-flow-light"
    >
      <template #node-agent="nodeProps">
        <DagNode :data="nodeProps.data" />
      </template>
      <template #node-sub-agent="nodeProps">
        <div
          class="px-2 py-1.5 rounded border text-center text-[10px] w-[118px] shadow-sm"
          :class="[
            nodeProps.data.status === 'running' ? 'bg-purple-50 border-purple-400 animate-pulse text-purple-700' :
            nodeProps.data.status === 'done' ? 'bg-emerald-50 border-emerald-400 text-emerald-700' :
            'bg-red-50 border-red-400 text-red-700'
          ]"
        >
          <div class="truncate font-medium" :title="nodeProps.data.label">{{ nodeProps.data.label }}</div>
          <div v-if="nodeProps.data.claims != null" class="text-[9px] opacity-70">
            {{ nodeProps.data.claims }} claims
          </div>
        </div>
      </template>
      <Background :variant="BackgroundVariant.Lines" :gap="24" :size="0.4" color="#e2e8f0" />
      <Controls />
    </VueFlow>
  </div>
</template>

<style>
.vue-flow-light {
  --vf-node-bg: transparent;
  --vf-node-text: #334155;
}
.vue-flow__edge-path {
  stroke: #94a3b8;
  stroke-width: 2;
}
.vue-flow__controls {
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 0.5rem;
  box-shadow: 0 1px 3px rgba(0,0,0,0.08);
}
.vue-flow__controls-button {
  background: #fff;
  border-bottom: 1px solid #e2e8f0;
  fill: #64748b;
}
.vue-flow__controls-button:hover {
  background: #f1f5f9;
}
</style>
