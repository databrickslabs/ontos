/** Validation and stored-trigger warnings of the Workflow Designer (#1438): text and the node each one is about. */
import { describe, it, expect } from 'vitest';

import i18n from '@/i18n/config';
import { getEntityTypeLabel } from '@/lib/workflow-labels';
import type { EntityType } from '@/types/process-workflow';
import { workflowIssueNodeIds, workflowWarningText } from './workflow-warnings';

const en = i18n.getFixedT('en');

describe('workflowWarningText', () => {
  it('says a conditional has no step on a branch, and what that branch does', () => {
    const text = workflowWarningText(
      { code: 'conditional_branch_missing', message: 'backend text', params: { step: 'check', branch: 'false' } },
      en,
    );
    expect(text).toContain('"check"');
    expect(text).toContain('False');
    expect(text).not.toBe('backend text');
  });

  it('says a Pass or Fail step ignores its link', () => {
    const text = workflowWarningText(
      { code: 'terminal_step_has_next', message: 'backend text', params: { step: 'done', target: 'other' } },
      en,
    );
    expect(text).toContain('"done"');
    expect(text).toContain('"other"');
  });

  it('translates the missing policy of a policy check', () => {
    const issue = {
      code: 'policy_check_policy_missing',
      message: 'backend text',
      params: { step: 'gate', policyId: 'p1' },
    };
    const text = workflowWarningText(issue, en);
    expect(text).toContain('"gate"');
    expect(text).not.toBe('backend text');
    expect(workflowWarningText(issue, i18n.getFixedT('pt'))).not.toBe(text);
  });

  it('lists the unreachable steps', () => {
    const text = workflowWarningText(
      { code: 'unreachable_steps', message: 'backend text', params: { steps: ['a', 'b'] } },
      en,
    );
    expect(text).toContain('a, b');
  });

  it('names the trigger and entity type of a stored trigger warning', () => {
    const text = workflowWarningText(
      {
        code: 'stored_entity_type_unsupported',
        message: 'backend text',
        params: { triggerType: 'before_update', entityType: 'data_product' },
      },
      en,
    );
    expect(text).not.toBe('backend text');
    expect(text).toContain(getEntityTypeLabel('data_product' as EntityType, en));
  });

  it('translates into the UI language', () => {
    const issue = {
      code: 'conditional_branch_missing',
      message: 'backend text',
      params: { step: 'check', branch: 'false' },
    };
    expect(workflowWarningText(issue, i18n.getFixedT('de'))).not.toBe(workflowWarningText(issue, en));
  });

  it('falls back to the backend message for a code it does not know', () => {
    expect(workflowWarningText({ code: 'some_future_code', message: 'Backend text' }, en)).toBe('Backend text');
  });
});

describe('workflowIssueNodeIds', () => {
  const stepIds = ['check', 'a', 'b'];

  it('is the step a warning names', () => {
    expect(workflowIssueNodeIds(
      { code: 'conditional_branch_missing', params: { step: 'check', branch: 'true' } },
      stepIds,
    )).toEqual(['check']);
  });

  it('is each existing step of an unreachable-steps warning', () => {
    expect(workflowIssueNodeIds(
      { code: 'unreachable_steps', params: { steps: ['a', 'gone'] } },
      stepIds,
    )).toEqual(['a']);
  });

  it('is the trigger for a stored trigger warning', () => {
    expect(workflowIssueNodeIds(
      { code: 'stored_entity_type_unknown', params: { triggerType: 'on_create', entityType: 'dataset' } },
      stepIds,
    )).toEqual(['trigger']);
  });

  it('is empty for a warning about the workflow as a whole', () => {
    expect(workflowIssueNodeIds({ code: 'some_future_code', params: {} }, stepIds)).toEqual([]);
  });
});
