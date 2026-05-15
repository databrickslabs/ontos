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
  ENTITY_TYPE_MULTISELECT_LABEL,
  prettyEntityTypeLabel,
} from './entity-type-multiselect';

describe('prettyEntityTypeLabel', () => {
  it('converts single-word lowercase values to Sentence case', () => {
    expect(prettyEntityTypeLabel('role')).toBe('Role');
    expect(prettyEntityTypeLabel('project')).toBe('Project');
  });

  it('converts snake_case to Sentence case (only first letter capitalized)', () => {
    expect(prettyEntityTypeLabel('data_product')).toBe('Data product');
    expect(prettyEntityTypeLabel('data_contract')).toBe('Data contract');
  });

  it('applies display overrides for wire values that read as internal jargon', () => {
    // access_grant is overridden — "Access grant" reads as internal jargon
    // when surfaced as a "kind of object". "Data object" reads naturally
    // next to "When a user requests access — Applies to: Data object".
    expect(prettyEntityTypeLabel('access_grant')).toBe('Data object');
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

  it('renders snake_case multi-word values pretty-printed (with overrides applied)', () => {
    render(
      <EntityTypeMultiselect
        triggerType="for_request_access"
        value={[]}
        onChange={vi.fn()}
        supportedEntityTypes={['access_grant', 'data_product']}
      />,
    );
    // access_grant is overridden to "Data object"; data_product follows
    // the default snake_case → Sentence case rule.
    expect(screen.getByText('Data object')).toBeInTheDocument();
    expect(screen.getByText('Data product')).toBeInTheDocument();
  });

  it('renders the "Applies to" field label above the checkboxes', () => {
    render(
      <EntityTypeMultiselect
        triggerType="on_create"
        value={[]}
        onChange={vi.fn()}
        supportedEntityTypes={['catalog']}
      />,
    );
    expect(screen.getByText(ENTITY_TYPE_MULTISELECT_LABEL)).toBeInTheDocument();
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
