import { describe, it, expect, vi, beforeEach, afterAll } from 'vitest';
import { render, screen } from '@testing-library/react';
import i18n from '@/i18n/config';

const mockGet = vi.fn();
vi.mock('@/hooks/use-api', () => ({
  useApi: () => ({ get: mockGet, post: vi.fn(), put: vi.fn(), delete: vi.fn() }),
}));

import ComplianceModal from './compliance-modal';

const field = (overrides: Record<string, unknown>) => ({
  id: 'f-1',
  template_id: 't-1',
  group_title: '',
  group_order: 0,
  key: 'k',
  label: 'Label',
  reference_id: 'k',
  value_type: 'string',
  possible_values: null,
  default_value: null,
  hint_text: null,
  is_mandatory: false,
  field_order: 0,
  ...overrides,
});

const entity = {
  template: {
    id: 't-1', name: 'Doku', description: null, entity_type: 'asset',
    is_active: true, fields: [],
  },
  fields: [
    field({ id: 'f-1', label: 'Freigegeben', value_type: 'boolean' }),
    field({ id: 'f-2', label: 'Spanne', value_type: 'range', field_order: 1 }),
    field({ id: 'f-3', label: 'Kanäle', value_type: 'multi_enum', field_order: 2 }),
  ],
  values: [],
};

describe('ComplianceModal', () => {
  beforeEach(async () => {
    mockGet.mockReset();
    await i18n.changeLanguage('de');
  });

  afterAll(async () => {
    await i18n.changeLanguage('en');
  });

  it('renders its texts in the user language', async () => {
    mockGet.mockResolvedValue({ data: entity, error: null });
    render(
      <ComplianceModal open onOpenChange={vi.fn()} entityType="asset" entityId="a-1" canWrite />,
    );

    expect(await screen.findByText('Freigegeben')).toBeInTheDocument();
    expect(
      screen.getByText('Vervollständigen Sie die Compliance-Informationen für dieses Element.'),
    ).toBeInTheDocument();
    expect(screen.getByText('Nein')).toBeInTheDocument();
    expect(screen.getByPlaceholderText('Von')).toBeInTheDocument();
    expect(screen.getByLabelText('Spanne bis')).toBeInTheDocument();
    expect(screen.getByText('Keine Optionen definiert.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Abbrechen' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Speichern' })).toBeInTheDocument();
  });

  it('renders the read-only and empty states in the user language', async () => {
    mockGet.mockResolvedValue({ data: { template: null, fields: [], values: [] }, error: null });
    render(
      <ComplianceModal
        open onOpenChange={vi.fn()} entityType="asset" entityId="a-1" canWrite={false}
      />,
    );

    expect(
      await screen.findByText('Keine aktive Compliance-Vorlage für dieses Element.'),
    ).toBeInTheDocument();
    expect(
      screen.getByText('Compliance-Informationen für dieses Element (schreibgeschützt).'),
    ).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Schließen' })).toBeInTheDocument();
  });
});
