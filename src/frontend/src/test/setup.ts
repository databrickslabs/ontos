import '@testing-library/jest-dom/vitest';
// Install the localStorage mock before any other import so it exists at
// module-evaluation time for imports that touch it (e.g. the i18n config).
import './localstorage';
import { cleanup } from '@testing-library/react';
import { afterEach, beforeEach, vi } from 'vitest';

// Initialize the real i18n instance (loads all English namespaces) so that
// components using useTranslation()/t() render resolved English text instead
// of raw keys. Without this, migrated components emit keys like
// "workflows:templateVars.loadFailedWithError" and assertions written against
// the English copy fail. Force English for deterministic output regardless of
// jsdom's navigator language.
import i18n from '../i18n/config';
i18n.changeLanguage('en');

// Cleanup after each test
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

// Mock IntersectionObserver
class MockIntersectionObserver implements IntersectionObserver {
  readonly root: Element | Document | null = null;
  readonly rootMargin: string = '';
  readonly thresholds: ReadonlyArray<number> = [];
  
  constructor(_callback: IntersectionObserverCallback, _options?: IntersectionObserverInit) {}
  
  observe(): void {}
  disconnect(): void {}
  unobserve(): void {}
  takeRecords(): IntersectionObserverEntry[] {
    return [];
  }
}
global.IntersectionObserver = MockIntersectionObserver;

// Mock ResizeObserver
global.ResizeObserver = class ResizeObserver {
  constructor() {}
  observe() {
    return null;
  }
  disconnect() {
    return null;
  }
  unobserve() {
    return null;
  }
};

// Mock scrollIntoView
Element.prototype.scrollIntoView = vi.fn();

// Mock getBoundingClientRect
Element.prototype.getBoundingClientRect = vi.fn(() => ({
  x: 0,
  y: 0,
  width: 0,
  height: 0,
  top: 0,
  right: 0,
  bottom: 0,
  left: 0,
  toJSON: vi.fn(),
}));

// Mock DOMRect
global.DOMRect = {
  fromRect: vi.fn(() => ({
    x: 0,
    y: 0,
    width: 0,
    height: 0,
    top: 0,
    right: 0,
    bottom: 0,
    left: 0,
    toJSON: vi.fn(),
  })),
} as any;

// Mock matchMedia
Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: vi.fn().mockImplementation(query => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: vi.fn(), // deprecated
    removeListener: vi.fn(), // deprecated
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })),
});

// Suppress console warnings in tests
const originalError = console.error;
const originalWarn = console.warn;

beforeEach(() => {
  console.error = (...args: any[]) => {
    if (
      typeof args[0] === 'string' &&
      (args[0].includes('Function components cannot be given refs') ||
       args[0].includes('Warning: React.forwardRef'))
    ) {
      return;
    }
    originalError.call(console, ...args);
  };

  console.warn = (...args: any[]) => {
    if (
      typeof args[0] === 'string' &&
      args[0].includes('Warning:')
    ) {
      return;
    }
    originalWarn.call(console, ...args);
  };
});

afterEach(() => {
  console.error = originalError;
  console.warn = originalWarn;
});

// localStorage mock is installed via the './localstorage' import above.
// Clear it before each test.
beforeEach(() => {
  localStorage.clear();
});