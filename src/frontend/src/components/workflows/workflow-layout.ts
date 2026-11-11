/**
 * Node layout for the Workflow Designer (#1419).
 *
 * Step positions are stored on the steps (`workflow_steps.position`). A
 * workflow opens as the user arranged it. Steps without a position (added
 * through the API or YAML after the layout was saved) are placed below the step
 * that leads to them, without moving the others. A workflow is auto-arranged
 * only when no step has a position (older workflows) or the stored positions
 * overlap (hand-written seed data, never shown before). The trigger node has
 * no stored position: it is placed above the first step.
 */
import type { StepPosition } from '@/types/process-workflow';

/** Vertical distance between the trigger node and the first step. */
export const TRIGGER_GAP = 150;

/** About the rendered size of a step node, for overlap checks and placing new steps. */
export const NODE_BOX = { width: 180, height: 90 };

/** Horizontal step between steps placed side by side. */
const SIDE_GAP = 220;

const isPosition = (p: unknown): p is StepPosition =>
  !!p && typeof p === 'object'
  && Number.isFinite((p as StepPosition).x) && Number.isFinite((p as StepPosition).y);

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

const overlaps = (a: StepPosition, b: StepPosition) =>
  Math.abs(a.x - b.x) < NODE_BOX.width && Math.abs(a.y - b.y) < NODE_BOX.height;

/** Whether two of the stored step positions overlap, so the stored layout isn't usable. */
export function storedLayoutOverlaps(steps: { position?: unknown }[]): boolean {
  const placed = steps.map(s => s.position).filter(isPosition);
  return placed.some((p, i) => placed.slice(i + 1).some(q => overlaps(p, q)));
}

/** Whether the stored positions can be shown: at least one step has one, and none overlap. */
export function hasUsableLayout(steps: { position?: unknown }[]): boolean {
  return steps.some(s => isPosition(s.position)) && !storedLayoutOverlaps(steps);
}

interface LinkedStep {
  step_id: string;
  on_pass?: string | null;
  on_fail?: string | null;
  position?: StepPosition | null;
}

/**
 * The steps, with a position for every step that has none: below the step that
 * links to it (or below the lowest step), moved sideways until it overlaps no
 * other step. Steps that have a position keep it.
 */
export function placeMissingSteps<T extends LinkedStep>(steps: T[]): T[] {
  const result = steps.map(s => ({ ...s }));
  const placed = () => result.map(s => s.position).filter(isPosition);
  const free = (start: StepPosition): StepPosition => {
    const pos = { ...start };
    while (placed().some(p => overlaps(p, pos))) pos.x += SIDE_GAP;
    return pos;
  };
  let pending = result.filter(s => !isPosition(s.position));
  // Steps whose predecessor gets placed first are placed in later rounds.
  while (pending.length > 0) {
    let progress = false;
    for (const step of pending) {
      const from = result.find(s => isPosition(s.position) && (s.on_pass === step.step_id || s.on_fail === step.step_id));
      if (from?.position) {
        step.position = free({ x: from.position.x, y: from.position.y + TRIGGER_GAP });
        progress = true;
      }
    }
    pending = pending.filter(s => !isPosition(s.position));
    if (!progress && pending.length > 0) {
      // Nothing links to it from a placed step: below the lowest step.
      const all = placed();
      const lowest = all.length > 0 ? Math.max(...all.map(p => p.y)) : -TRIGGER_GAP;
      const left = all.length > 0 ? Math.min(...all.map(p => p.x)) : 0;
      pending[0].position = free({ x: left, y: lowest + TRIGGER_GAP });
      pending = pending.slice(1);
    }
  }
  return result as T[];
}
