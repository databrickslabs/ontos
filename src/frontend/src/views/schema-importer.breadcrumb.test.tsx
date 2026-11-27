import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, waitFor } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';

// ---------------------------------------------------------------------------
// Schema Importer breadcrumb trail.
//
// The same view is reachable from Assets (/schema-importer) and from the
// Concepts shell (/concepts/import). The trail must anchor to whichever shell
// opened it. The store is captured so we can assert the segments written.
// ---------------------------------------------------------------------------

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, fallback?: string) => (typeof fallback === 'string' ? fallback : key),
    i18n: { language: 'en', changeLanguage: vi.fn() },
  }),
}));

const setStaticSegments = vi.fn();
const setDynamicTitle = vi.fn();
vi.mock('@/stores/breadcrumb-store', () => ({
  default: (selector: (s: unknown) => unknown) =>
    selector({ setStaticSegments, setDynamicTitle }),
}));

vi.mock('@/stores/ui-customization-store', () => ({
  useUICustomizationStore: (selector: (s: unknown) => unknown) =>
    selector({ getAppName: () => 'Ontos' }),
}));

const stableApi = { get: vi.fn().mockResolvedValue({ data: [] }), post: vi.fn(), put: vi.fn(), delete: vi.fn() };
vi.mock('@/hooks/use-api', () => ({ useApi: () => stableApi }));
vi.mock('@/hooks/use-toast', () => ({ useToast: () => ({ toast: vi.fn() }) }));

vi.mock('@/components/schema-importer/schema-browser', () => ({ default: () => null }));
vi.mock('@/components/schema-importer/import-preview-dialog', () => ({ default: () => null }));

import SchemaImporterView from './schema-importer';

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/schema-importer" element={<SchemaImporterView />} />
        <Route path="/concepts/import" element={<SchemaImporterView />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe('SchemaImporterView breadcrumb trail', () => {
  beforeEach(() => {
    setStaticSegments.mockClear();
    setDynamicTitle.mockClear();
  });

  it('anchors to Assets when opened from /schema-importer', async () => {
    renderAt('/schema-importer');

    await waitFor(() =>
      expect(setStaticSegments).toHaveBeenLastCalledWith([{ label: 'assets:title', path: '/assets' }]),
    );
  });

  it('anchors to Concepts > Define when opened from /concepts/import', async () => {
    renderAt('/concepts/import');

    await waitFor(() =>
      expect(setStaticSegments).toHaveBeenLastCalledWith([
        { label: 'concepts:title', path: '/concepts/browser' },
        { label: 'concepts:sections.define', path: '/concepts/define' },
      ]),
    );
  });
});
