/**
 * Tests for <EntityTypeMultiselect>.
 *
 * Renders the component directly — Checkbox is a much simpler Radix
 * primitive than Select and works reliably in jsdom. We cover:
 *   - Rendering each supported entity type as a row.
 *   - Auto-prefill when there is exactly one supported type.
 *   - Toggling persists the new array.
 *   - Empty supported set renders the muted "fires regardless of entity"
 *     placeholder instead of an empty box.
 */
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';

import { EntityTypeMultiselect } from './entity-type-multiselect';

describe('<EntityTypeMultiselect>', () => {
  it('renders one row per supported entity type', () => {
    render(
      <EntityTypeMultiselect
        triggerType="on_create"
        value={[]}
        onChange={vi.fn()}
        supportedEntityTypes={['catalog', 'schema', 'table']}
      />,
    );
    // All three labels visible
    expect(screen.getByText('catalog')).toBeInTheDocument();
    expect(screen.getByText('schema')).toBeInTheDocument();
    expect(screen.getByText('table')).toBeInTheDocument();
  });

  it('renders the placeholder when the trigger fires regardless of entity', () => {
    render(
      <EntityTypeMultiselect
        triggerType="scheduled"
        value={[]}
        onChange={vi.fn()}
        supportedEntityTypes={[]}
      />,
    );
    expect(
      screen.getByText(/fires regardless of entity type/i),
    ).toBeInTheDocument();
  });

  it('auto-prefills the single supported type', () => {
    const onChange = vi.fn();
    render(
      <EntityTypeMultiselect
        triggerType="on_revoke"
        value={[]}
        onChange={onChange}
        supportedEntityTypes={['access_grant']}
      />,
    );
    expect(onChange).toHaveBeenCalledWith(['access_grant']);
  });

  it('does not auto-prefill when there are multiple supported types', () => {
    const onChange = vi.fn();
    render(
      <EntityTypeMultiselect
        triggerType="on_create"
        value={[]}
        onChange={onChange}
        supportedEntityTypes={['catalog', 'schema', 'table']}
      />,
    );
    expect(onChange).not.toHaveBeenCalled();
  });

  it('toggling an unchecked row adds it to value', () => {
    const onChange = vi.fn();
    render(
      <EntityTypeMultiselect
        triggerType="on_create"
        value={['catalog']}
        onChange={onChange}
        supportedEntityTypes={['catalog', 'schema', 'table']}
      />,
    );
    fireEvent.click(screen.getByLabelText('schema'));
    expect(onChange).toHaveBeenCalledWith(['catalog', 'schema']);
  });

  it('toggling a checked row removes it from value', () => {
    const onChange = vi.fn();
    render(
      <EntityTypeMultiselect
        triggerType="on_create"
        value={['catalog', 'schema']}
        onChange={onChange}
        supportedEntityTypes={['catalog', 'schema', 'table']}
      />,
    );
    fireEvent.click(screen.getByLabelText('catalog'));
    expect(onChange).toHaveBeenCalledWith(['schema']);
  });
});
