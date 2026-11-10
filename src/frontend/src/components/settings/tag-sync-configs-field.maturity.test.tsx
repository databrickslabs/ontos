import { describe, it, expect, vi } from 'vitest';
import { fireEvent, render, screen, within } from '@testing-library/react';
import type { TagSyncConfig } from '@/types/workflow-configurations';
import TagSyncConfigsField from './tag-sync-configs-field';
import { defaultMaturityEntry, supportsMaturityMapping } from './tag-sync-configs';

const assetType: TagSyncConfig = {
  entity_type: 'asset', enabled: true,
  tag_key_format: 'ontos_asset_type', tag_value_format: '{ASSET.TYPE}',
};
const maturity: TagSyncConfig = {
  entity_type: 'asset', mapping: 'maturity', enabled: true,
  tag_key_format: 'ontos_context_tier', tag_value_format: '{ASSET.MATURITY}',
};

function renderField(value: TagSyncConfig[], entityTypes = ['asset']) {
  const onChange = vi.fn();
  render(<TagSyncConfigsField value={value} onChange={onChange} entityTypes={entityTypes} />);
  return onChange;
}

describe('TagSyncConfigsField asset maturity tag', () => {
  it('defaults the maturity entry like the job YAML', () => {
    expect(defaultMaturityEntry()).toEqual({
      entity_type: 'asset', mapping: 'maturity', enabled: false,
      tag_key_format: 'ontos_maturity', tag_value_format: '{ASSET.MATURITY}',
    });
    expect(supportsMaturityMapping('asset')).toBe(true);
    expect(supportsMaturityMapping('data_product')).toBe(false);
  });

  it('lists the asset variables, maturity included, on the asset tab', () => {
    renderField([assetType, maturity]);

    expect(screen.getAllByText('{ASSET.MATURITY}').length).toBeGreaterThan(0);
    expect(screen.getAllByText('{ASSET.MATURITY_ORDER}').length).toBeGreaterThan(0);
    expect(screen.getByText(/Maturity level number of a table or view asset/))
      .toBeInTheDocument();
    expect(screen.getByLabelText(/Tag Key Format/, { selector: '#asset-key-format' }))
      .toHaveValue('ontos_asset_type');
  });

  it('shows the maturity entry in its own card with an example tag', () => {
    renderField([maturity, assetType]);
    const card = screen.getByTestId('asset-maturity-card');

    expect(within(card).getByText('Maturity level tag')).toBeInTheDocument();
    expect(within(card).getByRole('switch')).toBeChecked();
    expect(within(card).getByDisplayValue('ontos_context_tier')).toBeInTheDocument();
    expect(within(card).getByText('ontos_context_tier = 2 stars')).toBeInTheDocument();
  });

  it('accepts the level order as the value', () => {
    const onChange = renderField([assetType, maturity]);
    const card = screen.getByTestId('asset-maturity-card');

    fireEvent.change(within(card).getByDisplayValue('{ASSET.MATURITY}'),
      { target: { value: '{ASSET.MATURITY_ORDER}' } });

    expect(onChange).toHaveBeenCalledWith([
      assetType, { ...maturity, tag_value_format: '{ASSET.MATURITY_ORDER}' },
    ]);
  });

  it('reports a value without a maturity variable and an invalid key', () => {
    renderField([assetType,
      { ...maturity, tag_key_format: 'context.tier', tag_value_format: '{ASSET.TYPE}' }]);
    const card = screen.getByTestId('asset-maturity-card');

    expect(within(card).getByText(/Use \{ASSET.MATURITY\} or \{ASSET.MATURITY_ORDER\}/))
      .toBeInTheDocument();
    expect(within(card).getByText("Tag key cannot contain '.'")).toBeInTheDocument();
  });

  it('adds the maturity entry, off, when the list has none', () => {
    const onChange = renderField([assetType]);
    const card = screen.getByTestId('asset-maturity-card');

    expect(within(card).getByRole('switch')).not.toBeChecked();
    expect(within(card).queryByText(/Use \{ASSET.MATURITY\}/)).not.toBeInTheDocument();
    fireEvent.click(within(card).getByRole('switch'));

    expect(onChange).toHaveBeenCalledWith([
      assetType, { ...defaultMaturityEntry(), enabled: true },
    ]);
  });

  it('has no maturity card for other entity types', () => {
    renderField([], ['data_product']);

    expect(screen.queryByTestId('asset-maturity-card')).not.toBeInTheDocument();
  });
});
