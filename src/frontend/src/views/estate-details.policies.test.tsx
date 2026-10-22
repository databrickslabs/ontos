/**
 * The estate page lists export and import policies separately (#146), shows
 * the resource type in the user's language, and adds a new policy to the list
 * whose "Add Policy" button was used.
 */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';

import i18n from '@/i18n/config';
import type { Estate } from '@/types/estate';
import EstateDetailsView from './estate-details';

const estate: Estate = {
  id: 'e-1',
  name: 'EU Analytics',
  description: 'Analytics workspace',
  workspace_url: 'https://eu.cloud.databricks.com',
  cloud_type: 'azure',
  metastore_name: 'eu',
  connection_type: 'delta_share',
  export_policies: [
    {
      id: 'p-1', name: 'Active products', resource_type: 'data_product', is_enabled: true,
      rules: [{ filter_type: 'status', operator: 'equals', filter_value: 'active' }],
      created_at: '2026-10-19T00:00:00Z', updated_at: '2026-10-19T00:00:00Z',
    },
  ],
  import_policies: [
    {
      id: 'p-2', name: 'Shared terms', resource_type: 'business_term', is_enabled: true, rules: [],
      created_at: '2026-10-19T00:00:00Z', updated_at: '2026-10-19T00:00:00Z',
    },
  ],
  is_enabled: true,
  sync_schedule: '0 0 * * *',
  created_at: '2026-10-19T00:00:00Z',
  updated_at: '2026-10-19T00:00:00Z',
};

const api = vi.hoisted(() => ({
  get: vi.fn(),
  put: vi.fn(),
  toast: vi.fn(),
}));

vi.mock('@/hooks/use-api', () => ({ useApi: () => ({ get: api.get, put: api.put }) }));
vi.mock('@/hooks/use-toast', () => ({ useToast: () => ({ toast: api.toast }) }));
vi.mock('@/components/estates/add-sharing-policy-dialog', () => ({
  default: ({ onSaveSuccess }: { onSaveSuccess: (p: unknown) => void }) => (
    <button
      type="button"
      onClick={() => onSaveSuccess({
        name: 'New concepts', resource_type: 'concept', is_enabled: true, rules: [],
        created_at: '', updated_at: '',
      })}
    >
      save-policy
    </button>
  ),
}));

function ListPage() {
  const location = useLocation();
  return <p data-testid="estate-list">{location.search}</p>;
}

function renderPage() {
  api.get.mockResolvedValue({ data: estate });
  api.put.mockImplementation(async (_url: string, body: Estate) => ({ data: body }));
  return render(
    <MemoryRouter initialEntries={['/estates/e-1']}>
      <Routes>
        <Route path="/estates/:estateId" element={<EstateDetailsView />} />
        <Route path="/estate-manager" element={<ListPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

afterEach(async () => {
  vi.clearAllMocks();
  await i18n.changeLanguage('en');
});

describe('EstateDetailsView policies', () => {
  it('lists export and import policies in their own sections', async () => {
    renderPage();
    const exports = await screen.findByTestId('estate-export-policies');
    const imports = screen.getByTestId('estate-import-policies');

    expect(within(exports).getByText('Export Policies')).toBeTruthy();
    expect(within(exports).getByText('Active products')).toBeTruthy();
    expect(within(exports).getByText('Data Product')).toBeTruthy();
    expect(within(exports).queryByText('Shared terms')).toBeNull();

    expect(within(imports).getByText('Import Policies')).toBeTruthy();
    expect(within(imports).getByText('Shared terms')).toBeTruthy();
    expect(within(imports).getByText('Business Term')).toBeTruthy();
  });

  it('shows the sections and resource types in Portuguese', async () => {
    await i18n.changeLanguage('pt');
    renderPage();
    const imports = await screen.findByTestId('estate-import-policies');

    expect(within(imports).getByText('Políticas de Importação')).toBeTruthy();
    expect(within(imports).getByText('Termo de Negócio')).toBeTruthy();
  });

  it('adds a policy to the import list when added from the import section', async () => {
    renderPage();
    const imports = await screen.findByTestId('estate-import-policies');
    fireEvent.click(within(imports).getByRole('button', { name: /Add Policy/ }));
    fireEvent.click(await screen.findByText('save-policy'));

    await waitFor(() => expect(api.put).toHaveBeenCalled());
    const [url, body] = api.put.mock.calls[0];
    expect(url).toBe('/api/estates/e-1');
    expect(body.import_policies.map((p: { name: string }) => p.name)).toEqual(['Shared terms', 'New concepts']);
    expect(body.export_policies.map((p: { name: string }) => p.name)).toEqual(['Active products']);
  });
});

describe('EstateDetailsView rules and editing', () => {
  it('shows a rule as one translated sentence', async () => {
    await i18n.changeLanguage('pt');
    renderPage();
    const exports = await screen.findByTestId('estate-export-policies');

    expect(within(exports).getByRole('listitem')).toHaveTextContent(
      "Filtrar por status onde o valor é igual a 'active'",
    );
  });

  it('says each operator in its own sentence', async () => {
    const sentence = (operator: string) => i18n.t(`estates:details.policies.ruleText.${operator}`, {
      filterType: 'tag', value: 'pii',
    });
    expect(sentence('starts_with')).toBe("Filter by <b>tag</b> where the value starts with <b>'pii'</b>");
    await i18n.changeLanguage('de');
    expect(sentence('contains')).toBe("Nach <b>tag</b> filtern, wobei der Wert <b>'pii'</b> enthält");
  });

  it('opens the edit dialog of the estate on the estate list', async () => {
    renderPage();
    fireEvent.click(await screen.findByRole('button', { name: /Edit Estate/ }));

    expect(await screen.findByTestId('estate-list')).toHaveTextContent('?edit=e-1');
  });
});
