/**
 * Tests for the preview-mode step walker on ApprovalWizardDialog (issue #405).
 *
 * The wizard's preview branch walks the workflow's on_pass graph entirely on
 * the client — no /api/approvals/sessions* call, no agreement, no
 * notifications. The bulk of that walker is extracted as the pure helper
 * ``computePreviewNextStep`` so we can verify the graph rules without
 * spinning up the Radix dialog (which is hard to drive in jsdom).
 *
 * What we lock down here:
 *   1. Linear walk follows ``on_pass`` to the next step.
 *   2. Non-visual steps (persist_agreement, generate_pdf, deliver) get
 *      surfaced as the next step — the component's auto-advance effect
 *      then chains them; the walker itself doesn't skip them in one tick.
 *   3. Terminal detection: missing ``on_pass`` ⇒ complete.
 *   4. Terminal detection: a PASS step with no outgoing edges ⇒ complete.
 *   5. The visual-step index returned matches the ordering used by the
 *      progress indicator (non-visual + pass/fail filtered out).
 *   6. Empty / missing steps array is treated as terminal (safety).
 */
import { describe, it, expect } from 'vitest';
import { computePreviewNextStep } from './approval-wizard-dialog';

type Step = Parameters<typeof computePreviewNextStep>[0] extends (infer S)[] | undefined ? S : never;

function step(partial: Partial<Step> & Pick<Step, 'step_id' | 'step_type'>): Step {
  return {
    name: partial.step_id,
    config: {},
    on_pass: null,
    on_fail: null,
    ...partial,
  } as Step;
}

describe('computePreviewNextStep', () => {
  it('advances via on_pass to the next visual step', () => {
    const steps = [
      step({ step_id: 's1', step_type: 'user_action', on_pass: 's2' }),
      step({ step_id: 's2', step_type: 'legal_document' }),
    ];
    const result = computePreviewNextStep(steps, 's1');
    expect(result.kind).toBe('advance');
    if (result.kind !== 'advance') throw new Error('unreachable');
    expect(result.next.step_id).toBe('s2');
    expect(result.nextVisualIndex).toBe(1); // s1 is visual idx 0, s2 is visual idx 1
  });

  it('returns non-visual steps as-is — the auto-advance effect chains them', () => {
    // Component design: walker advances one step per tick. Non-visual steps
    // re-fire the effect, which calls submitStep again, which calls this
    // helper again — eventually reaching a visual step or a terminal.
    const steps = [
      step({ step_id: 's1', step_type: 'user_action', on_pass: 'p1' }),
      step({ step_id: 'p1', step_type: 'persist_agreement', on_pass: 'd1' }),
      step({ step_id: 'd1', step_type: 'deliver' }),
    ];
    const result = computePreviewNextStep(steps, 's1');
    expect(result.kind).toBe('advance');
    if (result.kind !== 'advance') throw new Error('unreachable');
    expect(result.next.step_id).toBe('p1');
    expect(result.next.step_type).toBe('persist_agreement');
    expect(result.nextVisualIndex).toBe(-1); // non-visual steps don't appear in the progress indicator
  });

  it('treats a step with no on_pass as terminal', () => {
    const steps = [step({ step_id: 's1', step_type: 'user_action' })];
    expect(computePreviewNextStep(steps, 's1')).toEqual({ kind: 'terminal' });
  });

  it('treats a PASS step with no outgoing edges as terminal', () => {
    // Mirrors backend rule: when on_pass lands on a PASS step that has no
    // further on_pass/on_fail, the session completes.
    const steps = [
      step({ step_id: 's1', step_type: 'user_action', on_pass: 'end' }),
      step({ step_id: 'end', step_type: 'pass' }),
    ];
    expect(computePreviewNextStep(steps, 's1')).toEqual({ kind: 'terminal' });
  });

  it('does NOT treat a PASS step that branches further as terminal', () => {
    // Edge case: a PASS step used as a branching node (has on_pass) is not
    // terminal — keep walking. Unlikely in practice but the rule is symmetric
    // with the backend.
    const steps = [
      step({ step_id: 's1', step_type: 'user_action', on_pass: 'gate' }),
      step({ step_id: 'gate', step_type: 'pass', on_pass: 's2' }),
      step({ step_id: 's2', step_type: 'legal_document' }),
    ];
    const result = computePreviewNextStep(steps, 's1');
    expect(result.kind).toBe('advance');
    if (result.kind !== 'advance') throw new Error('unreachable');
    expect(result.next.step_id).toBe('gate');
  });

  it('computes visual index correctly when non-visual steps are interleaved', () => {
    // visualSteps = [s1, s2]; non-visual p1 sits between them in workflow
    // order but isn't counted in the progress indicator.
    const steps = [
      step({ step_id: 's1', step_type: 'user_action', on_pass: 'p1' }),
      step({ step_id: 'p1', step_type: 'persist_agreement', on_pass: 's2' }),
      step({ step_id: 's2', step_type: 'acknowledgement_checklist' }),
    ];
    const fromP1 = computePreviewNextStep(steps, 'p1');
    expect(fromP1.kind).toBe('advance');
    if (fromP1.kind !== 'advance') throw new Error('unreachable');
    expect(fromP1.next.step_id).toBe('s2');
    expect(fromP1.nextVisualIndex).toBe(1); // s1=0, s2=1 in the filtered list
  });

  it('returns terminal for missing or empty steps array (safety)', () => {
    expect(computePreviewNextStep(undefined, 's1')).toEqual({ kind: 'terminal' });
    expect(computePreviewNextStep([], 's1')).toEqual({ kind: 'terminal' });
  });

  it('returns terminal when on_pass points to a step that does not exist', () => {
    // Dangling edge: workflow author saved a step with on_pass='gone' but the
    // target was deleted. Treat as terminal so preview at least finishes.
    const steps = [step({ step_id: 's1', step_type: 'user_action', on_pass: 'gone' })];
    expect(computePreviewNextStep(steps, 's1')).toEqual({ kind: 'terminal' });
  });
});
