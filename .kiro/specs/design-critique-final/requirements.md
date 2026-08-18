# Requirements Document — Design Critique Final (F1, F4, F9)

## Introduction

Final batch of the design critique (#15): navigation ambiguity between the sidebar "Users" section and the Dashboard "Users" tab (#16 / F1), identical styling on the two tab levels in Administration (#19 / F4), and the context-free Churn Risk percentage (#24 / F9). Closing these closes the parent tracking issue.

## Requirements

### Requirement 1: Disambiguate the sidebar section (#16)

**User Story:** As a user, I want "Users" to mean one thing, so that navigation is predictable.

#### Acceptance Criteria

1. THE sidebar section currently labeled "Users" SHALL be renamed to "Analytics" ("Análises" in pt-BR); the Dashboard "Users" tab keeps its name (it lists users).
2. No routes or component structure SHALL change.

### Requirement 2: Visually differentiate the Administration tab levels (#19)

**User Story:** As an administrator, I want the two tab levels to look different, so that I always know which level I am navigating.

#### Acceptance Criteria

1. THE inner Settings tabs SHALL use the Cloudscape `container` variant, visually distinct from the outer default-variant tabs.
2. Tab ids, state management, and URL behavior SHALL remain unchanged.

### Requirement 3: Churn Risk context (#24)

**User Story:** As an administrator, I want to understand what the Churn Risk percentage means, so that I can judge whether it is alarming for my population size.

#### Acceptance Criteria

1. THE engagement funnel response SHALL include the raw `idleCount`, `dormantCount`, and `totalUsers` values (already computed in `funnel_calculator.py`).
2. THE Churn Risk label SHALL carry a Popover explaining the formula (idle + dormant ÷ total), showing the raw counts, and noting the >50% high-risk flag threshold.
3. THE Popover texts SHALL be localized (en + pt-BR).
