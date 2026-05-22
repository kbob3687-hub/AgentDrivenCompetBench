export type AgentName = 'collector' | 'analyst' | 'writer' | 'qa'
export type NodeStatus = 'idle' | 'running' | 'done' | 'error' | 'revise'

export interface SSEAgentStart { agent: AgentName; iteration: number }
export interface SSEAgentEnd { agent: AgentName; iteration: number; duration_ms: number }
export interface SSELog { message: string; agent?: AgentName; iteration?: number }
export interface SSEQaVerdict { verdict: string; score: number; missing_dims: string[]; iteration: number }
export interface SSEComplete { final_status: string; qa_score: number; report_markdown: string; feedback_history: FeedbackRecord[] }

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
  status: 'idle' | 'running' | 'completed' | 'failed'
  nodeStates: Record<AgentName, NodeStatus>
  logs: LogEntry[]
  result: SSEComplete | null
  currentIteration: number
}

export interface LogEntry {
  timestamp: number
  message: string
  type: 'info' | 'success' | 'warning' | 'error'
  agent?: AgentName
}
