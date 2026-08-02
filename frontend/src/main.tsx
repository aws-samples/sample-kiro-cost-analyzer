import { createRoot } from 'react-dom/client';
import { BrowserRouter } from 'react-router';
import '@cloudscape-design/global-styles/index.css';
import './index.css';
// Side-effect import: initializes the shared i18next instance before any
// component calls `useTranslation()` / `useI18n()`.
import './i18n';
import { I18nProvider } from './i18n/I18nProvider';
import { ThemeProvider } from './theme/ThemeProvider';
import App from './App.tsx';

// Note: `applyMode(Mode.Dark)` used to run here statically. It now lives
// inside `ThemeProvider`, which applies the user's persisted preference
// (or the default `'dark'`) on first render and keeps the DOM in sync on
// every change. The static call was removed to avoid a flash of the
// wrong mode on boot.

createRoot(document.getElementById('root')!).render(
  <I18nProvider>
    <ThemeProvider>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </ThemeProvider>
  </I18nProvider>,
);
