import { reactive } from 'vue'
import type { AnalysisState, AgentName, LogEntry } from '../types'
import { useSSE, type SSEEvent } from './useSSE'

function createInitialState(): AnalysisState {
  return {
    taskId: null,
    status: 'idle',
    pauseVerdict: null,
    pauseContext: null,
    nodeStates: {
      discovery: 'idle',
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
        const missing = event.data.missing_dimensions || []
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
        let hostname = event.data.url
        try { hostname = new URL(event.data.url).hostname } catch {}
        addLog(`Sub-agent [${event.data.sub_id}] fetching ${hostname}`, 'info', 'collector')
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
        state.pauseVerdict = (event.data.verdict === 'pass' || event.data.verdict === 'revise')
          ? event.data.verdict
          : 'revise'
        state.pauseContext = {
          score: event.data.score,
          iteration: event.data.iteration,
          missing_dimensions: event.data.missing_dimensions || [],
          message: event.data.message || '',
          issues: event.data.issues || [],
          score_trend: event.data.score_trend || [],
          suggested_strategy: event.data.suggested_strategy || '',
          current_strategy: event.data.current_strategy || '',
          report_preview: event.data.report_preview || '',
          iterations_left: event.data.iterations_left ?? 0,
          target_agent: event.data.target_agent || '',
          resolved_fields: event.data.resolved_fields || [],
          regressed_fields: event.data.regressed_fields || [],
        }
        addLog(`Pipeline paused: ${event.data.message} (score: ${event.data.score})`, 'warning', 'qa')
        break
      }
      case 'hitl_resume': {
        state.status = 'running'
        state.pauseVerdict = null
        state.pauseContext = null
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
      if (!response.ok) {
        // 任务不存在，清除hash
        window.location.hash = ''
        return false
      }

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
        // 检查SSE连接是否可用，如果不可用则标记为失败
        state.status = 'running'
        connect(hash)
        // 设置超时：如果10秒内没有收到任何事件，认为任务已中断
        setTimeout(() => {
          if (state.status === 'running' && state.logs.length === 0) {
            state.status = 'failed'
            addLog('任务连接超时，可能已中断', 'error')
            close()
            window.location.hash = ''
          }
        }, 10000)
      } else if (data.status === 'failed') {
        state.status = 'failed'
      }
      return true
    } catch {
      // 网络错误，清除hash避免循环恢复
      window.location.hash = ''
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
    if (!state.taskId) {
      addLog('无法介入：当前没有活跃任务', 'error')
      return
    }
    addLog(`发送人工介入指令: ${action}`, 'info')
    try {
      const response = await fetch(`/api/analyze/${state.taskId}/intervene`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action, reason })
      })
      if (!response.ok) {
        const text = await response.text().catch(() => '')
        addLog(`介入失败 (HTTP ${response.status}): ${text || response.statusText}`, 'error')
        return
      }
      // Optimistic state update — don't wait for SSE which may have disconnected
      state.pauseVerdict = null
      state.pauseContext = null
      if (action === 'force_pass') {
        state.status = 'running'
        addLog(`人工确认发布${reason ? ' (' + reason + ')' : ''}，等待报告产出...`, 'warning')
        // Fallback: SSE might miss COMPLETE if connection dropped — poll status
        pollTaskUntilDone(state.taskId)
      } else if (action === 'abort') {
        state.status = 'failed'
        addLog(`已终止任务${reason ? ' (' + reason + ')' : ''}`, 'error')
      } else {
        state.status = 'running'
        addLog(`继续迭代`, 'info')
      }
    } catch (err: any) {
      addLog(`介入请求异常: ${err.message}`, 'error')
    }
  }

  async function pollTaskUntilDone(taskId: string, maxAttempts = 30) {
    for (let i = 0; i < maxAttempts; i++) {
      await new Promise(r => setTimeout(r, 2000))
      // Already updated by SSE → done
      if (state.status === 'completed' || state.status === 'failed') return
      try {
        const r = await fetch(`/api/analyze/${taskId}`)
        if (!r.ok) continue
        const data = await r.json()
        if (data.status === 'completed') {
          state.status = 'completed'
          state.result = data.result
          if (data.result?.feedback_history) {
            state.iterations = data.result.feedback_history
            state.currentIteration = data.result.feedback_history.length
          }
          addLog('任务已完成（轮询补齐）', 'success')
          return
        }
        if (data.status === 'failed') {
          state.status = 'failed'
          addLog(`任务失败: ${data.result?.error || 'unknown'}`, 'error')
          return
        }
      } catch {
        // ignore transient errors
      }
    }
  }

  return { state, startAnalysis, resetState, restoreFromHash, intervene }
}
