/**
 * assign_tag step form (#1423, designer part): fixed value, value from the run
 * or no value, with the tag's possible values offered as a select.
 */
import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

import AssignTagStepForm, { configForMode, valueModeOf } from './assign-tag-step-form';

const api = vi.hoisted(() => ({ get: vi.fn() }));
vi.mock('@/hooks/use-api', () => ({ useApi: () => ({ get: api.get }) }));

beforeAll(() => {
  // Radix Select opens on pointer events jsdom doesn't implement.
  Element.prototype.hasPointerCapture = () => false;
  Element.prototype.releasePointerCapture = () => {};
});

function openSelect(name: string) {
  fireEvent.pointerDown(screen.getByRole('combobox', { name }), { button: 0, ctrlKey: false, pointerType: 'mouse' });
}

function renderForm(config: Record<string, unknown>) {
  const onChange = vi.fn();
  render(<AssignTagStepForm config={config} onChange={onChange} />);
  return onChange;
}

beforeEach(() => {
  api.get.mockReset();
  api.get.mockResolvedValue({ data: null, error: 'Not found' });
});

describe('valueModeOf / configForMode', () => {
  it('reads the mode from the stored config', () => {
    expect(valueModeOf({ key: 'k', value_source: 'current_user' })).toBe('source');
    expect(valueModeOf({ key: 'k', value: 'x' })).toBe('fixed');
    expect(valueModeOf({ key: 'k' })).toBe('none');
    expect(valueModeOf({ key: 'k', value: '' })).toBe('none');
  });

  it('keeps only the fields of the chosen mode', () => {
    const config = { key: 'k', value: 'x', value_source: 'timestamp' };
    expect(configForMode(config, 'none')).toEqual({ key: 'k' });
    expect(configForMode(config, 'fixed')).toEqual({ key: 'k', value: 'x' });
    expect(configForMode(config, 'source')).toEqual({ key: 'k', value_source: 'timestamp' });
    expect(configForMode({ key: 'k' }, 'source')).toEqual({ key: 'k', value_source: 'current_user' });
  });
});

describe('AssignTagStepForm', () => {
  it('sets a fixed value as free text when the tag has no possible values', async () => {
    api.get.mockResolvedValue({ data: { fully_qualified_name: 'default/owner', possible_values: [] } });
    const onChange = renderForm({ key: 'default/owner', value: 'a' });

    fireEvent.change(await screen.findByLabelText('Tag value'), { target: { value: 'team-a' } });

    expect(onChange).toHaveBeenLastCalledWith({ key: 'default/owner', value: 'team-a' });
  });

  it('offers the possible values of the tag', async () => {
    api.get.mockResolvedValue({
      data: { fully_qualified_name: 'governance/classification', possible_values: ['public', 'confidential'] },
    });
    const onChange = renderForm({ key: 'governance/classification', value: 'public' });

    await waitFor(() => expect(api.get).toHaveBeenCalledWith('/api/tags/fqn/governance/classification'));
    await waitFor(() => expect(screen.getByRole('combobox', { name: 'Tag value' })).toBeInTheDocument());
    openSelect('Tag value');
    fireEvent.click(await screen.findByRole('option', { name: 'confidential' }));

    expect(onChange).toHaveBeenLastCalledWith({ key: 'governance/classification', value: 'confidential' });
  });

  it('switches to no value, which drops the value and the value source', async () => {
    const onChange = renderForm({ key: 'governance/pii', value_source: 'current_user' });

    openSelect('Value');
    fireEvent.click(await screen.findByRole('option', { name: 'No value' }));

    expect(onChange).toHaveBeenLastCalledWith({ key: 'governance/pii' });
    expect(await screen.findByText(/assigned without a value/i)).toBeInTheDocument();
  });

  it('switches to a value from the run, defaulting to the current user', async () => {
    const onChange = renderForm({ key: 'owner', value: 'x' });

    openSelect('Value');
    fireEvent.click(await screen.findByRole('option', { name: 'Value from the run' }));

    expect(onChange).toHaveBeenLastCalledWith({ key: 'owner', value_source: 'current_user' });
  });

  it('offers the entity name as a value source', async () => {
    const onChange = renderForm({ key: 'owner', value_source: 'current_user' });

    openSelect('Value Source');
    fireEvent.click(await screen.findByRole('option', { name: 'Entity Name' }));

    expect(onChange).toHaveBeenLastCalledWith({ key: 'owner', value_source: 'entity_name' });
  });

  it('says when no tag has the key', async () => {
    renderForm({ key: 'nope' });

    expect(await screen.findByText(/no tag has this name/i)).toBeInTheDocument();
  });
});
