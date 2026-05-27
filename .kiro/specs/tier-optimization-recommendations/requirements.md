# Requirements Document

## Introduction

Tier Optimization Recommendations analyzes users with overage-enabled subscriptions to determine whether upgrading or downgrading their subscription tier would reduce costs. The system computes a projection of the current month's usage based on average daily credits, compares projected overage cost against tier price deltas, and surfaces actionable results on a dedicated Dashboard tab and via badges in the users table. This gives administrators direct financial actionability — not just usage visibility, but concrete cost-optimization guidance.

## Glossary

- **Recommendation_Engine**: The backend component that computes tier optimization recommendations by projecting current-month usage and comparing overage costs against tier upgrade/downgrade deltas.
- **Pricing_Config**: The configurable pricing table stored in SSM Parameter Store containing tier definitions and overage rates. All monetary values are in USD.
- **Recommendation_API**: The backend endpoint that returns computed tier optimization recommendations.
- **Recommendations_Tab**: The frontend tab within the existing Dashboard page that displays the tier optimization recommendations table, filters, and summary card.
- **User_Table_Badge**: The frontend badge/tag displayed next to a user's name in the existing users table when a recommendation exists (e.g., "↑ Upgrade" or "↓ Downgrade").
- **Recommendation_Modal**: The Cloudscape Modal that opens when an administrator clicks a User_Table_Badge, showing detailed analysis including current tier, projected usage, current cost vs recommended tier cost, and estimated savings.
- **Overage_Credits**: Credits consumed beyond the included credits in a user's subscription tier, billed at the overage rate.
- **Tier_Delta**: The difference in monthly price between two adjacent subscription tiers.
- **Annual_Savings**: The projected yearly cost reduction if a recommendation is applied, computed as `(projected_overage_cost - tier_delta) × 12` for upgrades or `(current_tier_monthlyPrice - lower_tier_monthlyPrice) × 12` for downgrades.
- **Projected_Monthly_Usage**: The estimated full-month credit usage computed as `average_credits_per_day × 30`, where `average_credits_per_day` is derived from the start of the current month until today.
- **Pricing_Settings_Panel**: The admin-only frontend section in the Settings page where administrators configure the pricing table.

## Requirements

### Requirement 1: Pricing Configuration Storage

**User Story:** As an administrator, I want to configure tier pricing and overage rates, so that the recommendation engine uses my organization's contracted pricing.

#### Acceptance Criteria

1. THE Pricing_Config SHALL be stored in SSM Parameter Store at the path `/kiro-cost-analyzer/tier-pricing`.
2. THE Pricing_Config SHALL contain a JSON object with the structure: `{"tiers": {"<tierName>": {"monthlyPrice": <number>, "includedCredits": <number>}}, "overagePricePerCredit": <number>}`.
3. WHEN the SSM parameter is not found or contains invalid JSON, THE Recommendation_Engine SHALL return a descriptive error indicating that pricing configuration is required.
4. THE Pricing_Config SHALL support a minimum of two tiers and a maximum of ten tiers.
5. WHEN an administrator updates the Pricing_Config via the configuration API, THE Recommendation_Engine SHALL apply the new configuration on the next request without requiring a restart.
6. THE Pricing_Config SHALL store all monetary values in USD with sufficient decimal precision to represent per-credit costs (e.g., $0.003/credit).

### Requirement 2: Pricing Configuration Validation

**User Story:** As an administrator, I want the system to validate my pricing configuration, so that invalid data does not produce incorrect recommendations.

#### Acceptance Criteria

1. THE Recommendation_Engine SHALL validate that each tier entry contains `monthlyPrice` as a non-negative number and `includedCredits` as a positive integer.
2. THE Recommendation_Engine SHALL validate that `overagePricePerCredit` is a positive number.
3. THE Recommendation_Engine SHALL validate that tier names are non-empty strings.
4. IF the Pricing_Config contains invalid values, THEN THE Recommendation_Engine SHALL reject the update and return a descriptive error message identifying the invalid field.
5. THE Recommendation_Engine SHALL validate that tiers are ordered by ascending `monthlyPrice` (each tier costs more than the previous one).

### Requirement 3: Projection Computation

**User Story:** As an administrator, I want the system to project each user's monthly usage from current-month data, so that recommendations reflect the most recent usage trend.

#### Acceptance Criteria

1. WHEN computing recommendations, THE Recommendation_Engine SHALL aggregate `STATS#DAILY` records per user from the first day of the current month through today to compute `average_credits_per_day`.
2. THE Recommendation_Engine SHALL compute Projected_Monthly_Usage as `average_credits_per_day × 30`.
3. THE Recommendation_Engine SHALL compute projected overage credits as `max(0, Projected_Monthly_Usage - includedCredits)` for the user's current tier.
4. THE Recommendation_Engine SHALL compute projected overage cost as `projected_overage_credits × overagePricePerCredit`.
5. THE Recommendation_Engine SHALL only consider users whose subscription tier has `overage_enabled` set to true in the usage data.
6. THE Recommendation_Engine SHALL use fixed-point or decimal arithmetic for all monetary calculations to avoid floating-point precision errors.
7. THE Recommendation_Engine SHALL display monetary values formatted as USD with appropriate decimal places.

### Requirement 4: Upgrade Recommendation Logic

**User Story:** As an administrator, I want the system to recommend tier upgrades when projected overage cost exceeds the upgrade price difference, so that I can reduce costs for heavy users.

#### Acceptance Criteria

1. THE Recommendation_Engine SHALL compute the Tier_Delta as `next_tier_monthlyPrice - current_tier_monthlyPrice` for each user's current tier relative to the next higher tier.
2. THE Recommendation_Engine SHALL recommend an upgrade WHEN the user's projected overage cost for the current month exceeds the Tier_Delta to the next tier.
3. THE Recommendation_Engine SHALL compute Annual_Savings as `(projected_overage_cost - tier_delta) × 12` for each upgrade recommendation.
4. THE Recommendation_Engine SHALL ensure Annual_Savings is non-negative for every upgrade recommendation.
5. WHEN a user is already on the highest configured tier, THE Recommendation_Engine SHALL not generate an upgrade recommendation for that user.
6. THE Recommendation_Engine SHALL recommend upgrading to the optimal tier (not just the next tier) when skipping a tier produces greater Annual_Savings.
7. THE Recommendation_Engine SHALL exclude users with zero overage credits in the current month from upgrade recommendations.

### Requirement 5: Downgrade Recommendation Logic

**User Story:** As an administrator, I want the system to flag users who are projected to under-use their tier, so that I can identify potential cost savings from downgrades.

#### Acceptance Criteria

1. THE Recommendation_Engine SHALL identify users whose Projected_Monthly_Usage does not reach the `includedCredits` of the next lower tier.
2. THE Recommendation_Engine SHALL compute downgrade Annual_Savings as `(current_tier_monthlyPrice - lower_tier_monthlyPrice) × 12`.
3. THE Recommendation_Engine SHALL not recommend a downgrade if the user's Projected_Monthly_Usage exceeds the next-lower tier's `includedCredits`.
4. WHEN a user is already on the lowest configured tier, THE Recommendation_Engine SHALL not generate a downgrade recommendation for that user.

### Requirement 6: Recommendation API Endpoint

**User Story:** As a frontend developer, I want a dedicated API endpoint for tier optimization recommendations, so that the dashboard can display actionable cost-saving data.

#### Acceptance Criteria

1. WHEN a GET request is made to `/api/recommendations/tier-optimization`, THE Recommendation_API SHALL return the computed recommendations.
2. THE response SHALL include a `recommendations` array where each entry contains: `userId`, `displayName`, `currentTier`, `recommendedTier`, `recommendationType` (upgrade/downgrade), `projectedMonthlyUsage`, `projectedOverageCost`, `annualSavings`.
3. THE response SHALL include a `summary` object containing: `totalRecommendations`, `totalProjectedAnnualSavings`, `upgradeCount`, and `downgradeCount`.
4. THE Recommendation_API SHALL sort recommendations by `annualSavings` in descending order.
5. THE Recommendation_API SHALL be restricted to administrators only.
6. IF the Pricing_Config is not configured, THEN THE Recommendation_API SHALL return a 400 status with an error message indicating that pricing configuration is required.

### Requirement 7: Recommendations Dashboard Tab

**User Story:** As an administrator, I want a dedicated tab in the Dashboard showing tier optimization recommendations, so that I can quickly identify cost-saving opportunities.

#### Acceptance Criteria

1. THE Recommendations_Tab SHALL be displayed as a new tab in the existing Dashboard page alongside overview and breakdown tabs.
2. THE Recommendations_Tab SHALL display a table with columns: User, Current Tier, Projected Monthly Usage, Recommended Tier, Projected Annual Savings, and Recommendation Type.
3. THE Recommendations_Tab SHALL display a summary card showing total projected annual savings if all recommendations are applied.
4. THE Recommendations_Tab SHALL provide filter controls to filter by recommendation type (Upgrade, Downgrade, All).
5. THE Recommendations_Tab SHALL display the number of recommendations matching the current filter.
6. WHILE recommendation data is loading, THE Recommendations_Tab SHALL display a loading skeleton placeholder.
7. IF the API returns an error, THEN THE Recommendations_Tab SHALL display an error alert with a retry option.
8. IF the Pricing_Config is not configured, THEN THE Recommendations_Tab SHALL display a setup prompt directing the administrator to the Pricing Settings.

### Requirement 8: User Table Badge and Recommendation Modal

**User Story:** As an administrator, I want to see recommendation badges in the users table and view detailed analysis in a modal, so that I am aware of optimization opportunities while managing users.

#### Acceptance Criteria

1. WHEN a tier optimization recommendation exists for a user, THE User_Table_Badge SHALL display a badge next to the user's name in the existing users table indicating the recommendation type ("↑ Upgrade" or "↓ Downgrade").
2. WHEN no recommendation exists for a user, THE User_Table_Badge SHALL not be displayed.
3. WHEN an administrator clicks the User_Table_Badge, THE Recommendation_Modal SHALL open displaying detailed analysis.
4. THE Recommendation_Modal SHALL display: current tier, projected monthly usage, current monthly cost (tier price + projected overage), recommended tier, recommended tier monthly cost, and estimated annual savings.
5. THE Recommendation_Modal SHALL be implemented as a Cloudscape Modal component.

### Requirement 9: Pricing Settings Panel

**User Story:** As an administrator, I want a settings interface to manage the pricing configuration, so that I can update tier prices and overage rates without direct SSM access.

#### Acceptance Criteria

1. THE Pricing_Settings_Panel SHALL be displayed in the existing Settings page as an admin-only section.
2. THE Pricing_Settings_Panel SHALL display the current Pricing_Config in an editable form with fields for each tier (name, monthly price, included credits) and overage price per credit.
3. WHEN the administrator submits the form, THE Pricing_Settings_Panel SHALL validate the input client-side before sending to the API.
4. WHEN the API returns a validation error, THE Pricing_Settings_Panel SHALL display the error message inline next to the relevant field.
5. THE Pricing_Settings_Panel SHALL allow adding and removing tiers (within the 2–10 tier limit).
6. THE Pricing_Settings_Panel SHALL be accessible only to users in the Admins group.
7. WHEN the configuration is saved successfully, THE Pricing_Settings_Panel SHALL display a success notification.

### Requirement 10: Recommendation Determinism

**User Story:** As a developer, I want the recommendation computation to be deterministic, so that the same inputs always produce the same outputs and the logic is testable via property-based tests.

#### Acceptance Criteria

1. THE Recommendation_Engine SHALL produce identical recommendations given identical inputs (user activity data, pricing configuration, and current date).
2. THE Recommendation_Engine SHALL not depend on wall-clock time beyond the explicit "today" parameter, random values, or external state beyond the explicit inputs.
3. FOR ALL valid inputs, THE Recommendation_Engine SHALL ensure that `annualSavings >= 0` for every upgrade recommendation.
4. FOR ALL valid inputs, THE Recommendation_Engine SHALL ensure that a user with zero overage credits in the current month receives no upgrade recommendation.
5. FOR ALL valid inputs, THE Recommendation_Engine SHALL ensure that a downgrade is not recommended if the user's Projected_Monthly_Usage exceeds the next-lower tier's `includedCredits`.
6. FOR ALL valid inputs, THE projection calculation SHALL be linear: doubling the average daily credit rate SHALL double the Projected_Monthly_Usage.

### Requirement 11: Internationalization

**User Story:** As a user, I want the tier optimization UI to be available in both English and Portuguese, so that I can use the application in my preferred language.

#### Acceptance Criteria

1. THE Recommendations_Tab SHALL display all labels, column headers, recommendation types, and messages using translation keys resolved via the i18n system.
2. THE Pricing_Settings_Panel SHALL display all form labels, validation messages, and notifications using translation keys resolved via the i18n system.
3. THE User_Table_Badge and Recommendation_Modal SHALL display badge text, labels, and savings values using translation keys resolved via the i18n system.
4. THE translation catalogs SHALL include keys for both `en` and `pt-BR` locales with identical key sets for all tier optimization strings.
5. THE Recommendations_Tab SHALL use locale-aware number formatting for currency values and percentages via the `formatNumber` helper from `useI18n()`.
