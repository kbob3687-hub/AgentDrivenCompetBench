import { reactive } from 'vue'
import type { AnalysisState, AgentName, LogEntry, SubAgentState } from '../types'
import { useSSE, type SSEEvent } from './useSSE'

function createInitialState(): AnalysisState {
  return {
    taskId: null,
    status: 'idle',
    pauseVerdict: null,
    nodeStates: {
      collector: 'idle',
      analyst: 'idle',
      writer: 'idle',
      qa: 'idle'
    },
    logs: [],
    result: null,
    currentIteration: 0,
    iterations: [],
    subAgents: []
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
        if (agent === 'collector') {
          state.subAgents = []
        }
        addLog(`Agent [${agent}] started (iteration ${iteration})`, 'info', agent)
        break
      }
      case 'agent_end': {
        const { agent, iteration, duration_ms } = event.data
        state.nodeStates[agent] = 'done'
        if (agent === 'collector') {
          state.subAgents = []
        }
        addLog(`Agent [${agent}] completed in ${duration_ms}ms (iteration ${iteration})`, 'success', agent)
        break
      }
      case 'log': {
        const { message, agent } = event.data
        addLog(message, 'info', agent)
        break
      }
      case 'qa_verdict': {
        const { verdict, score, iteration } = event.data
        const missing = event.data.missing_dimensions || event.data.missing_dims || []
        if (verdict === 'revise') {
          state.nodeStates.collector = 'revise'
          state.nodeStates.analyst = 'revise'
          state.nodeStates.writer = 'revise'
          state.nodeStates.qa = 'done'
          addLog(
            `QA verdict: REVISE (score: ${score}, missing: ${missing.join(', ')}) — iteration ${iteration}`,
            'warning',
            'qa'
          )
        } else {
          addLog(`QA verdict: ${verdict.toUpperCase()} (score: ${score}) — iteration ${iteration}`, 'success', 'qa')
        }
        break
      }
      case 'iteration_summary': {
        state.iterations.push(event.data)
        break
      }
      case 'sub_agent_start': {
        state.subAgents.push({
          sub_id: event.data.sub_id,
          url: event.data.url,
          status: 'running',
        })
        addLog(`Sub-agent [${event.data.sub_id}] fetching ${new URL(event.data.url).hostname}`, 'info', 'collector')
        break
      }
      case 'sub_agent_end': {
        const sa = state.subAgents.find(s => s.sub_id === event.data.sub_id)
        if (sa) {
          sa.status = event.data.success ? 'done' : 'error'
          sa.claims_count = event.data.claims_count
          sa.duration_ms = event.data.duration_ms
        }
        break
      }
      case 'complete': {
        state.status = 'completed'
        state.result = event.data
        addLog(`Analysis complete! Final score: ${event.data.qa_score}`, 'success')
        break
      }
      case 'hitl_pause': {
        state.status = 'paused'
        state.pauseVerdict = event.data.verdict || 'revise'
        addLog(`Pipeline paused: ${event.data.message} (score: ${event.data.score})`, 'warning', 'qa')
        break
      }
      case 'hitl_resume': {
        state.status = 'running'
        state.pauseVerdict = null
        addLog(`Human decision: ${event.data.decision}, pipeline resumed`, 'info')
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

  async function startAnalysis(competitorName: string, dimensions: string[], industry: string = 'saas', targetUrls: string[] = []) {
    resetState()
    state.status = 'running'

    try {
      const response = await fetch('/api/analyze', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ competitor_name: competitorName, dimensions, industry, target_urls: targetUrls })
      })

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${await response.text()}`)
      }

      const data = await response.json()
      state.taskId = data.task_id
      window.location.hash = data.task_id
      addLog(`Analysis started for "${competitorName}" (task: ${data.task_id})`, 'info')
      connect(data.task_id)
    } catch (err: any) {
      state.status = 'failed'
      addLog(`Failed to start analysis: ${err.message}`, 'error')
    }
  }

  async function restoreFromHash(): Promise<boolean> {
    const hash = window.location.hash.slice(1)
    if (!hash || !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(hash)) {
      return false
    }

    try {
      const response = await fetch(`/api/analyze/${hash}`)
      if (!response.ok) return false

      const data = await response.json()
      state.taskId = hash

      if (data.status === 'completed') {
        state.status = 'completed'
        state.result = data.result
        if (data.result?.feedback_history) {
          state.iterations = data.result.feedback_history
          state.currentIteration = data.result.feedback_history.length
        }
      } else if (data.status === 'running') {
        state.status = 'running'
        connect(hash)
      } else if (data.status === 'failed') {
        state.status = 'failed'
      }
      return true
    } catch {
      return false
    }
  }

  function resetState() {
    close()
    Object.assign(state, createInitialState())
    window.location.hash = ''
  }

  function addLog(message: string, type: LogEntry['type'], agent?: AgentName) {
    state.logs.push({
      timestamp: Date.now(),
      message,
      type,
      agent
    })
  }

  async function intervene(action: 'force_pass' | 'abort' | 'continue', reason: string = '') {
    if (!state.taskId) return
    try {
      const response = await fetch(`/api/analyze/${state.taskId}/intervene`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action, reason })
      })
      if (response.ok) {
        if (action === 'force_pass') {
          addLog(`Human intervention: force pass (${reason || 'no reason'})`, 'warning')
        } else if (action === 'abort') {
          state.status = 'failed'
          addLog(`Human intervention: aborted (${reason || 'no reason'})`, 'error')
        } else {
          addLog(`Human intervention: continue iteration`, 'info')
        }
      }
    } catch (err: any) {
      addLog(`Intervene failed: ${err.message}`, 'error')
    }
  }

  return { state, startAnalysis, resetState, restoreFromHash, intervene }
}
