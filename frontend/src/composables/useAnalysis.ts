import { reactive } from 'vue'
import type { AnalysisState, AgentName, LogEntry } from '../types'
import { useSSE, type SSEEvent } from './useSSE'

function createInitialState(): AnalysisState {
  return {
    taskId: null,
    status: 'idle',
    nodeStates: {
      collector: 'idle',
      analyst: 'idle',
      writer: 'idle',
      qa: 'idle'
    },
    logs: [],
    result: null,
    currentIteration: 0
  }
}

export function useAnalysis() {
  const state = reactive<AnalysisState>(createInitialState())

  function handleEvent(event: SSEEvent) {
    switch (event.type) {
      case 'agent_start': {
        const { agent, iteration } = event.data
        state.nodeStates[agent] = 'running'
        state.currentIteration = iteration
        addLog(`Agent [${agent}] started (iteration ${iteration})`, 'info', agent)
        break
      }
      case 'agent_end': {
        const { agent, iteration, duration_ms } = event.data
        state.nodeStates[agent] = 'done'
        addLog(`Agent [${agent}] completed in ${duration_ms}ms (iteration ${iteration})`, 'success', agent)
        break
      }
      case 'log': {
        const { message, agent } = event.data
        addLog(message, 'info', agent)
        break
      }
      case 'qa_verdict': {
        const { verdict, score, missing_dims, iteration } = event.data
        if (verdict === 'revise') {
          state.nodeStates.collector = 'revise'
          state.nodeStates.analyst = 'revise'
          state.nodeStates.writer = 'revise'
          state.nodeStates.qa = 'done'
          addLog(
            `QA verdict: REVISE (score: ${score}, missing: ${missing_dims.join(', ')}) — iteration ${iteration}`,
            'warning',
            'qa'
          )
        } else {
          addLog(`QA verdict: PASS (score: ${score}) — iteration ${iteration}`, 'success', 'qa')
        }
        break
      }
      case 'complete': {
        state.status = 'completed'
        state.result = event.data
        addLog(`Analysis complete! Final score: ${event.data.qa_score}`, 'success')
        break
      }
      case 'error': {
        state.status = 'failed'
        addLog(`Error: ${event.data.message}`, 'error')
        break
      }
    }
  }

  const { connect, close } = useSSE(handleEvent)

  async function startAnalysis(competitorName: string, dimensions: string[]) {
    resetState()
    state.status = 'running'

    try {
      const response = await fetch('/api/analyze', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ competitor_name: competitorName, dimensions })
      })

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${await response.text()}`)
      }

      const data = await response.json()
      state.taskId = data.task_id
      addLog(`Analysis started for "${competitorName}" (task: ${data.task_id})`, 'info')
      connect(data.task_id)
    } catch (err: any) {
      state.status = 'failed'
      addLog(`Failed to start analysis: ${err.message}`, 'error')
    }
  }

  function resetState() {
    close()
    Object.assign(state, createInitialState())
  }

  function addLog(message: string, type: LogEntry['type'], agent?: AgentName) {
    state.logs.push({
      timestamp: Date.now(),
      message,
      type,
      agent
    })
  }

  return { state, startAnalysis, resetState }
}
