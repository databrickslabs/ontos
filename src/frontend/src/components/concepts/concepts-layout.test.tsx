import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import ConceptsLayout from './concepts-layout';

// Renders the Concepts shell at a given /concepts path. The nested route just
// echoes a marker so we can assert the outlet still renders (deep links work).
function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/concepts" element={<ConceptsLayout />}>
          <Route path="browser" element={<div>browser-view</div>} />
          <Route path="browser/:iri" element={<div>concept-detail-view</div>} />
          <Route path="search" element={<div>search-view</div>} />
          <Route path="graph" element={<div>graph-view</div>} />
          <Route path="hierarchy" element={<div>hierarchy-view</div>} />
          <Route path="collections" element={<div>collections-view</div>} />
          <Route path="generator" element={<div>generator-view</div>} />
          <Route path="import" element={<div>import-view</div>} />
          <Route path="mapping" element={<div>mapping-view</div>} />
        </Route>
      </Routes>
    </MemoryRouter>
  );
}

describe('ConceptsLayout — v2 3-section nav', () => {
  it('renders the three primary sections as tabs', () => {
    renderAt('/concepts/browser');
    const tabs = screen.getAllByRole('tab');
    const labels = tabs.map((t) => t.textContent);
    expect(labels).toEqual(expect.arrayContaining(['Define', 'Explore', 'Enrich']));
  });

  it('marks Explore active on the browser (default) route and shows view toggles', () => {
    renderAt('/concepts/browser');
    const exploreTab = screen.getByRole('tab', { name: 'Explore' });
    expect(exploreTab).toHaveAttribute('aria-selected', 'true');
    // Explore view toggles reuse the four existing views.
    expect(screen.getByRole('tab', { name: 'Concepts' })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: 'Search' })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: 'Hierarchy' })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: 'Graph' })).toBeInTheDocument();
  });

  it('marks Define active on Collections/Generator/Import routes', () => {
    for (const path of ['/concepts/collections', '/concepts/generator', '/concepts/import']) {
      const { unmount } = renderAt(path);
      expect(screen.getByRole('tab', { name: 'Define' })).toHaveAttribute('aria-selected', 'true');
      unmount();
    }
  });

  it('marks Enrich active on the Mapping route', () => {
    renderAt('/concepts/mapping');
    expect(screen.getByRole('tab', { name: 'Enrich' })).toHaveAttribute('aria-selected', 'true');
  });

  it('keeps the browser/:iri deep link working (outlet renders detail view)', () => {
    renderAt('/concepts/browser/some%3Airi');
    expect(screen.getByText('concept-detail-view')).toBeInTheDocument();
    // Deep link still resolves to the Explore section.
    expect(screen.getByRole('tab', { name: 'Explore' })).toHaveAttribute('aria-selected', 'true');
  });
});
