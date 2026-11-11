/**
 * Node layout for the Workflow Designer (#1419).
 *
 * Step positions are stored on the steps (`workflow_steps.position`). A
 * workflow whose steps all have one opens as the user arranged it; otherwise
 * (older workflows, workflows created through the API or YAML) it is
 * auto-arranged once. The trigger node has no stored position: it is placed
 * above the first step, which keeps it next to the step it starts.
 */
import type { StepPosition } from '@/types/process-workflow';

/** Vertical distance between the trigger node and the first step. */
export const TRIGGER_GAP = 150;

const isPosition = (p: unknown): p is StepPosition =>
  !!p && typeof p === 'object'
  && Number.isFinite((p as StepPosition).x) && Number.isFinite((p as StepPosition).y);

/** Whether every step has a stored position, so the saved layout can be used as is. */
export function hasStoredLayout(steps: { position?: unknown }[]): boolean {
  return steps.length > 0 && steps.every(s => isPosition(s.position));
}

/** Where the trigger node goes for a workflow whose first step is at `entry`. */
export function triggerPositionFor(entry: StepPosition): StepPosition {
  return { x: entry.x, y: entry.y - TRIGGER_GAP };
}

/** Positions are stored as whole pixels. */
export function roundPosition(p: StepPosition): StepPosition {
  return { x: Math.round(p.x), y: Math.round(p.y) };
}

/**
 * The steps with the positions of the matching nodes. Steps without a node keep
 * their position; nodes that are no step (the trigger) are ignored. Returns the
 * same step object when its position doesn't change, so dirty checks stay quiet.
 */
export function withNodePositions<T extends { step_id: string; position?: StepPosition | null }>(
  steps: T[],
  nodes: { id: string; position: StepPosition }[],
): T[] {
  const byId = new Map(nodes.map(n => [n.id, n.position]));
  return steps.map(step => {
    const pos = byId.get(step.step_id);
    if (!pos || !isPosition(pos)) return step;
    const rounded = roundPosition(pos);
    if (step.position && step.position.x === rounded.x && step.position.y === rounded.y) return step;
    return { ...step, position: rounded };
  });
}
