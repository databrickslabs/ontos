// localStorage mock, installed as a side effect on import.
//
// Kept in its own module (imported first from setup.ts) so that global
// localStorage exists before any other setup import runs — notably the i18n
// config, which reads localStorage at module-evaluation time.
const localStorageMock = (() => {
  let store: Record<string, string> = {};

  return {
    getItem: (key: string) => store[key] || null,
    setItem: (key: string, value: string) => {
      store[key] = value.toString();
    },
    removeItem: (key: string) => {
      delete store[key];
    },
    clear: () => {
      store = {};
    },
    get length() {
      return Object.keys(store).length;
    },
    key: (index: number) => {
      const keys = Object.keys(store);
      return keys[index] || null;
    },
  };
})();

// `globalThis.localStorage` is getter-only in recent Node/Vitest, so plain
// assignment throws; redefine the property instead.
Object.defineProperty(globalThis, 'localStorage', {
  value: localStorageMock,
  writable: true,
  configurable: true,
});
