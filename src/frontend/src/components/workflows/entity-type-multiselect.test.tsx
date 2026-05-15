/**
 * Tests for <EntityTypeMultiselect>.
 *
 * Renders the component directly — Checkbox is a much simpler Radix
 * primitive than Select and works reliably in jsdom. We cover:
 *   - Rendering each supported entity type as a row (pretty-printed).
 *   - Auto-prefill when there is exactly one supported type.
 *   - Toggling persists the new array (wire format stays snake_case).
 *   - Empty supported set renders the muted "fires regardless of entity"
 *     placeholder instead of an empty box.
 *   - prettyEntityTypeLabel pure helper — display-only conversion.
 */
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';

import {
  EntityTypeMultiselect,
  prettyEntityTypeLabel,
} from './entity-type-multiselect';

describe('prettyEntityTypeLabel', () => {
  it('converts single-word lowercase values to Sentence case', () => {
    expect(prettyEntityTypeLabel('role')).toBe('Role');
    expect(prettyEntityTypeLabel('project')).toBe('Project');
  });

  it('converts snake_case to Sentence case (only first letter capitalized)', () => {
    expect(prettyEntityTypeLabel('access_grant')).toBe('Access grant');
    expect(prettyEntityTypeLabel('data_product')).toBe('Data product');
    expect(prettyEntityTypeLabel('data_contract')).toBe('Data contract');
  });

  it('handles multi-underscore values', () => {
    expect(prettyEntityTypeLabel('data_asset_review')).toBe('Data asset review');
  });

  it('returns an empty string unchanged', () => {
    expect(prettyEntityTypeLabel('')).toBe('');
  });

  it('leaves already-capitalized single tokens alone (idempotent for sentence-case input)', () => {
    // Defensive: in case any caller hands us an already-pretty value.
    expect(prettyEntityTypeLabel('Role')).toBe('Role');
  });
});

describe('<EntityTypeMultiselect>', () => {
  it('renders one row per supported entity type with Sentence-case labels', () => {
    render(
      <EntityTypeMultiselect
        triggerType="on_create"
        value={[]}
        onChange={vi.fn()}
        supportedEntityTypes={['catalog', 'schema', 'table']}
      />,
    );
    // Pretty-printed labels are visible
    expect(screen.getByText('Catalog')).toBeInTheDocument();
    expect(screen.getByText('Schema')).toBeInTheDocument();
    expect(screen.getByText('Table')).toBeInTheDocument();
  });

  it('renders snake_case multi-word values pretty-printed', () => {
    render(
      <EntityTypeMultiselect
        triggerType="for_request_access"
        value={[]}
        onChange={vi.fn()}
        supportedEntityTypes={['access_grant', 'data_product']}
      />,
    );
    expect(screen.getByText('Access grant')).toBeInTheDocument();
    expect(screen.getByText('Data product')).toBeInTheDocument();
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

  it('auto-prefills the single supported type using the raw snake_case value', () => {
    const onChange = vi.fn();
    render(
      <EntityTypeMultiselect
        triggerType="on_revoke"
        value={[]}
        onChange={onChange}
        supportedEntityTypes={['access_grant']}
      />,
    );
    // Wire format is preserved on the onChange callback — only the label
    // is pretty-printed.
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

  it('toggling an unchecked row adds the raw snake_case value to value[]', () => {
    const onChange = vi.fn();
    render(
      <EntityTypeMultiselect
        triggerType="on_create"
        value={['catalog']}
        onChange={onChange}
        supportedEntityTypes={['catalog', 'schema', 'table']}
      />,
    );
    fireEvent.click(screen.getByLabelText('Schema'));
    // Wire format stays snake_case — the label is just display.
    expect(onChange).toHaveBeenCalledWith(['catalog', 'schema']);
  });

  it('toggling a checked row removes it from value (wire format preserved)', () => {
    const onChange = vi.fn();
    render(
      <EntityTypeMultiselect
        triggerType="on_create"
        value={['catalog', 'schema']}
        onChange={onChange}
        supportedEntityTypes={['catalog', 'schema', 'table']}
      />,
    );
    fireEvent.click(screen.getByLabelText('Catalog'));
    expect(onChange).toHaveBeenCalledWith(['schema']);
  });
});
