<script setup lang="ts">
import { computed } from 'vue'
import { VueFlow, Position } from '@vue-flow/core'
import { Background } from '@vue-flow/background'
import { Controls } from '@vue-flow/controls'
import type { AgentName, NodeStatus, SubAgentState } from '../types'
import DagNode from './DagNode.vue'

const props = defineProps<{
  nodeStates: Record<AgentName, NodeStatus>
  subAgents: SubAgentState[]
}>()

function getHostname(url: string): string {
  try { return new URL(url).hostname.replace('www.', '') }
  catch { return url.slice(0, 20) }
}

const agentNodes = computed(() => [
  {
    id: 'collector',
    type: 'agent',
    position: { x: 50, y: 100 },
    data: { label: 'Collector', status: props.nodeStates.collector },
    sourcePosition: Position.Right,
    targetPosition: Position.Left
  },
  {
    id: 'analyst',
    type: 'agent',
    position: { x: 250, y: 100 },
    data: { label: 'Analyst', status: props.nodeStates.analyst },
    sourcePosition: Position.Right,
    targetPosition: Position.Left
  },
  {
    id: 'writer',
    type: 'agent',
    position: { x: 450, y: 100 },
    data: { label: 'Writer', status: props.nodeStates.writer },
    sourcePosition: Position.Right,
    targetPosition: Position.Left
  },
  {
    id: 'qa',
    type: 'agent',
    position: { x: 650, y: 100 },
    data: { label: 'QA', status: props.nodeStates.qa },
    sourcePosition: Position.Right,
    targetPosition: Position.Left
  }
])

const subNodes = computed(() =>
  props.subAgents.map((sa, i) => ({
    id: `sub-${sa.sub_id}`,
    type: 'sub-agent',
    position: { x: 20 + i * 100, y: 220 },
    data: { label: getHostname(sa.url), status: sa.status, claims: sa.claims_count },
    sourcePosition: Position.Top,
    targetPosition: Position.Top
  }))
)

const nodes = computed(() => [...agentNodes.value, ...subNodes.value])

const mainEdges = computed(() => [
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
  props.subAgents.map(sa => ({
    id: `e-collector-${sa.sub_id}`,
    source: 'collector',
    target: `sub-${sa.sub_id}`,
    type: 'smoothstep',
    style: { stroke: '#a855f7', strokeWidth: 1.5 },
    animated: sa.status === 'running'
  }))
)

const edges = computed(() => [...mainEdges.value, ...subEdges.value])
</script>

<template>
  <div class="h-full bg-slate-900 rounded-lg border border-slate-700 overflow-hidden">
    <VueFlow
      :nodes="nodes"
      :edges="edges"
      :fit-view-on-init="true"
      :nodes-draggable="false"
      :nodes-connectable="false"
      :zoom-on-scroll="false"
      :pan-on-drag="false"
      class="vue-flow-dark"
    >
      <template #node-agent="nodeProps">
        <DagNode :data="nodeProps.data" />
      </template>
      <template #node-sub-agent="nodeProps">
        <div
          class="px-2 py-1.5 rounded border text-center text-[10px] min-w-[70px]"
          :class="[
            nodeProps.data.status === 'running' ? 'bg-purple-900/80 border-purple-500 animate-pulse text-purple-100' :
            nodeProps.data.status === 'done' ? 'bg-green-900/80 border-green-600 text-green-100' :
            'bg-red-900/80 border-red-600 text-red-100'
          ]"
        >
          <div class="truncate font-medium">{{ nodeProps.data.label }}</div>
          <div v-if="nodeProps.data.claims != null" class="text-[9px] opacity-70">
            {{ nodeProps.data.claims }} claims
          </div>
        </div>
      </template>
      <Background />
      <Controls />
    </VueFlow>
  </div>
</template>

<style>
.vue-flow-dark {
  --vf-node-bg: transparent;
  --vf-node-text: #e2e8f0;
}
.vue-flow__edge-path {
  stroke: #64748b;
  stroke-width: 2;
}
.vue-flow__controls {
  background: #1e293b;
  border: 1px solid #334155;
  border-radius: 0.5rem;
}
.vue-flow__controls-button {
  background: #1e293b;
  border-bottom: 1px solid #334155;
  fill: #94a3b8;
}
.vue-flow__controls-button:hover {
  background: #334155;
}
</style>
