import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import type { ColumnDef } from '@tanstack/react-table';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, defaultValue?: string) => defaultValue || key,
    i18n: { language: 'en', changeLanguage: vi.fn() },
  }),
}));

// Swap Radix Select (page-size picker) for a native <select>: driving Radix's
// pointer/portal machinery through jsdom hung the CI runner.
vi.mock('@/components/ui/select', async () => {
  const React = await import('react');
  const SelectTrigger = () => null;
  const SelectValue = () => null;
  const SelectContent = ({ children }: { children?: React.ReactNode }) => <>{children}</>;
  const SelectItem = ({ value, children }: { value: string; children?: React.ReactNode }) => (
    <option value={value}>{children}</option>
  );
  const Select = ({
    value,
    onValueChange,
    children,
  }: {
    value?: string;
    onValueChange?: (v: string) => void;
    children?: React.ReactNode;
  }) => {
    const options: React.ReactNode[] = [];
    React.Children.forEach(children, (child) => {
      if (!React.isValidElement(child)) return;
      if ((child as React.ReactElement).type !== SelectTrigger) options.push(child);
    });
    return (
      <select aria-label="page size" value={value} onChange={(e) => onValueChange?.(e.target.value)}>
        {options}
      </select>
    );
  };
  return { Select, SelectTrigger, SelectValue, SelectContent, SelectItem };
});

import { DataTable } from './data-table';

interface Item {
  id: string;
  name: string;
  size: number;
}

const items: Item[] = Array.from({ length: 25 }, (_, i) => ({
  id: `i${i}`,
  name: `Item ${String(i).padStart(2, '0')}`,
  size: (i * 7) % 25,
}));

const columns: ColumnDef<Item>[] = [
  {
    accessorKey: 'name',
    header: ({ column }) => (
      <button onClick={() => column.toggleSorting(column.getIsSorted() === 'asc')}>Name</button>
    ),
  },
  {
    accessorKey: 'size',
    header: ({ column }) => (
      <button onClick={() => column.toggleSorting(column.getIsSorted() === 'asc')}>Size</button>
    ),
  },
];

const names = (container: HTMLElement) =>
  Array.from(container.querySelectorAll('tbody tr')).map(
    (tr) => tr.querySelectorAll('td')[1]?.textContent,
  );

beforeEach(() => localStorage.clear());

describe('DataTable', () => {
  describe('defaults (no new props)', () => {
    it('sorts by the name column, persists sorting via storageKey, and renders no footer', () => {
      const { container } = render(
        <DataTable columns={columns} data={items} storageKey="dt-test-sort" />,
      );
      expect(names(container)[0]).toBe('Item 00');
      expect(container.querySelectorAll('tbody tr')).toHaveLength(10);
      expect(container.querySelector('tfoot')).toBeNull();
      fireEvent.click(screen.getByRole('button', { name: 'Name' }));
      expect(names(container)[0]).toBe('Item 24');
      expect(JSON.parse(localStorage.getItem('dt-test-sort') ?? '[]')).toEqual([
        { id: 'name', desc: true },
      ]);
    });

    it('keeps page size internal', () => {
      const { container } = render(<DataTable columns={columns} data={items} />);
      fireEvent.change(screen.getByLabelText('page size'), { target: { value: '20' } });
      expect(container.querySelectorAll('tbody tr')).toHaveLength(20);
    });
  });

  describe('controlled sorting', () => {
    it('renders the given sorting and reports changes without touching storageKey', () => {
      const onSortingChange = vi.fn();
      const { container, rerender } = render(
        <DataTable
          columns={columns}
          data={items}
          storageKey="dt-test-controlled"
          sorting={[{ id: 'size', desc: true }]}
          onSortingChange={onSortingChange}
        />,
      );
      // size 24 is the largest
      expect(container.querySelectorAll('tbody tr')[0].querySelectorAll('td')[2].textContent).toBe('24');
      fireEvent.click(screen.getByRole('button', { name: 'Name' }));
      expect(onSortingChange).toHaveBeenCalledWith([{ id: 'name', desc: false }]);
      // Still controlled: order only changes when the parent passes new state.
      expect(container.querySelectorAll('tbody tr')[0].querySelectorAll('td')[2].textContent).toBe('24');
      expect(localStorage.getItem('dt-test-controlled')).toBeNull();

      rerender(
        <DataTable
          columns={columns}
          data={items}
          storageKey="dt-test-controlled"
          sorting={[{ id: 'name', desc: false }]}
          onSortingChange={onSortingChange}
        />,
      );
      expect(names(container)[0]).toBe('Item 00');
      expect(localStorage.getItem('dt-test-controlled')).toBeNull();
    });

    it('ignores a stored storageKey sort when sorting is controlled', () => {
      localStorage.setItem('dt-test-ignored', JSON.stringify([{ id: 'name', desc: true }]));
      const { container } = render(
        <DataTable
          columns={columns}
          data={items}
          storageKey="dt-test-ignored"
          sorting={[{ id: 'name', desc: false }]}
        />,
      );
      expect(names(container)[0]).toBe('Item 00');
    });
  });

  describe('controlled page size', () => {
    it('uses the given page size and reports changes', () => {
      const onPageSizeChange = vi.fn();
      const { container, rerender } = render(
        <DataTable columns={columns} data={items} pageSize={20} onPageSizeChange={onPageSizeChange} />,
      );
      expect(container.querySelectorAll('tbody tr')).toHaveLength(20);
      expect(screen.getByLabelText('page size')).toHaveValue('20');

      fireEvent.change(screen.getByLabelText('page size'), { target: { value: '10' } });
      expect(onPageSizeChange).toHaveBeenCalledWith(10);
      // Controlled: unchanged until the parent passes the new size.
      expect(container.querySelectorAll('tbody tr')).toHaveLength(20);

      rerender(
        <DataTable columns={columns} data={items} pageSize={10} onPageSizeChange={onPageSizeChange} />,
      );
      expect(container.querySelectorAll('tbody tr')).toHaveLength(10);
    });

    it('still pages through the data', () => {
      const { container } = render(<DataTable columns={columns} data={items} pageSize={10} />);
      fireEvent.click(screen.getByText('pagination.goToNextPage').closest('button') as HTMLElement);
      expect(names(container)[0]).toBe('Item 10');
    });

    it('returns to the first page when the controlled search changes', () => {
      const { container, rerender } = render(
        <DataTable columns={columns} data={items} pageSize={10} searchValue="" onSearchChange={() => {}} />,
      );
      fireEvent.click(screen.getByText('pagination.goToNextPage').closest('button') as HTMLElement);
      expect(names(container)[0]).toBe('Item 10');
      rerender(
        <DataTable
          columns={columns}
          data={items.slice(0, 3)}
          pageSize={10}
          searchValue="x"
          onSearchChange={() => {}}
        />,
      );
      expect(names(container)).toEqual(['Item 00', 'Item 01', 'Item 02']);
    });
  });

  describe('footer', () => {
    it('renders a ReactNode footer inside the same table', () => {
      const { container } = render(
        <DataTable
          columns={columns}
          data={items}
          footer={
            <tr>
              <td />
              <td>Total</td>
              <td>300</td>
            </tr>
          }
        />,
      );
      const tfoot = container.querySelector('table tfoot');
      expect(tfoot).not.toBeNull();
      expect(tfoot?.closest('table')).toBe(container.querySelector('tbody')?.closest('table'));
      expect(tfoot?.textContent).toBe('Total300');
    });

    it('passes the table instance to a function footer', () => {
      const { container } = render(
        <DataTable
          columns={columns}
          data={items}
          footer={(table) => (
            <tr>
              {table.getVisibleLeafColumns().map((c) => (
                <td key={c.id}>{c.id}</td>
              ))}
            </tr>
          )}
        />,
      );
      const cells = Array.from(container.querySelectorAll('tfoot td')).map((c) => c.textContent);
      expect(cells).toEqual(['select', 'name', 'size']);
    });
  });

  describe('dense and fixedLayout', () => {
    const sized: ColumnDef<Item>[] = [
      { ...columns[0] },
      { ...columns[1], size: 90 },
    ];

    it('keeps the default layout and padding when the props are absent', () => {
      const { container } = render(<DataTable columns={sized} data={items} />);
      const table = container.querySelector('table') as HTMLTableElement;
      expect(table).not.toHaveClass('table-fixed');
      expect(table.style.minWidth).toBe('');
      expect(container.querySelector('thead th')).not.toHaveClass('h-9');
      expect(container.querySelector('tbody td')).not.toHaveClass('py-2');
      // No width is set on any header
      container.querySelectorAll('thead th').forEach((th) => expect((th as HTMLElement).style.width).toBe(''));
    });

    it('dense uses compact header and cell padding', () => {
      const { container } = render(<DataTable columns={sized} data={items} dense />);
      expect(container.querySelector('thead th')).toHaveClass('h-9', 'px-3');
      expect(container.querySelector('tbody td')).toHaveClass('px-3', 'py-2');
    });

    it('fixedLayout fixes only the widths a column declares and keeps a minimum table width', () => {
      const { container } = render(<DataTable columns={sized} data={items} fixedLayout selectable={false} />);
      const table = container.querySelector('table') as HTMLTableElement;
      expect(table).toHaveClass('table-fixed');
      const ths = Array.from(container.querySelectorAll('thead th')) as HTMLElement[];
      // name has no declared size -> flexible (TanStack's default 150 must not be applied)
      expect(ths[0].style.width).toBe('');
      expect(ths[1].style.width).toBe('90px');
      // 90 declared + 130 for the one flexible column
      expect(table.style.minWidth).toBe('220px');
    });
  });

  describe('view state persistence (storageKey)', () => {
    const filterable: ColumnDef<Item>[] = [
      {
        accessorKey: 'name',
        header: ({ column }) => (
          <>
            <button onClick={() => column.toggleSorting(column.getIsSorted() === 'asc')}>Name</button>
            <button onClick={() => column.setFilterValue('Item 1')}>Filter names</button>
          </>
        ),
      },
      columns[1],
    ];
    const searchInput = () => screen.getByPlaceholderText('filter items...') as HTMLInputElement;
    const viewOf = (key: string) => JSON.parse(localStorage.getItem(`${key}:view`) ?? 'null');

    it('restores the search filter and page index after a remount', () => {
      const first = render(<DataTable columns={filterable} data={items} storageKey="dt-view-search" />);
      fireEvent.change(searchInput(), { target: { value: 'Item' } });
      fireEvent.click(screen.getByText('pagination.goToNextPage').closest('button') as HTMLElement);
      expect(viewOf('dt-view-search')).toEqual({
        columnFilters: [],
        globalFilter: 'Item',
        pageIndex: 1,
        pageSize: 10,
      });
      first.unmount();

      const { container } = render(<DataTable columns={filterable} data={items} storageKey="dt-view-search" />);
      expect(searchInput().value).toBe('Item');
      expect(names(container)[0]).toBe('Item 10');
    });

    it('restores a column filter after a remount', () => {
      const first = render(<DataTable columns={filterable} data={items} storageKey="dt-view-column" />);
      fireEvent.click(screen.getByRole('button', { name: 'Filter names' }));
      expect(container10(first.container)).toBe(10);
      first.unmount();

      const { container } = render(<DataTable columns={filterable} data={items} storageKey="dt-view-column" />);
      expect(container10(container)).toBe(10);
      expect(names(container)[0]).toBe('Item 10');
    });

    it('drops stored column filters for columns that no longer exist', () => {
      localStorage.setItem(
        'dt-view-gone:view',
        JSON.stringify({ columnFilters: [{ id: 'gone', value: 'x' }] }),
      );
      const { container } = render(<DataTable columns={filterable} data={items} storageKey="dt-view-gone" />);
      expect(container10(container)).toBe(10);
      expect(screen.queryByText('noResults')).toBeNull();
    });

    it('clamps a stored page beyond the last page once the data shrinks', () => {
      localStorage.setItem('dt-view-clamp:view', JSON.stringify({ pageIndex: 2, pageSize: 10 }));
      const { container, rerender } = render(
        <DataTable columns={filterable} data={items} storageKey="dt-view-clamp" />,
      );
      expect(names(container)[0]).toBe('Item 20');
      rerender(<DataTable columns={filterable} data={items.slice(0, 5)} storageKey="dt-view-clamp" />);
      expect(names(container)).toEqual(['Item 00', 'Item 01', 'Item 02', 'Item 03', 'Item 04']);
      expect(viewOf('dt-view-clamp').pageIndex).toBe(0);
    });

    it('keeps a stored page while the data is still empty (loading)', () => {
      localStorage.setItem('dt-view-loading:view', JSON.stringify({ pageIndex: 2, pageSize: 10 }));
      const { container, rerender } = render(
        <DataTable columns={filterable} data={[]} storageKey="dt-view-loading" />,
      );
      rerender(<DataTable columns={filterable} data={items} storageKey="dt-view-loading" />);
      expect(names(container)[0]).toBe('Item 20');
    });

    it('moves a stored page back to the first page when a stored search hides every row', () => {
      localStorage.setItem('dt-view-hidden:view', JSON.stringify({ pageIndex: 2, pageSize: 10, globalFilter: 'zzz' }));
      render(<DataTable columns={filterable} data={items} storageKey="dt-view-hidden" />);
      expect(viewOf('dt-view-hidden').pageIndex).toBe(0);
    });

    it('shows a stored search that hides every row, and clearing it restores the rows', () => {
      localStorage.setItem('dt-view-none:view', JSON.stringify({ globalFilter: 'zzz' }));
      const { container } = render(<DataTable columns={filterable} data={items} storageKey="dt-view-none" />);
      expect(searchInput().value).toBe('zzz');
      expect(screen.getByText('noResults')).toBeInTheDocument();
      fireEvent.change(searchInput(), { target: { value: '' } });
      expect(container10(container)).toBe(10);
    });

    it('persists the page size', () => {
      const first = render(<DataTable columns={filterable} data={items} storageKey="dt-view-size" />);
      fireEvent.change(screen.getByLabelText('page size'), { target: { value: '20' } });
      expect(viewOf('dt-view-size').pageSize).toBe(20);
      first.unmount();

      const { container } = render(<DataTable columns={filterable} data={items} storageKey="dt-view-size" />);
      expect(container10(container)).toBe(20);
    });

    it('does not persist the search when the parent controls it', () => {
      render(
        <DataTable
          columns={filterable}
          data={items}
          storageKey="dt-view-controlled"
          searchValue="abc"
          onSearchChange={() => {}}
        />,
      );
      expect(viewOf('dt-view-controlled')).not.toHaveProperty('globalFilter');
    });

    it('does not copy the view into another storageKey after a key change', () => {
      localStorage.setItem('dt-view-other:view', JSON.stringify({ pageIndex: 0, pageSize: 20 }));
      const { rerender } = render(<DataTable columns={filterable} data={items} storageKey="dt-view-first" />);
      fireEvent.change(screen.getByLabelText('page size'), { target: { value: '30' } });
      rerender(<DataTable columns={filterable} data={items} storageKey="dt-view-other" />);
      expect(viewOf('dt-view-other').pageSize).toBe(20);
    });

    it('ignores a corrupt stored view', () => {
      localStorage.setItem('dt-view-corrupt:view', 'not json');
      const { container } = render(<DataTable columns={filterable} data={items} storageKey="dt-view-corrupt" />);
      expect(container10(container)).toBe(10);
    });
  });
});

function container10(container: HTMLElement) {
  return container.querySelectorAll('tbody tr').length;
}
