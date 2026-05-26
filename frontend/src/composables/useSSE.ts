import { ref, onUnmounted } from 'vue'
import type { SSEAgentStart, SSEAgentEnd, SSELog, SSEQaVerdict, SSEComplete, SSESubAgentStart, SSESubAgentEnd, FeedbackRecord } from '../types'

export type SSEEvent =
  | { type: 'agent_start'; data: SSEAgentStart }
  | { type: 'agent_end'; data: SSEAgentEnd }
  | { type: 'log'; data: SSELog }
  | { type: 'qa_verdict'; data: SSEQaVerdict }
  | { type: 'iteration_summary'; data: FeedbackRecord }
  | { type: 'sub_agent_start'; data: SSESubAgentStart }
  | { type: 'sub_agent_end'; data: SSESubAgentEnd }
  | { type: 'hitl_pause'; data: { iteration: number; score: number; verdict: string; missing_dimensions: string[]; message: string } }
  | { type: 'hitl_resume'; data: { decision: string; iteration: number } }
  | { type: 'complete'; data: SSEComplete }
  | { type: 'error'; data: { message: string } }

const MAX_RECONNECT_ATTEMPTS = 5

export function useSSE(onEvent: (event: SSEEvent) => void) {
  const connected = ref(false)
  let eventSource: EventSource | null = null
  let currentTaskId: string | null = null
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null
  let reconnectAttempts = 0

  function connect(taskId: string) {
    close()
    currentTaskId = taskId
    reconnectAttempts = 0
    _open(taskId)
  }

  function _open(taskId: string) {
    const url = `/api/analyze/${taskId}/stream`
    eventSource = new EventSource(url)
    connected.value = true

    eventSource.addEventListener('agent_start', (e: MessageEvent) => {
      onEvent({ type: 'agent_start', data: JSON.parse(e.data) })
    })

    eventSource.addEventListener('agent_end', (e: MessageEvent) => {
      onEvent({ type: 'agent_end', data: JSON.parse(e.data) })
    })

    eventSource.addEventListener('log', (e: MessageEvent) => {
      onEvent({ type: 'log', data: JSON.parse(e.data) })
    })

    eventSource.addEventListener('qa_verdict', (e: MessageEvent) => {
      onEvent({ type: 'qa_verdict', data: JSON.parse(e.data) })
    })

    eventSource.addEventListener('iteration_summary', (e: MessageEvent) => {
      onEvent({ type: 'iteration_summary', data: JSON.parse(e.data) })
    })

    eventSource.addEventListener('sub_agent_start', (e: MessageEvent) => {
      onEvent({ type: 'sub_agent_start', data: JSON.parse(e.data) })
    })

    eventSource.addEventListener('sub_agent_end', (e: MessageEvent) => {
      onEvent({ type: 'sub_agent_end', data: JSON.parse(e.data) })
    })

    eventSource.addEventListener('hitl_pause', (e: MessageEvent) => {
      onEvent({ type: 'hitl_pause', data: JSON.parse(e.data) })
    })

    eventSource.addEventListener('hitl_resume', (e: MessageEvent) => {
      onEvent({ type: 'hitl_resume', data: JSON.parse(e.data) })
    })

    eventSource.addEventListener('complete', (e: MessageEvent) => {
      onEvent({ type: 'complete', data: JSON.parse(e.data) })
      close()
    })

    eventSource.addEventListener('error', (e: MessageEvent) => {
      if (e.data) {
        onEvent({ type: 'error', data: JSON.parse(e.data) })
      }
      close()
    })

    eventSource.onerror = () => {
      if (eventSource) {
        eventSource.close()
        eventSource = null
        connected.value = false
      }

      reconnectAttempts++

      // Stop reconnecting after max attempts
      if (reconnectAttempts >= MAX_RECONNECT_ATTEMPTS) {
        onEvent({
          type: 'error',
          data: { message: `SSE连接失败，已重试${MAX_RECONNECT_ATTEMPTS}次` }
        })
        currentTaskId = null
        return
      }

      // Auto-reconnect after 2s if not explicitly closed
      if (currentTaskId) {
        reconnectTimer = setTimeout(() => {
          if (currentTaskId) _open(currentTaskId)
        }, 2000)
      }
    }
  }

  function close() {
    currentTaskId = null
    reconnectAttempts = 0
    if (reconnectTimer) {
      clearTimeout(reconnectTimer)
      reconnectTimer = null
    }
    if (eventSource) {
      eventSource.close()
      eventSource = null
      connected.value = false
    }
  }

  onUnmounted(() => {
    close()
  })

  return { connect, close, connected }
}
