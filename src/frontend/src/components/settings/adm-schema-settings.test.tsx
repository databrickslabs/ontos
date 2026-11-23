/**
 * The shared ADM schema settings: conformance of the configured schema, the findings of a
 * non-conformant one, the refusal of a save (422) listing its findings, and read-only for non-admins.
 */
import { screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import i18n from '@/i18n/config';
import { renderWithProviders } from '@/test/utils';
import AdmSchemaSettings from './adm-schema-settings';

const mockGet = vi.fn();
const mockPut = vi.fn();
const mockToast = vi.fn();
let mockIsAdmin = true;

vi.mock('@/hooks/use-api', () => ({
  useApi: () => ({ get: mockGet, put: mockPut, post: vi.fn(), delete: vi.fn() }),
}));
vi.mock('@/hooks/use-toast', () => ({ useToast: () => ({ toast: mockToast }) }));
vi.mock('@/stores/permissions-store', () => ({
  usePermissions: () => ({ hasPermission: () => mockIsAdmin, isLoading: false }),
}));

const tr = (key: string, opts?: Record<string, unknown>) => i18n.t(`authority-resolution:${key}`, opts);

const conformant = {
  schema: 'demo.arf_adm',
  adm_version: 'ADM v0.4',
  conformance: { status: 'conformant', schema: 'demo.arf_adm', adm_version: 'ADM v0.4', findings: [], checked_tables: ['decisions'] },
};

const nonconformant = {
  schema: 'demo.arf_adm',
  adm_version: 'ADM v0.4',
  conformance: {
    status: 'nonconformant', schema: 'demo.arf_adm', adm_version: 'ADM v0.4', checked_tables: ['decisions'],
    findings: [{ code: 'missing_column', table: 'decisions', column: 'approved_at' }],
  },
};

describe('AdmSchemaSettings', () => {
  beforeEach(() => {
    mockIsAdmin = true;
    mockGet.mockImplementation(async (url: string) => {
      if (url === '/api/authority/adm-schema') return { data: conformant };
      return { data: 'CREATE TABLE IF NOT EXISTS demo.arf_adm.decisions ();' };
    });
    mockPut.mockResolvedValue({ data: conformant });
  });

  afterEach(async () => {
    vi.clearAllMocks();
    await i18n.changeLanguage('en');
  });

  it('shows the configured schema as conformant with its checked tables', async () => {
    renderWithProviders(<AdmSchemaSettings />);

    expect(await screen.findByText(tr('adm.settings.conformant', { version: 'ADM v0.4' }))).toBeInTheDocument();
    expect(screen.getByDisplayValue('demo.arf_adm')).toBeInTheDocument();
    expect(screen.getByText('decisions')).toBeInTheDocument();
  });

  it('lists the findings of a non-conformant schema with the table and column', async () => {
    mockGet.mockImplementation(async () => ({ data: nonconformant }));
    renderWithProviders(<AdmSchemaSettings />);

    expect(await screen.findByText(tr('adm.settings.nonconformant', { version: 'ADM v0.4' }))).toBeInTheDocument();
    expect(screen.getByText(tr('adm.findings.missing_column'))).toBeInTheDocument();
    expect(screen.getByText('decisions.approved_at')).toBeInTheDocument();
  });

  it('lists the findings of a refused save (422) and keeps the schema unsaved', async () => {
    mockPut.mockResolvedValue({
      data: {}, error: 'not conformant', errorCode: 'adm_nonconformant', status: 422,
      errorParams: { schema: 'team.bad', findings: [{ code: 'type_mismatch', table: 'decisions', column: 'value', expected: 'double', actual: 'string' }] },
    });
    renderWithProviders(<AdmSchemaSettings />);

    const input = await screen.findByDisplayValue('demo.arf_adm');
    fireEvent.change(input, { target: { value: 'team.bad' } });
    fireEvent.click(screen.getByRole('button', { name: i18n.t('common:actions.save') }));

    expect(await screen.findByText(tr('adm.errors.nonconformant'))).toBeInTheDocument();
    expect(screen.getByText('decisions.value')).toBeInTheDocument();
    expect(mockPut).toHaveBeenCalledWith('/api/authority/adm-schema', { adm_schema: 'team.bad' });
    expect(mockToast).toHaveBeenCalledWith(expect.objectContaining({ variant: 'destructive', description: tr('adm.errors.nonconformant') }));
  });

  it('shows the schema read-only for a non-admin, with no save action', async () => {
    mockIsAdmin = false;
    renderWithProviders(<AdmSchemaSettings />);

    const input = await screen.findByDisplayValue('demo.arf_adm');
    expect(input).toBeDisabled();
    expect(screen.queryByRole('button', { name: i18n.t('common:actions.save') })).toBeNull();
    expect(screen.getByText(tr('adm.settings.readOnly'))).toBeInTheDocument();
  });

  it('copies the DDL of the configured schema from the DDL endpoint', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true });
    renderWithProviders(<AdmSchemaSettings />);

    fireEvent.click(await screen.findByRole('button', { name: tr('adm.settings.copyDdl') }));

    await waitFor(() => expect(writeText).toHaveBeenCalledWith('CREATE TABLE IF NOT EXISTS demo.arf_adm.decisions ();'));
    expect(mockGet).toHaveBeenCalledWith('/api/authority/adm-schema/ddl?schema=demo.arf_adm');
  });
});
