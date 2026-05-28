export type AgentName = 'discovery' | 'collector' | 'analyst' | 'writer' | 'qa'
export type NodeStatus = 'idle' | 'running' | 'done' | 'error' | 'revise'

export interface SSEAgentStart { agent: AgentName; iteration: number }
export interface SSEAgentEnd { agent: AgentName; iteration: number; duration_ms: number }
export interface SSELog { message: string; agent?: AgentName; iteration?: number }
export interface SSEQaVerdict { verdict: string; score: number; missing_dimensions: string[]; iteration: number; issues_count?: number }
export interface SSEComplete { final_status: string; qa_score: number; report_markdown: string; feedback_history: FeedbackRecord[]; agent_traces: AgentTrace[]; trace_id: string }

export interface AgentTrace {
  agent: AgentName
  iteration: number
  duration_ms: number
  model: string
  input_tokens: number
  output_tokens: number
  prompt_preview: string
  output_preview: string
  timestamp: string
}

export interface SSESubAgentStart {
  parent: AgentName
  sub_id: string
  url: string
  iteration: number
}

export interface SSESubAgentEnd {
  parent: AgentName
  sub_id: string
  url: string
  iteration: number
  success: boolean
  claims_count: number
  duration_ms: number
}

export interface SubAgentState {
  sub_id: string
  url: string
  status: 'running' | 'done' | 'error'
  claims_count?: number
  duration_ms?: number
}

export interface FeedbackRecord {
  iteration: number
  verdict: string
  score: number
  issues_count: number
  critical_issues: number
  action_taken: string
  feedback_summary: string
}

export interface AnalysisState {
  taskId: string | null
  status: 'idle' | 'running' | 'completed' | 'failed' | 'paused'
  pauseVerdict: 'pass' | 'revise' | null
  pauseContext: PauseContext | null
  nodeStates: Record<AgentName, NodeStatus>
  logs: LogEntry[]
  result: SSEComplete | null
  currentIteration: number
  iterations: FeedbackRecord[]
  subAgents: SubAgentState[]
}

export interface PauseContext {
  score: number
  iteration: number
  missing_dimensions: string[]
  message: string
}

export interface LogEntry {
  timestamp: number
  message: string
  type: 'info' | 'success' | 'warning' | 'error'
  agent?: AgentName
}
