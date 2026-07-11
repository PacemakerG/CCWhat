export type Locale = 'zh' | 'en';
export type Theme = 'light' | 'dark';

export interface GraphNode {
  node_id: string;
  type: string;
  label: string;
  timestamp?: string | null;
  event_id?: string | null;
  data?: Record<string, unknown>;
}

export interface ActionNode {
  action_id: string;
  type: string;
  label: string;
  status: string;
  ordinal?: number;
  event_ids: string[];
  started_at?: string | null;
  ended_at?: string | null;
}

export interface GraphEdge {
  edge_id: string;
  from: string;
  to: string;
  type: string;
}

export interface GraphPayload {
  change?: string;
  actionGraph: { actions?: ActionNode[]; edges?: GraphEdge[]; metadata?: Record<string, unknown> };
  eventGraph: { nodes?: GraphNode[]; edges?: GraphEdge[]; metadata?: Record<string, unknown> };
  diagnosis?: Record<string, unknown>;
}

export interface DocumentRef {
  path: string;
  kind: 'requirement' | 'section' | 'document' | 'task';
  anchor: string | null;
}

export interface PrecheckFinding {
  precheck_finding_id: string;
  type: string;
  action_id?: string;
  event_ids?: string[];
  target?: string;
  expected?: string;
  observed?: string;
}

export interface SuspiciousAction {
  action_id?: string;
  reason?: string;
  precheck_finding_ids?: string[];
  document_refs?: DocumentRef[];
}

export interface FeedbackDiagnosis {
  available?: boolean;
  summary?: string;
  symptoms?: Array<{ type?: string; summary?: string }>;
  suspicious_actions?: SuspiciousAction[];
  suspicious_events?: Array<{ event_id?: string; action_id?: string; reason?: string }>;
  precheck_findings?: PrecheckFinding[];
  missing_evidence?: string[];
}

export interface GraphDiagnosisContext {
  changeName: string;
  sessionId?: string;
  taskId?: string;
  locale: Locale;
  theme: Theme;
  graphPayload?: GraphPayload;
  feedbackDiagnosis?: FeedbackDiagnosis;
}
