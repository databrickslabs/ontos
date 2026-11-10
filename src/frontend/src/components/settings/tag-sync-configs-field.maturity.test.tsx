import { describe, it, expect, vi } from 'vitest';
import { fireEvent, render, screen, within } from '@testing-library/react';
import type { TagSyncConfig } from '@/types/workflow-configurations';
import TagSyncConfigsField from './tag-sync-configs-field';
import {
  defaultMaturityEntry,
  hasInvalidMaturityThreshold,
  resolveMaturityThresholds,
  supportsMaturityMapping,
  usesMaturityVariable,
} from './tag-sync-configs';

describe('maturity threshold helpers', () => {
  it('recognises the threshold variable as a maturity variable', () => {
    expect(usesMaturityVariable('{ASSET.MATURITY_AT_LEAST:2}')).toBe(true);
    expect(usesMaturityVariable('{ASSET.TYPE}')).toBe(false);
  });

  it('flags a threshold that is not a level number', () => {
    expect(hasInvalidMaturityThreshold('{ASSET.MATURITY_AT_LEAST:2}')).toBe(false);
    expect(hasInvalidMaturityThreshold('{ASSET.MATURITY_AT_LEAST:}')).toBe(true);
    expect(hasInvalidMaturityThreshold('{ASSET.MATURITY_AT_LEAST:-1}')).toBe(true);
    expect(hasInvalidMaturityThreshold('{ASSET.MATURITY_AT_LEAST:2')).toBe(true);
  });

  it('resolves thresholds to true or false, and false without a level', () => {
    expect(resolveMaturityThresholds('{ASSET.MATURITY_AT_LEAST:2}', 2)).toBe('true');
    expect(resolveMaturityThresholds('{ASSET.MATURITY_AT_LEAST:3}', 2)).toBe('false');
    expect(resolveMaturityThresholds('{ASSET.MATURITY_AT_LEAST:1}', null)).toBe('false');
  });
});

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

  it('lists the threshold variable on the asset tab with its own description', () => {
    renderField([assetType, maturity]);

    expect(screen.getAllByText('{ASSET.MATURITY_AT_LEAST:<order>}').length).toBeGreaterThan(0);
    expect(screen.getByText(/is at least <order>/)).toBeInTheDocument();
  });

  it('accepts a threshold value and previews it as true or false', () => {
    renderField([assetType, {
      ...maturity, tag_key_format: 'agent_readable',
      tag_value_format: '{ASSET.MATURITY_AT_LEAST:1}',
    }]);
    const card = screen.getByTestId('asset-maturity-card');

    expect(within(card).queryByText(/Use \{ASSET.MATURITY\}/)).not.toBeInTheDocument();
    // The example asset is at level 3: 1 is reached
    expect(within(card).getByText('agent_readable = true')).toBeInTheDocument();
  });

  it('reports a malformed threshold instead of previewing it', () => {
    renderField([assetType, {
      ...maturity, tag_key_format: 'agent_readable',
      tag_value_format: '{ASSET.MATURITY_AT_LEAST:x}',
    }]);
    const card = screen.getByTestId('asset-maturity-card');

    expect(within(card).getByText(/Use \{ASSET.MATURITY_AT_LEAST:<order>\} with a level number/))
      .toBeInTheDocument();
    expect(within(card).queryByText(/agent_readable = /)).not.toBeInTheDocument();
  });

  it('has no maturity card for other entity types', () => {
    renderField([], ['data_product']);

    expect(screen.queryByTestId('asset-maturity-card')).not.toBeInTheDocument();
  });
});
