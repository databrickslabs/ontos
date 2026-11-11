import { describe, expect, it } from 'vitest';

import {
  TRIGGER_GAP, hasUsableLayout, placeMissingSteps, roundPosition, storedLayoutOverlaps,
  triggerPositionFor, withNodePositions,
} from './workflow-layout';

describe('hasUsableLayout', () => {
  it('needs at least one stored position', () => {
    expect(hasUsableLayout([{ position: { x: 0, y: 0 } }, {}])).toBe(true);
    expect(hasUsableLayout([{}, { position: null }])).toBe(false);
    expect(hasUsableLayout([{ position: { x: 0, y: Number.NaN } }])).toBe(false);
    expect(hasUsableLayout([])).toBe(false);
  });

  it('is false when stored positions overlap (e.g. hand-written seed data)', () => {
    const seeded = [{ position: { x: 400, y: 300 } }, { position: { x: 350, y: 340 } }];
    expect(storedLayoutOverlaps(seeded)).toBe(true);
    expect(hasUsableLayout(seeded)).toBe(false);
  });

  it('accepts steps that are far enough apart', () => {
    const spaced = [{ position: { x: 0, y: 0 } }, { position: { x: 0, y: 150 } }, { position: { x: 220, y: 0 } }];
    expect(storedLayoutOverlaps(spaced)).toBe(false);
    expect(hasUsableLayout(spaced)).toBe(true);
  });
});

describe('placeMissingSteps', () => {
  it('keeps the stored positions and puts a new step below the step that links to it', () => {
    const result = placeMissingSteps([
      { step_id: 'a', on_pass: 'b', position: { x: 400, y: 40 } },
      { step_id: 'b' },
    ]);

    expect(result.map(s => s.position)).toEqual([{ x: 400, y: 40 }, { x: 400, y: 40 + TRIGGER_GAP }]);
  });

  it('moves a placed step sideways when the spot is taken', () => {
    const result = placeMissingSteps([
      { step_id: 'a', on_pass: 'b', on_fail: 'c', position: { x: 0, y: 0 } },
      { step_id: 'b' },
      { step_id: 'c' },
    ]);

    const [, b, c] = result.map(s => s.position!);
    expect(b).toEqual({ x: 0, y: TRIGGER_GAP });
    expect(c.y).toBe(TRIGGER_GAP);
    expect(Math.abs(c.x - b.x)).toBeGreaterThanOrEqual(180);
  });

  it('places chains and unlinked steps', () => {
    const result = placeMissingSteps([
      { step_id: 'c' },
      { step_id: 'a', on_pass: 'b', position: { x: 10, y: 10 } },
      { step_id: 'b', on_pass: 'c' },
      { step_id: 'lonely' },
    ]);
    const byId = Object.fromEntries(result.map(s => [s.step_id, s.position]));

    expect(byId.b).toEqual({ x: 10, y: 10 + TRIGGER_GAP });
    expect(byId.c).toEqual({ x: 10, y: 10 + 2 * TRIGGER_GAP });
    expect(byId.lonely!.y).toBe(10 + 3 * TRIGGER_GAP);
    expect(storedLayoutOverlaps(result)).toBe(false);
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
