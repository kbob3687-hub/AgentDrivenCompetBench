<script setup lang="ts">
import { computed } from 'vue'
import { VueFlow, Position } from '@vue-flow/core'
import { Background } from '@vue-flow/background'
import { Controls } from '@vue-flow/controls'
import type { AgentName, NodeStatus } from '../types'
import DagNode from './DagNode.vue'

const props = defineProps<{
  nodeStates: Record<AgentName, NodeStatus>
}>()

const nodes = computed(() => [
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
    position: { x: 230, y: 100 },
    data: { label: 'Analyst', status: props.nodeStates.analyst },
    sourcePosition: Position.Right,
    targetPosition: Position.Left
  },
  {
    id: 'writer',
    type: 'agent',
    position: { x: 410, y: 100 },
    data: { label: 'Writer', status: props.nodeStates.writer },
    sourcePosition: Position.Right,
    targetPosition: Position.Left
  },
  {
    id: 'qa',
    type: 'agent',
    position: { x: 590, y: 100 },
    data: { label: 'QA', status: props.nodeStates.qa },
    sourcePosition: Position.Right,
    targetPosition: Position.Left
  }
])

const edges = computed(() => [
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
