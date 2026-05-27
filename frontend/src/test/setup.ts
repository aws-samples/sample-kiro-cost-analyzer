import '@testing-library/jest-dom'

// Node 25+ with jsdom may not provide a functional localStorage.
// Provide a Storage-prototype-based mock so that vi.spyOn(Storage.prototype, ...)
// works correctly in persistence tests.
(() => {
  // If localStorage already works (e.g., jsdom on Node <25), skip.
  try {
    const testKey = '__vitest_storage_probe__';
    globalThis.localStorage.setItem(testKey, '1');
    if (globalThis.localStorage.getItem(testKey) === '1') {
      globalThis.localStorage.removeItem(testKey);
      return; // native localStorage works fine
    }
  } catch {
    // fall through to install mock
  }

  // Install a localStorage backed by a plain object but routed through
  // Storage.prototype so that vi.spyOn(Storage.prototype, 'setItem') works.
  const store: Record<string, string> = {};

  Storage.prototype.getItem = function (key: string) {
    return store[key] ?? null;
  };
  Storage.prototype.setItem = function (key: string, value: string) {
    store[key] = String(value);
  };
  Storage.prototype.removeItem = function (key: string) {
    delete store[key];
  };
  Storage.prototype.clear = function () {
    Object.keys(store).forEach(k => delete store[k]);
  };
  Storage.prototype.key = function (i: number) {
    return Object.keys(store)[i] ?? null;
  };
  Object.defineProperty(Storage.prototype, 'length', {
    get() { return Object.keys(store).length; },
    configurable: true,
  });

  // Ensure globalThis.localStorage is an instance of Storage
  if (!(globalThis.localStorage instanceof Storage)) {
    Object.defineProperty(globalThis, 'localStorage', {
      value: Object.create(Storage.prototype),
      writable: true,
      configurable: true,
    });
  }
})();
