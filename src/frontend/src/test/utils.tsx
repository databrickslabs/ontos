import { ReactElement } from 'react';
import { render, RenderOptions } from '@testing-library/react';
import { BrowserRouter } from 'react-router-dom';
import { vi, beforeEach, afterEach } from 'vitest';
import { userEvent } from '@testing-library/user-event';
import { TooltipProvider } from '@/components/ui/tooltip';

/**
 * Custom render function that includes Router context
 */
export const renderWithRouter = (
  ui: ReactElement,
  {
    route = '/',
    ...renderOptions
  }: RenderOptions & { route?: string } = {}
) => {
  window.history.pushState({}, 'Test page', route);

  const Wrapper = ({ children }: { children: React.ReactNode }) => (
    <BrowserRouter>{children}</BrowserRouter>
  );

  return render(ui, { wrapper: Wrapper, ...renderOptions });
};

/**
 * Custom render function that includes UI providers (Tooltip, etc.) and Router
 */
export const renderWithProviders = (
  ui: ReactElement,
  {
    route = '/',
    ...renderOptions
  }: RenderOptions & { route?: string } = {}
) => {
  window.history.pushState({}, 'Test page', route);

  const Wrapper = ({ children }: { children: React.ReactNode }) => (
    <BrowserRouter>
      <TooltipProvider>{children}</TooltipProvider>
    </BrowserRouter>
  );

  return render(ui, { wrapper: Wrapper, ...renderOptions });
};

/**
 * Helper to create mock API responses
 */
export const createMockApiResponse = <T,>(data: T, status = 200) => ({
  status,
  data,
  statusText: status === 200 ? 'OK' : 'Error',
});

/**
 * Helper to create mock error responses
 */
export const createMockApiError = (message: string, status = 500) => ({
  response: {
    status,
    data: { message },
  },
  message,
});

/**
 * Wait for a specific amount of time (useful for debounce testing)
 */
export const wait = (ms: number) => new Promise(resolve => setTimeout(resolve, ms));

/**
 * Mock console methods to avoid noise in tests
 */
export const mockConsole = () => {
  const originalError = console.error;
  const originalWarn = console.warn;
  const originalLog = console.log;

  beforeEach(() => {
    console.error = vi.fn();
    console.warn = vi.fn();
    console.log = vi.fn();
  });

  afterEach(() => {
    console.error = originalError;
    console.warn = originalWarn;
    console.log = originalLog;
  });
};

/**
 * Create a mock file for file upload testing
 */
export const createMockFile = (
  name: string,
  content: string,
  type: string = 'text/plain'
): File => {
  const blob = new Blob([content], { type });
  return new File([blob], name, { type });
};

/**
 * Helper to mock localStorage
 */
export const mockLocalStorage = () => {
  const localStorageMock = {
    getItem: vi.fn(),
    setItem: vi.fn(),
    removeItem: vi.fn(),
    clear: vi.fn(),
  };

  global.localStorage = localStorageMock as any;

  return localStorageMock;
};

/**
 * Helper to mock fetch
 */
export const mockFetch = (response: any, ok = true) => {
  global.fetch = vi.fn(() =>
    Promise.resolve({
      ok,
      json: () => Promise.resolve(response),
      text: () => Promise.resolve(JSON.stringify(response)),
      status: ok ? 200 : 500,
      statusText: ok ? 'OK' : 'Internal Server Error',
    } as Response)
  );
};

/**
 * Re-export userEvent for convenience
 */
export { userEvent };
