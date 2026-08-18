/// <reference types="vite/client" />

/**
 * Application version injected at build time from the root VERSION file
 * (see vite.config.ts `define`). Single source of truth for the version
 * shown in the UI header.
 */
declare const __APP_VERSION__: string;
