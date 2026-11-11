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

  it('renders an activation notice in Portuguese', async () => {
    await i18n.changeLanguage('pt');
    expect(notificationTitle(notice('activation', 'x'), i18n.t)).toBe('Produto ativado');
    expect(notificationDescription(notice('activation', 'x'), i18n.t))
      .toContain("'Vendas' foi ativado");
  });
});

// The owner notice of the "Owner Deprecation Notice" default workflow
// (lifecycle_notice in the backend): one line per fact, each with its key.
const ownerNotice = {
  title: 'Deprecation Notice',
  description: "data_product 'Orders' has been deprecated.\nReason: Superseded",
  data: {
    i18n: {
      title: 'notifications:workflowDefaults.templates.entity_deprecated.title',
      descriptionLines: [
        {
          key: 'notifications:workflowDefaults.templates.entity_deprecated.message',
          text: "data_product 'Orders' has been deprecated.",
          params: { entity_type: 'data_product', entity_name: 'Orders' },
        },
        {
          key: 'notifications:lifecycle.ownerNotice.reason',
          text: 'Reason: Superseded',
          params: { reason: 'Superseded' },
        },
        {
          key: 'notifications:lifecycle.ownerNotice.sunsetDate',
          text: 'Sunset date: 2026-12-31',
          params: { sunsetDate: '2026-12-31' },
        },
        {
          key: 'notifications:lifecycle.ownerNotice.replacement',
          text: 'Replacement: Orders v2',
          params: { replacementName: 'Orders v2', replacementId: 'p-2' },
        },
      ],
    },
  },
} as any;

describe('owner lifecycle notice', () => {
  it('renders one line per fact, with the entity type label', () => {
    expect(notificationTitle(ownerNotice, i18n.t)).toBe('Deprecation Notice');
    expect(notificationDescription(ownerNotice, i18n.t)).toBe(
      "Data Product 'Orders' has been deprecated.\nReason: Superseded\n"
      + 'Sunset date: 2026-12-31\nReplacement: Orders v2',
    );
  });

  it('renders in Portuguese', async () => {
    await i18n.changeLanguage('pt');
    expect(notificationTitle(ownerNotice, i18n.t)).toBe('Aviso de obsolescência');
    expect(notificationDescription(ownerNotice, i18n.t)).toBe(
      "Produto de dados 'Orders' foi marcado como obsoleto.\nMotivo: Superseded\n"
      + 'Data de desativação: 2026-12-31\nSubstituto: Orders v2',
    );
  });
});

describe('owner lifecycle notice with versions', () => {
  // A new version keeps the name, so the lines name the versions
  const versioned = {
    title: 'Deprecation Notice',
    description: 'English fallback',
    data: {
      i18n: {
        title: 'notifications:workflowDefaults.templates.entity_deprecated.title',
        descriptionLines: [
          {
            key: 'notifications:lifecycle.ownerNotice.deprecatedVersion',
            text: "data_product 'Orders' (version 1.0.0) has been deprecated.",
            params: { entity_type: 'data_product', entity_name: 'Orders', version: '1.0.0' },
          },
          {
            key: 'notifications:lifecycle.ownerNotice.replacementVersion',
            text: 'Replacement: Orders (version 2.0.0)',
            params: {
              replacementName: 'Orders', replacementVersion: '2.0.0', replacementId: 'p-2',
            },
          },
        ],
      },
    },
  } as any;

  it('renders the versions in English and Portuguese', async () => {
    expect(notificationDescription(versioned, i18n.t)).toBe(
      "Data Product 'Orders' (version 1.0.0) has been deprecated.\n"
      + 'Replacement: Orders (version 2.0.0)',
    );
    await i18n.changeLanguage('pt');
    expect(notificationDescription(versioned, i18n.t)).toBe(
      "Produto de dados 'Orders' (versão 1.0.0) foi marcado como obsoleto.\n"
      + 'Substituto: Orders (versão 2.0.0)',
    );
  });
});
