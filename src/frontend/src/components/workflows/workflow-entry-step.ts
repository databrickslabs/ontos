import { MarkerType } from 'reactflow';
import type { Edge } from 'reactflow';

// The executor starts a workflow at its first step, and the designer saves the
// steps in list order. The trigger edge is therefore not stored: it always
// points at the first step, and connecting the trigger to a step makes that
// step the first one.

export const TRIGGER_NODE_ID = 'trigger';
export const TRIGGER_EDGE_ID = 'trigger-to-first';

export function makeTriggerEdge(target: string): Edge {
  return {
    id: TRIGGER_EDGE_ID,
    source: TRIGGER_NODE_ID,
    target,
    type: 'deletable',
    // Removing it would not be saved: the first step is still where a run starts
    deletable: false,
    markerEnd: { type: MarkerType.ArrowClosed },
  };
}

/**
 * Whether a newly added step is linked from the current last node. Pass / fail
 * steps end a run and have no outgoing handle, so a link from them would be
 * saved as an on_pass the canvas can't show.
 */
export function linksToNewStep(lastNodeType?: string): boolean {
  return lastNodeType !== 'pass' && lastNodeType !== 'fail';
}

/** The steps with `stepId` moved to the front, the rest in their order. */
export function withEntryStep<T extends { step_id: string }>(steps: T[], stepId: string): T[] {
  const entry = steps.find(s => s.step_id === stepId);
  if (!entry) return steps;
  return [entry, ...steps.filter(s => s.step_id !== stepId)];
}

/** The edges with the trigger edge pointing at `firstStepId` (none if there are no steps). */
export function withTriggerEdge(edges: Edge[], firstStepId?: string): Edge[] {
  const rest = edges.filter(e => e.source !== TRIGGER_NODE_ID);
  return firstStepId ? [makeTriggerEdge(firstStepId), ...rest] : rest;
}
