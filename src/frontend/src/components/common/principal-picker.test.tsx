/**
 * Unit tests for PrincipalPicker.
 *
 * Scope: behaviour we can verify reliably in jsdom -- badges, manual
 * entry, and the API call shape for configured-mode searches. The
 * Radix Popover dropdown itself is exercised in Playwright E2E
 * (tag-selector tests in this repo follow the same split for the same
 * reason).
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { userEvent } from '@testing-library/user-event';

import { renderWithProviders } from '@/test/utils';
import { PrincipalPicker } from './principal-picker';
import { useDirectoryStore } from '@/stores/directory-store';

function setDirectoryStatus(configured: boolean) {
  // Bypass the network call by seeding the store directly.
  useDirectoryStore.setState({
    status: configured
      ? { configured: true, provider_type: 'entra', connection_name: 'graph' }
      : { configured: false, provider_type: null, connection_name: null },
    loaded: true,
    degraded: false,
    _inflight: null,
  });
}

const fetchMock = vi.fn();

beforeEach(() => {
  fetchMock.mockReset();
  // Default: status fetch returns unconfigured. Individual tests
  // override this either by seeding the store or by overriding the
  // mock.
  fetchMock.mockResolvedValue(
    new Response(
      JSON.stringify({ configured: false, provider_type: null, connection_name: null }),
      { status: 200, headers: { 'Content-Type': 'application/json' } },
    ),
  );
  global.fetch = fetchMock as unknown as typeof fetch;
  // Reset the zustand store between tests.
  useDirectoryStore.getState().reset();
});

afterEach(() => {
  useDirectoryStore.getState().reset();
});

describe('PrincipalPicker — pre-existing values', () => {
  it('renders a badge for each existing id without resolving against the directory', () => {
    setDirectoryStatus(false);
    renderWithProviders(
      <PrincipalPicker multiple value={['alice@x.com', 'Producers']} onChange={() => {}} />,
    );
    const badges = screen.getAllByTestId('principal-badge');
    expect(badges).toHaveLength(2);
    expect(badges[0]).toHaveTextContent('alice@x.com');
    expect(badges[1]).toHaveTextContent('Producers');
    // No directory search was attempted for pre-existing values.
    expect(fetchMock).not.toHaveBeenCalledWith(
      expect.stringContaining('/api/directory/search'),
      expect.anything(),
    );
  });

  it('emits the remaining ids after X-removing a badge', async () => {
    setDirectoryStatus(false);
    const onChange = vi.fn();
    renderWithProviders(
      <PrincipalPicker multiple value={['alice@x.com', 'Producers']} onChange={onChange} />,
    );
    const aliceBadge = screen.getAllByTestId('principal-badge')[0];
    const removeBtn = within(aliceBadge).getByRole('button', { name: /remove alice@x\.com/i });
    await userEvent.click(removeBtn);
    expect(onChange).toHaveBeenCalledWith(['Producers']);
  });

  it('does not render a remove button when disabled', () => {
    setDirectoryStatus(false);
    renderWithProviders(
      <PrincipalPicker value="alice@x.com" onChange={() => {}} disabled />,
    );
    const badge = screen.getByTestId('principal-badge');
    expect(within(badge).queryByRole('button')).toBeNull();
  });
});

describe('PrincipalPicker — unconfigured mode (manual entry)', () => {
  beforeEach(() => setDirectoryStatus(false));

  it('Enter commits the typed value as a badge in single mode', async () => {
    const onChange = vi.fn();
    renderWithProviders(
      <PrincipalPicker value={null} onChange={onChange} />,
    );
    const input = screen.getByTestId('principal-picker-input');
    await userEvent.type(input, 'alice@x.com{Enter}');
    expect(onChange).toHaveBeenLastCalledWith('alice@x.com');
  });

  it('comma commits a value in multi mode and appends to existing selections', async () => {
    const onChange = vi.fn();
    renderWithProviders(
      <PrincipalPicker multiple value={['existing@x']} onChange={onChange} />,
    );
    const input = screen.getByTestId('principal-picker-input');
    await userEvent.type(input, 'new@x,');
    expect(onChange).toHaveBeenLastCalledWith(['existing@x', 'new@x']);
  });

  it('Tab commits a value', async () => {
    const onChange = vi.fn();
    renderWithProviders(
      <PrincipalPicker multiple value={[]} onChange={onChange} />,
    );
    const input = screen.getByTestId('principal-picker-input');
    await userEvent.type(input, 'someone@y');
    await userEvent.tab();
    expect(onChange).toHaveBeenCalledWith(['someone@y']);
  });

  it('blur commits the buffered text', () => {
    const onChange = vi.fn();
    renderWithProviders(
      <PrincipalPicker multiple value={[]} onChange={onChange} />,
    );
    const input = screen.getByTestId('principal-picker-input') as HTMLInputElement;
    fireEvent.change(input, { target: { value: 'late@x' } });
    fireEvent.blur(input);
    expect(onChange).toHaveBeenCalledWith(['late@x']);
  });

  it('ignores empty / whitespace-only entries', async () => {
    const onChange = vi.fn();
    renderWithProviders(
      <PrincipalPicker multiple value={[]} onChange={onChange} />,
    );
    const input = screen.getByTestId('principal-picker-input');
    await userEvent.type(input, '   {Enter}');
    expect(onChange).not.toHaveBeenCalled();
  });

  it('does not duplicate an already-selected value', async () => {
    const onChange = vi.fn();
    renderWithProviders(
      <PrincipalPicker multiple value={['alice@x.com']} onChange={onChange} />,
    );
    const input = screen.getByTestId('principal-picker-input');
    await userEvent.type(input, 'alice@x.com{Enter}');
    expect(onChange).not.toHaveBeenCalled();
  });
});

describe('PrincipalPicker — configured mode', () => {
  beforeEach(() => {
    setDirectoryStatus(true);
    // Provide an empty result set; we only assert on the URL shape.
    fetchMock.mockImplementation((url: RequestInfo | URL) => {
      const u = url.toString();
      if (u.includes('/api/directory/search')) {
        return Promise.resolve(
          new Response(JSON.stringify({ results: [] }), {
            status: 200,
            headers: { 'Content-Type': 'application/json' },
          }),
        );
      }
      return Promise.resolve(
        new Response('{}', {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      );
    });
  });

  it('calls /api/directory/search with the typed query and accepts filter', async () => {
    renderWithProviders(
      <PrincipalPicker accepts={['user']} value={null} onChange={() => {}} />,
    );
    const input = screen.getByTestId('principal-picker-input');
    await userEvent.type(input, 'ali');
    // Debounce is 250ms; rely on the test framework's natural wait.
    await waitFor(() => {
      const calls = fetchMock.mock.calls.map((c) => String(c[0]));
      expect(calls.some((u) => u.includes('/api/directory/search'))).toBe(true);
    });
    const searchUrl = String(
      fetchMock.mock.calls.find((c) => String(c[0]).includes('/api/directory/search'))![0],
    );
    expect(searchUrl).toContain('q=ali');
    expect(searchUrl).toContain('types=user');
    expect(searchUrl).not.toContain('types=group');
  });

  it('does not search for queries shorter than 2 chars', async () => {
    renderWithProviders(
      <PrincipalPicker value={null} onChange={() => {}} />,
    );
    const input = screen.getByTestId('principal-picker-input');
    await userEvent.type(input, 'a');
    // Give the debounce a moment to fire.
    await new Promise((r) => setTimeout(r, 350));
    const searches = fetchMock.mock.calls.filter((c) =>
      String(c[0]).includes('/api/directory/search'),
    );
    expect(searches).toHaveLength(0);
  });

  it('passes both types when accepts is default', async () => {
    renderWithProviders(
      <PrincipalPicker value={null} onChange={() => {}} />,
    );
    const input = screen.getByTestId('principal-picker-input');
    await userEvent.type(input, 'al');
    await waitFor(() => {
      expect(
        fetchMock.mock.calls.some((c) => String(c[0]).includes('/api/directory/search')),
      ).toBe(true);
    });
    const searchUrl = String(
      fetchMock.mock.calls.find((c) => String(c[0]).includes('/api/directory/search'))![0],
    );
    // URLSearchParams encodes commas as %2C in some Node versions; check both.
    expect(/types=user(,|%2C)group/.test(searchUrl)).toBe(true);
  });

  it('flips into manual-entry mode when search fails (graceful degradation)', async () => {
    fetchMock.mockImplementation((url: RequestInfo | URL) => {
      const u = url.toString();
      if (u.includes('/api/directory/search')) {
        return Promise.reject(new Error('network down'));
      }
      return Promise.resolve(new Response('{}', { status: 200 }));
    });
    const onChange = vi.fn();
    renderWithProviders(
      <PrincipalPicker multiple value={[]} onChange={onChange} />,
    );
    // Type two chars to trigger the search, which will fail.
    await userEvent.type(screen.getByTestId('principal-picker-input'), 'al');
    await waitFor(() => {
      expect(useDirectoryStore.getState().degraded).toBe(true);
    });
    // The picker has now re-rendered with the manual ManualInput
    // (different component instance, fresh state). Type the full
    // value and commit with Enter.
    const manualInput = screen.getByTestId('principal-picker-input');
    await userEvent.type(manualInput, 'alice@x.com{Enter}');
    expect(onChange).toHaveBeenLastCalledWith(['alice@x.com']);
  });
});

describe('PrincipalPicker — manual-entry hint', () => {
  it('renders the manual-mode hint only when directory is unconfigured', () => {
    setDirectoryStatus(false);
    const { rerender } = renderWithProviders(
      <PrincipalPicker multiple value={[]} onChange={() => {}} />,
    );
    expect(screen.getByTestId('principal-picker-manual-hint')).toBeInTheDocument();

    setDirectoryStatus(true);
    rerender(<PrincipalPicker multiple value={[]} onChange={() => {}} />);
    expect(screen.queryByTestId('principal-picker-manual-hint')).toBeNull();
  });
});

describe('PrincipalPicker — pill placement', () => {
  it('renders badges below the input row in the DOM', () => {
    setDirectoryStatus(false);
    renderWithProviders(
      <PrincipalPicker multiple value={['alice@x.com']} onChange={() => {}} />,
    );
    const input = screen.getByTestId('principal-picker-input');
    const badge = screen.getByTestId('principal-badge');
    // ``compareDocumentPosition`` returns bitmask DOCUMENT_POSITION_FOLLOWING (4)
    // when the second node follows the first. The badge should follow the input.
    expect(input.compareDocumentPosition(badge) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });
});

describe('PrincipalPicker — Browse dialog', () => {
  beforeEach(() => {
    setDirectoryStatus(true);
    fetchMock.mockImplementation((url: RequestInfo | URL) => {
      const u = url.toString();
      if (u.includes('/api/directory/search')) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              results: [
                { type: 'group', id: 'Producers', display_name: 'Data Producers', sub_label: 'producers-guid' },
              ],
            }),
            { status: 200, headers: { 'Content-Type': 'application/json' } },
          ),
        );
      }
      return Promise.resolve(new Response('{}', { status: 200 }));
    });
  });

  it('clears the search query and filter when the dialog is reopened', async () => {
    renderWithProviders(
      <PrincipalPicker multiple accepts={['group']} value={[]} onChange={() => {}} />,
    );
    // Open once.
    await userEvent.click(screen.getByRole('button', { name: /browse directory/i }));
    const dialogInput1 = await screen.findByTestId('principal-picker-dialog-input');
    await userEvent.type(dialogInput1, 'pro');
    expect((dialogInput1 as HTMLInputElement).value).toBe('pro');

    // Close via the in-dialog Close button (the path that previously
    // bypassed reset because it called onOpenChange directly). Radix
    // also renders an icon-only close button with sr-only "Close" text;
    // pick the visible footer button (the one without the sr-only span).
    const closeButtons = screen.getAllByRole('button', { name: /^close$/i });
    const visibleClose = closeButtons.find((b) => !b.querySelector('.sr-only'))!;
    await userEvent.click(visibleClose);
    await waitFor(() => {
      expect(screen.queryByTestId('principal-picker-dialog-input')).toBeNull();
    });

    // Reopen.
    await userEvent.click(screen.getByRole('button', { name: /browse directory/i }));
    const dialogInput2 = await screen.findByTestId('principal-picker-dialog-input');
    expect((dialogInput2 as HTMLInputElement).value).toBe('');
  });

  it('picks a row on click and emits the principal id', async () => {
    const onChange = vi.fn();
    renderWithProviders(
      <PrincipalPicker multiple accepts={['group']} value={[]} onChange={onChange} />,
    );
    await userEvent.click(screen.getByRole('button', { name: /browse directory/i }));
    const dialogInput = await screen.findByTestId('principal-picker-dialog-input');
    await userEvent.type(dialogInput, 'pro');

    const row = await screen.findByTestId('principal-row');
    await userEvent.click(row);

    expect(onChange).toHaveBeenLastCalledWith(['Producers']);
  });

  it('closes the dialog after a pick in multi-select mode', async () => {
    // Browse is the discovery path -- it should always close after a
    // pick so the user is returned to the form. Adding several entries
    // is done via the inline type-ahead.
    renderWithProviders(
      <PrincipalPicker multiple accepts={['group']} value={[]} onChange={() => {}} />,
    );
    await userEvent.click(screen.getByRole('button', { name: /browse directory/i }));
    const dialogInput = await screen.findByTestId('principal-picker-dialog-input');
    await userEvent.type(dialogInput, 'pro');

    const row = await screen.findByTestId('principal-row');
    await userEvent.click(row);

    await waitFor(() => {
      expect(screen.queryByTestId('principal-picker-dialog-input')).toBeNull();
    });
  });

  it('row mousedown is default-prevented to keep focus on the input (regression for fix #1)', async () => {
    renderWithProviders(
      <PrincipalPicker multiple accepts={['group']} value={[]} onChange={() => {}} />,
    );
    await userEvent.click(screen.getByRole('button', { name: /browse directory/i }));
    const dialogInput = await screen.findByTestId('principal-picker-dialog-input');
    await userEvent.type(dialogInput, 'pro');

    const row = await screen.findByTestId('principal-row');
    const event = new MouseEvent('mousedown', { bubbles: true, cancelable: true });
    row.dispatchEvent(event);
    expect(event.defaultPrevented).toBe(true);
  });
});
