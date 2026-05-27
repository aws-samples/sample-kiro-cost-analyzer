# Implementation Plan: i18n and English as Default Locale

## Overview

This plan maps onto the 9-step migration order from `design.md`. Each step is independently deployable, keeps `main` green, and preserves the pt-BR experience byte-for-byte until the default-locale flip in Step 6. Tasks are grouped by step and reference specific requirements.

Implementation language: **TypeScript** (frontend) and **Python** (backend), matching the existing stack. No pseudocode-to-language conversion is needed — the design document already targets these languages directly.

Conventions:

- Sub-tasks marked with `*` are optional and can be skipped for a fast MVP. Test sub-tasks are the usual optional candidates, except for the ten Correctness Properties (Property 1 through Property 10), which are REQUIRED — they are the core correctness guarantee of this feature.
- Each task cites the requirement clauses it implements (e.g., `_Requirements: 1.1, 1.6_`).
- Property-based test tasks cite the corresponding Property number from `design.md` (e.g., `_Property 4, Requirements: 5.1, 5.3, 16.4_`).
- Checkpoint tasks validate the end of each migration step before the next one starts.

## Tasks

### Step 1 — Scaffold the i18n module with no call sites yet

- [x] 1. Add i18n runtime dependencies and scaffold module
  - [x] 1.1 Add `i18next`, `react-i18next`, `i18next-resources-to-backend` to `frontend/package.json`
    - Pin exact versions compatible with React 19
    - Run `npm install` inside `frontend/` to update `package-lock.json`
    - _Requirements: 1.1, 1.6, 15.1_

  - [x] 1.2 Create `frontend/src/i18n/constants.ts`
    - Export `SUPPORTED_LOCALES` (readonly tuple `['en', 'pt-BR']`), `DEFAULT_LOCALE` (set to `'pt-BR'` initially so Step 1 does not change default behavior — flipped to `'en'` in Step 6), `LOCALE_STORAGE_KEY` (`'kiro_locale'`), and `BRAND_STRINGS` (`{ productName: 'Kiro Cost Analyzer', short: 'Kiro' }`)
    - _Requirements: 1.1, 2.1, 4.1, 9.1_

  - [x] 1.3 Create `frontend/src/i18n/types.ts`
    - Export `SupportedLocale` (literal union `'en' | 'pt-BR'`) and `I18nContextExtras` interface (extends `Formatters` with `locale: SupportedLocale` and `setLocale: (next: SupportedLocale) => Promise<void>`)
    - _Requirements: 1.1, 2.1_

  - [x] 1.4 Create `frontend/src/i18n/resolveLocale.ts`
    - Export pure function `resolveInitialLocale(stored, navigatorLanguage)` implementing the three-step chain: stored (if supported) → normalized `navigator.language` → `DEFAULT_LOCALE`
    - Implement `normalizeToSupported` that maps `'en'`, `'en-*'` → `'en'`; `'pt'`, `'pt-*'`, `'pt_*'` → `'pt-BR'`; everything else → `null`
    - _Requirements: 2.1, 2.2, 2.4, 2.5, 2.6, 16.1_

  - [x] 1.5 Create `frontend/src/i18n/persistence.ts`
    - Implement `readStored()` with `try/catch` around `localStorage.getItem`, returning `null` on failure
    - Implement `persistLocale(locale)` with `try/catch` around `localStorage.setItem`, emitting one `console.warn` per session on failure via a module-scoped `persistWarned` flag
    - _Requirements: 4.1, 4.2, 4.3_

  - [x] 1.6 Create `frontend/src/i18n/formatters.ts`
    - Export `Formatters` interface (`formatNumber`, `formatDate`, `formatTime`, `formatDateTime`)
    - Export `createFormatters(locale)` factory returning a `Formatters` object whose members delegate to `Intl.NumberFormat` / `Intl.DateTimeFormat` bound to the given locale
    - Use default options `{ year: 'numeric', month: '2-digit', day: '2-digit' }` for date, `{ hour: '2-digit', minute: '2-digit' }` for time, and their union for date-time
    - _Requirements: 5.1, 5.3, 5.4, 5.5_

  - [x] 1.7 Create `frontend/src/i18n/index.ts`
    - Resolve initial locale synchronously via `resolveInitialLocale(readStored(), navigator.language)`
    - Create an `i18next` instance with `createInstance()`, wire `initReactI18next` and `resourcesToBackend`
    - Static-import `en.json` and serve it inline from the resources backend when `language === 'en'`; dynamic-`import()` non-default catalogs so Vite emits per-locale chunks
    - Init with `lng: initialLocale`, `fallbackLng: 'en'`, `supportedLngs`, `defaultNS: 'translation'`, `keySeparator: false`, `nsSeparator: false`, `interpolation: { escapeValue: false, prefix: '{{', suffix: '}}' }`, `returnNull: false`, `saveMissing: import.meta.env.DEV`, and a `missingKeyHandler` that `console.error`s once per key per session (deduped via a module-scoped `Set`)
    - On `languageChanged`, call `persistLocale`; after init resolves, if `readStored()` differs from `i18n.language`, persist the resolved value (Requirement 2.4)
    - _Requirements: 1.1, 1.6, 2.3, 2.4, 2.6, 10.3, 10.4, 15.1_

  - [x] 1.8 Create `frontend/src/i18n/I18nProvider.tsx`
    - Export `I18nExtrasContext` (React context typed as `I18nContextExtras | null`)
    - Export `I18nProvider` that wraps children in `I18nextProvider` (from `react-i18next`, bound to the shared i18next instance)
    - Inside, define `InnerProvider` that reads `useTranslation()`, memoizes `Formatters` with `useMemo(() => createFormatters(locale), [locale])`, memoizes the extras object, and exposes a `setLocale` callback that calls `persistLocale` first and then `instance.changeLanguage`
    - Wrap the inner tree in `CloudscapeI18nProvider` from `@cloudscape-design/components/i18n` with the active locale and the matching `all.<locale>.json` message bundle
    - _Requirements: 1.1, 1.4, 2.6, 3.2, 3.3, 4.1_

  - [x] 1.9 Create `frontend/src/i18n/useI18n.ts`
    - Export `useI18n()` hook that calls `useTranslation()` for `t`, reads `I18nExtrasContext`, throws if the context is `null`, and returns the spread `{ ...extras, t }`
    - Export the `UseI18nResult` interface
    - _Requirements: 1.1, 3.3_

  - [x] 1.10 Create `frontend/src/locales/en.json` and `frontend/src/locales/pt-BR.json` seeded with brand, common, and cron keys
    - Populate `brand.productName` (`"Kiro Cost Analyzer"` in both), `brand.short` (`"Kiro"` in both), and `common.languageSwitcher.ariaLabel` (`"Language"` in en, `"Idioma"` in pt-BR)
    - Add every `cron.*` key enumerated in `design.md` (cron.rate.daily, cron.rate.days, cron.rate.hourly, cron.rate.hours, cron.rate.minute, cron.rate.minutes, cron.cron.daily, cron.cron.dayOfMonth, cron.cron.daysRange, cron.cron.daysList, cron.days.SUN through cron.days.SAT) with their en and pt-BR values
    - Keep keys sorted alphabetically and values non-empty strings
    - _Requirements: 1.2, 8.1, 9.1, 10.1, 10.2_

  - [x] 1.11 Create `scripts/check-locales.ts`
    - Read both catalog files under `frontend/src/locales/`
    - Exit `1` with a diagnostic message when key sets diverge (print symmetric difference), any value is non-string or empty, or either file is not alphabetically sorted by key
    - On success, emit `frontend/src/locales/keys.d.ts` containing: (1) `export type TranslationKey = keyof typeof enCatalog;` and (2) a `declare module 'i18next'` block augmenting `CustomTypeOptions.resources` with `{ translation: typeof enCatalog }`, `defaultNS: 'translation'`, `returnNull: false`
    - Use Node stdlib only — no new dependencies
    - _Requirements: 10.1, 10.2, 10.5_

  - [x] 1.12 Wire `check-locales` into build
    - Add `"check:locales": "node --experimental-strip-types scripts/check-locales.ts"` (or equivalent runner) to `frontend/package.json` scripts
    - Update the `build` script to `"check:locales && tsc -b && vite build"` so key parity is enforced before TypeScript compilation
    - _Requirements: 10.5_

  - [x] 1.13 Integrate `I18nProvider` into `frontend/src/main.tsx`
    - Import `I18nProvider` and wrap the existing `BrowserRouter` / `App` tree so the provider sits above `AuthProvider` (note: `AuthProvider` is inside `App.tsx`; place `I18nProvider` in `main.tsx` as the outermost provider before `BrowserRouter`)
    - Ensure `src/i18n/index.ts` is imported for its side-effect (i18next init) before the `createRoot` call
    - _Requirements: 1.1, 1.4, 2.6_

  - [ ]* 1.14 Unit tests for `resolveLocale.ts` (required, not optional — pure and high-leverage)
    - Cover each branch: stored valid, stored invalid, stored null; navigator `'en'`, `'en-US'`, `'en-GB'`, `'pt-BR'`, `'pt-br'`, `'pt'`, `'pt-PT'`, `'fr-FR'`, `undefined`
    - _Requirements: 2.1, 2.2, 2.4, 2.5_

  - [x] 1.15 **Property 1**: locale-resolution totality
    - **Property 1: Resolution totality — `resolveInitialLocale` is total over `(string | null, string | undefined)`**
    - Use fast-check with `storedArb = fc.oneof(fc.constant(null), fc.string())` and `navArb = fc.oneof(fc.constant(undefined), fc.string(), fc.constantFrom('en', 'en-US', 'en-GB', 'pt', 'pt-BR', 'pt-br', 'fr', 'de'))`
    - Assert the result is a member of `SUPPORTED_LOCALES`; ≥ 500 runs
    - **Validates: Requirements 2.1, 2.2, 2.4, 2.5, 16.1**
    - _Requirements: 2.1, 2.2, 2.4, 2.5, 16.1_

  - [x] 1.16 Unit tests for `formatters.ts`
    - Concrete expectations for `formatNumber(1234.5)` under both locales; analogous for `formatDate`, `formatTime`, `formatDateTime` with a fixed `Date`
    - Verify invalid inputs return `Intl`'s native `"Invalid Date"` string without throwing
    - _Requirements: 5.1, 5.3, 5.4, 5.5_

  - [x] 1.17 Unit tests for `persistence.ts`
    - Cover the happy path (write then read round-trip), the `localStorage.getItem` throwing case, the `localStorage.setItem` throwing case, and the single-warning-per-session dedup behavior
    - _Requirements: 4.1, 4.2, 4.3_

  - [x] 1.18 Unit tests for `I18nProvider` adapter
    - Verify `useI18n()` throws when called outside the provider
    - Verify `setLocale(L)` calls `persistLocale(L)` before `i18n.changeLanguage(L)` (use spies; assert call order)
    - Verify a locale change produces exactly one re-render of a probe child component (use a render-counter)
    - _Requirements: 3.2, 3.3, 4.1, NFR-1_

  - [ ]* 1.19 Unit tests for `i18n/index.ts` init behavior (optional)
    - Assert `keySeparator` and `nsSeparator` are `false`, `fallbackLng` is `'en'`, `missingKeyHandler` fires exactly once per missing key per session
    - _Requirements: 1.6, 10.3, 10.4_

  - [x] 1.20 Checkpoint — Step 1 complete
    - Run `npm run build` — key-parity check passes, TypeScript compiles, Vite builds
    - Run `npm run test` — all unit and property tests pass
    - Run `python -m pytest tests/ -v` — backend unchanged, all tests still pass
    - Ensure all tests pass, ask the user if questions arise.

### Step 2 — Refactor the formatters (replace every `toLocaleString('pt-BR')` call site)

- [x] 2. Migrate formatter call sites (locale still defaults to pt-BR; outputs remain byte-identical)
  - [x] 2.1 Replace formatters in `frontend/src/components/AccountSummaryCards.tsx`
    - Replace both `n.toLocaleString('pt-BR', {...})` call sites with `formatNumber(n, {...})` from `useI18n()`
    - _Requirements: 5.1, 5.2_

  - [x] 2.2 Replace formatters in `frontend/src/components/UserSummaryCards.tsx`
    - Replace both `n.toLocaleString('pt-BR', {...})` call sites with `formatNumber(n, {...})`
    - _Requirements: 5.1, 5.2_

  - [x] 2.3 Replace formatters in `frontend/src/components/UsageTable.tsx`
    - Replace both `item.totalMessages.toLocaleString('pt-BR')` call sites with `formatNumber(value)`
    - _Requirements: 5.1, 5.2_

  - [x] 2.4 Replace formatters in `frontend/src/components/RecentPromptsTable.tsx`
    - Replace `d.toLocaleString('pt-BR')` with `formatDateTime(d)` and two `item.promptLength.toLocaleString('pt-BR')` calls with `formatNumber(value)`
    - _Requirements: 5.1, 5.2_

  - [x] 2.5 Replace formatters in `frontend/src/components/PromptDetailPanel.tsx`
    - Replace `d.toLocaleString('pt-BR')` with `formatDateTime(d)`
    - _Requirements: 5.1, 5.2_

  - [x] 2.6 Replace formatters in `frontend/src/components/DistributionCharts.tsx`
    - Replace all six `datum.value.toLocaleString('pt-BR')` call sites with `formatNumber(datum.value)`
    - _Requirements: 5.1, 5.2_

  - [x] 2.7 Replace formatters in `frontend/src/pages/SettingsPage.tsx`
    - Replace `new Date(value).toLocaleString('pt-BR')` in `formatDateTime` helper with the `formatDateTime` formatter from `useI18n()`
    - _Requirements: 5.1, 5.2_

  - [x] 2.8 Replace formatters in `frontend/src/pages/UsersPage.tsx`
    - Replace `new Date(item.createdAt).toLocaleString('pt-BR')` with `formatDateTime(item.createdAt)`
    - _Requirements: 5.1, 5.2_

  - [x] 2.9 Replace formatters in `frontend/src/pages/FeedbackAdminPage.tsx`
    - Replace `new Date(iso).toLocaleString('pt-BR')` with `formatDateTime(iso)`
    - _Requirements: 5.1, 5.2_

  - [x] 2.10 Audit `frontend/src/hooks/useLastUpdated.ts` and `frontend/src/hooks/useSplitPanel.tsx`
    - Confirm there are no `toLocaleString('pt-BR')` calls; if any are found, replace them with the locale-aware formatter
    - _Requirements: 5.1, 5.2_

  - [x] 2.11 **Property 4**: number formatter locale coherence
    - **Property 4: Number formatter locale coherence — `formatNumber(n, opts)` equals `new Intl.NumberFormat(L, opts).format(n)` for every `(n, L, opts)`**
    - fast-check over `fc.double({ noNaN: false, noDefaultInfinity: false })` × `fc.constantFrom('en', 'pt-BR')` × a small options arbitrary (`minimumFractionDigits ∈ 0..4`, `maximumFractionDigits ∈ 0..4`, `style ∈ 'decimal' | 'percent'`)
    - ≥ 200 runs
    - **Validates: Requirements 5.1, 5.3, 5.4, 16.4**
    - _Requirements: 5.1, 5.3, 5.4, 16.4_

  - [x] 2.12 **Property 5**: date and time formatter locale coherence
    - **Property 5: Date/time formatter locale coherence — `formatDateTime(t, opts)` equals `new Intl.DateTimeFormat(L, opts).format(t)` for every `(t, L, opts)`; same for `formatDate` and `formatTime`**
    - fast-check over `fc.date({ min: new Date('1970-01-01'), max: new Date('2100-12-31') })` × `fc.constantFrom('en', 'pt-BR')` with the documented default option objects; separate runs for `formatDate` and `formatTime`
    - ≥ 200 runs each
    - **Validates: Requirements 5.1, 5.3, 5.4, 5.5, 16.5**
    - _Requirements: 5.1, 5.3, 5.4, 5.5, 16.5_

  - [x] 2.13 Checkpoint — Step 2 complete
    - Manual visual pass on each affected page with `locale = 'pt-BR'` (still the default): pt-BR output is byte-identical to pre-Step-2
    - Run `npm run build` and `npm run test` — all tests pass
    - Ensure all tests pass, ask the user if questions arise.

### Step 3 — Refactor the cronHumanizer and add cron catalog keys

- [x] 3. Migrate cron humanization to catalog-driven TFunction signature
  - [x] 3.1 Refactor `frontend/src/utils/cronHumanizer.ts` to `humanize(expression, t)`
    - Keep `parseRate`, `parseCron`, `formatTime`, `humanizeDaysOfWeek`, `capitalize` intact
    - Replace every hardcoded pt-BR display string with a `t(key, vars)` call using the keys enumerated in `design.md` (`cron.rate.*`, `cron.cron.*`, `cron.days.*`)
    - Preserve the unparsable-fallback behavior (`return expression` verbatim)
    - _Requirements: 6.1, 6.2, 6.3, 6.4_

  - [x] 3.2 Verify catalog keys seeded in Step 1 cover every branch of the parser
    - Cross-reference `cronHumanizer.ts` paths with `en.json` / `pt-BR.json` keys; add any missing key in both files (sorted, non-empty)
    - Validate pt-BR values reproduce the current `humanizeSchedule` output byte-for-byte for every supported pattern
    - _Requirements: 8.1, 8.3, 10.1, 10.2_

  - [x] 3.3 Update `frontend/src/pages/SettingsPage.tsx` to call the new humanizer
    - Replace the display of `schedule.humanReadable` with `humanize(schedule?.expression ?? '', t)`
    - Keep the existing fallback UI for `schedule.error` and the `"Schedule unavailable"` key (from the catalog — not the backend response)
    - _Requirements: 6.5, 7.3_

  - [x] 3.4 Update cron humanizer unit tests
    - Rewrite existing tests to pass a synthetic `t(key, vars)` that reads directly from a catalog object and applies `{{name}}` interpolation (avoids spinning up i18next)
    - Keep the existing pt-BR expected outputs (Requirement 8.3); add parallel en expected outputs
    - Cover: `rate(1 day)`, `rate(2 hours)`, `rate(5 minutes)`, `cron(59 23 * * ? *)`, `cron(0 12 ? * MON-FRI *)`, `cron(0 8 1 * ? *)`, unparsable inputs
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 8.3_

  - [x] 3.5 **Property 6**: cron humanizer locale coherence and fallback
    - **Property 6: Cron humanizer locale coherence — for parsable expressions, `humanize(E, tFor(L))` equals the template composed from `catalog[L]` applied to `parse(E)`; for unparsable `E`, `humanize(E, tFor(L)) == E`**
    - fast-check with arbitraries for each parsable pattern (`rate(N minutes)`, `rate(N hours)`, `rate(N days)`, `cron(M H * * ? *)`, `cron(M H ? * DOW *)`, `cron(M H D * ? *)`) × `fc.constantFrom('en', 'pt-BR')`; ≥ 300 runs
    - Separate run for unparsable expressions: `fc.string().filter(s => !isParsable(s))` × `fc.constantFrom('en', 'pt-BR')`; ≥ 200 runs; assert identity
    - Use `synthT(catalog)` helper from design section 6
    - **Validates: Requirements 6.1, 6.2, 6.3, 6.4, 16.6**
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 16.6_

  - [x] 3.6 Checkpoint — Step 3 complete
    - All cron tests pass with `locale = 'pt-BR'` producing byte-identical output to the previous version
    - Run `npm run build` and `npm run test`
    - Ensure all tests pass, ask the user if questions arise.

### Step 4 — Migrate page and component strings to t(key)

- [x] 4. Page and component i18n migration (pt-BR remains default; each commit leaves the tree green)
  - [x] 4.1 Migrate `frontend/src/App.tsx` navigation labels
    - Replace hardcoded `'Dashboard'`, `'Consumo da Conta'`, `'Usuários'`, `'Configurações'`, `'Feedbacks'`, `'Sair'`, and the `TopNavigation.identity.title` (use `brand.productName` — untranslated per Req. 9.1) with `t(key)` calls from `useI18n()`
    - Add the corresponding keys to `en.json` and `pt-BR.json`, sorted, non-empty
    - _Requirements: 1.3, 9.1, 9.2_

  - [x] 4.2 Migrate `frontend/src/pages/LoginPage.tsx`
    - Replace every hardcoded user-facing string with `t(key)` calls
    - Product name renders via `brand.productName` (untranslated across locales)
    - _Requirements: 1.3, 9.2_

  - [x] 4.3 Migrate `frontend/src/pages/ForgotPasswordPage.tsx`
    - Replace every hardcoded user-facing string with `t(key)` calls
    - _Requirements: 1.3_

  - [x] 4.4 Migrate `frontend/src/pages/NewPasswordPage.tsx`
    - Replace every hardcoded user-facing string with `t(key)` calls
    - _Requirements: 1.3_

  - [x] 4.5 Migrate `frontend/src/pages/ResetPasswordPage.tsx`
    - Replace every hardcoded user-facing string with `t(key)` calls
    - _Requirements: 1.3_

  - [x] 4.6 Migrate `frontend/src/pages/SignupPage.tsx`
    - Replace every hardcoded user-facing string with `t(key)` calls
    - _Requirements: 1.3_

  - [x] 4.7 Migrate `frontend/src/pages/DashboardPage.tsx`
    - Replace every hardcoded user-facing string with `t(key)` calls (headers, filters, empty states)
    - _Requirements: 1.3_

  - [x] 4.8 Migrate `frontend/src/pages/AccountUsagePage.tsx`
    - Replace every hardcoded user-facing string with `t(key)` calls
    - _Requirements: 1.3_

  - [x] 4.9 Migrate `frontend/src/pages/UserDetailPage.tsx`
    - Replace every hardcoded user-facing string with `t(key)` calls (including chart titles, tab labels)
    - _Requirements: 1.3_

  - [x] 4.10 Migrate `frontend/src/pages/UsersPage.tsx`
    - Replace every hardcoded user-facing string with `t(key)` calls (table columns, action buttons, empty state, error messages)
    - _Requirements: 1.3_

  - [x] 4.11 Migrate `frontend/src/pages/SettingsPage.tsx`
    - Replace every hardcoded user-facing string (form labels, descriptions, button text, placeholders, error messages, the `"Agendamento indisponível"` fallback → `settings.etl.schedule.unavailable` key) with `t(key)` calls
    - _Requirements: 1.3, 6.5_

  - [x] 4.12 Migrate `frontend/src/pages/FeedbackAdminPage.tsx`
    - Replace every hardcoded user-facing string with `t(key)` calls
    - _Requirements: 1.3_

  - [x] 4.13 Migrate `frontend/src/components/AccountSummaryCards.tsx`
    - Replace every hardcoded user-facing string (card titles, labels) with `t(key)` calls
    - _Requirements: 1.3_

  - [x] 4.14 Migrate `frontend/src/components/UserSummaryCards.tsx`
    - Replace every hardcoded user-facing string with `t(key)` calls
    - _Requirements: 1.3_

  - [x] 4.15 Migrate `frontend/src/components/SummaryCards.tsx`
    - Replace every hardcoded user-facing string with `t(key)` calls
    - _Requirements: 1.3_

  - [x] 4.16 Migrate `frontend/src/components/UsageTable.tsx`
    - Replace every hardcoded user-facing string (column headers, empty state, pagination labels) with `t(key)` calls
    - _Requirements: 1.3_

  - [x] 4.17 Migrate `frontend/src/components/RecentPromptsTable.tsx`
    - Replace every hardcoded user-facing string with `t(key)` calls
    - _Requirements: 1.3_

  - [x] 4.18 Migrate `frontend/src/components/PromptDetailPanel.tsx`
    - Replace every hardcoded user-facing string with `t(key)` calls
    - _Requirements: 1.3_

  - [x] 4.19 Migrate `frontend/src/components/FeedbackModal.tsx`
    - Replace every hardcoded user-facing string (title, form labels, error messages, submit text) with `t(key)` calls
    - _Requirements: 1.3, 11.3_

  - [x] 4.20 Migrate `frontend/src/components/DistributionCharts.tsx`
    - Replace every hardcoded user-facing string (chart titles, legend labels) with `t(key)` calls
    - _Requirements: 1.3_

  - [x] 4.21 Migrate `frontend/src/components/BreakdownCharts.tsx`
    - Replace every hardcoded user-facing string with `t(key)` calls
    - _Requirements: 1.3_

  - [x] 4.22 Migrate `frontend/src/components/DailyUsageChart.tsx`
    - Replace every hardcoded user-facing string with `t(key)` calls
    - _Requirements: 1.3_

  - [x] 4.23 Migrate `frontend/src/components/TimelineChart.tsx`
    - Replace every hardcoded user-facing string with `t(key)` calls
    - _Requirements: 1.3_

  - [x] 4.24 Migrate `frontend/src/components/LocalizedDateRangePicker.tsx`
    - Replace every hardcoded user-facing string with `t(key)` calls; continue passing `locale` to Cloudscape's native DatePicker props so native strings follow the Cloudscape I18nProvider
    - _Requirements: 1.3, 1.4_

  - [x] 4.25 Audit `frontend/src/components/SkeletonLoader.tsx` for user-visible strings
    - If any user-facing labels exist (e.g., loading hints), replace with `t(key)`. Otherwise, mark this task done with a no-op note.
    - _Requirements: 1.3_

  - [x] 4.26 Audit `frontend/src/hooks/useLastUpdated.ts` and `frontend/src/hooks/useSplitPanel.tsx` for user-visible strings
    - Replace any user-facing strings with `t(key)`; otherwise mark done
    - _Requirements: 1.3_

  - [x] 4.27 **Property 7**: catalog key parity
    - **Property 7: Catalog key parity — `keys(en.json) == keys(pt-BR.json)` as sets**
    - Vitest assertion that the symmetric difference of the two key sets is empty; also enforced at build time by `scripts/check-locales.ts`
    - **Validates: Requirements 10.1, 16.7**
    - _Requirements: 10.1, 16.7_

  - [x] 4.28 **Property 8**: no empty translations
    - **Property 8: No empty translations — every `(locale, key)` resolves to a non-empty string**
    - Iterate both catalogs and assert `typeof v === 'string'` and `v.length > 0`; also enforced at build time
    - **Validates: Requirements 10.2, 16.8**
    - _Requirements: 10.2, 16.8_

  - [x] 4.29 **Property 9**: missing-key fallback
    - **Property 9: Missing-key fallback — for every key missing from the active locale but present in en, `t(k)` equals `catalog['en'][k]`**
    - fast-check async property using `fc.subarray(Object.keys(enCatalog), { minLength: 1 })` as the hole set; seed a fresh `i18next.createInstance()` with a partial pt-BR catalog and the full en catalog; assert every holed key resolves to the en value; ≥ 100 runs
    - **Validates: Requirements 10.3, 16.9**
    - _Requirements: 10.3, 16.9_

  - [x] 4.30 **Property 10**: brand invariance
    - **Property 10: Brand invariance — for every locale and every brand key, the value equals the canonical brand literal (`"Kiro Cost Analyzer"` / `"Kiro"`)**
    - Combine `test.each` concrete assertion with a fast-check property over `fc.constantFrom(...SUPPORTED_LOCALES)` × `fc.constantFrom(...Object.keys(BRAND_STRINGS))`; ≥ 100 runs
    - **Validates: Requirements 9.1, 9.2, 16.10**
    - _Requirements: 9.1, 9.2, 16.10_

  - [x] 4.31 pt-BR snapshot regression tests — scoped to translated text
    - One vitest snapshot test per major page (`LoginPage`, `DashboardPage`, `AccountUsagePage`, `UserDetailPage`, `UsersPage`, `SettingsPage`, `FeedbackAdminPage`) rendering with `locale = 'pt-BR'`
    - Scope snapshots to translated-text content (e.g., `container.textContent` or filtered node queries), not the full DOM tree, to stay robust against Cloudscape internal DOM churn
    - Snapshots must match the pre-Step-4 baseline byte-for-byte for translated strings
    - _Requirements: 8.1, 8.2_

  - [ ]* 4.32 Unit tests for migrated pages/components (optional)
    - Smoke tests that assert the correct `t` key is invoked and rendered text matches the expected catalog value under each locale
    - _Requirements: 1.3_

  - [x] 4.33 Checkpoint — Step 4 complete
    - `scripts/check-locales.ts` passes — no divergent keys, no empty values, files sorted
    - All pt-BR snapshot tests pass
    - Run `npm run build` and `npm run test`
    - Ensure all tests pass, ask the user if questions arise.

### Step 5 — Add the LanguageSwitcher to TopNavigation

- [x] 5. Build and wire the language switcher
  - [x] 5.1 Create `frontend/src/components/LanguageSwitcher.tsx`
    - Use Cloudscape `ButtonDropdown` with items derived from `SUPPORTED_LOCALES`
    - Option labels from a `LOCALE_LABELS` map in the target language (`'en'` → `"English"`, `'pt-BR'` → `"Português (Brasil)"`); keep `lang="pt-BR"` on the pt-BR option's text node
    - Mark the active option with `iconName: 'check'`
    - `ariaLabel` resolves from `t('common.languageSwitcher.ariaLabel')`
    - `onItemClick` calls `setLocale(detail.id as SupportedLocale)`
    - _Requirements: 3.1, 3.2, 3.5, 14.1, 14.2, 14.3_

  - [x] 5.2 Wire `LanguageSwitcher` into `App.tsx` `TopNavigation`
    - Add the switcher to `TopNavigation.utilities` — either as a sibling utility to the user menu or using the `type: 'button'` shape with the switcher as its rendered node; placement is the implementation detail, the contract is "reachable, keyboard-accessible, labeled"
    - Ensure the switcher is rendered for both authenticated and unauthenticated users (so users on `LoginPage` can switch locale)
    - _Requirements: 3.1, 14.1_

  - [x] 5.3 Unit tests for `LanguageSwitcher`
    - Renders both options with the correct target-language labels
    - Active option receives the `check` icon
    - `aria-label` reflects the active locale (`"Language"` in en, `"Idioma"` in pt-BR)
    - `Tab` reaches the trigger; `Enter` / `Space` open it; `Enter` / `Space` on an item invokes `setLocale` identically to mouse click
    - _Requirements: 3.1, 3.2, 3.5, 14.1, 14.2, 14.3, 14.4, 14.5_

  - [x] 5.4 **Property 2**: preference round-trip
    - **Property 2: Preference round-trip — setting `L` via `setLocale` and then simulating a restart yields `Active_Locale = L`**
    - fast-check over `fc.constantFrom<SupportedLocale>('en', 'pt-BR')`; arrange with an in-memory storage implementation and a fresh resolver invocation; ≥ 100 runs
    - **Validates: Requirements 3.2, 4.1, 4.2, 16.2**
    - _Requirements: 3.2, 4.1, 4.2, 16.2_

  - [x] 5.5 **Property 3**: state preservation under locale switch
    - **Property 3: State preservation — for any application-state snapshot `S` and any locale `L`, switching the active locale leaves `S` byte-identical before and after**
    - fast-check over a `stateArb` record (`dateRange`, `pageSize`, `pageIndex`, `sortingField`, `filterValue`, `selectedRowId`, `splitPanelOpen`) × `fc.constantFrom('en', 'pt-BR')`; assert JSON-equal via `structuredClone` of the snapshot before and after applying a pure reducer that handles `{ type: 'SET_LOCALE', locale }` as a no-op; ≥ 200 runs
    - **Validates: Requirements 3.4, 11.1, 11.3, 16.3**
    - _Requirements: 3.4, 11.1, 11.3, 16.3_

  - [x] 5.6 Integration tests for locale switching
    - State preservation end-to-end: render `DashboardPage` with a non-default date range, sort a table, switch locale, assert (a) the date range is unchanged, (b) the sort indicator is still on the same column, (c) translated column headers changed
    - In-flight request across switch: mock a delayed `GET /api/usage`, switch locale while pending, resolve the promise, assert the rendered response uses the new-locale formatters
    - Modal open across switch: open `FeedbackModal`, switch locale, assert the modal is still open with updated labels
    - _Requirements: 11.1, 11.2, 11.3_

  - [x] 5.7 Checkpoint — Step 5 complete
    - Switcher works end-to-end under the current `pt-BR` default
    - All integration tests pass
    - Run `npm run build` and `npm run test`
    - Ensure all tests pass, ask the user if questions arise.

### Step 6 — Flip the default locale from pt-BR to English

- [x] 6. Flip `DEFAULT_LOCALE` to `'en'` (the single step that changes default behavior for new users)
  - [x] 6.1 Verify Step-2 through Step-5 migration completeness before flipping
    - Search the codebase for any remaining `'pt-BR'` literal outside `src/i18n/constants.ts`, `src/locales/pt-BR.json`, and locale labels — there should be none in formatters or display strings
    - Confirm pt-BR snapshot tests are still green
    - _Requirements: 8.2_

  - [x] 6.2 Update `frontend/src/i18n/constants.ts` to set `DEFAULT_LOCALE = 'en'`
    - This is a one-line change; the resolution chain continues to honor `navigator.language`, so Brazilian browsers still resolve to pt-BR on first visit
    - _Requirements: 2.2, 2.6_

  - [x] 6.3 Add explicit tests for every branch of the resolution chain after the flip
    - Stored `'en'` → active `'en'`; stored `'pt-BR'` → active `'pt-BR'`; stored invalid → navigator fallback path
    - Navigator `'en-US'`, `'en-GB'`, `'pt-BR'`, `'pt-br'`, `'pt'`, `'pt-PT'`, `'fr-FR'`, `undefined` — assert expected resolution
    - Verify that when stored is invalid, the resolved locale is persisted back to `localStorage` (Requirement 2.4)
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5_

  - [x] 6.4 Checkpoint — Step 6 complete
    - A fresh browser (no `kiro_locale` in storage) with `navigator.language = 'en-US'` renders in English
    - A fresh browser with `navigator.language = 'pt-BR'` still renders in pt-BR
    - A fresh browser with `navigator.language = 'fr-FR'` renders in English (the intended default change)
    - pt-BR snapshot tests still pass (by explicitly setting `kiro_locale` to `'pt-BR'` before render)
    - Run `npm run build` and `npm run test`
    - Ensure all tests pass, ask the user if questions arise.

### Step 7 — Backend handler migration

- [x] 7. Replace every pt-BR user-facing string in `backend/handlers/**` with English equivalents
  - [x] 7.1 Migrate `backend/handlers/config_handler.py`
    - Replace `"Bucket acessível e configuração salva com sucesso"` → `"Bucket is accessible and configuration saved successfully"`
    - Replace `"Prompts prefix salvo com sucesso"` → `"Prompts prefix saved successfully"`
    - Replace `"Identity Store ID salvo com sucesso"` → `"Identity Store ID saved successfully"`
    - Replace `"Formato de ARN inválido. Esperado: arn:aws:iam::<account-id>:role/<role-name>"` → `"Invalid ARN format. Expected: arn:aws:iam::<account-id>:role/<role-name>"`
    - Replace `"Source bucket role ARN salvo com sucesso"` → `"Source bucket role ARN saved successfully"`
    - Replace `"Modo cross-account desabilitado"` → `"Cross-account mode disabled"`
    - Replace `"Agendamento indisponível"` → `"Schedule unavailable"`
    - Rewrite `_humanize_schedule` to emit English: `"Every day"` for `rate(1 day)` and `cron(... daily)` patterns, `"Every N hours"`, `"Every N minutes"`, `"Every day at HH:MM"`
    - Keep all stable machine codes (`status: "error"`, `status: "valid"`) unchanged
    - _Requirements: 7.1, 7.2, 7.4, 7.5_

  - [x] 7.2 Migrate `backend/handlers/feedback_handler.py`
    - Replace `"Prompt com requestId '{}' não encontrado"` → `"Prompt with requestId '{}' not found"`
    - Replace `"A categoria sugerida deve ser diferente da categoria atual"` → `"The suggested category must differ from the current category"`
    - Replace `"Já existe uma correção pendente para este prompt"` → `"A pending correction already exists for this prompt"`
    - Replace `"Feedback enviado com sucesso"` → `"Feedback submitted successfully"`
    - Replace `"Ação inválida. Use 'approve' ou 'reject'"` → `"Invalid action. Use 'approve' or 'reject'"`
    - Replace `"Feedback não encontrado"` → `"Feedback not found"`
    - Replace `"Este feedback já foi revisado"` → `"This feedback has already been reviewed"`
    - Replace `"Feedback revisado com sucesso"` → `"Feedback reviewed successfully"`
    - Replace `"Categoria inválida. Categorias válidas: ..."` → `"Invalid category. Valid categories: ..."`
    - Keep all machine error codes (`"NotFound"`, `"Conflict"`, `"InvalidCategory"`, `"SameCategory"`, `"AlreadyReviewed"`, `"InvalidAction"`) unchanged
    - _Requirements: 7.1, 7.4, 7.5_

  - [x] 7.3 Migrate `backend/handlers/prompts_handler.py`
    - Replace `"O parâmetro userId é obrigatório para listagem de prompts"` → `"The userId query parameter is required to list prompts"`
    - Replace `"Prompt com requestId '{}' não encontrado"` → `"Prompt with requestId '{}' not found"`
    - Replace `"Conteúdo do prompt '{}' não encontrado no S3"` → `"Prompt content for '{}' not found in S3"`
    - Keep `"InvalidParameters"`, `"NotFound"` error slugs unchanged
    - _Requirements: 7.1, 7.4, 7.5_

  - [x] 7.4 Migrate `backend/handlers/users_handler.py`
    - Replace both `"Usuário '{}' não encontrado"` occurrences → `"User '{}' not found"`
    - Replace `"Você não pode alterar seu próprio papel."` → `"You cannot change your own role."`
    - Replace `"Você não pode excluir sua própria conta."` → `"You cannot delete your own account."`
    - Keep error codes (`"error"`, `"updated"`, `"deleted"`) unchanged
    - _Requirements: 7.1, 7.4, 7.5_

  - [x] 7.5 Add banned-strings regression test for backend handlers
    - In `tests/`, create or extend a test module (e.g., `tests/test_backend_english_only.py`)
    - For every handler response under `backend/handlers/`, assert that every human-readable field (`message`, `description`, `humanReadable`, etc.) matches `^[\x00-\x7f]+$` (ASCII) and does not contain the case-insensitive substrings `"sucesso"`, `"não"`, `"usuário"`, `"inválido"`, `"acessível"`, `"obrigatório"`, `"agendamento"`, `"desabilitado"`, `"salvo"`, `"habilitado"`, `"indisponível"`
    - Use moto to mock AWS calls where needed
    - _Requirements: 7.1, 7.4_

  - [x] 7.6 Unit tests for `_humanize_schedule` English outputs
    - Cover `rate(1 day)` → `"Every day"`; `rate(2 hours)` → `"Every 2 hours"`; `rate(5 minutes)` → `"Every 5 minutes"`; `cron(59 23 * * ? *)` → `"Every day at 23:59"`; unparsable → returns the raw expression
    - _Requirements: 7.2_

  - [ ]* 7.7 Handler-level unit tests for migrated messages (optional extension of existing coverage)
    - For each handler, add explicit assertions that the English replacement strings appear in responses for their corresponding code paths
    - _Requirements: 7.1, 7.5_

  - [x] 7.8 Checkpoint — Step 7 complete
    - Run `python -m pytest tests/ -v` — all tests pass, including the new banned-strings test
    - Frontend continues to function (backend response shape is unchanged; only prose changed)
    - Ensure all tests pass, ask the user if questions arise.

### Step 8 — Documentation migration

- [x] 8. README migration and steering-file verification
  - [x] 8.1 Rename the current README to `README.pt-BR.md`
    - Run `git mv README.md README.pt-BR.md`
    - Add a cross-link at the top of `README.pt-BR.md` back to `README.md` under a heading such as "Other languages" / "Outros idiomas"
    - _Requirements: 12.2_

  - [x] 8.2 Create the new English `README.md`
    - Mirror every section, diagram, table, and command-line snippet from `README.pt-BR.md`
    - Translate prose to English; leave command-line snippets, CloudFormation keys, YAML/JSON identifiers, and DynamoDB PK/SK examples unchanged
    - Preserve the Mermaid architecture diagram, the ETL sequence diagram, the Step Functions pipeline table, the DynamoDB schema tables, the deploy instructions, the Makefile reference table, the estimated cost table, and the changelog
    - Add a cross-link to `README.pt-BR.md` under a heading such as "Other languages"
    - _Requirements: 12.1, 12.3, 12.4_

  - [x] 8.3 Verify `.kiro/steering/development-standards.md` reflects all design decisions
    - Confirm section 2.3 declares English as the default language for UI text and top-level documentation (Requirement 13.1)
    - Confirm section 2.3 retains the rule that code, variable names, function names, docstrings, and technical comments are written in English (Requirement 13.2)
    - Confirm section 4.2 documents the i18n file structure, flat dot-notation key convention, identical key sets requirement, `{{name}}` interpolation, and the locale resolution chain (Requirement 13.3)
    - Confirm section 4.2 "Adding a new locale" subsection documents the steps (Requirement 13.4)
    - Confirm section 4.2 references `.kiro/specs/i18n-english-default/` as the authoritative source (Requirement 13.5)
    - Apply any final polish or cross-reference fixes that emerged during implementation
    - _Requirements: 13.1, 13.2, 13.3, 13.4, 13.5_

  - [x] 8.4 Checkpoint — Step 8 complete
    - Manual read-through of both READMEs; verify both cross-links resolve
    - Verify diagrams render correctly in `README.md` (GitHub Mermaid rendering)
    - Ensure all tests pass, ask the user if questions arise.

### Step 9 — i18n bundle-size observability

- [x] 9. Report-only bundle-size observability (no CI gate)
  - [x] 9.1 Create `scripts/report-i18n-sizes.js`
    - Read `frontend/dist/.vite/manifest.json` and the on-disk chunk files under `frontend/dist/assets/`
    - Identify i18n-relevant chunks: `i18next`, `react-i18next`, `i18next-resources-to-backend`, each locale catalog (`en.json`-derived initial inline + `pt-BR.json` dynamic chunk), and the Cloudscape i18n message bundles if they appear as separate chunks
    - Gzip each chunk (Node `zlib.gzipSync`) and print a summary table (name, raw bytes, gzipped bytes)
    - Always exit `0`; output is informational
    - _Requirements: 15.3, 15.4_

  - [x] 9.2 Wire the report into the build output
    - Add `"report:i18n-sizes": "node scripts/report-i18n-sizes.js"` to `frontend/package.json` scripts
    - Optionally chain it after `vite build` in the `build` script so `npm run build` prints the table automatically (script still exits 0 on any issue)
    - _Requirements: 15.3, 15.4_

  - [x] 9.3 Checkpoint — Step 9 complete
    - `npm run build` prints the i18n-sizes table
    - No CI gate is introduced (Requirement 15.4 — observed, not gated)
    - Ensure all tests pass, ask the user if questions arise.

### Final validation

- [x] 10. Full-project validation
  - [x] 10.1 Run the full Python test suite
    - `python -m pytest tests/ -v`
    - Assert every test passes, including the banned-strings regression
    - _Requirements: 7.1, 7.4_

  - [x] 10.2 Run the full frontend test suite
    - From `frontend/`, run `npm run test`
    - Assert every unit test, property-based test, snapshot test, and integration test passes
    - _Requirements: 1.1, 5.1, 6.1, 10.1, 10.2, 11.1, 16.1–16.10_

  - [x] 10.3 Run the build and key-parity check
    - From `frontend/`, run `npm run check:locales` standalone and then `npm run build`
    - Confirm no divergent keys, no empty values, alphabetical sort, and that `tsc -b` + `vite build` succeed
    - Confirm the i18n-sizes report is printed
    - _Requirements: 10.5, 15.3_

  - [x] 10.4 Run diagnostics on the migrated files
    - Verify no TypeScript or linter regressions in `frontend/src/**` and `backend/handlers/**`
    - _Requirements: 1.3_

  - [x] 10.5 Final checkpoint — ensure all tests pass
    - Confirm no regressions; all ten Correctness Properties pass; pt-BR snapshots are byte-identical where required (Requirement 8)
    - Ensure all tests pass, ask the user if questions arise.

### Step 11 — User settings menu (post-MVP)

This step refactors the standalone `LanguageSwitcher` in the top bar into a unified "User settings" gear-icon menu (modeled after the AWS Console), hosting both the language selector and a new Light/Dark/Browser-default theme selector. Fixes the pre-existing overlap between the absolute-positioned `LanguageSwitcher` and the user-email dropdown in the `TopNavigation`.

- [x] 11. Build the user settings menu with language + visual-mode sections
  - [x] 11.1 Add `userSettings.*` keys to both locale catalogs
    - `userSettings.title`, `userSettings.description`, `userSettings.openAriaLabel`, `userSettings.close`
    - `userSettings.language.label`
    - `userSettings.visualMode.label`, `.browserDefault`, `.browserDefaultDescription`, `.light`, `.lightDescription`, `.dark`, `.darkDescription`
    - Sorted alphabetically; non-empty strings; pt-BR values for all 13 keys
    - _Requirements: 17.1, 17.3, 17.7, 17.10_

  - [x] 11.2 Create the `src/theme/` module
    - `constants.ts`: `THEME_STORAGE_KEY = "kiro_theme"`, `DEFAULT_VISUAL_MODE = "dark"` (preserves pre-feature behavior)
    - `types.ts`: `VisualMode = "browser-default" | "light" | "dark"`, `ResolvedMode = "light" | "dark"`, `SUPPORTED_VISUAL_MODES`
    - `persistence.ts`: `readStoredVisualMode`, `persistVisualMode` with try/catch + single-warn-per-session dedup
    - `resolveVisualMode.ts`: pure `resolveInitialVisualMode(stored)` and `resolveToCloudscapeMode(mode)` (consults `matchMedia('(prefers-color-scheme: dark)')` for `'browser-default'`)
    - _Requirements: 17.11, 17.12, 17.13, 17.14, 17.15, 18.1_

  - [x] 11.3 Create `ThemeProvider` and `useTheme` hook
    - `ThemeContext.ts` in its own file so `ThemeProvider.tsx` only exports components (react-refresh/only-export-components rule)
    - `ThemeProvider.tsx`: resolves initial `VisualMode` on mount, applies Cloudscape `Mode` via `applyMode`, subscribes to `matchMedia` change events when `VisualMode = "browser-default"`
    - `useTheme()` hook throws when called outside the provider
    - _Requirements: 17.11, 17.12, 17.14_

  - [x] 11.4 Wire `ThemeProvider` into `main.tsx`
    - Place `<ThemeProvider>` inside `<I18nProvider>` and outside `<BrowserRouter>`
    - Remove the static `applyMode(Mode.Dark)` call from `main.tsx` — `ThemeProvider` applies the mode on first render
    - _Requirements: 17.12_

  - [x] 11.5 Create `UserSettingsModal` component
    - Header: `t('userSettings.title')`; footer: primary Close button; `closeAriaLabel` from the catalog
    - "Language" section: `FormField` + `RadioGroup` with items from `SUPPORTED_LOCALES`, labels from `LOCALE_LABELS` (self-referential, e.g. `"English"`, `"Português (Brasil)"`), `value = locale`, `onChange` calls `setLocale`
    - "Visual mode" section: `FormField` + `RadioGroup` with three items (`browser-default`, `light`, `dark`), labels and descriptions from the catalog, `value = visualMode`, `onChange` calls `setVisualMode`
    - Hidden `<span lang="pt-BR">` for AT phonetics on the non-active option
    - _Requirements: 17.4, 17.7, 17.8, 17.9, 17.10, 17.11_

  - [x] 11.6 Create `UserSettingsMenu` hook-based descriptor
    - Export `useUserSettingsMenu()` returning `{ utility, modalNode }`
    - `utility` is a `TopNavigationProps.Utility` of `type: 'button'` with `iconName: 'settings'`, `ariaLabel` from `userSettings.openAriaLabel`, `onClick` sets local open state to `true`
    - `modalNode` is the rendered `<UserSettingsModal>` bound to the same open state
    - _Requirements: 17.1, 17.2, 17.3, 17.5_

  - [x] 11.7 Refactor `App.tsx` to use the settings menu
    - Import `useUserSettingsMenu`; call it once at the top of `AppContent`
    - Unauthenticated branch: `TopNavigation` with `utilities={[settingsMenu.utility]}`; render `settingsMenu.modalNode` as sibling
    - Authenticated branch: `TopNavigation` with `utilities={[settingsMenu.utility, userEmailDropdown]}`; render `settingsMenu.modalNode` as sibling
    - Remove the standalone `<LanguageSwitcher>` and its absolute-positioned wrapper from `App.tsx`
    - _Requirements: 17.1, 17.2, 17.6_

  - [x] 11.8 Unit tests for `resolveInitialVisualMode` and `resolveToCloudscapeMode`
    - Every branch: stored `"light"`, `"dark"`, `"browser-default"`, `null`, `""`, `"solarized"`, `"LIGHT"`
    - `resolveToCloudscapeMode`: `"light"` → `"light"`, `"dark"` → `"dark"`, `"browser-default"` → derived from `matchMedia`
    - Stub `window.matchMedia` to cover both `matches: true` and `matches: false` branches plus the missing-matchMedia fallback
    - _Requirements: 17.11, 18.1_

  - [x] 11.9 Unit tests for `theme/persistence.ts`
    - Happy-path round-trip for each `VisualMode`
    - `setItem` throwing → swallowed; `console.warn` emitted once per session
    - Mirror the structure of `i18n/persistence.test.ts`
    - _Requirements: 17.11, 17.15_

  - [x] 11.10 Integration tests for `UserSettingsModal`
    - Renders header, description, language options, and visual-mode options in the active locale
    - Switching the language radio to `"pt-BR"` calls `setLocale` and updates `i18n.language`
    - Switching the visual mode to `"light"` persists `"light"` under `THEME_STORAGE_KEY`
    - Footer Close button invokes `onDismiss`
    - _Requirements: 17.3, 17.4, 17.7, 17.9, 17.11, 17.15_

  - [ ]* 11.11 **Property 11**: visual-mode resolution totality
    - **Property 11**: `resolveInitialVisualMode(s)` is total over `(string | null)` and always returns a member of `{ "browser-default", "light", "dark" }`
    - fast-check over `fc.oneof(fc.constant(null), fc.string())`; ≥ 200 runs
    - **Validates: Requirement 18.1**
    - _Requirements: 18.1_

  - [ ]* 11.12 **Property 12**: visual-mode preference round-trip
    - **Property 12**: for every `V ∈ { "browser-default", "light", "dark" }`, persisting `V` and restarting yields `Visual_Mode = V`
    - fast-check over the three supported modes using an in-memory `Map` as storage; ≥ 100 runs
    - **Validates: Requirement 18.2**
    - _Requirements: 18.2_

  - [x] 11.13 Checkpoint — Step 11 complete
    - `npm run check:locales` — 13 new `userSettings.*` keys; parity verified
    - `npm run test` — all unit, property, and integration tests pass (pre-Step-11 118 + new `UserSettingsModal` + theme tests)
    - `npm run build` — clean build, no new TypeScript regressions
    - Visually verify: the gear icon opens the modal; selecting a language flips the UI in place; selecting a visual mode flips the Cloudscape theme; the email dropdown is no longer overlapped
    - _Requirements: 17.1–17.15_

## Notes

- Sub-tasks marked with `*` are optional and can be skipped for a fast MVP. The ten Correctness Properties (Property 1 through Property 10) are REQUIRED and never marked optional — they are the core correctness guarantee.
- Each task references specific requirement clauses for traceability.
- Each migration step ends with a checkpoint that validates the step is independently deployable and keeps `main` green.
- The pt-BR experience remains byte-identical through Step 5; Step 6 is the single step that changes default behavior for new users.
- Property-based tests run ≥ 100 iterations (≥ 200 for numeric/temporal inputs, ≥ 300 for cron, ≥ 500 for resolution totality) per the project standard.
- This workflow produces design and planning artifacts only. To begin implementation, open `tasks.md` and click "Start task" next to a task item.
