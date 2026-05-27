# Requirements Document — i18n and English as Default Locale

## Introduction

This feature introduces an internationalization (i18n) layer in the Kiro Cost Analyzer (KCA) frontend and flips the default UI language from Brazilian Portuguese (pt-BR) to English (en), so the project can be published under `aws-samples` and reach a broader audience. Brazilian Portuguese is preserved as a first-class, supported locale.

Today, every user-facing string, every number formatted via `toLocaleString('pt-BR')`, every date formatted via `toLocaleDateString('pt-BR')` / `toLocaleTimeString('pt-BR')`, and the `cronHumanizer.ts` output are hardcoded to pt-BR. The project steering file (`.kiro/steering/development-standards.md`, section 2.3 and 4.2) currently mandates pt-BR for the UI. This feature changes that convention.

Scope: the React/Cloudscape/TypeScript frontend, the top-level documentation (README), the steering file, and a narrow backend change that makes backend-returned user-facing strings English-only. A full `Accept-Language`-driven backend is out of scope.

GitHub issue: `#12 — Make KCA speak English (i18n + English as default locale)`.

## Glossary

- **KCA**: Kiro Cost Analyzer, the product (brand name, not translated).
- **Supported_Locales**: The finite set `{"en", "pt-BR"}`. "en" is the default.
- **Active_Locale**: The locale currently selected by the application, drawn from `Supported_Locales`.
- **Default_Locale**: The fallback locale used when no user preference exists and the browser language is unsupported. Its value is `"en"`.
- **Locale_Storage_Key**: The `localStorage` key `kiro_locale` used to persist the user's locale preference.
- **Locale_Resolution_Chain**: The deterministic algorithm that computes the initial `Active_Locale`: `localStorage.kiro_locale` → `navigator.language` (normalized to a supported locale when possible) → `Default_Locale`.
- **Locale_Catalogs**: Two JSON files, `frontend/src/locales/en.json` and `frontend/src/locales/pt-BR.json`, each mapping translation keys to strings for its locale.
- **Translation_Key**: A stable identifier (dot-notation, e.g. `dashboard.header.title`) used in code in place of hardcoded strings.
- **I18n_Provider**: The frontend React context that exposes the `Active_Locale`, the `t(key, vars?)` translator, the locale setter, and the locale-aware formatters for numbers, dates, times, and cron expressions.
- **Language_Switcher**: The control in the top navigation that lets the user change the `Active_Locale` and persists the choice to `Locale_Storage_Key`.
- **Cloudscape_I18nProvider**: The `@cloudscape-design/components/i18n` provider that localizes Cloudscape native component strings (e.g. DatePicker, Table empty state).
- **Locale_Aware_Formatter**: A set of helpers (`formatNumber`, `formatDate`, `formatTime`, `formatDateTime`) driven by `Active_Locale`, replacing all direct calls to `toLocaleString('pt-BR')`, `toLocaleDateString('pt-BR')`, and `toLocaleTimeString('pt-BR')`.
- **Cron_Humanizer**: The module `frontend/src/utils/cronHumanizer.ts`, converted from pt-BR-only to locale-aware using `Locale_Catalogs`.
- **Backend_User_Strings**: User-facing strings returned in API responses, including validation messages, operator messages, and the humanized schedule in `GET /api/config/schedule`.
- **Steering_File**: `.kiro/steering/development-standards.md`, which documents project conventions.
- **Readme_Files**: `README.md` (the root English README after this feature) and `README.pt-BR.md` (the preserved Portuguese translation).
- **Missing_Key_Fallback**: The behavior where a `Translation_Key` that is absent from the `Active_Locale` catalog resolves to the value from the `en` catalog.
- **Brand_Strings**: The set of strings that must not be translated, at minimum: `"Kiro Cost Analyzer"`, `"Kiro"`, `"AWS"`, and any product-name usage.

## Requirements

### Requirement 1: Introduce an i18n layer and locale catalogs

**User Story:** As an open-source contributor, I want a single source of truth for all UI strings, so that I can add a new locale without hunting strings across the codebase.

#### Acceptance Criteria

1. THE Frontend SHALL introduce an `I18n_Provider` that exposes the `Active_Locale`, a translator function `t(key, vars?)`, a locale setter, and the `Locale_Aware_Formatter` helpers.
2. THE Frontend SHALL ship exactly two `Locale_Catalogs` at `frontend/src/locales/en.json` and `frontend/src/locales/pt-BR.json`, populated with translations for every user-facing string currently rendered in `frontend/src`.
3. THE Frontend SHALL remove every hardcoded pt-BR user-facing string from `frontend/src/pages/**`, `frontend/src/components/**`, and `frontend/src/hooks/**`, replacing each occurrence with a call to `t(key)` resolved against the `Locale_Catalogs`.
4. THE Frontend SHALL wrap the application root with the `Cloudscape_I18nProvider` bound to the `Active_Locale`, so Cloudscape native component strings follow the selected locale.
5. WHERE a new locale is added, THE Frontend SHALL require only a new JSON file under `frontend/src/locales/` and its registration in the `I18n_Provider`, with no changes to page or component code.
6. WHEN the `I18n_Provider` initializes, THE I18n_Provider SHALL lazy-load the JSON catalog for the `Active_Locale` via dynamic import, so non-active locales are not shipped in the initial bundle.

### Requirement 2: Default to English with a deterministic resolution chain

**User Story:** As an English-speaking admin, I want the UI in English by default, so that I can use KCA without translation on my first visit.

#### Acceptance Criteria

1. WHEN the application boots and no value is stored under `Locale_Storage_Key`, THE I18n_Provider SHALL resolve the `Active_Locale` by applying the `Locale_Resolution_Chain` in order and selecting the first entry that yields a locale in `Supported_Locales`.
2. WHEN the application boots and no value is stored under `Locale_Storage_Key` and `navigator.language` is absent or does not match any locale in `Supported_Locales`, THE I18n_Provider SHALL set the `Active_Locale` to `Default_Locale`.
3. WHEN the application boots and a value `v` exists under `Locale_Storage_Key` such that `v ∈ Supported_Locales`, THE I18n_Provider SHALL set the `Active_Locale` to `v`.
4. IF a value `v` exists under `Locale_Storage_Key` such that `v ∉ Supported_Locales`, THEN THE I18n_Provider SHALL ignore `v`, continue the `Locale_Resolution_Chain`, and overwrite `Locale_Storage_Key` with the resolved `Active_Locale`.
5. THE I18n_Provider SHALL normalize `navigator.language` by matching the BCP-47 primary subtag case-insensitively, so `"en"`, `"en-US"`, and `"en-GB"` all resolve to `"en"`, and `"pt-BR"`, `"pt-br"`, and `"pt"` all resolve to `"pt-BR"`.
6. THE I18n_Provider SHALL expose the resolved `Active_Locale` synchronously to all components on first render, so no component ever renders with an undefined locale.

### Requirement 3: Language switcher in the top navigation

**User Story:** As a Brazilian admin, I want to switch to pt-BR in one click, so that my team keeps the current experience.

#### Acceptance Criteria

1. THE Frontend SHALL render a `Language_Switcher` control in the top navigation that lists every locale in `Supported_Locales`.
2. WHEN the user selects a locale `L` in the `Language_Switcher`, THE I18n_Provider SHALL set the `Active_Locale` to `L` and persist `L` to `Locale_Storage_Key` in the same synchronous operation.
3. WHEN the `Active_Locale` changes, THE Frontend SHALL re-render all components bound to the `I18n_Provider` so every visible translated string, number, date, and time reflects the new `Active_Locale` without a full page reload.
4. WHEN the `Active_Locale` changes, THE Frontend SHALL preserve the current application state, including active filters, selected date range, table pagination index, table sorting state, selected user or row, open split panels, and form input values.
5. THE `Language_Switcher` SHALL be reachable by keyboard and expose an accessible name identifying it as a language control in the `Active_Locale`.

### Requirement 4: Persistence across reloads and sessions

**User Story:** As a returning user, I want the UI to remember my language choice, so that I do not need to select it again on every visit.

#### Acceptance Criteria

1. WHEN the user selects a locale `L` in the `Language_Switcher`, THE I18n_Provider SHALL write `L` to `Locale_Storage_Key` before the re-render completes.
2. WHEN the application is reloaded in the same browser profile, THE I18n_Provider SHALL recover the previously selected locale from `Locale_Storage_Key` and use it as the `Active_Locale`, subject to the validation rule in Requirement 2.4.
3. IF `localStorage` is unavailable, THEN THE I18n_Provider SHALL fall back to in-memory state and SHALL log one structured warning on the browser console identifying the unavailability, without throwing.

### Requirement 5: Locale-aware formatting (numbers, dates, times)

**User Story:** As any user, I want numbers and dates to match the locale I selected, so that reports are readable in my conventions.

#### Acceptance Criteria

1. THE Frontend SHALL provide `formatNumber(value, options?)`, `formatDate(value, options?)`, `formatTime(value, options?)`, and `formatDateTime(value, options?)` helpers that delegate to `Intl.NumberFormat` and `Intl.DateTimeFormat` using the `Active_Locale`.
2. THE Frontend SHALL replace every direct call to `toLocaleString('pt-BR')`, `toLocaleDateString('pt-BR')`, and `toLocaleTimeString('pt-BR')` in `frontend/src/**` with a call to the corresponding `Locale_Aware_Formatter`.
3. WHILE the `Active_Locale` is `"en"`, THE Locale_Aware_Formatter SHALL format numbers, dates, and times using the `"en"` conventions for every render.
4. WHILE the `Active_Locale` is `"pt-BR"`, THE Locale_Aware_Formatter SHALL format numbers, dates, and times using the `"pt-BR"` conventions for every render.
5. WHEN the `Active_Locale` changes, THE Locale_Aware_Formatter SHALL produce outputs that match the new locale in all subsequent renders, with no residual pt-BR formatting appearing under `"en"` and no residual en formatting appearing under `"pt-BR"`.

### Requirement 6: Locale-aware cron humanizer

**User Story:** As any user, I want the ETL schedule description to appear in my selected language, so that the Settings page is fully translated.

#### Acceptance Criteria

1. THE Cron_Humanizer SHALL accept `(expression, locale)` and SHALL return the humanized text in the given `locale`, drawing day names, connectives, and templates from the `Locale_Catalogs`.
2. WHEN the Cron_Humanizer is invoked with `expression = "cron(59 23 * * ? *)"` and `locale = "en"`, THE Cron_Humanizer SHALL return the English equivalent of "Every day at 23:59" as defined in `en.json`.
3. WHEN the Cron_Humanizer is invoked with `expression = "cron(59 23 * * ? *)"` and `locale = "pt-BR"`, THE Cron_Humanizer SHALL return "Todos os dias às 23:59" to preserve the current pt-BR output.
4. IF the Cron_Humanizer cannot parse `expression`, THEN THE Cron_Humanizer SHALL return `expression` unchanged, irrespective of `locale`.
5. THE SettingsPage SHALL call the Cron_Humanizer with the `Active_Locale` when rendering `EtlSchedule.humanReadable`, and SHALL ignore the humanized string returned by the backend for the purpose of display.

### Requirement 7: Backend speaks English only for user-facing strings

**User Story:** As a frontend developer, I want every user-facing string to come from the frontend catalogs, so that backend responses never leak a pt-BR string into the English UI.

#### Acceptance Criteria

1. THE Backend SHALL return English-only text in every user-facing field of every API response produced by handlers under `backend/handlers/`, including validation `message` fields, error descriptions, and operator summaries.
2. THE Backend SHALL replace every pt-BR literal in `backend/handlers/config_handler.py` (including the `_humanize_schedule` output and success messages such as `"Bucket acessível e configuração salva com sucesso"`) with an English equivalent.
3. THE Frontend SHALL not rely on the backend `EtlSchedule.humanReadable` field for display; the frontend SHALL compute the humanized schedule locally via the Cron_Humanizer using the `Active_Locale`.
4. WHERE the backend returns a machine-readable status code or stable slug (for example `status: "error"`, error codes), THE Backend SHALL NOT translate or alter it.
5. WHEN a backend handler returns an error, THE Backend SHALL include an English `message` field, leaving display translation to the frontend mapping keyed on the error code.

### Requirement 8: Preserve Brazilian Portuguese as a first-class locale

**User Story:** As a Brazilian admin, I want pt-BR to behave exactly as it does today after I switch to it, so that there is no regression for my team.

#### Acceptance Criteria

1. THE `pt-BR.json` catalog SHALL contain, for every `Translation_Key`, the exact string that the application renders today in the corresponding place in the UI.
2. WHILE the `Active_Locale` is `"pt-BR"`, THE Frontend SHALL render every page, component, and control with strings that are byte-for-byte identical to the current pt-BR experience, except for strings intentionally changed by another requirement of this spec.
3. WHILE the `Active_Locale` is `"pt-BR"`, THE Cron_Humanizer SHALL return outputs that are byte-for-byte identical to the current output of `humanizeSchedule` in `frontend/src/utils/cronHumanizer.ts`.

### Requirement 9: Branding strings remain untranslated

**User Story:** As a maintainer, I want brand names kept in their canonical form across all locales, so that the product identity is stable.

#### Acceptance Criteria

1. FOR every locale `L` in `Supported_Locales`, THE Frontend SHALL resolve the brand key(s) to the literal value `"Kiro Cost Analyzer"` (and related brand strings in `Brand_Strings`), without translation.
2. THE LoginPage SHALL render the product name `"Kiro Cost Analyzer"` unchanged across locales and SHALL render the tagline using the `Active_Locale` catalog.

### Requirement 10: Translation correctness invariants

**User Story:** As a developer, I want the i18n layer to be self-consistent, so that missing or drifting translations are caught early.

#### Acceptance Criteria

1. FOR every `Translation_Key` present in either `en.json` or `pt-BR.json`, THE Frontend SHALL guarantee that the key is present in both catalogs (the symmetric difference of keys SHALL be empty).
2. FOR every `Translation_Key` in either catalog, THE Frontend SHALL guarantee that the resolved string is a non-empty string.
3. IF a `Translation_Key` requested at runtime is missing from the catalog for the `Active_Locale`, THEN THE I18n_Provider SHALL apply the `Missing_Key_Fallback` by returning the string from the `en` catalog, and SHALL emit exactly one `console.warn` per missing key per session in non-production builds.
4. IF a `Translation_Key` requested at runtime is missing from both catalogs, THEN THE I18n_Provider SHALL return the key itself as the rendered string and SHALL emit exactly one `console.error` per missing key per session in non-production builds.
5. THE Build SHALL fail when the automated key-parity check detects any `Translation_Key` present in one catalog but absent from the other.

### Requirement 11: State preservation across locale switches

**User Story:** As any user, I want my filters and selections to survive a language switch, so that switching language never costs me context.

#### Acceptance Criteria

1. WHEN the user changes the `Active_Locale` via the `Language_Switcher` on any page, THE Frontend SHALL preserve the current date-range filter, page size, pagination index, column sorting, text-filter value, selected user, selected row, and open split panel.
2. WHEN the user changes the `Active_Locale` during an in-flight API request, THE Frontend SHALL allow the request to complete and SHALL render its result using the new `Active_Locale` for all translated, numeric, and date fields.
3. WHEN the user changes the `Active_Locale` while a modal or split panel is open, THE Frontend SHALL keep the modal or split panel open and SHALL re-render its contents in the new `Active_Locale`.

### Requirement 12: Documentation migration

**User Story:** As a new visitor to the repository, I want the README in English, so that I can understand what KCA does without translation.

#### Acceptance Criteria

1. THE Repository SHALL contain `README.md` written in English, covering the same scope and sections as the current pt-BR README.
2. THE Repository SHALL contain `README.pt-BR.md` whose content is the current pt-BR `README.md`, preserved without edits beyond the addition of a cross-link back to `README.md`.
3. THE English `README.md` SHALL include a prominent link to `README.pt-BR.md` under a heading such as "Other languages".
4. THE English `README.md` SHALL retain all diagrams, tables, and command-line snippets from the current README, with prose translated to English and commands left unchanged.

### Requirement 13: Update the project steering file

**User Story:** As a maintainer, I want the steering rules updated, so that future contributions default to English and follow the new i18n conventions.

#### Acceptance Criteria

1. THE Steering_File SHALL declare English as the default language for UI text and top-level documentation, replacing the current pt-BR mandate in its "Idioma" and "Localização" sections.
2. THE Steering_File SHALL retain the existing rule that code, variable names, function names, docstrings, and technical comments are written in English.
3. THE Steering_File SHALL document the i18n file structure: the location of `Locale_Catalogs` under `frontend/src/locales/`, the translation-key naming convention, and the requirement that both catalogs have identical key sets.
4. THE Steering_File SHALL document the steps for adding a new locale: create `frontend/src/locales/<locale>.json` with identical keys to `en.json`, register the locale in the `I18n_Provider`, and add it to the `Language_Switcher`.
5. THE Steering_File SHALL reference this spec (`.kiro/specs/i18n-english-default/`) as the authoritative source for i18n decisions.

### Requirement 14: Language switcher accessibility

**User Story:** As a keyboard and screen-reader user, I want the language switcher to be fully accessible, so that I can change the locale without a mouse.

#### Acceptance Criteria

1. THE Language_Switcher SHALL be reachable via the standard `Tab` order in the top navigation.
2. THE Language_Switcher SHALL expose an accessible name drawn from the `Active_Locale` catalog (for example `"Language"` in `en`, `"Idioma"` in `pt-BR`).
3. THE Language_Switcher SHALL expose each locale option with an accessible label that identifies the target language, written in that target language (for example the `pt-BR` option is labeled `"Português (Brasil)"`).
4. WHEN the Language_Switcher is opened via keyboard, THE Language_Switcher SHALL place focus on the first locale option.
5. WHEN a locale option is selected via keyboard `Enter` or `Space`, THE Language_Switcher SHALL trigger the same locale change as a mouse click.

### Requirement 15: Bundle size and performance

**User Story:** As a performance-conscious maintainer, I want the i18n layer to avoid unnecessary weight on the initial bundle, so that the first-load experience stays reasonable and future growth is visible.

#### Acceptance Criteria

1. THE Frontend SHALL load exactly one locale catalog at startup: the one corresponding to the resolved `Active_Locale`.
2. THE Frontend SHALL load additional locale catalogs only when the user switches to a locale whose catalog has not yet been fetched.
3. THE Build SHALL report the gzipped size of the i18n runtime and each locale catalog in the build output, so regressions are visible to maintainers.
4. THE Build SHALL NOT fail based on an i18n bundle-size threshold; bundle growth is observed, not gated.

### Requirement 16: Correctness properties (validated by property-based tests in `design.md`)

**User Story:** As a developer, I want the critical i18n invariants stated explicitly as properties, so that `design.md` can turn each one into a property-based test.

#### Acceptance Criteria

1. **Locale-resolution totality**: FOR every `(storedLocale, navigatorLanguage)` pair, THE I18n_Provider SHALL resolve to a locale in `Supported_Locales`.
2. **Preference round-trip**: FOR every locale `L ∈ Supported_Locales`, setting `L` via the `Language_Switcher` and then restarting the application SHALL yield `Active_Locale = L`.
3. **State preservation under locale switch**: FOR every recorded application-state snapshot `S` (filters, pagination, sorting, selection, open panels) and every locale `L`, switching the `Active_Locale` to `L` SHALL leave `S` unchanged.
4. **Formatter locale coherence for numbers**: FOR every numeric value `n` rendered in the UI and the current `Active_Locale = L`, the rendered string SHALL equal `Intl.NumberFormat(L, opts).format(n)` for the options declared at the call site.
5. **Formatter locale coherence for dates and times**: FOR every timestamp `t` rendered in the UI and the current `Active_Locale = L`, the rendered string SHALL equal `Intl.DateTimeFormat(L, opts).format(t)` for the options declared at the call site.
6. **Cron humanizer locale coherence**: FOR every parsable EventBridge expression `E` and every locale `L ∈ Supported_Locales`, `humanize(E, L)` SHALL equal the template composed from `Locale_Catalogs[L]` applied to `parse(E)`; and FOR every unparsable `E`, `humanize(E, L) == E`.
7. **Catalog key parity**: `keys(en.json) == keys(pt-BR.json)`, as sets.
8. **No empty translations**: FOR every `(locale, key)` in the catalogs, `catalog[locale][key]` is a non-empty string.
9. **Missing-key fallback**: FOR every `Translation_Key` absent from `catalog[Active_Locale]` but present in `catalog["en"]`, the rendered string SHALL equal `catalog["en"][key]`.
10. **Brand invariance**: FOR every locale `L ∈ Supported_Locales` and every brand key `b ∈ Brand_Strings` defined in the catalogs, `catalog[L][b] == "Kiro Cost Analyzer"` (or the corresponding canonical brand literal).

### Requirement 17: User settings menu (language + visual mode)

**User Story:** As any user, I want a single, discoverable entry point for my preferences, so that I can change both language and theme without hunting separate controls across the top bar.

Glossary additions:
- **User_Settings_Menu**: The gear-icon control rendered in the `TopNavigation.utilities` array that opens a modal hosting every user preference.
- **User_Settings_Modal**: The modal opened by the `User_Settings_Menu`, titled "User settings". Hosts one `FormField` per preference.
- **Visual_Mode**: The user-facing theme selection, drawn from `{ "browser-default", "light", "dark" }`. The default is `"dark"` to preserve pre-feature behavior.
- **Theme_Storage_Key**: The `localStorage` key `kiro_theme` used to persist the user's `Visual_Mode`.
- **Resolved_Mode**: The actual Cloudscape mode applied to the DOM (`"light"` or `"dark"`). When `Visual_Mode = "browser-default"`, `Resolved_Mode` is derived from `window.matchMedia('(prefers-color-scheme: dark)')`.

#### Acceptance Criteria

1. THE Frontend SHALL render the `User_Settings_Menu` as an icon-only button inside `TopNavigation.utilities`, keyboard-reachable, with an accessible name drawn from `common.userSettings.openAriaLabel` in the `Active_Locale`.
2. THE Frontend SHALL render the `User_Settings_Menu` for both authenticated and unauthenticated users, so a user on the login flow can still change their preferences.
3. WHEN the user activates the `User_Settings_Menu`, THE Frontend SHALL open the `User_Settings_Modal` titled from `userSettings.title` in the `Active_Locale`.
4. THE `User_Settings_Modal` SHALL contain a "Language" section (per Requirement 17.7) and a "Visual mode" section (per Requirement 17.10), in that order.
5. WHEN the `User_Settings_Modal` is open and the user dismisses it (footer Close button, header close icon, or `Escape` key), THE Frontend SHALL close the modal without discarding preference changes — every change SHALL have been applied immediately at selection time.
6. THE `User_Settings_Modal` SHALL NOT expose the standalone `LanguageSwitcher` component in `TopNavigation`; the switcher SHALL be rendered only inside the modal. This removes the pre-existing overlap with the user-email dropdown.
7. THE "Language" section SHALL list every locale in `Supported_Locales` exactly once, with each option labeled in the target language itself (for example `"English"` for `en`, `"Português (Brasil)"` for `pt-BR`), and the `Active_Locale` pre-selected.
8. WHEN the user selects a locale `L` in the "Language" section, THE I18n_Provider SHALL set the `Active_Locale` to `L` and persist `L` to `Locale_Storage_Key`, with the same semantics as Requirement 3.2.
9. WHILE the `User_Settings_Modal` is open and the user changes the `Active_Locale`, THE Frontend SHALL re-render the modal's own contents in the new `Active_Locale` without closing it.
10. THE "Visual mode" section SHALL list the three options "Browser default", "Light", and "Dark", in that order, with localized labels and short descriptions from the catalog, and the current `Visual_Mode` pre-selected.
11. WHEN the user selects a `Visual_Mode` `V`, THE Frontend SHALL:
    a. persist `V` to `Theme_Storage_Key` before applying the visual change;
    b. compute the `Resolved_Mode` via the rule in the glossary (the `matchMedia` lookup for `"browser-default"`);
    c. invoke Cloudscape `applyMode(Mode.Dark | Mode.Light)` with the `Resolved_Mode`.
12. WHEN the application boots and a value `v` exists under `Theme_Storage_Key` such that `v ∈ { "browser-default", "light", "dark" }`, THE Frontend SHALL set the `Visual_Mode` to `v` before the first paint.
13. IF a value under `Theme_Storage_Key` is not in the supported set, THEN THE Frontend SHALL ignore it and apply the default `Visual_Mode` (`"dark"`).
14. WHILE the `Visual_Mode` is `"browser-default"`, THE Frontend SHALL subscribe to `window.matchMedia('(prefers-color-scheme: dark)')` and re-apply the `Resolved_Mode` whenever the system preference changes, without a page reload.
15. IF `localStorage` is unavailable when writing the `Theme_Storage_Key`, THEN THE Frontend SHALL fall back to in-memory state and SHALL log one structured warning per session on the browser console, mirroring Requirement 4.3 for the locale preference.

### Requirement 18: Theme correctness invariants

**User Story:** As a developer, I want the theme layer to obey the same correctness properties as the i18n layer, so that future changes do not break the settings menu.

#### Acceptance Criteria

1. **Visual-mode resolution totality**: FOR every stored string `s ∈ (string | null)`, `resolveInitialVisualMode(s)` SHALL return a member of `{ "browser-default", "light", "dark" }`.
2. **Visual-mode preference round-trip**: FOR every `V ∈ { "browser-default", "light", "dark" }`, persisting `V` and then restarting the application SHALL yield `Visual_Mode = V`.
3. **Resolved-mode invariance with no preference drift**: FOR any sequence of `setVisualMode` calls, the final `Resolved_Mode` SHALL depend only on (a) the final `Visual_Mode` and (b) the current `matchMedia('(prefers-color-scheme: dark)').matches` value — never on intermediate states.
4. **State preservation under visual-mode switch**: FOR every recorded application-state snapshot `S` (filters, pagination, sorting, selection, open panels) and every `Visual_Mode` `V`, switching the `Visual_Mode` to `V` SHALL leave `S` unchanged. Mirrors Requirement 11.1 for the theme dimension.

## Non-Functional Requirements

### NFR-1: Performance

- Initial locale catalog load MUST NOT add more than one additional network request beyond the current baseline on first page load.
- Switching locale MUST complete its visible re-render within one animation frame (≤ 16 ms) on a baseline reference machine, excluding any catalog fetch time.

### NFR-2: Accessibility

- The `Language_Switcher` MUST meet the keyboard and ARIA expectations in Requirement 14.
- Translated strings MUST NOT remove ARIA labels or accessible names present in the current pt-BR UI.

### NFR-3: Bundle size

- Per Requirement 15: bundle size is **observed**, not gated. The build reports the gzipped size of the i18n runtime and each locale catalog.
- Locale catalogs are served as separate chunks, loaded on demand.

### NFR-4: Observability

- In non-production builds, missing keys MUST be visible in the browser console, exactly once per key per session, per Requirement 10.3 and 10.4.

### NFR-5: Compatibility with existing features

- The i18n layer MUST NOT change the shape of any existing API response or any existing TypeScript interface in `frontend/src/types/index.ts`, with the single exception that `EtlSchedule.humanReadable` becomes informational-only on the frontend, per Requirement 6.5 and 7.3.

## Out of Scope

The following items are explicitly excluded from this feature and will not be addressed:

1. **Right-to-left (RTL) locales**: no Arabic, Hebrew, or other RTL language support; no CSS `dir` switching; no mirrored layouts.
2. **Translation of Bedrock prompt categories**: the 14 category identifiers used by the classifier remain in their current (English-leaning) form and are treated as stable slugs.
3. **Translation of stored historical data**: user names, prompt contents, responses, model IDs, and any other persisted data remain as stored.
4. **`Accept-Language`-driven backend**: the backend will not negotiate a response language from request headers. User-facing strings returned by the backend are English-only for this release. If backend-driven copy grows significantly, a future spec can revisit header-driven negotiation.
5. **Translation of engineering artifacts**: log messages, structured logger fields, CloudWatch entries, SAM template descriptions, Makefile targets, and scripts remain in their current language (English where it already is; unchanged otherwise).
6. **Locale auto-detection based on IP geolocation**: the `Locale_Resolution_Chain` uses `localStorage` and `navigator.language` only.
7. **Per-user server-side locale preference**: the preference is stored client-side only, in `localStorage`.
8. **Per-user server-side theme preference**: the `Visual_Mode` is stored client-side only, in `localStorage`, mirroring the locale preference.
9. **Per-page theme overrides**: the `Visual_Mode` is global; individual pages or components do not expose their own theme control.

## Traceability Summary

| Requirement | Testable As                                | Primary Validation                                          |
|-------------|--------------------------------------------|-------------------------------------------------------------|
| 1.1–1.5     | example                                    | Unit/integration tests; presence/structure assertions       |
| 1.6         | example                                    | Bundle/dynamic-import assertion                             |
| 2.1–2.5     | property (Req. 16.1) + examples            | PBT over `(storedLocale, navigatorLanguage)`                |
| 2.6         | example                                    | Synchronous first-render assertion                          |
| 3.1–3.5     | example                                    | Testing Library interaction tests                           |
| 4.1–4.2     | property (Req. 16.2)                       | PBT round-trip: set → reload → read                         |
| 4.3         | edge-case                                  | Test with `localStorage` mocked to throw                    |
| 5.1–5.5     | property (Req. 16.4, 16.5)                 | PBT over numeric/temporal inputs × locales                  |
| 6.1–6.5     | property (Req. 16.6) + examples            | PBT over cron/rate expressions × locales                    |
| 7.1–7.5     | example                                    | Backend integration tests per handler                       |
| 8.1–8.3     | example                                    | Snapshot tests against the current pt-BR UI                 |
| 9.1–9.2     | property (Req. 16.10)                      | PBT over `Brand_Strings` × locales                          |
| 10.1        | property (Req. 16.7)                       | Catalog key symmetric-difference assertion                  |
| 10.2        | property (Req. 16.8)                       | Iteration over both catalogs                                |
| 10.3–10.4   | edge-case (Req. 16.9)                      | Unit tests with synthetic partial catalogs                  |
| 10.5        | example                                    | Build-time check (CI)                                       |
| 11.1–11.3   | property (Req. 16.3)                       | PBT over synthetic state × locales                          |
| 12.1–12.4   | example                                    | File presence and content spot-check                        |
| 13.1–13.5   | example                                    | Steering-file content assertion                             |
| 14.1–14.5   | example                                    | Testing Library + `@testing-library/user-event`             |
| 15.1–15.4   | example                                    | Build reports catalog and runtime sizes (observability)     |
| 16.1–16.10  | property                                   | Hypothesis / fast-check property-based tests in `design.md` |
| 17.1–17.15  | example + property (Req. 18)               | Testing Library modal/harness tests; PBT for resolution     |
| 18.1–18.4   | property                                   | fast-check over stored inputs × VisualMode × matchMedia     |
