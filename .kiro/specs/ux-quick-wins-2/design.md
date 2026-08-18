# Design — UX Quick Wins 2 (F2, F8, F10)

## Overview

Three independent, frontend-only fixes in one batch. #17 reuses the `users` state already fetched by `ProductivityPage` (it only fed the dropdown) to render a top-10 ranking table replacing the empty state. #23 is a one-line style fix on the login hero. #25 is a label change (the "hide the gear" recommendation is rejected — it conflicts with the documented pre-auth switcher requirement; the icon works as designed).

### Design Decisions

1. **#17 — no new API**: `/api/usage?limit=50` already returns `UserUsage[]` with credits/messages/daily averages; sorting client-side and rendering the top 10 keeps the page self-contained. Rows link to `/user/{userId}?tab=productivity` (same navigation as the dropdown).
2. **#23 — cap instead of restructure**: `maxHeight: 180` + drop `transform: scale(1.5)`; a side-by-side hero layout would be a structural refactor disproportionate to a Minor finding.
3. **#25 — relabel instead of hide**: update `userSettings.openAriaLabel` to "Language & theme" (both the tooltip/title and aria-label flow from it); close the issue documenting the Req 3.1 conflict.

## Components and Interfaces

### 1. ProductivityPage ranking (#17)

**File:** `frontend/src/pages/ProductivityPage.tsx` — replace the empty-state `Box` with a Cloudscape `Table`:
columns rank (index), user (Link → productivity tab), totalCredits (`formatCardValue`-style 2-dec), totalMessages (int), averageDailyCredits, lastActiveDate (`formatDate`). Items: `[...users].sort((a, b) => b.totalCredits - a.totalCredits).slice(0, 10)`.
New i18n keys under `productivity.ranking.*` (title, description, headers).

### 2. LoginPage hero (#23)

**File:** `frontend/src/pages/LoginPage.tsx` line ~56:
`style={{ maxWidth: '100%', maxHeight: 180, height: 'auto', objectFit: 'contain', marginBottom: 16 }}`

### 3. Gear label (#25)

**Files:** `frontend/src/locales/en.json` / `pt-BR.json` — `userSettings.openAriaLabel`: "Language & theme" / "Idioma e tema".

## Correctness Properties

*A correctness property is a characteristic or behavior that must hold in all valid executions of a system.*

### Property 1: Ranking order and size

*For any* users array, the ranking SHALL contain at most 10 rows ordered by `totalCredits` descending.

**Validates: Requirements 1.1**

## Error Handling

| Scenario | Behavior |
|---|---|
| Usage fetch fails | Existing page error handling unchanged; ranking simply not rendered |
| Fewer than 10 users | Ranking shows all users |

## Testing Strategy

| Property | Test File | Tag |
|---|---|---|
| Property 1: Ranking order and size | `frontend/src/pages/__tests__/ProductivityPage.test.tsx` (new) | Feature: ux-quick-wins-2, Property 1: Ranking order and size |

---

# Implementation Plan

- [ ] 1. #17 — Productivity ranking table (component + i18n keys)
  - _Requirements: 1.1, 1.2, 1.3, 1.4_
- [ ] 2. #23 — Login hero cap
  - _Requirements: 2.1, 2.2_
- [ ] 3. #25 — Gear label + close issue with Req 3.1 rationale
  - _Requirements: 3.1, 3.2_
- [ ]* 4. Test: Property 1 (ranking order/size)
- [ ] 5. Checkpoint — build, tests, deploy-frontend, user validation

## Notes

- Tasks marked with `*` are optional; frontend-only batch (deploy-frontend suffices)
