export type RunState =
  | "draft"
  | "awaiting_approval"
  | "executing"
  | "completed"
  | "failed"
  | "cancelled";

export interface Citation {
  document_id: string;
  page: number;
  chunk_id: string;
}

export interface CitedClaim {
  text: string;
  citations: Citation[];
}

export interface ResearchRun {
  id: string;
  query: string;
  state: RunState;
  approval_required: boolean;
  trace_id: string;
  answer?: {answer: string; claims: CitedClaim[]; abstained: boolean};
}

export interface AuditEvent {
  id: number;
  event_type: string;
  state: RunState;
  actor: string;
  created_at: string;
}
