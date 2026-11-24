import { describe, expect, it } from 'vitest';

import {
  NODE_BOX, TRIGGER_GAP, hasUsableLayout, newStepPosition, nonDragMoves, placeMissingSteps,
  roundPosition, stepsOverlap, triggerPositionFor, withNodePositions,
} from './workflow-layout';

describe('hasUsableLayout', () => {
  it('needs at least one stored position', () => {
    expect(hasUsableLayout([{ position: { x: 0, y: 0 } }, {}])).toBe(true);
    expect(hasUsableLayout([{}, { position: null }])).toBe(false);
    expect(hasUsableLayout([{ position: { x: 0, y: Number.NaN } }])).toBe(false);
    expect(hasUsableLayout([])).toBe(false);
  });

  it('detects overlapping positions', () => {
    expect(stepsOverlap([{ position: { x: 400, y: 300 } }, { position: { x: 350, y: 340 } }])).toBe(true);
    expect(stepsOverlap([{ position: { x: 0, y: 0 } }, { position: { x: 0, y: 150 } }, { position: { x: 220, y: 0 } }]))
      .toBe(false);
  });
});

describe('placeMissingSteps', () => {
  it('moves only the step that overlaps an earlier one (e.g. hand-written seed data)', () => {
    const result = placeMissingSteps([
      { step_id: 'a', position: { x: 400, y: 300 } },
      { step_id: 'b', position: { x: 350, y: 340 } },
      { step_id: 'c', position: { x: 0, y: 600 } },
    ]);

    expect(result[0].position).toEqual({ x: 400, y: 300 });
    expect(result[2].position).toEqual({ x: 0, y: 600 });
    expect(result[1].position!.y).toBe(340);
    expect(stepsOverlap(result)).toBe(false);
  });

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
    expect(stepsOverlap(result)).toBe(false);
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

describe('newStepPosition', () => {
  it('goes below the lowest node, on a free spot', () => {
    expect(newStepPosition([{ x: 100, y: 50 }])).toEqual({ x: 100, y: 50 + TRIGGER_GAP });
    const taken = [{ x: 0, y: 0 }, { x: 0, y: 300 }, { x: 0, y: 450 }];
    const pos = newStepPosition([...taken, { x: 0, y: 150 }]);
    expect(pos.y).toBe(600);
    expect([...taken, pos].every((p, i, all) => all.slice(i + 1).every(q => (
      Math.abs(p.x - q.x) >= NODE_BOX.width || Math.abs(p.y - q.y) >= NODE_BOX.height
    )))).toBe(true);
  });

  it('starts below the trigger of an empty canvas', () => {
    expect(newStepPosition([])).toEqual({ x: 100, y: 120 });
  });
});

describe('nonDragMoves', () => {
  it('keeps position changes that are not drags', () => {
    expect(nonDragMoves([
      { type: 'position', id: 'a', position: { x: 25, y: 0 } },
      { type: 'position', id: 'b', position: { x: 5, y: 5 }, dragging: true },
      { type: 'position', id: 'c', dragging: false },
      { type: 'select', id: 'd' },
    ])).toEqual([{ id: 'a', position: { x: 25, y: 0 } }]);
  });
});
