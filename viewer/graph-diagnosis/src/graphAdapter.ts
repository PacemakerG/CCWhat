import type { ActionNode, FeedbackDiagnosis, GraphNode } from './types';

export const actionNodePosition = (index: number) => ({ x: 56 + index * 248, y: 190 });

export const eventNodePosition = (index: number) => ({
  x: 58 + index * 184,
  y: 188 + ((index % 3) - 1) * 86,
});

export function actionForEvent(actions: ActionNode[], eventId: string): ActionNode | undefined {
  return actions.find((action) => action.event_ids.includes(eventId));
}

export function diagnosisActionIds(diagnosis?: FeedbackDiagnosis): Set<string> {
  return new Set((diagnosis?.suspicious_actions || [])
    .map((item) => item.action_id)
    .filter((id): id is string => Boolean(id)));
}

export function diagnosisEventIds(diagnosis?: FeedbackDiagnosis): Set<string> {
  return new Set((diagnosis?.suspicious_events || [])
    .map((item) => item.event_id)
    .filter((id): id is string => Boolean(id)));
}

export function isRelevantEvent(
  event: GraphNode,
  _actions: ActionNode[],
  diagnosis?: FeedbackDiagnosis,
): boolean {
  return diagnosisEventIds(diagnosis).has(event.node_id);
}
