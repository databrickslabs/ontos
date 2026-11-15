/**
 * The review stage the approve action reaches is the entity's group's own, not
 * the key `approved`: a custom group can name it anything, and a stage keyed
 * `approved` that approve doesn't reach awaits a decision like any other.
 */
import { describe, it, expect } from 'vitest';
import {
  approvedReviewStages, awaitsReviewDecision, isContractPublishable,
} from '@/lib/lifecycle-stages';
import type { LifecycleStage, LifecycleStageGroup } from '@/types/lifecycle-stage-groups';

const stage = (key: string, category: string, order: number): LifecycleStage => ({
  key, label: key, category: category as LifecycleStage['category'], color: null, order,
  is_initial: order === 0,
});
const move = (from_key: string, to_key: string) => ({ from_key, to_key });

// intake -> triage -> signed_off -> live; no `approved` stage
const CUSTOM: LifecycleStageGroup = {
  id: 'g-custom', name: 'Signed off', entity_type: 'data_contract', is_default_for_type: false,
  stages: [
    stage('intake', 'draft', 0), stage('triage', 'review', 1),
    stage('signed_off', 'review', 2), stage('live', 'active', 3),
  ],
  transitions: [move('intake', 'triage'), move('triage', 'signed_off'),
    move('signed_off', 'live')],
};
// `approved` exists but approve doesn't reach it: check -> approved is not a move
const DEFAULT: LifecycleStageGroup = {
  id: 'g-default', name: 'Default', entity_type: 'data_contract', is_default_for_type: true,
  stages: [
    stage('draft', 'draft', 0), stage('proposed', 'review', 1),
    stage('under_review', 'review', 2), stage('approved', 'review', 3),
    stage('active', 'active', 4),
  ],
  transitions: [move('draft', 'proposed'), move('proposed', 'under_review'),
    move('under_review', 'approved'), move('approved', 'active')],
};
const groups = [DEFAULT, CUSTOM];
const row = (status: string, group: string, category: string) => ({
  status, status_category: category, lifecycle_stage_group_id: group,
});

describe('the approve stage of a group', () => {
  it('is the review stage approve reaches, whatever its key', () => {
    expect([...approvedReviewStages(CUSTOM)]).toEqual(['signed_off']);
    expect([...approvedReviewStages(DEFAULT)]).toEqual(['approved']);
  });

  it('decides what awaits a decision and what may be published', () => {
    const signedOff = row('signed_off', 'g-custom', 'review');
    expect(awaitsReviewDecision(signedOff, groups)).toBe(false);
    expect(isContractPublishable(signedOff, groups)).toBe(true);
    const triage = row('triage', 'g-custom', 'review');
    expect(awaitsReviewDecision(triage, groups)).toBe(true);
    expect(isContractPublishable(triage, groups)).toBe(false);
    // The default group keeps today's rule
    expect(isContractPublishable(row('approved', 'g-default', 'review'), groups)).toBe(true);
    expect(awaitsReviewDecision(row('under_review', 'g-default', 'review'), groups)).toBe(true);
  });

  it('keeps a stage keyed approved that approve does not reach awaiting a decision', () => {
    const odd: LifecycleStageGroup = {
      ...CUSTOM, id: 'g-odd',
      stages: [...CUSTOM.stages, stage('approved', 'review', 4)],
      transitions: [...CUSTOM.transitions, move('triage', 'approved')],
    };
    // triage -> approved is allowed, so approve reaches `approved` and not signed_off
    expect([...approvedReviewStages(odd)]).toEqual(['approved']);
    const oddNoMove: LifecycleStageGroup = {
      ...odd, id: 'g-odd2', transitions: CUSTOM.transitions,
    };
    // `approved` exists but approve (from triage) has no move to it: no approve stage
    expect([...approvedReviewStages(oddNoMove)]).toEqual([]);
    expect(awaitsReviewDecision(row('approved', 'g-odd2', 'review'), [oddNoMove])).toBe(true);
  });

  it('falls back to the seeded approved while the groups are not loaded', () => {
    expect(awaitsReviewDecision({ status: 'approved', status_category: 'review' })).toBe(false);
    expect(awaitsReviewDecision({ status: 'proposed', status_category: 'review' })).toBe(true);
  });
});
