import { afterEach, describe, expect, it } from 'vitest';

import i18n from '@/i18n/config';
import { notificationDescription, notificationTitle } from './notification-text';

afterEach(async () => {
  await i18n.changeLanguage('en');
});

// The shape the backend stores (notification_i18n_data) for the lifecycle notices.
const notice = (key: string, title: string) => ({
  title,
  description: 'English fallback',
  message: undefined,
  data: {
    i18n: {
      title: `notifications:lifecycle.${key}.title`,
      description: `notifications:lifecycle.${key}.description`,
      params: { productName: 'Vendas' },
    },
  },
}) as any;

describe('lifecycle notifications', () => {
  it('renders a deprecation notice in Portuguese', async () => {
    await i18n.changeLanguage('pt');
    const n = notice('deprecation', "Product 'Vendas' has been deprecated");
    expect(notificationTitle(n, i18n.t)).toBe('Produto obsoleto');
    expect(notificationDescription(n, i18n.t)).toContain("'Vendas' foi marcado como obsoleto");
  });

  it('renders a deletion notice in Portuguese', async () => {
    await i18n.changeLanguage('pt');
    const n = notice('deletion', "Product 'Vendas' has been deleted");
    expect(notificationTitle(n, i18n.t)).toBe('Produto excluído');
    expect(notificationDescription(n, i18n.t)).toBe("O produto de dados 'Vendas' foi excluído.");
  });

  it('renders a retirement notice in English', () => {
    const n = notice('retirement', 'x');
    expect(notificationTitle(n, i18n.t)).toBe('Product retired');
    expect(notificationDescription(n, i18n.t)).toContain("'Vendas' has been retired");
  });

  it('renders an activation and a certification notice in Portuguese', async () => {
    await i18n.changeLanguage('pt');
    expect(notificationTitle(notice('activation', 'x'), i18n.t)).toBe('Produto ativado');
    expect(notificationDescription(notice('certification', 'x'), i18n.t))
      .toContain("'Vendas' obteve o status certificado");
  });
});
