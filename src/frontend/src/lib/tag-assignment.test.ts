import { describe, it, expect } from 'vitest';
import { toTagAssignment, toTagAssignments } from './tag-assignment';

describe('toTagAssignment', () => {
  it('sends a picked tag as its FQN', () => {
    expect(toTagAssignment('governance/pii')).toBe('governance/pii');
  });

  it('sends an assigned tag with its value', () => {
    expect(
      toTagAssignment({ fully_qualified_name: 'governance/classification', tag_id: 't-1', assigned_value: 'confidential' }),
    ).toEqual({ tag_fqn: 'governance/classification', assigned_value: 'confidential' });
  });

  it('sends an assigned tag without a value as its FQN', () => {
    expect(toTagAssignment({ fully_qualified_name: 'governance/pii', tag_id: 't-1', assigned_value: null })).toBe(
      'governance/pii',
    );
  });

  it('falls back to the tag id when the FQN is missing', () => {
    expect(toTagAssignment({ tag_id: 't-1', assigned_value: 'eu' })).toEqual({ tag_id: 't-1', assigned_value: 'eu' });
    expect(toTagAssignment({ id: 't-2' })).toEqual({ tag_id: 't-2' });
  });

  it('keeps an empty string, which clears the value', () => {
    expect(toTagAssignment({ fully_qualified_name: 'governance/pii', assigned_value: '' })).toEqual({
      tag_fqn: 'governance/pii',
      assigned_value: '',
    });
  });
});

describe('toTagAssignments', () => {
  it('maps a mixed selection and tolerates a missing list', () => {
    expect(
      toTagAssignments([
        'governance/pii',
        { fully_qualified_name: 'governance/classification', assigned_value: 'confidential' },
      ]),
    ).toEqual(['governance/pii', { tag_fqn: 'governance/classification', assigned_value: 'confidential' }]);
    expect(toTagAssignments(undefined)).toEqual([]);
  });
});
