# Requirements Document

## Introduction

This feature enriches the Kiro Cost Analyzer's engagement segmentation system with activity frequency awareness. It introduces a "dormant" user category (users inactive for 90+ days), pre-computed activity summary metrics per user, frequency-based status badges in the Users table, and corresponding updates to the segmentation and funnel widgets. The goal is to enable admins to identify churn-risk users who have stopped using Kiro.

## Glossary

- **ETL_Pipeline**: The Step Functions pipeline that processes daily usage stats and writes them to DynamoDB.
- **Segmentation_Engine**: The pure classification module (`segmentation_engine.py`) that categorizes users into engagement tiers.
- **Engagement_Handler**: The API handler that orchestrates segmentation, funnel computation, and derived metrics for the `/api/usage/engagement` endpoint.
- **Analytics_Repository**: The data access layer that reads aggregated user stats from the Analytics_Table in DynamoDB.
- **Activity_Summary**: A pre-computed DynamoDB item (PK=`USER#{userId}`, SK=`ACTIVITY_SUMMARY`) storing `firstActiveDate`, `lastActiveDate`, and `activeDays` for a user.
- **Segmentation_Widget**: The frontend pie chart component displaying user engagement distribution.
- **Funnel_Widget**: The frontend D3 funnel chart component displaying engagement progression stages.
- **Users_Table**: The frontend table component listing individual users with their usage metrics.
- **Dormant_Threshold**: The configurable number of days (default 90) after which an idle user is classified as dormant.
- **Frequency_Status**: A derived status badge (Active, Recent, Inactive, Dormant) based on `daysSinceLastActive`.

---

## Requirements

### Requirement 1: Activity Summary Computation in ETL

**User Story:** As an admin, I want per-user activity frequency metrics pre-computed during ETL, so that the API can serve frequency data without scanning all daily stats at query time.

#### Acceptance Criteria

1. WHEN the ETL_Pipeline processes daily stats for a user, THE ETL_Pipeline SHALL upsert an Activity_Summary item with PK=`USER#{userId}` and SK=`ACTIVITY_SUMMARY` containing `firstActiveDate`, `lastActiveDate`, and `activeDays`.
2. WHEN a new daily stat is written for a user, THE ETL_Pipeline SHALL update `lastActiveDate` to the stat's date if the stat's date is later than the current `lastActiveDate`.
3. WHEN a new daily stat is written for a user, THE ETL_Pipeline SHALL update `firstActiveDate` to the stat's date if the stat's date is earlier than the current `firstActiveDate`.
4. WHEN a new daily stat is written for a user, THE ETL_Pipeline SHALL increment `activeDays` by 1.
5. THE ETL_Pipeline SHALL use conditional expressions (`if_not_exists` for `firstActiveDate`, comparison for `lastActiveDate`) to ensure correctness under concurrent or out-of-order writes.

---

### Requirement 2: Activity Summary Read Access

**User Story:** As an admin, I want the API to return frequency metrics for each user, so that I can see when users were last active.

#### Acceptance Criteria

1. THE Analytics_Repository SHALL provide a method to retrieve the Activity_Summary item for a given user.
2. THE Analytics_Repository SHALL provide a method to batch-retrieve Activity_Summary items for multiple users.
3. WHEN an Activity_Summary item does not exist for a user, THE Analytics_Repository SHALL return `null` for that user's frequency data.
4. THE Engagement_Handler SHALL compute `daysSinceLastActive` at read time as the difference in days between the current date and `lastActiveDate`.

---

### Requirement 3: Dormant Classification

**User Story:** As an admin, I want idle users who have been inactive for 90+ days to be classified as "dormant", so that I can distinguish between recently idle users and long-term churned users.

#### Acceptance Criteria

1. THE Segmentation_Engine SHALL accept a `dormant_days_threshold` parameter (default: 30) in the Thresholds configuration.
2. WHEN a user is classified as "idle" AND the user's `daysSinceLastActive` is greater than or equal to the Dormant_Threshold, THE Segmentation_Engine SHALL classify that user as "dormant" instead of "idle".
3. WHEN a user is classified as "idle" AND the user's `daysSinceLastActive` is less than the Dormant_Threshold, THE Segmentation_Engine SHALL retain the "idle" classification.
4. WHEN a user has no Activity_Summary (graceful degradation), THE Segmentation_Engine SHALL classify that user as "idle" without attempting dormant reclassification.
5. THE Segmentation_Engine SHALL support five categories: "power", "active", "light", "idle", "dormant".

---

### Requirement 4: Configurable Dormant Threshold via SSM

**User Story:** As an admin, I want the dormant threshold to be configurable via the same SSM mechanism used for engagement thresholds, so that I can tune the definition of dormancy.

#### Acceptance Criteria

1. THE Engagement_Handler SHALL read the `dormantDaysThreshold` value from the SSM engagement-thresholds parameter.
2. WHEN the SSM parameter does not contain a `dormantDaysThreshold` field, THE Engagement_Handler SHALL use the default value of 30 days.
3. THE threshold validation logic SHALL accept an optional `dormantDaysThreshold` field that is a positive integer.
4. WHEN a PUT request updates engagement thresholds with a `dormantDaysThreshold` value, THE Engagement_Handler SHALL persist the value to SSM alongside existing threshold fields.

---

### Requirement 5: Segmentation Widget Update

**User Story:** As an admin, I want the engagement pie chart to display five categories including "dormant", so that I can visualize the proportion of churned users.

#### Acceptance Criteria

1. THE Segmentation_Widget SHALL display five segments: "power", "active", "light", "idle", "dormant".
2. THE Segmentation_Widget SHALL render the "dormant" segment with a distinct dark red/maroon color (`#8b0000`).
3. THE Engagement_Handler SHALL include a `dormantRate` field in the `derivedMetrics` response, computed as `(dormant_count / total_users) * 100` rounded to 1 decimal place.
4. THE Segmentation_Widget SHALL display the `dormantRate` metric alongside existing metrics (powerUserPercentage, activationRate, idleRate).

---

### Requirement 6: Funnel Widget Churn Risk Indicator

**User Story:** As an admin, I want a churn risk metric displayed near the funnel, so that I can quickly assess the proportion of users at risk of leaving.

#### Acceptance Criteria

1. THE Engagement_Handler SHALL include a `churnRiskRate` field in the `derivedMetrics` response, computed as `((idle_count + dormant_count) / total_users) * 100` rounded to 1 decimal place.
2. THE Funnel_Widget SHALL display the `churnRiskRate` as a supplementary metric below the funnel chart.
3. WHEN `churnRiskRate` exceeds 50%, THE Funnel_Widget SHALL render the metric with a warning color to draw attention.

---

### Requirement 7: Users Table Frequency Columns

**User Story:** As an admin, I want to see "Last Active" date and "Days Ago" columns in the Users table, so that I can quickly identify inactive users.

#### Acceptance Criteria

1. THE Users_Table SHALL display a "Last Active" column showing the `lastActiveDate` formatted as a locale-aware date.
2. THE Users_Table SHALL display a "Days Ago" column showing the `daysSinceLastActive` value as a number.
3. WHEN a user has no Activity_Summary, THE Users_Table SHALL display a dash ("—") in both frequency columns.
4. THE API endpoint for the users list SHALL include `lastActiveDate` and `daysSinceLastActive` fields in each user object.

---

### Requirement 8: Users Table Frequency Status Badge

**User Story:** As an admin, I want a color-coded status badge for each user based on their frequency, so that I can visually scan for at-risk users.

#### Acceptance Criteria

1. THE Users_Table SHALL display a status badge for each user based on `daysSinceLastActive`:
   - 🟢 Active: 0–3 days
   - 🟡 Recent: 4–14 days
   - 🔴 Inactive: 15–29 days
   - ⚫ Dormant: 30+ days
2. WHEN a user has no Activity_Summary, THE Users_Table SHALL display no badge (empty state).
3. THE status badge thresholds (7, 30, 89) SHALL be derived from the Dormant_Threshold configuration where applicable.

---

### Requirement 9: Users Table Frequency Filter

**User Story:** As an admin, I want to filter the Users table by frequency status, so that I can focus on specific groups of users (e.g., only dormant users).

#### Acceptance Criteria

1. THE Users_Table SHALL provide a filter control above the table with options: "All", "Active", "Recent", "Inactive", "Dormant".
2. WHEN a frequency filter is selected, THE Users_Table SHALL display only users matching the selected Frequency_Status.
3. THE frequency filter SHALL operate client-side on the already-loaded user data.
4. THE default filter selection SHALL be "All" (no filtering applied).

---

### Requirement 10: Internationalization

**User Story:** As a user, I want all new labels to be available in English and Portuguese (pt-BR), so that the interface remains fully localized.

#### Acceptance Criteria

1. THE frontend SHALL include English translations for all new labels: "Active", "Recent", "Inactive", "Dormant", "Last Active", "Days Ago", "Churn Risk", "Dormant Rate".
2. THE frontend SHALL include Portuguese (pt-BR) translations for all new labels: "Ativo", "Recente", "Inativo", "Adormecido", "Última Atividade", "Dias Atrás", "Risco de Churn", "Taxa de Adormecidos".
3. THE build-time locale check SHALL pass with the new keys present in both `en.json` and `pt-BR.json`.

---

### Requirement 11: Backward Compatibility

**User Story:** As an admin, I want the system to work correctly even if Activity_Summary items have not been computed yet, so that existing deployments are not broken.

#### Acceptance Criteria

1. WHEN no Activity_Summary items exist in the database, THE Engagement_Handler SHALL return segmentation results with zero dormant users (all idle users remain classified as "idle").
2. WHEN the ETL_Pipeline has not yet run with the new summary logic, THE API SHALL continue to serve engagement data using the existing classification (4 categories).
3. IF the Activity_Summary item is missing for some users but present for others, THEN THE Segmentation_Engine SHALL apply dormant classification only to users with available frequency data.

---

### Requirement 13: Engagement Thresholds Configuration UI

**User Story:** As an admin, I want to configure engagement and dormancy thresholds from the Settings page, so that I can tune classification criteria without accessing AWS SSM directly.

#### Acceptance Criteria

1. THE Settings page SHALL include an "Engagement" tab displaying the current threshold configuration: power messages, power days active, active messages, active days active, and dormant days threshold.
2. THE "Engagement" tab SHALL display a help text section explaining the classification logic: what each threshold means, how users are classified into power/active/light/idle/dormant, and how frequency status badges (Active/Recent/Inactive/Dormant) relate to the dormant days threshold.
3. THE "Engagement" tab SHALL provide editable form fields for each threshold value with validation (positive integers, power > active).
4. WHEN the admin saves the thresholds, THE Settings page SHALL call PUT `/api/config/engagement-thresholds` with the updated values.
5. WHEN validation fails (e.g., power.messages <= active.messages), THE Settings page SHALL display an inline error message without submitting.
6. THE help text SHALL be internationalized (EN + PT-BR) and explain both the volume-based classification (power/active/light/idle) and the frequency-based classification (Active/Recent/Inactive/Dormant) clearly.

---

### Requirement 14: Performance

**User Story:** As an admin, I want frequency data to load quickly, so that the dashboard remains responsive.

#### Acceptance Criteria

1. THE ETL_Pipeline SHALL pre-compute Activity_Summary items during write operations, avoiding full-table scans at query time.
2. THE Analytics_Repository SHALL retrieve Activity_Summary items using direct key queries (not scans).
3. WHEN the engagement endpoint is called, THE Engagement_Handler SHALL retrieve Activity_Summary items in a single batch operation (BatchGetItem) rather than individual queries per user.
