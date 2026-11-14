/**
 * The value editor of a selected tag waits for the tag definitions (#1494).
 *
 * A tag may have possible_values, so until /api/tags answers, the editor is disabled
 * instead of falling back to free text. If the definitions fail or are denied, it
 * stays disabled. Only a loaded definition without possible_values gets free text.
 *
 * Only the value editors are rendered; the picker popover stays closed (it hangs in jsdom).
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';

const mockGet = vi.fn();

vi.mock('@/hooks/use-api', () => ({
  useApi: () => ({ get: mockGet, post: vi.fn(), put: vi.fn(), delete: vi.fn(), loading: false }),
}));

vi.mock('@/stores/permissions-store', () => ({
  usePermissions: () => ({ hasPermission: () => true }),
}));

// TagChip needs a router and app settings; the chip is not under test here.
vi.mock('./tag-chip', () => ({
  default: ({ tag }: { tag: string }) => <span>{tag}</span>,
}));

import TagSelector, { TagSelection } from './tag-selector';

const classification = {
  id: 'tag-1',
  name: 'classification',
  namespace_name: 'governance',
  fully_qualified_name: 'governance/classification',
  status: 'active',
  possible_values: ['public', 'confidential'],
};

const owner = {
  id: 'tag-2',
  name: 'owner',
  namespace_name: 'governance',
  fully_qualified_name: 'governance/owner',
  status: 'active',
};

const selected: TagSelection[] = [
  { fqn: 'governance/classification', storedValue: 'confidential' },
];

const renderSelector = (value: TagSelection[] = selected) =>
  render(<TagSelector value={value} onChange={vi.fn()} editValues />);

// The editor is the only textbox or combobox labelled "Value".
const valueEditor = () => screen.getByLabelText('Value');

describe('TagSelector value editor waits for the tag definitions', () => {
  beforeEach(() => {
    mockGet.mockReset();
  });

  it('disables the editor with a loading hint while /api/tags is pending', () => {
    mockGet.mockReturnValue(new Promise(() => {}));

    renderSelector();

    expect(valueEditor()).toBeDisabled();
    expect(valueEditor()).toHaveAttribute('placeholder', "Loading the tag's values...");
  });

  it('keeps the editor disabled when the definitions fail to load', async () => {
    mockGet.mockRejectedValue(new Error('network down'));

    renderSelector();

    await waitFor(() =>
      expect(valueEditor()).toHaveAttribute('placeholder', 'Values unavailable: the tag definitions could not be loaded.'),
    );
    expect(valueEditor()).toBeDisabled();
  });

  it('keeps the editor disabled when the definitions are denied', async () => {
    mockGet.mockResolvedValue({ data: {}, error: 'Forbidden', errorCode: null, errorParams: null });

    renderSelector();

    await waitFor(() =>
      expect(valueEditor()).toHaveAttribute('placeholder', 'Values unavailable: the tag definitions could not be loaded.'),
    );
    expect(valueEditor()).toBeDisabled();
  });

  it('shows the stored value in the disabled editor while loading', () => {
    mockGet.mockReturnValue(new Promise(() => {}));

    renderSelector();

    expect(valueEditor()).toHaveValue('confidential');
  });

  it('offers the listed values once the definitions are loaded', async () => {
    mockGet.mockResolvedValue({ data: [classification], error: null });

    renderSelector();

    await waitFor(() => expect(valueEditor()).toBeEnabled());
    // A select, not free text: no textbox, the trigger is a combobox
    expect(screen.queryByRole('textbox', { name: 'Value' })).toBeNull();
    expect(valueEditor()).toHaveAttribute('role', 'combobox');
  });

  it('gives free text for a loaded tag without possible_values', async () => {
    mockGet.mockResolvedValue({ data: [owner], error: null });

    renderSelector([{ fqn: 'governance/owner', storedValue: 'team-a' }]);

    await waitFor(() => expect(valueEditor()).toBeEnabled());
    expect(screen.getByRole('textbox', { name: 'Value' })).toHaveValue('team-a');
  });

  it('shows no editor at all when value editing is off', () => {
    mockGet.mockReturnValue(new Promise(() => {}));

    render(<TagSelector value={selected} onChange={vi.fn()} editValues={false} />);

    expect(screen.queryByLabelText('Value')).toBeNull();
  });
});
