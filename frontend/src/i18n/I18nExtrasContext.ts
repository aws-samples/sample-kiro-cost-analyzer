/**
 * Standalone context module for the `I18nContextExtras` value.
 *
 * Kept in its own file so `I18nProvider.tsx` exports **only** React
 * components. This satisfies the `react-refresh/only-export-components`
 * convention: Fast Refresh can safely replace the provider without
 * invalidating every consumer of the context.
 */

import { createContext } from 'react';
import type { I18nContextExtras } from './types';

export const I18nExtrasContext = createContext<I18nContextExtras | null>(null);
