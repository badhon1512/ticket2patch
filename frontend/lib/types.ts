export type ActivityLevel = "info" | "success" | "warning" | "error";

export interface AgentRun {
  id: string;
  ticket_key: string;
  repository: string;
  status: string;
  started_at: string;
  updated_at: string;
  completed_at: string | null;
  summary: string | null;
  failure_reason: string | null;
  event_count: number;
  last_activity_at: string | null;
}

export interface ActivityEvent {
  id: string;
  run_id: string;
  sequence: number;
  event_type: string;
  title: string;
  detail: string | null;
  level: ActivityLevel;
  actor: string;
  payload: Record<string, unknown>;
  created_at: string;
}

export interface RunDetail extends AgentRun {
  events: ActivityEvent[];
}
