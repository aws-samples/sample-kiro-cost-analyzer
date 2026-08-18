# Requirements Document — Human-Readable User Identifiers

## Introduction

This document specifies issue #18 (design critique F3): raw UUIDs appear as the primary user identifier across tables and headers. Root cause: the backend returns `displayName: ""` for users not resolved in Identity Center, and the frontend universally falls back to the raw `userId`. The fix enriches the backend fallback (so `displayName` is never empty when a `userName` exists) and hardens the frontend fallback chain in the remaining spots.

## Glossary

- **Display Name**: The human-readable name resolved from Identity Center.
- **User Name**: The account-level username (e.g. Cognito/CSV `userName`), always present.
- **Fallback Chain**: `displayName` → `userName` → truncated `userId` (first 8 chars + ellipsis).

## Requirements

### Requirement 1: Backend never returns an empty display name when a userName exists

**User Story:** As a user of any listing, I want a readable name for every user, so that I never have to scan UUIDs.

#### Acceptance Criteria

1. WHEN Identity Center resolution fails or is unavailable, THE usage/user listing responses SHALL populate `displayName` with the `userName` when one exists, instead of an empty string.
2. THE change SHALL apply to every response that carries `displayName` (usage listing, user detail, recommendations), through the shared name-resolution path.
3. IF neither a resolved name nor a `userName` exists, THEN `displayName` MAY remain empty (frontend fallback applies).

### Requirement 2: Frontend fallback chain

**User Story:** As a user, I want tables to degrade gracefully when a name is missing, so that a raw 36-char UUID is never the primary identifier.

#### Acceptance Criteria

1. WHEN `displayName` is empty, THE `UsageTable` and `RecommendationsTab` primary cells SHALL fall back to `userName`, and only then to a truncated `userId` (8 chars + ellipsis).
2. THE Git settings mapping delete-confirmation modal SHALL show the resolved display name (same lookup as the mappings table), falling back to the raw `userId`.
3. Full `userId` values intentionally shown as secondary identifiers (subtitles) SHALL remain unchanged.
