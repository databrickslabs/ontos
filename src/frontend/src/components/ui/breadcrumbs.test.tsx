import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { BrowserRouter } from 'react-router-dom';
import { Breadcrumbs } from './breadcrumbs';
import useBreadcrumbStore from '@/stores/breadcrumb-store';
import type { BreadcrumbSegment as _BreadcrumbSegment } from '@/stores/breadcrumb-store';
import { act } from '@testing-library/react';

// Wrapper component to provide Router context
const RouterWrapper = ({ children }: { children: React.ReactNode }) => (
  <BrowserRouter>{children}</BrowserRouter>
);

describe('Breadcrumbs Component', () => {
  beforeEach(() => {
    // Reset breadcrumb store before each test
    act(() => {
      useBreadcrumbStore.setState({
        staticSegments: [],
        dynamicTitle: null,
      });
    });
  });

  afterEach(() => {
    // Clean up
    act(() => {
      useBreadcrumbStore.setState({
        staticSegments: [],
        dynamicTitle: null,
      });
    });
  });

  describe('Home Icon', () => {
    it('renders home icon link', () => {
      render(
        <RouterWrapper>
          <Breadcrumbs />
        </RouterWrapper>
      );

      const homeLink = screen.getByRole('link');
      expect(homeLink).toBeInTheDocument();
      expect(homeLink).toHaveAttribute('href', '/');
    });

    it('home icon is always visible', () => {
      render(
        <RouterWrapper>
          <Breadcrumbs />
        </RouterWrapper>
      );

      const nav = screen.getByRole('navigation');
      expect(nav).toBeInTheDocument();
      expect(screen.getByRole('link')).toBeInTheDocument();
    });
  });

  describe('Static Segments', () => {
    it('renders single static segment without path', () => {
      act(() => {
        useBreadcrumbStore.getState().setStaticSegments([
          { label: 'Data Products' },
        ]);
      });

      render(
        <RouterWrapper>
          <Breadcrumbs />
        </RouterWrapper>
      );

      expect(screen.getByText('Data Products')).toBeInTheDocument();
      // Should be span, not link since no path
      const segment = screen.getByText('Data Products');
      expect(segment.tagName).toBe('SPAN');
    });

    it('renders single static segment with path as link', () => {
      act(() => {
        useBreadcrumbStore.getState().setStaticSegments([
          { label: 'Data Products', path: '/data-products' },
        ]);
      });

      render(
        <RouterWrapper>
          <Breadcrumbs />
        </RouterWrapper>
      );

      const link = screen.getByText('Data Products');
      expect(link).toBeInTheDocument();
      expect(link.closest('a')).toHaveAttribute('href', '/data-products');
    });

    it('renders multiple static segments', () => {
      act(() => {
        useBreadcrumbStore.getState().setStaticSegments([
          { label: 'Data Products', path: '/data-products' },
          { label: 'Details', path: '/data-products/123' },
          { label: 'Edit' },
        ]);
      });

      render(
        <RouterWrapper>
          <Breadcrumbs />
        </RouterWrapper>
      );

      expect(screen.getByText('Data Products')).toBeInTheDocument();
      expect(screen.getByText('Details')).toBeInTheDocument();
      expect(screen.getByText('Edit')).toBeInTheDocument();
    });

    it('renders chevron separators between segments', () => {
      act(() => {
        useBreadcrumbStore.getState().setStaticSegments([
          { label: 'Data Products', path: '/data-products' },
          { label: 'Details' },
        ]);
      });

      const { container } = render(
        <RouterWrapper>
          <Breadcrumbs />
        </RouterWrapper>
      );

      // Should have chevron icons between segments
      const chevrons = container.querySelectorAll('svg');
      // Expect at least 3: home icon + 2 chevrons (home->first, first->second)
      expect(chevrons.length).toBeGreaterThanOrEqual(3);
    });

    it('applies correct styles to segments with paths', () => {
      act(() => {
        useBreadcrumbStore.getState().setStaticSegments([
          { label: 'Clickable', path: '/clickable' },
        ]);
      });

      render(
        <RouterWrapper>
          <Breadcrumbs />
        </RouterWrapper>
      );

      const link = screen.getByText('Clickable').closest('a');
      expect(link).toBeInTheDocument();
    });

    it('applies correct styles to segments without paths', () => {
      act(() => {
        useBreadcrumbStore.getState().setStaticSegments([
          { label: 'Current Page' },
        ]);
      });

      render(
        <RouterWrapper>
          <Breadcrumbs />
        </RouterWrapper>
      );

      const span = screen.getByText('Current Page');
      expect(span.tagName).toBe('SPAN');
    });

    it('handles empty static segments', () => {
      act(() => {
        useBreadcrumbStore.getState().setStaticSegments([]);
      });

      render(
        <RouterWrapper>
          <Breadcrumbs />
        </RouterWrapper>
      );

      // Should only show home icon
      const links = screen.getAllByRole('link');
      expect(links).toHaveLength(1); // Only home link
    });
  });

  describe('Dynamic Title', () => {
    it('renders dynamic title when static segments exist', () => {
      act(() => {
        useBreadcrumbStore.getState().setStaticSegments([
          { label: 'Data Products', path: '/data-products' },
        ]);
        useBreadcrumbStore.getState().setDynamicTitle('Product Name');
      });

      render(
        <RouterWrapper>
          <Breadcrumbs />
        </RouterWrapper>
      );

      expect(screen.getByText('Product Name')).toBeInTheDocument();
    });

    it('renders dynamic title when no static segments', () => {
      act(() => {
        useBreadcrumbStore.getState().setStaticSegments([]);
        useBreadcrumbStore.getState().setDynamicTitle('Standalone Title');
      });

      render(
        <RouterWrapper>
          <Breadcrumbs />
        </RouterWrapper>
      );

      expect(screen.getByText('Standalone Title')).toBeInTheDocument();
    });

    it('does not render dynamic title when null', () => {
      act(() => {
        useBreadcrumbStore.getState().setStaticSegments([
          { label: 'Data Products', path: '/data-products' },
        ]);
        useBreadcrumbStore.getState().setDynamicTitle(null);
      });

      render(
        <RouterWrapper>
          <Breadcrumbs />
        </RouterWrapper>
      );

      expect(screen.queryByText('Product Name')).not.toBeInTheDocument();
    });

    it('dynamic title is rendered as span (not link)', () => {
      act(() => {
        useBreadcrumbStore.getState().setDynamicTitle('Dynamic Title');
      });

      render(
        <RouterWrapper>
          <Breadcrumbs />
        </RouterWrapper>
      );

      const title = screen.getByText('Dynamic Title');
      expect(title.tagName).toBe('SPAN');
    });

    it('renders chevron before dynamic title', () => {
      act(() => {
        useBreadcrumbStore.getState().setStaticSegments([
          { label: 'Data Products', path: '/data-products' },
        ]);
        useBreadcrumbStore.getState().setDynamicTitle('Product Name');
      });

      const { container } = render(
        <RouterWrapper>
          <Breadcrumbs />
        </RouterWrapper>
      );

      // Should have chevrons: home->first, first->dynamic
      const chevrons = container.querySelectorAll('svg');
      expect(chevrons.length).toBeGreaterThanOrEqual(2);
    });
  });

  describe('Combined Scenarios', () => {
    it('renders home + static segments + dynamic title', () => {
      act(() => {
        useBreadcrumbStore.getState().setStaticSegments([
          { label: 'Data Products', path: '/data-products' },
          { label: 'Details', path: '/data-products/123' },
        ]);
        useBreadcrumbStore.getState().setDynamicTitle('Product ABC');
      });

      render(
        <RouterWrapper>
          <Breadcrumbs />
        </RouterWrapper>
      );

      // Home link
      expect(screen.getAllByRole('link')).toHaveLength(3); // Home + 2 static segments with paths

      // Static segments
      expect(screen.getByText('Data Products')).toBeInTheDocument();
      expect(screen.getByText('Details')).toBeInTheDocument();

      // Dynamic title
      expect(screen.getByText('Product ABC')).toBeInTheDocument();
    });

    it('renders home + only dynamic title (no static segments)', () => {
      act(() => {
        useBreadcrumbStore.getState().setDynamicTitle('Just Title');
      });

      render(
        <RouterWrapper>
          <Breadcrumbs />
        </RouterWrapper>
      );

      // Home link
      expect(screen.getAllByRole('link')).toHaveLength(1);

      // Dynamic title
      expect(screen.getByText('Just Title')).toBeInTheDocument();
    });

    it('handles deep breadcrumb trail', () => {
      act(() => {
        useBreadcrumbStore.getState().setStaticSegments([
          { label: 'Level 1', path: '/level1' },
          { label: 'Level 2', path: '/level1/level2' },
          { label: 'Level 3', path: '/level1/level2/level3' },
          { label: 'Level 4', path: '/level1/level2/level3/level4' },
        ]);
        useBreadcrumbStore.getState().setDynamicTitle('Level 5');
      });

      render(
        <RouterWrapper>
          <Breadcrumbs />
        </RouterWrapper>
      );

      expect(screen.getByText('Level 1')).toBeInTheDocument();
      expect(screen.getByText('Level 2')).toBeInTheDocument();
      expect(screen.getByText('Level 3')).toBeInTheDocument();
      expect(screen.getByText('Level 4')).toBeInTheDocument();
      expect(screen.getByText('Level 5')).toBeInTheDocument();
    });
  });

  describe('Edge Cases', () => {
    it('handles segments with special characters', () => {
      act(() => {
        useBreadcrumbStore.getState().setStaticSegments([
          { label: 'R&D Department', path: '/rnd' },
          { label: 'Project #42' },
        ]);
      });

      render(
        <RouterWrapper>
          <Breadcrumbs />
        </RouterWrapper>
      );

      expect(screen.getByText('R&D Department')).toBeInTheDocument();
      expect(screen.getByText('Project #42')).toBeInTheDocument();
    });

    it('handles segments with long names', () => {
      const longLabel = 'A'.repeat(100);
      act(() => {
        useBreadcrumbStore.getState().setStaticSegments([
          { label: longLabel },
        ]);
      });

      render(
        <RouterWrapper>
          <Breadcrumbs />
        </RouterWrapper>
      );

      expect(screen.getByText(longLabel)).toBeInTheDocument();
    });

    it('handles empty string labels', () => {
      act(() => {
        useBreadcrumbStore.getState().setStaticSegments([
          { label: '', path: '/empty' },
        ]);
      });

      const { container } = render(
        <RouterWrapper>
          <Breadcrumbs />
        </RouterWrapper>
      );

      // Should still render, just with empty content
      expect(container.querySelector('nav')).toBeInTheDocument();
    });

    it('handles segments with query parameters in paths', () => {
      act(() => {
        useBreadcrumbStore.getState().setStaticSegments([
          { label: 'Search', path: '/search?q=test' },
          { label: 'Results', path: '/search?q=test&page=2' },
        ]);
      });

      render(
        <RouterWrapper>
          <Breadcrumbs />
        </RouterWrapper>
      );

      const searchLink = screen.getByText('Search').closest('a');
      expect(searchLink).toHaveAttribute('href', '/search?q=test');
    });

    it('handles segments with hash fragments', () => {
      act(() => {
        useBreadcrumbStore.getState().setStaticSegments([
          { label: 'Page', path: '/page#section' },
        ]);
      });

      render(
        <RouterWrapper>
          <Breadcrumbs />
        </RouterWrapper>
      );

      const link = screen.getByText('Page').closest('a');
      expect(link).toHaveAttribute('href', '/page#section');
    });
  });

  describe('Accessibility', () => {
    it('has proper aria-label', () => {
      render(
        <RouterWrapper>
          <Breadcrumbs />
        </RouterWrapper>
      );

      const nav = screen.getByRole('navigation');
      expect(nav).toHaveAttribute('aria-label', 'breadcrumb');
    });

    it('uses semantic HTML (nav and ol)', () => {
      render(
        <RouterWrapper>
          <Breadcrumbs />
        </RouterWrapper>
      );

      const nav = screen.getByRole('navigation');
      expect(nav).toBeInTheDocument();

      const list = nav.querySelector('ol');
      expect(list).toBeInTheDocument();
    });

    it('uses list items for breadcrumb segments', () => {
      act(() => {
        useBreadcrumbStore.getState().setStaticSegments([
          { label: 'Level 1', path: '/level1' },
          { label: 'Level 2' },
        ]);
      });

      const { container } = render(
        <RouterWrapper>
          <Breadcrumbs />
        </RouterWrapper>
      );

      const listItems = container.querySelectorAll('li');
      expect(listItems.length).toBeGreaterThan(0);
    });
  });

  describe('Custom Props', () => {
    it('accepts and applies custom className', () => {
      const { container } = render(
        <RouterWrapper>
          <Breadcrumbs className="custom-breadcrumbs" />
        </RouterWrapper>
      );

      // className is applied to the outer div wrapper, not the nav element
      const wrapper = container.querySelector('.custom-breadcrumbs');
      expect(wrapper).toBeInTheDocument();
    });

    it('merges custom className with default classes', () => {
      const { container } = render(
        <RouterWrapper>
          <Breadcrumbs className="my-custom-class" />
        </RouterWrapper>
      );

      // className is applied to the outer div wrapper, not the nav element
      const wrapper = container.querySelector('.my-custom-class');
      expect(wrapper).toBeInTheDocument();
      // Should still have some default classes
      expect(wrapper?.className).toContain('flex');
    });

    it('accepts custom HTML attributes', () => {
      render(
        <RouterWrapper>
          <Breadcrumbs data-testid="custom-breadcrumb" />
        </RouterWrapper>
      );

      const nav = screen.getByTestId('custom-breadcrumb');
      expect(nav).toBeInTheDocument();
    });
  });

  describe('Store Integration', () => {
    it('updates when static segments change', () => {
      act(() => {
        useBreadcrumbStore.getState().setStaticSegments([
          { label: 'Initial' },
        ]);
      });

      const { rerender } = render(
        <RouterWrapper>
          <Breadcrumbs />
        </RouterWrapper>
      );

      expect(screen.getByText('Initial')).toBeInTheDocument();

      act(() => {
        useBreadcrumbStore.getState().setStaticSegments([
          { label: 'Updated' },
        ]);
      });

      rerender(
        <RouterWrapper>
          <Breadcrumbs />
        </RouterWrapper>
      );

      expect(screen.queryByText('Initial')).not.toBeInTheDocument();
      expect(screen.getByText('Updated')).toBeInTheDocument();
    });

    it('updates when dynamic title changes', () => {
      act(() => {
        useBreadcrumbStore.getState().setDynamicTitle('Original Title');
      });

      const { rerender } = render(
        <RouterWrapper>
          <Breadcrumbs />
        </RouterWrapper>
      );

      expect(screen.getByText('Original Title')).toBeInTheDocument();

      act(() => {
        useBreadcrumbStore.getState().setDynamicTitle('New Title');
      });

      rerender(
        <RouterWrapper>
          <Breadcrumbs />
        </RouterWrapper>
      );

      expect(screen.queryByText('Original Title')).not.toBeInTheDocument();
      expect(screen.getByText('New Title')).toBeInTheDocument();
    });

    it('updates when dynamic title is cleared', () => {
      act(() => {
        useBreadcrumbStore.getState().setDynamicTitle('Has Title');
      });

      const { rerender } = render(
        <RouterWrapper>
          <Breadcrumbs />
        </RouterWrapper>
      );

      expect(screen.getByText('Has Title')).toBeInTheDocument();

      act(() => {
        useBreadcrumbStore.getState().setDynamicTitle(null);
      });

      rerender(
        <RouterWrapper>
          <Breadcrumbs />
        </RouterWrapper>
      );

      expect(screen.queryByText('Has Title')).not.toBeInTheDocument();
    });
  });
});
