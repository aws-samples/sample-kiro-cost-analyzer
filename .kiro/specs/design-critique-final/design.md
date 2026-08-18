# Design — Design Critique Final (F1, F4, F9)

## Overview

Three independent fixes. #16 is locale-only (the ambiguity lives in the section heading, not the link or routes). #19 is a one-prop Cloudscape-native fix (`variant="container"` on the inner tabs — the mechanism designed for sub-level navigation). #24 adds three already-computed fields to the funnel response and a `Popover` on the Churn Risk label.

### Design Decisions

1. **#16 — rename over restructure**: the issue's option 1 (removing the sidebar item) would bury Productivity; renaming the section to "Analytics" resolves the double-"Users" collision with zero structural risk.
2. **#19 — container variant over flattening**: flattening 6+3 tabs into one bar (issue option A) trades hierarchy confusion for crowding; the `container` variant provides native visual differentiation preserving ids/state/URLs.
3. **#24 — Popover over new metrics**: no trends/benchmarks exist to show honestly; the formula + raw counts ("3 idle + 2 dormant of 7 users") is the context that makes 71.4% interpretable in a pilot-size population. Backend change is additive (3 fields).

## Components and Interfaces

### 1. Sidebar rename (#16)
`en.json`: `nav.section.users` → "Analytics"; `pt-BR.json` → "Análises".

### 2. Inner tabs variant (#19)
`SettingsPage.tsx` line ~241: `<Tabs variant="container" tabs={configTabs} />`

### 3. Churn Risk context (#24)
- `backend/handlers/funnel_calculator.py`: add `"idleCount": idle_count, "dormantCount": dormant_count, "totalUsers": total_users` to `derivedMetrics`.
- `frontend/src/types/index.ts`: extend the derived-metrics type with the 3 optional fields.
- `EngagementFunnelWidget.tsx`: wrap the label in a `Popover` with formula, counts (interpolated), and threshold note.
- Keys: `engagement.metrics.churnRiskRate.popover.formula`, `.counts` (with `{{idle}}/{{dormant}}/{{total}}`), `.threshold`.

## Correctness Properties

*A correctness property is a characteristic or behavior that must hold in all valid executions of a system.*

### Property 1: Count consistency

*For any* funnel response, `churnRiskRate` SHALL equal `round((idleCount + dormantCount) / totalUsers * 100, 1)` when `totalUsers > 0`.

**Validates: Requirements 3.1**

## Error Handling

| Scenario | Behavior |
|---|---|
| Counts absent (older API cache) | Popover renders formula + threshold only (counts line omitted) |
| totalUsers = 0 | Existing behavior unchanged (metric not rendered) |

## Testing Strategy

| Property | Test File | Tag |
|---|---|---|
| Property 1: Count consistency | `tests/test_funnel_calculator.py` | Feature: design-critique-final, Property 1: Count consistency |

---

# Implementation Plan

- [ ] 1. #16 — rename `nav.section.users` (en + pt-BR)
  - _Requirements: 1.1, 1.2_
- [ ] 2. #19 — `variant="container"` on the inner Settings tabs
  - _Requirements: 2.1, 2.2_
- [ ] 3. #24 — counts in `derivedMetrics` + Popover + i18n keys
  - _Requirements: 3.1, 3.2, 3.3_
- [ ]* 4. Test: Property 1 (count consistency) in `tests/test_funnel_calculator.py`
- [ ] 5. Checkpoint — pytest + build/tests + full deploy (backend changed) + user validation

## Notes

- Tasks marked with `*` are optional; #24 touches the backend → full `make deploy`
