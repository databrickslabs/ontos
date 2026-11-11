/**
 * The new-version dialog: a contract version must be X.Y.Z (the contract page
 * clones the contract, which requires it); a product version stays free text.
 */
import { screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi, afterEach } from 'vitest';
import i18n from '@/i18n/config';
import { renderWithProviders } from '@/test/utils';
import CreateVersionDialog from './create-version-dialog';

const renderDialog = (requireSemver: boolean) => {
  const onSubmit = vi.fn();
  renderWithProviders(
    <CreateVersionDialog
      isOpen
      onOpenChange={() => {}}
      currentVersion="1.0.0"
      productTitle="orders"
      onSubmit={onSubmit}
      requireSemver={requireSemver}
    />,
  );
  return onSubmit;
};

const submit = (version: string) => {
  fireEvent.change(screen.getByRole('textbox'), { target: { value: version } });
  fireEvent.click(screen.getByRole('button', { name: i18n.t('data-products:createVersion.createButton') }));
};

describe('CreateVersionDialog', () => {
  afterEach(async () => {
    await i18n.changeLanguage('en');
  });

  it('refuses a contract version that is not X.Y.Z', () => {
    const onSubmit = renderDialog(true);

    submit('2.1');

    expect(onSubmit).not.toHaveBeenCalled();
    expect(screen.getByText('"2.1" is not in the X.Y.Z form (for example 2.0.0).')).toBeInTheDocument();
  });

  it('says it in Portuguese', async () => {
    await i18n.changeLanguage('pt');
    const onSubmit = renderDialog(true);

    submit('v2.0.0');

    expect(onSubmit).not.toHaveBeenCalled();
    expect(screen.getByText('"v2.0.0" não está no formato X.Y.Z (por exemplo 2.0.0).')).toBeInTheDocument();
  });

  it('sends an X.Y.Z contract version', () => {
    const onSubmit = renderDialog(true);

    submit(' 2.0.0 ');

    expect(onSubmit).toHaveBeenCalledWith('2.0.0');
  });

  it('keeps a product version free text', () => {
    const onSubmit = renderDialog(false);

    submit('v2.0-beta');

    expect(onSubmit).toHaveBeenCalledWith('v2.0-beta');
  });
});
