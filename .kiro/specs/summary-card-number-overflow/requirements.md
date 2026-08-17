# Requirements Document — Summary Card Number Overflow

## Introduction

This document specifies the requirements to fix issue #20 (Design Critique finding F5): large numeric values on summary/KPI cards wrap mid-number to a second line (e.g. "10,342.18" renders as "10,342.1" / "8"), breaking the visual rhythm of the KPI row. The fix applies a compact notation for large values and prevents mid-number line breaks, using the existing locale-aware `formatNumber` helper (which already supports `Intl.NumberFormat`'s `notation: 'compact'`). Five components share the vulnerable pattern: `SummaryCards` (the reported repro), `AccountSummaryCards`, `UserSummaryCards`, `GitSummaryCards`, and `ProductivitySummaryCards`.

## Glossary

- **Summary Card**: A KPI tile rendering a label and a large numeric value, laid out in a multi-column grid (Cloudscape `KeyValuePairs`, `ColumnLayout`, or `Cards`).
- **Compact Notation**: `Intl.NumberFormat` `notation: 'compact'` output (e.g. `10.3K` in `en`, `10,3 mil` in `pt-BR`).
- **Threshold**: The absolute value at or above which compact notation is applied (10,000).
- **formatNumber**: The locale-bound number formatter exposed by `useI18n()` (`frontend/src/i18n/formatters.ts`).

## Requirements

### Requirement 1: Compact rendering of large values

**User Story:** As a user scanning the KPI row, I want large values abbreviated (e.g. 10.3K), so that every value fits on a single line and the row scans cleanly.

#### Acceptance Criteria

1. WHEN a summary card numeric value is greater than or equal to 10,000 in absolute value, THE Summary Card SHALL render it using compact notation with at most 1 fraction digit via `formatNumber`.
2. WHEN a summary card numeric value is below 10,000 in absolute value, THE Summary Card SHALL keep the existing formatting (2 fraction digits for credit values; integer rendering for counts).
3. THE compact formatting SHALL be locale-aware, following the active UI locale (e.g. `10.3K` in `en`, `10,3 mil` in `pt-BR`).
4. THE fix SHALL apply to all five summary-card components: `SummaryCards`, `AccountSummaryCards`, `UserSummaryCards`, `GitSummaryCards`, and `ProductivitySummaryCards`.

### Requirement 2: No mid-number line breaks

**User Story:** As a user, I want numeric values to never wrap across two lines, so that the KPI grid alignment is preserved even in narrow columns.

#### Acceptance Criteria

1. THE Summary Card numeric value SHALL be rendered with `white-space: nowrap` so a value never breaks across lines.
2. THE label text of the card SHALL keep its default wrapping behavior (labels may wrap; values may not).

### Requirement 3: Shared helper for consistency

**User Story:** As a developer, I want a single shared helper for the threshold-based compact formatting, so that the five components cannot drift apart.

#### Acceptance Criteria

1. THE compact-formatting decision (threshold + options) SHALL live in a single shared utility consumed by all five components.
2. THE utility SHALL delegate the actual formatting to the `formatNumber` function provided by the caller, preserving locale-awareness and testability.
