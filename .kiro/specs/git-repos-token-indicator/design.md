# Design — Token Configured Indicator on Repos Table

## Overview

Add one column to the repos table `columnDefinitions` in `GitSettingsPage.tsx`, rendering a Cloudscape `StatusIndicator` from the existing `tokenConfigured` boolean. No backend or API-client changes.

### Design Decisions

1. **`success`/`warning` types**: "No token" is a degraded-but-not-broken state (sync will fail on private repos) — `warning` communicates attention without implying an error the user caused. Mirrors the `StatusIndicator` usage in `UsersPage`/`SettingsPage`.
2. **Column placement**: between `provider` and `actions`, width 150 — keeps identity fields (name/url/provider) contiguous.
3. **New i18n keys** `gitSettings.repos.header.token`, `gitSettings.repos.token.configured`, `gitSettings.repos.token.missing` (the pre-existing unused `header.status`/`header.lastSync` keys refer to sync status, not token status — not reused to avoid semantic drift).

## Components and Interfaces

### 1. GitSettingsPage — token column

**File:** `frontend/src/pages/GitSettingsPage.tsx`

```tsx
import StatusIndicator from '@cloudscape-design/components/status-indicator';

{
  id: 'token',
  header: t('gitSettings.repos.header.token'),
  cell: (item) => (
    <StatusIndicator type={item.tokenConfigured ? 'success' : 'warning'}>
      {t(item.tokenConfigured ? 'gitSettings.repos.token.configured' : 'gitSettings.repos.token.missing')}
    </StatusIndicator>
  ),
  width: 150,
},
```

### 2. Translation keys

| Key | en | pt-BR |
|---|---|---|
| `gitSettings.repos.header.token` | Access Token | Token de Acesso |
| `gitSettings.repos.token.configured` | Token configured | Token configurado |
| `gitSettings.repos.token.missing` | No token | Sem token |

## Correctness Properties

*A correctness property is a characteristic or behavior that must hold in all valid executions of a system.*

### Property 1: Indicator fidelity

*For any* repository row, the rendered indicator SHALL be `success`/"Token configured" if and only if `tokenConfigured` is true, and `warning`/"No token" otherwise.

**Validates: Requirements 1.1, 1.2, 1.3**

## Error Handling

| Scenario | Behavior |
|---|---|
| `tokenConfigured` absent (older API) | Falsy → renders "No token" (safe default) |

## Testing Strategy

| Property | Test File | Tag |
|---|---|---|
| Property 1: Indicator fidelity | `GitSettingsPage.test.tsx` | Feature: git-repos-token-indicator, Property 1: Indicator fidelity |
