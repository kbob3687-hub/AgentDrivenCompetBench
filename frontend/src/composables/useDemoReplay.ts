import { ref } from 'vue'
import { DEMO_EVENTS, DEMO_TOTAL_DURATION } from '../demo-data'
import type { SSEEvent } from '../types'

export interface DemoReplayState {
  playing: boolean
  completed: boolean
  progress: number
  currentIndex: number
  totalEvents: number
}

export function useDemoReplay(onEvent: (event: SSEEvent) => void) {
  const state = ref<DemoReplayState>({
    playing: false,
    completed: false,
    progress: 0,
    currentIndex: 0,
    totalEvents: DEMO_EVENTS.length,
  })

  let timers: ReturnType<typeof setTimeout>[] = []
  let elapsed = 0

  function start() {
    stop()
    state.value = {
      playing: true,
      completed: false,
      progress: 0,
      currentIndex: 0,
      totalEvents: DEMO_EVENTS.length,
    }
    elapsed = 0

    for (const [idx, item] of DEMO_EVENTS.entries()) {
      elapsed += item.delay
      const scheduledAt = elapsed
      const timer = setTimeout(() => {
        state.value.currentIndex = idx + 1
        state.value.progress = Math.min(
          Math.round((scheduledAt / DEMO_TOTAL_DURATION) * 100),
          100,
        )
        onEvent(item.event)

        if (idx === DEMO_EVENTS.length - 1) {
          state.value.playing = false
          state.value.completed = true
        }
      }, elapsed)
      timers.push(timer)
    }
  }

  function stop() {
    timers.forEach(clearTimeout)
    timers = []
    state.value.playing = false
  }

  return { state, start, stop }
}
