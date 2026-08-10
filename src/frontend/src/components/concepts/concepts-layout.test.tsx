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

  it('marks Explore active on the browser (default) route with no legacy sub-nav', () => {
    renderAt('/concepts/browser');
    const exploreTab = screen.getByRole('tab', { name: 'Explore' });
    expect(exploreTab).toHaveAttribute('aria-selected', 'true');
    // v2: Explore is one unified browse surface. List/Tree/Graph live as an
    // in-page view switch inside the view (not the layout), and the old
    // per-view sub-nav tabs (Concepts/Search/Hierarchy) are gone.
    expect(screen.queryByRole('tab', { name: 'Concepts' })).not.toBeInTheDocument();
    expect(screen.queryByRole('tab', { name: 'Search' })).not.toBeInTheDocument();
    expect(screen.queryByRole('tab', { name: 'Hierarchy' })).not.toBeInTheDocument();
    // Only the three primary section tabs remain.
    expect(screen.getAllByRole('tab')).toHaveLength(3);
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
