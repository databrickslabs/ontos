import { describe, it, expect } from 'vitest';
import { toTagPayload, toTagSelections } from './tag-selector';

// Values are sent only for tags edited in the picker (#1421). Untouched tags carry no
// assigned_value key, so the backend keeps the stored value (#1420).
describe('tag selections', () => {
  it('keeps the stored value of loaded tags for display only', () => {
    const selections = toTagSelections([
      { tag_id: 't1', tag_name: 'classification', namespace_id: 'n', namespace_name: 'governance', status: 'active', fully_qualified_name: 'governance/classification', assigned_value: 'confidential', assigned_at: '2026-01-01T00:00:00Z' },
    ]);

    expect(selections).toEqual([{ fqn: 'governance/classification', storedValue: 'confidential' }]);
    expect(toTagPayload(selections)).toEqual([{ tag_fqn: 'governance/classification' }]);
  });

  it('turns FQN strings into untouched selections', () => {
    expect(toTagSelections(['governance/pii'])).toEqual([{ fqn: 'governance/pii' }]);
  });

  it('sends the edited value, including an empty string that clears it', () => {
    expect(toTagPayload([
      { fqn: 'governance/classification', value: 'public', storedValue: 'confidential' },
      { fqn: 'governance/pii', value: '' },
      { fqn: 'governance/region' },
    ])).toEqual([
      { tag_fqn: 'governance/classification', assigned_value: 'public' },
      { tag_fqn: 'governance/pii', assigned_value: '' },
      { tag_fqn: 'governance/region' },
    ]);
  });
});
