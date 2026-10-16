import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { MemoryRouter, Routes, Route, useLocation } from 'react-router-dom';

// ---------------------------------------------------------------------------
// Define landing surface tests.
//
// Verifies the three creation-path cards render and route/open correctly, and
// that the in-progress list is fed by the ontology generator runs endpoint.
// The Import dialog is stubbed here (it has its own render path); we only
// assert it opens.
// ---------------------------------------------------------------------------

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, options?: any) => {
      if (typeof options === 'string') return options;
      if (options && typeof options === 'object' && 'defaultValue' in options) {
        return options.defaultValue as string;
      }
      return key;
    },
    i18n: { language: 'en', changeLanguage: vi.fn() },
  }),
}));

vi.mock('@/stores/breadcrumb-store', () => ({ default: () => () => undefined }));

let importDialogOpen = false;
let authorDialogOpen = false;
vi.mock('@/components/knowledge', () => ({
  ImportConceptsDialog: ({ open }: { open: boolean }) => {
    importDialogOpen = open;
    return open ? <div data-testid="import-dialog" /> : null;
  },
  // Author reuses the collection editor as the "New concept scheme" dialog.
  CollectionEditorDialog: ({ open }: { open: boolean }) => {
    authorDialogOpen = open;
    return open ? <div data-testid="author-dialog" /> : null;
  },
}));

let guidedDialogOpen = false;
vi.mock('@/components/concepts/guided-generate-dialog', () => ({
  GuidedGenerateDialog: ({ open }: { open: boolean }) => {
    guidedDialogOpen = open;
    return open ? <div data-testid="guided-dialog" /> : null;
  },
}));

vi.mock('@/components/concepts/mode-switch', () => ({
  ConceptModeSwitch: () => <div data-testid="mode-switch" />,
}));

vi.mock('@/hooks/use-toast', () => ({ useToast: () => ({ toast: vi.fn() }) }));

import DefineView from './define';

const RUNS = {
  runs: [
    {
      run_id: 'run-1',
      status: 'completed',
      progress_message: '156 draft terms from gold.*',
      created_at: '2026-07-10T12:00:00Z',
      step_count: 4,
    },
    {
      run_id: 'run-2',
      status: 'running',
      progress_message: 'Extracting classes…',
      created_at: '2026-07-12T12:00:00Z',
      step_count: 2,
    },
  ],
};

beforeEach(() => {
  importDialogOpen = false;
  authorDialogOpen = false;
  guidedDialogOpen = false;
  global.fetch = vi.fn(async (url: any) => {
    const u = String(url);
    if (u.includes('/api/ontology/runs')) {
      return { ok: true, status: 200, json: async () => RUNS } as any;
    }
    // collections
    return { ok: true, status: 200, json: async () => ({ collections: [] }) } as any;
  }) as unknown as typeof fetch;
});

function renderDefine() {
  let observed = { pathname: '' };
  function Probe() {
    const location = useLocation();
    observed = { pathname: location.pathname };
    return null;
  }
  render(
    <MemoryRouter initialEntries={['/concepts/define']}>
      <Routes>
        <Route path="/concepts/define" element={<><DefineView /><Probe /></>} />
        <Route path="/concepts/collections" element={<><div>collections-page</div><Probe /></>} />
        <Route path="/concepts/generator" element={<><div>generator-page</div><Probe /></>} />
      </Routes>
    </MemoryRouter>
  );
  return () => observed;
}

describe('DefineView', () => {
  it('renders the three creation-path cards', async () => {
    renderDefine();
    expect(screen.getByText('Author')).toBeInTheDocument();
    expect(screen.getByText('Generate')).toBeInTheDocument();
    expect(screen.getByText('Import')).toBeInTheDocument();
  });

  it('Author card opens the New concept scheme dialog in place', async () => {
    renderDefine();
    fireEvent.click(screen.getByText('New concept scheme'));
    await waitFor(() => expect(screen.getByTestId('author-dialog')).toBeInTheDocument());
    expect(authorDialogOpen).toBe(true);
  });

  it('Generate card opens the guided build dialog in place', async () => {
    renderDefine();
    fireEvent.click(screen.getByText('Start guided build'));
    await waitFor(() => expect(screen.getByTestId('guided-dialog')).toBeInTheDocument());
    expect(guidedDialogOpen).toBe(true);
  });

  it('Import card opens the import dialog', async () => {
    renderDefine();
    fireEvent.click(screen.getByText('Upload files'));
    await waitFor(() => expect(screen.getByTestId('import-dialog')).toBeInTheDocument());
    expect(importDialogOpen).toBe(true);
  });

  it('shows in-progress generator runs from the runs endpoint', async () => {
    renderDefine();
    await waitFor(() => {
      expect(screen.getByText('156 draft terms from gold.*')).toBeInTheDocument();
    });
    expect(screen.getByText('Extracting classes…')).toBeInTheDocument();
    // completed run surfaces the "Needs review" badge
    expect(screen.getByText('Needs review')).toBeInTheDocument();
  });
});
