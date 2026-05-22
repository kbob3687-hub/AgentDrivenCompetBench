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
  | { type: 'complete'; data: SSEComplete }
  | { type: 'error'; data: { message: string } }

export function useSSE(onEvent: (event: SSEEvent) => void) {
  const connected = ref(false)
  let eventSource: EventSource | null = null

  function connect(taskId: string) {
    close()
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
      close()
    }
  }

  function close() {
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
