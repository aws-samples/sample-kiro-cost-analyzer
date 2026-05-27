# Requirements Document

## Introduction

User Engagement Segmentation classifies users into engagement categories (Power, Active, Light, Idle) based on their aggregated activity within a selected period, and presents an engagement funnel visualization showing conversion rates between stages. This gives administrators and managers immediate visibility into Kiro adoption health, activation rates, and opportunities for training or enablement.

## Glossary

- **Segmentation_Engine**: The backend component that classifies users into engagement categories based on configurable thresholds and aggregated activity data.
- **Funnel_Calculator**: The backend component that computes engagement funnel stages and conversion rates between consecutive stages.
- **Segmentation_Widget**: The frontend component that displays the engagement segmentation pie chart on the dashboard.
- **Funnel_Widget**: The frontend component that displays the engagement funnel visualization with conversion rates on the dashboard.
- **Engagement_Category**: One of four classification levels (Power, Active, Light, Idle) assigned to a user based on their activity metrics.
- **Conversion_Rate**: The percentage of users who progress from one funnel stage to the next.
- **Segmentation_Thresholds**: Configurable numeric boundaries that define the criteria for each engagement category.
- **Activity_Period**: The date range selected by the user for which engagement metrics are computed.

## Requirements

### Requirement 1: Engagement Segmentation Classification

**User Story:** As an administrator, I want users classified into engagement categories based on their activity, so that I can understand the distribution of engagement levels across the organization.

#### Acceptance Criteria

1. WHEN the Segmentation_Engine receives aggregated user activity for an Activity_Period, THE Segmentation_Engine SHALL classify each user into exactly one Engagement_Category based on the following priority order: Power Users (highest), Active Users, Light Users, Idle Users (lowest).
2. THE Segmentation_Engine SHALL classify a user as Power Users WHEN the user has 100 or more messages within the Activity_Period.
3. THE Segmentation_Engine SHALL classify a user as Active Users WHEN the user has 20 or more messages within the Activity_Period, and the user does not qualify as Power Users.
4. THE Segmentation_Engine SHALL classify a user as Light Users WHEN the user has at least 1 message within the Activity_Period, and the user does not qualify as Power Users or Active Users.
5. THE Segmentation_Engine SHALL classify a user as Idle Users WHEN the user has zero messages within the Activity_Period.
6. THE Segmentation_Engine SHALL assign exactly one Engagement_Category to each user, with no user left unclassified.

### Requirement 2: Configurable Segmentation Thresholds

**User Story:** As an administrator, I want to customize the engagement thresholds, so that I can tune the segmentation criteria to match my organization's usage patterns.

#### Acceptance Criteria

1. THE Segmentation_Engine SHALL read Segmentation_Thresholds from SSM Parameter Store at the path `/kiro-cost-analyzer/engagement-thresholds`.
2. WHEN the SSM parameter is not found or is invalid, THE Segmentation_Engine SHALL use the default thresholds: Power Users (100 messages), Active Users (20 messages), Light Users (1 message).
3. THE Segmentation_Thresholds SHALL be stored as a JSON object with the structure: `{"power": {"messages": 100}, "active": {"messages": 20}}`.
4. WHEN an administrator updates the Segmentation_Thresholds via the configuration API, THE Segmentation_Engine SHALL apply the new thresholds on the next request without requiring a restart.
5. THE Segmentation_Engine SHALL validate that threshold values are positive integers and that Power thresholds are strictly greater than Active thresholds.
6. IF the Segmentation_Thresholds contain invalid values, THEN THE Segmentation_Engine SHALL reject the update and return a descriptive error message.

### Requirement 3: Engagement Funnel Computation

**User Story:** As an administrator, I want to see a conversion funnel showing how users progress through engagement stages, so that I can identify drop-off points and opportunities for enablement.

#### Acceptance Criteria

1. THE Funnel_Calculator SHALL compute the following stages in order: All Users, Sent Messages, Active Users, Power Users.
2. THE Funnel_Calculator SHALL define "All Users" as the total count of users known to the system within the Activity_Period (including Idle users).
3. THE Funnel_Calculator SHALL define "Sent Messages" as the count of users who sent at least 1 message within the Activity_Period.
4. THE Funnel_Calculator SHALL define "Active Users" as the count of users classified as Active Users or Power Users.
5. THE Funnel_Calculator SHALL define "Power Users" as the count of users classified as Power Users.
7. WHEN computing conversion rates, THE Funnel_Calculator SHALL calculate the percentage of users in stage N relative to stage N-1 (e.g., Sent Messages / All Users).
8. IF a stage has zero users, THEN THE Funnel_Calculator SHALL report the conversion rate from that stage to the next as 0%.

### Requirement 4: Segmentation API Endpoint

**User Story:** As a frontend developer, I want a dedicated API endpoint for engagement segmentation data, so that the dashboard can display segmentation and funnel visualizations.

#### Acceptance Criteria

1. WHEN a GET request is made to `/api/usage/engagement`, THE Segmentation_Engine SHALL return the segmentation distribution and funnel data for the specified Activity_Period.
2. THE response SHALL include a `segmentation` object containing the count and percentage of users in each Engagement_Category.
3. THE response SHALL include a `funnel` array containing each stage name, user count, and conversion rate from the previous stage.
4. THE response SHALL include a `derivedMetrics` object containing: percentage of Power Users, activation rate (percentage of users who sent at least one message), and idle rate (percentage of Idle users).
5. WHEN `startDate` and `endDate` query parameters are provided, THE Segmentation_Engine SHALL compute metrics only for activity within that date range.
6. WHEN no date range is provided, THE Segmentation_Engine SHALL compute metrics for all available data.

### Requirement 5: Segmentation Dashboard Visualization

**User Story:** As an administrator, I want to see engagement segmentation as a pie chart on the main dashboard, so that I can quickly assess the distribution of user engagement levels.

#### Acceptance Criteria

1. THE Segmentation_Widget SHALL display a pie chart showing the proportion of users in each Engagement_Category.
2. THE Segmentation_Widget SHALL display each category with a distinct color label (no emojis): Power Users, Active Users, Light Users, Idle Users.
3. THE Segmentation_Widget SHALL display the count and percentage for each category.
4. THE Segmentation_Widget SHALL update when the user changes the Activity_Period via the date range picker on the dashboard.
5. WHILE the segmentation data is loading, THE Segmentation_Widget SHALL display a loading skeleton placeholder.
6. IF the API returns an error, THEN THE Segmentation_Widget SHALL display an error alert with a retry option.

### Requirement 6: Funnel Dashboard Visualization

**User Story:** As an administrator, I want to see an engagement funnel chart on the dashboard, so that I can visualize conversion rates between engagement stages.

#### Acceptance Criteria

1. THE Funnel_Widget SHALL display a funnel visualization with stages ordered from widest (All Users) to narrowest (Power Users).
2. THE Funnel_Widget SHALL display the user count and conversion rate for each stage.
3. THE Funnel_Widget SHALL label conversion rates between stages (e.g., "Message Activation: 87%", "Power User Growth: 12%").
4. THE Funnel_Widget SHALL update when the user changes the Activity_Period via the date range picker on the dashboard.
5. WHILE the funnel data is loading, THE Funnel_Widget SHALL display a loading skeleton placeholder.
6. IF the API returns an error, THEN THE Funnel_Widget SHALL display an error alert with a retry option.

### Requirement 7: Derived Engagement Metrics

**User Story:** As an administrator, I want to see key engagement health metrics at a glance, so that I can quickly assess Kiro ROI and identify areas needing attention.

#### Acceptance Criteria

1. THE Segmentation_Widget SHALL display the following derived metrics: Power User percentage (adoption health), Activation Rate (percentage of users who sent at least one message), and Idle Rate (implicit churn).
2. THE derived metrics SHALL be computed from the segmentation data for the selected Activity_Period.
3. THE derived metrics SHALL be displayed as percentage values with one decimal place precision.

### Requirement 8: Internationalization

**User Story:** As a user, I want the engagement segmentation UI to be available in both English and Portuguese, so that I can use the application in my preferred language.

#### Acceptance Criteria

1. THE Segmentation_Widget SHALL display all labels, category names, and metric descriptions using translation keys resolved via the i18n system.
2. THE Funnel_Widget SHALL display all stage names, conversion rate labels, and descriptions using translation keys resolved via the i18n system.
3. THE translation catalogs SHALL include keys for both `en` and `pt-BR` locales with identical key sets for all engagement segmentation strings.
4. THE Segmentation_Widget SHALL use locale-aware number formatting for percentages and counts via the `formatNumber` helper from `useI18n()`.
