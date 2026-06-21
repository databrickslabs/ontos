import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { FeatureAccessLevel } from '@/types/settings';

// ---------------------------------------------------------------------------
// CUJ ONT-RBAC-007 — the "New Contract" / "Upload" create actions must be
// hidden for personas without contract-create (READ_WRITE) permission, e.g.
// Data Consumer. The backend already returns 403 on POST /api/data-contracts;
// this verifies the frontend no longer surfaces the control at all.
//
// We mock the heavy children (DataTable, dialogs, stores) and drive only the
// permission gate. `hasPermission` is swapped per-test via a mutable holder.
// ---------------------------------------------------------------------------

let mockHasPermission: (featureId: string, level: FeatureAccessLevel) => boolean = () => true;

vi.mock('@/stores/permissions-store', () => ({
  usePermissions: () => ({
    hasPermission: (featureId: string, level: FeatureAccessLevel) => mockHasPermission(featureId, level),
    isLoading: false,
  }),
}));

// `t` and `i18n` must be stable across renders. The DataContracts page lists
// `t` in an effect dependency array; a fresh `t` each render would loop the
// effect (and its fetch) forever in the test environment.
const { mockT, mockI18n } = vi.hoisted(() => ({
  mockT: (key: string, options?: any) =>
    options && typeof options === 'object' && 'defaultValue' in options
      ? (options.defaultValue as string)
      : key,
  mockI18n: { language: 'en', changeLanguage: () => undefined },
}));
vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: mockT, i18n: mockI18n }),
}));

vi.mock('@/hooks/use-toast', () => ({
  useToast: () => ({ toast: vi.fn() }),
}));

vi.mock('@/hooks/use-domains', () => ({
  useDomains: () => ({ getDomainName: () => undefined }),
}));

// `get` must keep a stable identity across renders — the real useApi memoizes
// it. A fresh fn each render would retrigger the certification-levels effect
// (dep: [get]) and spin an infinite refetch loop in the test environment.
const { mockStableGet } = vi.hoisted(() => ({
  mockStableGet: vi.fn(async () => ({ data: [] })),
}));
vi.mock('@/hooks/use-api', () => ({
  useApi: () => ({ get: mockStableGet }),
}));

// Breadcrumb setters are in the page's effect dep array — keep them stable so
// the effect does not re-run (and refetch) on every render.
const { mockBreadcrumbSetter } = vi.hoisted(() => ({
  mockBreadcrumbSetter: () => undefined,
}));
vi.mock('@/stores/breadcrumb-store', () => ({
  default: () => mockBreadcrumbSetter,
}));

vi.mock('@/stores/project-store', () => ({
  useProjectContext: () => ({ currentProject: null, hasProjectContext: false }),
}));

// Render only the toolbar actions so the gated create/upload controls are
// observable without pulling in the full table machinery.
vi.mock('@/components/ui/data-table', () => ({
  DataTable: ({ toolbarActions }: { toolbarActions?: React.ReactNode }) => (
    <div data-testid="data-table">{toolbarActions}</div>
  ),
}));

vi.mock('@/components/data-contracts/data-contract-basic-form-dialog', () => ({
  default: () => null,
}));

vi.mock('@/components/metadata/entity-info-dialog', () => ({
  default: () => null,
}));

// Radix tooltip primitives need a portal/provider context that jsdom does not
// fully support; render children inline so the upload control mounts plainly.
vi.mock('@/components/ui/tooltip', () => ({
  TooltipProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  Tooltip: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  TooltipTrigger: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  TooltipContent: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

beforeEach(() => {
  mockHasPermission = () => true;
  // setup.ts runs vi.clearAllMocks() between tests, which wipes the stable
  // get() implementation — restore it so it keeps returning a resolved promise.
  mockStableGet.mockImplementation(async () => ({ data: [] }));
  global.fetch = vi.fn(async () => ({
    ok: true,
    status: 200,
    json: async () => [],
    text: async () => '',
    headers: { get: () => null },
  })) as unknown as typeof fetch;
});

// Let any in-flight fetch/setState from the prior test settle before the next
// one mounts a fresh component, so loading state does not leak across tests.
afterEach(async () => {
  await new Promise((r) => setTimeout(r, 0));
});

import DataContracts from './data-contracts';

function renderView() {
  render(
    <MemoryRouter initialEntries={['/data-contracts']}>
      <DataContracts />
    </MemoryRouter>,
  );
}

describe('DataContracts create-action permission gating (ONT-RBAC-007)', () => {
  it('hides the New Contract action for personas without write permission (Data Consumer)', async () => {
    // Data Consumer: READ_ONLY only -> READ_WRITE check fails.
    mockHasPermission = (_featureId, level) => level === FeatureAccessLevel.READ_ONLY;

    renderView();

    // Wait for the list to finish loading (skeleton -> table) so we assert
    // against the real toolbar, not the loading placeholder.
    await waitFor(() => expect(screen.getByTestId('data-table')).toBeInTheDocument());
    expect(screen.queryByRole('button', { name: 'newContract' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'uploadFile' })).not.toBeInTheDocument();
  });

  it('shows the New Contract action for personas with write permission', async () => {
    mockHasPermission = (featureId, level) =>
      featureId === 'data-contracts' &&
      (level === FeatureAccessLevel.READ_ONLY || level === FeatureAccessLevel.READ_WRITE);

    renderView();

    // Create/upload controls appear once the list loads and the gate passes.
    await waitFor(() => expect(screen.getByTestId('data-table')).toBeInTheDocument());
    expect(screen.getByRole('button', { name: 'newContract' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'uploadFile' })).toBeInTheDocument();
  });
});
