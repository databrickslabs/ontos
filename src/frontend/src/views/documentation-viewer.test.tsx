import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import DocumentationViewer from './documentation-viewer';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key, i18n: { language: 'en' } }),
}));

vi.mock('@/stores/breadcrumb-store', () => ({
  default: (selector: (state: unknown) => unknown) =>
    selector({ setStaticSegments: vi.fn(), setDynamicTitle: vi.fn() }),
}));

// Keep the real markdown pipeline out of it: one heading whose id is the anchor under test.
vi.mock('@/components/ui/markdown-viewer', () => ({
  default: () => <h2 id="tag functions">Tag functions</h2>,
}));

const scrollIntoView = vi.fn();

function renderAt(hash: string) {
  return render(
    <MemoryRouter initialEntries={[`/user-docs/guide${hash}`]}>
      <Routes>
        <Route path="/user-docs/:docName" element={<DocumentationViewer />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe('DocumentationViewer hash navigation', () => {
  beforeEach(() => {
    scrollIntoView.mockReset();
    Element.prototype.scrollIntoView = scrollIntoView;
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string) => ({
        ok: true,
        json: async () =>
          url === '/api/user-docs' ? {} : { title: 'Guide', content: '## Tag functions' },
      })),
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('scrolls to the section named by a valid (percent-encoded) hash', async () => {
    renderAt('#tag%20functions');
    await screen.findByRole('heading', { name: 'Tag functions' });
    await waitFor(() => expect(scrollIntoView).toHaveBeenCalledTimes(1));
  });

  it('still renders the doc and does not throw for a malformed hash', async () => {
    renderAt('#%E0%A4%A');
    expect(await screen.findByRole('heading', { name: 'Tag functions' })).toBeTruthy();
    expect(scrollIntoView).not.toHaveBeenCalled();
  });
});
