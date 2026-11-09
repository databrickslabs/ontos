/**
 * The close button of dialogs and sheets is named in the user's language
 * (screen readers announce it; it was always "Close").
 */
import { afterEach, describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import i18n from '@/i18n/config';
import { Dialog, DialogContent, DialogTitle } from './dialog';
import { Sheet, SheetContent, SheetTitle } from './sheet';

describe('dialog and sheet close button', () => {
  afterEach(async () => {
    await i18n.changeLanguage('en');
  });

  it('names the dialog close button in the user language', async () => {
    await i18n.changeLanguage('pt');
    render(<Dialog open><DialogContent><DialogTitle>D</DialogTitle></DialogContent></Dialog>);
    expect(screen.getByRole('button', { name: 'Fechar' })).toBeInTheDocument();
  });

  it('names the sheet close button in the user language', async () => {
    await i18n.changeLanguage('pt');
    render(<Sheet open><SheetContent><SheetTitle>S</SheetTitle></SheetContent></Sheet>);
    expect(screen.getByRole('button', { name: 'Fechar' })).toBeInTheDocument();
  });
});
