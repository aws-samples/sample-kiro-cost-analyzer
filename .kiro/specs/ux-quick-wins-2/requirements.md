# Requirements Document — UX Quick Wins 2 (F2, F8, F10)

## Introduction

This document specifies the second batch of design-critique quick wins (parent issue #15): the Productivity page empty state (#17 / F2), the login form pushed below the fold (#23 / F8), and the settings gear discoverability on the login page (#25 / F10). Investigation note on #25: hiding the gear would violate the existing Requirement 3.1 (locale/theme switcher reachable pre-auth, documented in `App.tsx`) and the icon works as designed — the valid remainder is discoverability, addressed by a clearer label.

## Glossary

- **Productivity Page**: Admin-only `/productivity` selector page that navigates to a user's productivity tab.
- **Hero Image**: The logo illustration on the login page.
- **Settings Gear**: The `UserSettingsMenu` utility opening the locale/visual-mode modal.

## Requirements

### Requirement 1: Productivity overview before selection (#17)

**User Story:** As an administrator opening the Productivity page, I want to see a ranking of the most active users immediately, so that I can pick who to analyze without knowing the name in advance.

#### Acceptance Criteria

1. WHEN the Productivity page loads with no user selected, THE page SHALL display a ranking table of the top 10 users by total credits, using the already-fetched usage data (no new API call).
2. THE ranking SHALL show display name, total credits, messages, average daily credits, and last active date, using the existing locale-aware formatters.
3. WHEN a ranking row's user link is clicked, THE page SHALL navigate to that user's productivity tab.
4. THE existing user selector SHALL remain available above the ranking.

### Requirement 2: Login form above the fold (#23)

**User Story:** As a user landing on the login page, I want the sign-in form fully visible without scrolling, so that the primary action is immediately reachable.

#### Acceptance Criteria

1. THE hero image SHALL be capped at 180px height with the `scale(1.5)` transform removed.
2. THE single-column centered layout SHALL otherwise remain unchanged.

### Requirement 3: Settings gear discoverability (#25)

**User Story:** As an unauthenticated user, I want the gear icon to communicate that it opens display preferences, so that it does not read as broken account settings.

#### Acceptance Criteria

1. THE gear utility's title/aria-label SHALL say "Language & theme" (localized) instead of a generic settings label.
2. THE gear SHALL remain visible pre-auth (preserving Requirement 3.1 of the i18n spec).
