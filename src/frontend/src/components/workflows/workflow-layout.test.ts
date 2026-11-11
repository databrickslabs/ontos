import { describe, expect, it } from 'vitest';

import {
  TRIGGER_GAP, hasStoredLayout, roundPosition, triggerPositionFor, withNodePositions,
} from './workflow-layout';

describe('hasStoredLayout', () => {
  it('needs a position on every step', () => {
    expect(hasStoredLayout([{ position: { x: 0, y: 0 } }, { position: { x: 10, y: 200 } }])).toBe(true);
    expect(hasStoredLayout([{ position: { x: 0, y: 0 } }, {}])).toBe(false);
    expect(hasStoredLayout([{ position: { x: 0, y: Number.NaN } }])).toBe(false);
    expect(hasStoredLayout([{ position: null }])).toBe(false);
  });

  it('is false for a workflow without steps', () => {
    expect(hasStoredLayout([])).toBe(false);
  });
});

describe('triggerPositionFor', () => {
  it('places the trigger above the first step', () => {
    expect(triggerPositionFor({ x: 40, y: 300 })).toEqual({ x: 40, y: 300 - TRIGGER_GAP });
  });
});

describe('withNodePositions', () => {
  const steps = [
    { step_id: 'a', position: { x: 0, y: 100 } },
    { step_id: 'b' },
    { step_id: 'c', position: { x: 5, y: 5 } },
  ];

  it('copies the node positions onto the steps, rounded', () => {
    const result = withNodePositions(steps, [
      { id: 'trigger', position: { x: 1, y: 1 } },
      { id: 'a', position: { x: 12.4, y: 99.6 } },
      { id: 'b', position: { x: -30, y: 250 } },
    ]);

    expect(result.map(s => s.position)).toEqual([{ x: 12, y: 100 }, { x: -30, y: 250 }, { x: 5, y: 5 }]);
  });

  it('keeps the step objects whose position is unchanged', () => {
    const result = withNodePositions(steps, [{ id: 'a', position: { x: 0, y: 100 } }]);

    expect(result[0]).toBe(steps[0]);
    expect(result[2]).toBe(steps[2]);
  });
});

describe('roundPosition', () => {
  it('rounds to whole pixels', () => {
    expect(roundPosition({ x: 1.5, y: -2.4 })).toEqual({ x: 2, y: -2 });
  });
});
