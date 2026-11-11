import { describe, it, expect } from 'vitest';
import type { Edge } from 'reactflow';
import {
  TRIGGER_EDGE_ID, TRIGGER_NODE_ID, linksToNewStep, makeTriggerEdge, withEntryStep, withTriggerEdge,
} from './workflow-entry-step';

const steps = [
  { step_id: 'reason', order: 0 },
  { step_id: 'done', order: 1 },
  { step_id: 'obo', order: 2 },
];

const passEdge = (source: string, target: string): Edge => ({
  id: `${source}-pass`, source, sourceHandle: 'pass', target,
});

describe('withEntryStep', () => {
  it('moves the connected step to the front and keeps the others in order', () => {
    expect(withEntryStep(steps, 'obo').map(s => s.step_id)).toEqual(['obo', 'reason', 'done']);
  });

  it('keeps the steps when the step is already first', () => {
    expect(withEntryStep(steps, 'reason')).toEqual(steps);
  });

  it('keeps the steps when the step is unknown', () => {
    expect(withEntryStep(steps, 'nope')).toBe(steps);
  });
});

describe('withTriggerEdge', () => {
  it('replaces the trigger edge and keeps the step edges', () => {
    const edges = [makeTriggerEdge('reason'), passEdge('reason', 'done'), passEdge('obo', 'reason')];

    const result = withTriggerEdge(edges, 'obo');

    const fromTrigger = result.filter(e => e.source === TRIGGER_NODE_ID);
    expect(fromTrigger).toHaveLength(1);
    expect(fromTrigger[0].target).toBe('obo');
    expect(result.filter(e => e.source !== TRIGGER_NODE_ID)).toHaveLength(2);
  });

  it('drops the trigger edge when there is no step left', () => {
    expect(withTriggerEdge([makeTriggerEdge('reason')], undefined)).toEqual([]);
  });
});

describe('makeTriggerEdge', () => {
  it('cannot be deleted, since the first step stays the entry step', () => {
    const edge = makeTriggerEdge('reason');
    expect(edge.id).toBe(TRIGGER_EDGE_ID);
    expect(edge.deletable).toBe(false);
  });
});

describe('linksToNewStep', () => {
  it('links a new step from a step or the trigger', () => {
    expect(linksToNewStep('user_action')).toBe(true);
    expect(linksToNewStep('trigger')).toBe(true);
  });

  it('does not link it from a pass or fail step, which has no outgoing handle', () => {
    expect(linksToNewStep('pass')).toBe(false);
    expect(linksToNewStep('fail')).toBe(false);
  });
});

describe('connecting the trigger, then saving and reloading', () => {
  it('starts with the connected step, as the executor runs steps[0] first', () => {
    // The designer saves steps in list order, and draws the trigger edge
    // to steps[0] when the workflow is loaded again.
    const saved = withEntryStep(steps, 'obo').map((s, i) => ({ ...s, order: i }));

    expect(saved[0]).toEqual({ step_id: 'obo', order: 0 });
    expect(withTriggerEdge([], saved[0].step_id)[0].target).toBe('obo');
  });
});
