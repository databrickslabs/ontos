import { describe, it, expect, vi, beforeEach, afterAll } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import i18n from '@/i18n/config';

const mockGet = vi.fn();
const mockPost = vi.fn();
vi.mock('@/hooks/use-api', () => ({
  useApi: () => ({ get: mockGet, post: mockPost, put: vi.fn(), delete: vi.fn() }),
}));

import ComplianceTemplatesSettings from './compliance-templates-settings';

const template = {
  id: 't-1',
  name: 'Table documentation',
  description: null,
  entity_type: 'asset',
  is_active: true,
  fields: [],
};

describe('ComplianceTemplatesSettings', () => {
  beforeEach(async () => {
    mockGet.mockReset();
    mockPost.mockReset();
    mockGet.mockResolvedValue({ data: [template], error: null });
    mockPost.mockResolvedValue({ data: {}, error: null });
    await i18n.changeLanguage('en');
  });

  afterAll(async () => {
    await i18n.changeLanguage('en');
  });

  it('renders the page, the table and the editor in the user language', async () => {
    await i18n.changeLanguage('de');
    render(<ComplianceTemplatesSettings />);

    expect(await screen.findByText('Compliance-Vorlagen')).toBeInTheDocument();
    expect(screen.getByRole('columnheader', { name: 'Entitätstyp' })).toBeInTheDocument();
    expect(screen.getByText('Aktiv')).toBeInTheDocument();
    expect(screen.getByText('Tabellen und Views')).toBeInTheDocument();
    expect(screen.getByTitle('Deaktivieren')).toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: /Vorlage hinzufügen/ }));
    expect(screen.getByText('Compliance-Vorlage hinzufügen')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: /Feld hinzufügen/ }));
    expect(screen.getByPlaceholderText('Feldbezeichnung')).toBeInTheDocument();
    expect(screen.getByRole('option', { name: 'Mehrfachauswahl' })).toBeInTheDocument();
    expect(screen.getByLabelText('Pflichtfeld')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Erstellen' })).toBeInTheDocument();

    // No English text left in the dialog.
    for (const english of ['Add Field', 'Field label', 'Multiple choice', 'Mandatory', 'Create']) {
      expect(screen.queryByText(english)).not.toBeInTheDocument();
    }
  });

  it('keeps accented letters when it derives the reference id from the label', async () => {
    render(<ComplianceTemplatesSettings />);
    await userEvent.click(await screen.findByRole('button', { name: /Add Template/ }));
    await userEvent.type(screen.getByLabelText('Name'), 'Documentação');
    await userEvent.click(screen.getByRole('button', { name: /Add Field/ }));
    await userEvent.type(screen.getByPlaceholderText('Field label'), 'Limitações conhecidas');
    await userEvent.click(screen.getByRole('button', { name: 'Create' }));

    await waitFor(() => expect(mockPost).toHaveBeenCalled());
    const [url, body] = mockPost.mock.calls[0];
    expect(url).toBe('/api/compliance-templates');
    expect(body.fields[0]).toMatchObject({
      key: 'limitacoes-conhecidas',
      reference_id: 'limitacoes-conhecidas',
      label: 'Limitações conhecidas',
    });
  });

  it('transliterates an explicit reference id too', async () => {
    render(<ComplianceTemplatesSettings />);
    await userEvent.click(await screen.findByRole('button', { name: /Add Template/ }));
    await userEvent.type(screen.getByLabelText('Name'), 'Docs');
    await userEvent.click(screen.getByRole('button', { name: /Add Field/ }));
    await userEvent.type(screen.getByPlaceholderText('Field label'), 'Owner');
    await userEvent.type(screen.getByPlaceholderText('Reference id (auto)'), 'Área Responsável');
    await userEvent.click(screen.getByRole('button', { name: 'Create' }));

    await waitFor(() => expect(mockPost).toHaveBeenCalled());
    expect(mockPost.mock.calls[0][1].fields[0].reference_id).toBe('area-responsavel');
  });
});
