import { describe, it, expect, afterEach } from 'vitest';
import { act, render, screen } from '@testing-library/react';
import i18n from '@/i18n/config';

import { DescriptionSyncNotice, descriptionSyncText } from './description-sync-notice';

const sync = {
  status: 'out_of_sync' as const,
  code: 'uc_description_permission_denied',
  message: 'english fallback',
  params: { object: 'main.sales.orders' },
  at: '2026-11-12T10:00:00Z',
};

describe('DescriptionSyncNotice', () => {
  afterEach(async () => {
    await act(async () => {
      await i18n.changeLanguage('en');
    });
  });

  it('renders nothing when the description is in sync', () => {
    const { container } = render(<DescriptionSyncNotice sync={null} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('says the asset is not in sync, with the translated reason', () => {
    render(<DescriptionSyncNotice sync={sync} />);
    const notice = screen.getByRole('status');
    expect(notice).toHaveTextContent('Not in sync with Unity Catalog.');
    expect(notice).toHaveTextContent(
      'Unity Catalog refused to change the description of main.sales.orders'
    );
    expect(notice).not.toHaveTextContent('english fallback');
  });

  it('translates the reason in the user language', async () => {
    await act(async () => {
      await i18n.changeLanguage('pt');
    });
    render(<DescriptionSyncNotice sync={sync} />);
    expect(screen.getByRole('status')).toHaveTextContent('Não sincronizado com o Unity Catalog.');
  });

  it('falls back to the English message for an unknown code', () => {
    const warning = { code: 'something_new', message: 'english fallback' };
    const text = descriptionSyncText(i18n.t, warning);
    expect(text).toBe('english fallback');
  });
});
