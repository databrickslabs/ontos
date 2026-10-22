import { describe, it, expect, vi } from 'vitest';
import { fireEvent, render, screen, within } from '@testing-library/react';
import type { TagSyncConfig } from '@/types/workflow-configurations';
import TagSyncConfigsField from './tag-sync-configs-field';

const productName: TagSyncConfig = {
  entity_type: 'data_product', enabled: true,
  tag_key_format: 'ontos_product_name', tag_value_format: '{PRODUCT.NAME}',
};
const productLifecycle: TagSyncConfig = {
  entity_type: 'data_product', mapping: 'lifecycle_status', enabled: true,
  tag_key_format: 'ontos_lifecycle_status', tag_value_format: '{PRODUCT.STATUS}',
};

function renderField(value: TagSyncConfig[], entityTypes = ['data_product']) {
  const onChange = vi.fn();
  render(<TagSyncConfigsField value={value} onChange={onChange} entityTypes={entityTypes} />);
  return onChange;
}

describe('TagSyncConfigsField lifecycle status tag', () => {
  it('shows the lifecycle entry in its own card, apart from the main entry', () => {
    // The lifecycle entry comes first: the main card must still show the name entry.
    renderField([productLifecycle, productName]);

    expect(screen.getByLabelText(/Tag Key Format/, { selector: '#data_product-key-format' }))
      .toHaveValue('ontos_product_name');
    const card = screen.getByTestId('data_product-lifecycle-card');
    expect(within(card).getByText('Lifecycle status tag')).toBeInTheDocument();
    expect(within(card).getByRole('textbox')).toHaveValue('ontos_lifecycle_status');
    expect(within(card).getByText('{PRODUCT.STATUS}')).toBeInTheDocument();
    expect(within(card).getByRole('switch')).toBeChecked();
    expect(within(card).getByText(/data product that uses it/)).toBeInTheDocument();
  });

  it('turns the lifecycle tag off without touching the main entry', () => {
    const onChange = renderField([productName, productLifecycle]);

    fireEvent.click(within(screen.getByTestId('data_product-lifecycle-card')).getByRole('switch'));

    expect(onChange).toHaveBeenCalledWith([productName, { ...productLifecycle, enabled: false }]);
  });

  it('edits the lifecycle key and reports an invalid one', () => {
    const onChange = renderField([productName, { ...productLifecycle, tag_key_format: 'a.b' }]);
    const card = screen.getByTestId('data_product-lifecycle-card');

    expect(within(card).getByText("Tag key cannot contain '.'")).toBeInTheDocument();
    fireEvent.change(within(card).getByRole('textbox'), { target: { value: 'lifecycle' } });

    expect(onChange).toHaveBeenCalledWith([
      productName, { ...productLifecycle, tag_key_format: 'lifecycle' },
    ]);
  });

  it('adds the lifecycle entry when the list has none', () => {
    const onChange = renderField([productName]);
    const card = screen.getByTestId('data_product-lifecycle-card');

    fireEvent.change(within(card).getByRole('textbox'), { target: { value: 'status' } });

    expect(onChange).toHaveBeenCalledWith([
      productName, { ...productLifecycle, tag_key_format: 'status' },
    ]);
  });

  it('edits the main entry without touching the lifecycle entry', () => {
    const onChange = renderField([productLifecycle, productName]);

    fireEvent.change(screen.getByDisplayValue('ontos_product_name'),
      { target: { value: 'product' } });

    expect(onChange).toHaveBeenCalledWith([
      productLifecycle, { ...productName, tag_key_format: 'product' },
    ]);
  });

  it('shows the contract entry off by default, with the contract text', () => {
    renderField([], ['data_contract']);
    const card = screen.getByTestId('data_contract-lifecycle-card');

    expect(within(card).getByRole('switch')).not.toBeChecked();
    expect(within(card).getByRole('textbox')).toBeDisabled();
    expect(within(card).getByText('{CONTRACT.STATUS}')).toBeInTheDocument();
    expect(within(card).getByText(/data contract that uses it/)).toBeInTheDocument();
    expect(within(card).queryByText(/Tag key cannot/)).not.toBeInTheDocument();
  });

  it('has no lifecycle card for other entity types', () => {
    renderField([], ['data_domain']);

    expect(screen.queryByTestId('data_domain-lifecycle-card')).not.toBeInTheDocument();
  });
});
