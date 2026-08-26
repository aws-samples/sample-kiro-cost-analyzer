# Requirements Document

## Introduction

The Kiro Cost Analyzer dashboard shows a "Summary" block on the Users tab whose headline metric is "Total Users". Today that number is capped at 50 regardless of how many users actually have activity: the `/api/usage` endpoint returns at most one 50-row page and computes the summary from that single page. For any account with 50 or more active users the card therefore always reads exactly 50, which misrepresents the customer's real footprint (e.g. a customer with 127 Kiro subscriptions sees "50").

This feature corrects the summary so that it reflects the **entire** set of users with activity (subject to the currently applied filters), independent of pagination. The paginated `users` list is unchanged — only the aggregated summary is made accurate. The underlying data already contains every active user; the repository already scans and aggregates all of them. The defect is purely that the aggregated totals are never surfaced.

This feature is explicitly scoped to **active users** (users who have generated at least one usage/prompt record ingested by the ETL). Reporting the total number of paid Kiro **licenses/subscriptions** (including seats that have never generated any activity) requires ingesting the subscription roster, which the application does not do today. That capability is out of scope — see the Out of Scope section.

## Glossary

- **Usage_Handler**: The API handler (`backend/handlers/usage_handler.py`) that serves `GET /api/usage`.
- **Analytics_Repository**: The data access layer (`backend/repository/analytics_repository.py`) that reads and aggregates user stats from the Analytics_Table in DynamoDB.
- **Scan_User_Stats**: The `Analytics_Repository.scan_user_stats` method, which scans all `STATS#DAILY#` items, aggregates them by user, sorts, and returns one page plus a pagination cursor.
- **Summary_Block**: The aggregated object returned under the `summary` key of the `/api/usage` response (`totalUsers`, `totalCredits`, `totalOverageCredits`, `averageCreditsPerUser`).
- **Active_User**: A user who has at least one `STATS#DAILY#` item in the Analytics_Table within the applied filters (date range and/or subscription tier). This is the population the dashboard can count.
- **Summary_Cards**: The frontend component (`frontend/src/components/SummaryCards.tsx`) that renders the Summary_Block.
- **Filtered_Population**: The set of Active_Users remaining after the endpoint applies its filters (subscription tier and, when present, date range).
- **Page**: The bounded slice of at most `limit` users returned in a single `/api/usage` response.

---

## Requirements

### Requirement 1: Accurate total user count

**User Story:** As an admin, I want the "Total Users" card to show the real number of users with activity, so that the dashboard reflects my actual usage footprint instead of the page size.

#### Acceptance Criteria

1. THE Usage_Handler SHALL report `summary.totalUsers` as the count of every Active_User in the Filtered_Population, not the number of users in the returned Page.
2. WHEN the Filtered_Population contains more users than the page `limit`, THE Usage_Handler SHALL still report the full count in `summary.totalUsers`.
3. WHEN the Filtered_Population contains fewer users than the page `limit`, THE Usage_Handler SHALL report the exact number of Active_Users.
4. THE value of `summary.totalUsers` SHALL be independent of the `limit` and `nextToken` query parameters.

### Requirement 2: Accurate aggregated summary totals

**User Story:** As an admin, I want the credit and overage totals in the summary to reflect all users, so that the headline numbers are not silently truncated to the first page.

#### Acceptance Criteria

1. THE Usage_Handler SHALL compute `summary.totalCredits` as the sum of `totalCredits` over every Active_User in the Filtered_Population.
2. THE Usage_Handler SHALL compute `summary.totalOverageCredits` as the sum of `overageCredits` over every Active_User in the Filtered_Population.
3. THE Usage_Handler SHALL compute `summary.averageCreditsPerUser` as `summary.totalCredits` divided by `summary.totalUsers`, rounded to 2 decimal places.
4. WHEN `summary.totalUsers` is 0, THE Usage_Handler SHALL report `summary.averageCreditsPerUser` as 0.
5. THE Summary_Block values SHALL be invariant across pages: requesting page 1 and any subsequent page (via `nextToken`) for the same filters SHALL return identical Summary_Block values.

### Requirement 3: Consistency with applied filters

**User Story:** As an admin, I want the summary to match whatever filter I applied, so that filtering by subscription tier gives a correct count for that tier.

#### Acceptance Criteria

1. WHEN a `subscriptionTier` filter is applied, THE Usage_Handler SHALL compute the Summary_Block over only the Active_Users matching that tier.
2. WHEN a date range (`startDate`/`endDate`) is applied, THE Usage_Handler SHALL compute the Summary_Block over only the daily stats within that range.
3. THE set of users counted in `summary.totalUsers` SHALL be exactly the set of distinct users represented across all pages of the `users` list for the same filters.

### Requirement 4: Preserve pagination and existing response contract

**User Story:** As a developer, I want the paginated user list and the response schema to stay unchanged, so that existing clients and the export flow keep working.

#### Acceptance Criteria

1. THE Usage_Handler SHALL continue to return at most `limit` users in the `users` array (default and maximum 50).
2. THE Usage_Handler SHALL continue to return `nextToken` when more users exist beyond the current Page.
3. THE `/api/usage` response SHALL retain the existing field names and shape of the Summary_Block; only the computed values change.
4. THE per-user enrichment (`displayName`, `userName`, `tombstoned`, `lastActiveDate`, `daysSinceLastActive`) SHALL continue to apply to the returned Page only.
5. THE single-user scoped path (`userId` query parameter) SHALL be unaffected by this change.

### Requirement 5: No additional scan cost

**User Story:** As an operator, I want the accurate count to add no extra DynamoDB cost, so that fixing the number does not make the endpoint slower or more expensive.

#### Acceptance Criteria

1. THE Analytics_Repository SHALL compute the Summary_Block from the data it already aggregates during its existing full-table scan.
2. THE change SHALL NOT introduce an additional DynamoDB scan or query beyond what Scan_User_Stats already performs.

---

## Out of Scope

The following are explicitly **not** covered by this feature and are candidate future work:

- **Total licenses / subscriptions ("Option B").** Reporting the total number of paid Kiro subscriptions (e.g. 127), including seats that have never generated any activity, requires ingesting the subscription roster. The application has no data source for this today: the ETL only ingests activity CSVs and prompt logs, and IAM Identity Center is used only for name resolution (`DescribeUser` by known id) and tombstone reconciliation (`ListUsers`), never to seed the Analytics_Table. Surfacing total licenses and a license-utilization metric ("N active of M licensed") would be a separate feature.
- **Never-active idle seats.** The existing Recommendations tab (`inactiveSubscribers` in `recommendation_handler.py`) flags paid users with no recent activity, but only among users the application has ingested at least once. Seats provisioned in Kiro that never produced any usage are invisible to the application and are not addressed here; they depend on the roster ingestion above.
