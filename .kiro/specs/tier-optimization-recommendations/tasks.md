# Implementation Plan: Tier Optimization Recommendations

## Overview

This plan implements the tier optimization recommendations feature incrementally: starting with the pure backend logic (recommendation engine with Decimal arithmetic), then the handler and route registration, followed by the frontend components (Recommendations tab, badges, modal, pricing settings panel), and finally internationalization. The recommendation engine is a pure-function module with no I/O, enabling comprehensive property-based testing via Hypothesis.

## Tasks

- [x] 1. Implement the recommendation engine (pure logic)
  - [x] 1.1 Create `backend/handlers/recommendation_engine.py` with `TierConfig`, `PricingConfig`, `UserUsageData`, `Recommendation`, `RecommendationResult`, `RecommendationSummary` frozen dataclasses, plus `validate_pricing_config()`, `parse_pricing_config()`, and `compute_recommendations()` functions
    - Use `from dataclasses import dataclass` with `frozen=True` for immutability
    - Use `from decimal import Decimal` for all monetary calculations
    - `validate_pricing_config` checks: 2–10 tiers, ascending `monthlyPrice`, positive `includedCredits` (int), non-negative `monthlyPrice`, positive `overagePricePerCredit`, non-empty tier names
    - `parse_pricing_config` converts validated dict into `PricingConfig` with tiers sorted by ascending price; raises `ValueError` if invalid
    - `compute_recommendations` implements: projection (`total_credits / days_elapsed × 30`), overage cost (`max(0, projected - included) × rate`), optimal upgrade search (maximize annual savings across all higher tiers), downgrade check (projected < lower tier's included credits)
    - Only process users with `overage_enabled = True`
    - Skip upgrade for highest-tier users; skip downgrade for lowest-tier users
    - Skip upgrade for users with zero projected overage
    - Sort recommendations by `annual_savings` descending
    - Use try/except import pattern for compatibility with Lambda and test environments
    - No imports of boto3, os, or logging — pure functions only
    - _Requirements: 1.2, 1.4, 1.6, 2.1, 2.2, 2.3, 2.5, 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 5.1, 5.2, 5.3, 5.4, 6.3, 6.4, 10.1, 10.2, 10.6_

  - [ ]* 1.2 Write property test for pricing config validation round-trip
    - **Property 1: Pricing config validation round-trip**
    - File: `tests/test_recommendation_engine_properties.py`
    - Use Hypothesis to generate valid PricingConfig instances (2–10 tiers, ascending prices, positive credits, positive overage rate)
    - Assert `validate_pricing_config` accepts all valid configs
    - Assert `parse_pricing_config` followed by serialization produces equivalent config
    - Minimum 100 iterations
    - **Validates: Requirements 1.2, 1.4, 1.6, 2.1, 2.2, 2.3, 2.5**

  - [ ]* 1.3 Write property test for invalid config rejection
    - **Property 2: Invalid configs are rejected with field-specific errors**
    - Generate configs violating at least one rule (non-positive credits, non-ascending prices, empty tier name, tier count outside 2–10, non-positive overage rate)
    - Assert `validate_pricing_config` returns `(False, error_message)` with non-empty message
    - **Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.5**

  - [ ]* 1.4 Write property test for projection linearity
    - **Property 3: Projection linearity**
    - Generate positive `total_credits` and `days_elapsed`, plus a scalar multiplier `k > 0`
    - Assert multiplying total_credits by `k` multiplies projected_monthly_usage by exactly `k`
    - Assert `projected_monthly_usage = (total_credits / days_elapsed) × 30`
    - Use Decimal arithmetic for exact comparison
    - **Validates: Requirements 3.2, 10.6**

  - [ ]* 1.5 Write property test for overage computation correctness
    - **Property 4: Overage computation correctness**
    - Generate projected usage `P`, included credits `C`, and overage rate `R`
    - Assert overage cost equals `max(0, P - C) × R`
    - Assert overage cost is zero when `P ≤ C`
    - **Validates: Requirements 3.3, 3.4**

  - [ ]* 1.6 Write property test for upgrade non-negative annual savings
    - **Property 5: Upgrade recommendations have non-negative annual savings**
    - Generate valid user lists and pricing configs
    - Assert every recommendation with `recommendation_type = "upgrade"` has `annual_savings >= 0`
    - **Validates: Requirements 4.4, 10.3**

  - [ ]* 1.7 Write property test for zero overage implies no upgrade
    - **Property 6: Zero overage implies no upgrade recommendation**
    - Generate users with `projected_monthly_usage ≤ current_tier.includedCredits`
    - Assert no upgrade recommendation is produced for those users
    - **Validates: Requirements 4.7, 10.4**

  - [ ]* 1.8 Write property test for highest-tier no upgrade
    - **Property 7: Highest-tier users receive no upgrade**
    - Generate users on the highest tier (max monthlyPrice)
    - Assert no upgrade recommendation regardless of usage level
    - **Validates: Requirements 4.5**

  - [ ]* 1.9 Write property test for optimal tier maximizes savings
    - **Property 8: Optimal tier maximizes savings**
    - For each upgrade recommendation, assert no alternative higher tier produces greater annual savings
    - **Validates: Requirements 4.6**

  - [ ]* 1.10 Write property test for downgrade only when usage fits lower tier
    - **Property 9: Downgrade only when projected usage fits lower tier**
    - Assert downgrade is produced iff `projected_monthly_usage < next_lower_tier.includedCredits`
    - Assert no downgrade when `projected_monthly_usage >= next_lower_tier.includedCredits`
    - **Validates: Requirements 5.1, 5.3, 10.5**

  - [ ]* 1.11 Write property test for lowest-tier no downgrade
    - **Property 10: Lowest-tier users receive no downgrade**
    - Generate users on the lowest tier (min monthlyPrice)
    - Assert no downgrade recommendation regardless of usage level
    - **Validates: Requirements 5.4**

  - [ ]* 1.12 Write property test for overage-enabled filter
    - **Property 11: Only overage-enabled users receive recommendations**
    - Generate users with `overage_enabled = False`
    - Assert no recommendation (neither upgrade nor downgrade) is produced
    - **Validates: Requirements 3.5**

  - [ ]* 1.13 Write property test for summary consistency
    - **Property 12: Response summary consistency**
    - For any `RecommendationResult`, assert summary fields match computed values from recommendations list
    - Assert `total_recommendations == len(recommendations)`
    - Assert `upgrade_count` and `downgrade_count` match filtered counts
    - Assert `total_projected_annual_savings == sum(annual_savings)`
    - Assert recommendations sorted by `annual_savings` descending
    - **Validates: Requirements 6.3, 6.4**

  - [ ]* 1.14 Write property test for determinism
    - **Property 13: Determinism**
    - Call `compute_recommendations` twice with identical inputs
    - Assert outputs are identical (byte-for-byte via dataclass equality)
    - **Validates: Requirements 10.1, 10.2**

- [x] 2. Checkpoint — Verify recommendation engine pure logic
  - Ensure all tests pass, ask the user if questions arise.

- [x] 3. Implement the recommendation handler and route registration
  - [x] 3.1 Create `backend/handlers/recommendation_handler.py` with `handle_get_recommendations()`, `handle_get_tier_pricing()`, and `handle_put_tier_pricing()` functions
    - Follow the same pattern as `engagement_handler.py` (dependency injection for `dynamodb_resource`, `ssm_client`)
    - `handle_get_recommendations` reads pricing config from SSM (`/kiro-cost-analyzer/tier-pricing`), returns 400 if not configured, scans user stats from DynamoDB (current month: first day of month → today), builds `UserUsageData` list, calls `compute_recommendations()`, serializes Decimal values to float for JSON response
    - `handle_get_tier_pricing` reads from SSM and returns current config or 404 status if not configured
    - `handle_put_tier_pricing` validates via `validate_pricing_config()`, writes to SSM on success, returns validation error on failure
    - Use `from datetime import date` to compute current month boundaries
    - Use structured logging for errors
    - SSM parameter path: `/kiro-cost-analyzer/tier-pricing`
    - _Requirements: 1.1, 1.3, 1.5, 3.1, 6.1, 6.2, 6.3, 6.4, 6.5, 6.6_

  - [x] 3.2 Register routes in `backend/handler.py`
    - Add `GET /api/recommendations/tier-optimization` → `recommendation_handler.handle_get_recommendations(query_params)` (admin-only)
    - Add `GET /api/config/tier-pricing` → `recommendation_handler.handle_get_tier_pricing()` (admin-only)
    - Add `PUT /api/config/tier-pricing` → `recommendation_handler.handle_put_tier_pricing(body)` (admin-only)
    - Import `recommendation_handler` in the imports section
    - _Requirements: 6.1, 6.5_

  - [ ]* 3.3 Write unit tests for `recommendation_handler.py`
    - File: `tests/test_recommendation_handler.py`
    - Use moto `@mock_aws` to mock DynamoDB and SSM
    - Test: correct response structure with recommendations and summary
    - Test: 400 response when pricing config not in SSM
    - Test: pricing CRUD (get configured, get not configured, put valid, put invalid)
    - Test: only overage-enabled users are processed
    - Test: Decimal serialization to JSON-safe floats
    - _Requirements: 1.3, 6.1, 6.2, 6.5, 6.6_

- [x] 4. Checkpoint — Verify backend API integration
  - Ensure all tests pass, ask the user if questions arise.

- [x] 5. Add frontend types and API client usage
  - [x] 5.1 Add TypeScript interfaces to `frontend/src/types/index.ts`
    - Add `TierRecommendation`, `RecommendationSummary`, `TierRecommendationsResponse`, `TierPricingEntry`, `TierPricingConfig`, and `TierPricingResponse` interfaces
    - Match the backend API response schema exactly
    - _Requirements: 6.2, 6.3_

- [x] 6. Implement the Recommendations Tab component
  - [x] 6.1 Create `frontend/src/components/RecommendationsTab.tsx`
    - Fetch data from `/api/recommendations/tier-optimization` using the shared `get()` client
    - Display a Cloudscape `Container` summary card showing `totalProjectedAnnualSavings`, `upgradeCount`, `downgradeCount`
    - Display a Cloudscape `Table` with columns: User, Current Tier, Projected Monthly Usage, Recommended Tier, Projected Annual Savings, Recommendation Type
    - Add Cloudscape `Select` filter for recommendation type (All, Upgrade, Downgrade)
    - Display count of recommendations matching current filter
    - Show `SkeletonLoader` during loading
    - Show Cloudscape `Alert` with retry button on error
    - Show setup prompt with link to Settings when API returns 400 (pricing not configured)
    - Show empty state message when recommendations array is empty
    - Format currency values using `formatNumber` from `useI18n()` with `{ style: 'currency', currency: 'USD' }`
    - Use `useI18n()` for all labels
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7, 7.8, 11.1, 11.5_

- [x] 7. Implement the TierBadge component
  - [x] 7.1 Create `frontend/src/components/TierBadge.tsx`
    - Accept props: `recommendation: TierRecommendation | null`, `onClick: () => void`
    - Render nothing when `recommendation` is null
    - Render a Cloudscape `Badge` with "↑ Upgrade" or "↓ Downgrade" text based on `recommendationType`
    - Use color variants: blue for upgrade, grey for downgrade
    - Make badge clickable (triggers `onClick`)
    - Use `useI18n()` for badge text
    - _Requirements: 8.1, 8.2, 11.3_

- [ ] 8. Implement the RecommendationModal component
  - [x] 8.1 Create `frontend/src/components/RecommendationModal.tsx`
    - Accept props: `recommendation: TierRecommendation | null`, `visible: boolean`, `onDismiss: () => void`
    - Implement as a Cloudscape `Modal` component
    - Display: current tier, projected monthly usage, current monthly cost (tier price + projected overage), recommended tier, recommended tier monthly cost, estimated annual savings
    - Use Cloudscape `ColumnLayout` for structured data display
    - Format all monetary values as USD using `formatNumber` from `useI18n()`
    - Use `useI18n()` for all labels
    - _Requirements: 8.3, 8.4, 8.5, 11.3_

- [x] 9. Integrate TierBadge into the Users table
  - [x] 9.1 Modify `frontend/src/components/UsageTable.tsx` to display `TierBadge` next to user names
    - Fetch recommendations from `/api/recommendations/tier-optimization` (cache in component state)
    - Match recommendations to users by `userId`
    - Render `TierBadge` inline next to the user's display name column
    - On badge click, open `RecommendationModal` with the selected recommendation
    - Handle case where recommendations API returns error (gracefully hide badges)
    - _Requirements: 8.1, 8.2, 8.3_

- [x] 10. Integrate Recommendations Tab into the Dashboard page
  - [x] 10.1 Add `RecommendationsTab` as a new tab in `DashboardPage.tsx`
    - Add a third tab alongside "overview" and "users" tabs with id "recommendations"
    - Update `TabId` type to include `'recommendations'`
    - Tab label uses `t('recommendations.tab.title')`
    - Tab content renders `<RecommendationsTab />`
    - _Requirements: 7.1_

- [x] 11. Checkpoint — Verify frontend recommendations display
  - Ensure all tests pass, ask the user if questions arise.

- [x] 12. Implement the Pricing Settings Panel
  - [x] 12.1 Create `frontend/src/components/PricingSettingsPanel.tsx`
    - Fetch current pricing config from `GET /api/config/tier-pricing`
    - Display editable form with fields for each tier (name, monthly price, included credits) and overage price per credit
    - Allow adding tiers (up to 10) and removing tiers (minimum 2)
    - Client-side validation: non-empty tier names, non-negative monthly price, positive included credits, positive overage rate, ascending price order
    - Display inline validation errors next to relevant fields
    - On submit, call `PUT /api/config/tier-pricing`
    - Display Cloudscape `Flashbar` success notification on save
    - Display API validation errors inline
    - Show loading skeleton while fetching config
    - Show empty/setup state when config is not yet configured
    - Use Cloudscape `Form`, `FormField`, `Input`, `Button`, `SpaceBetween`, `Container`
    - Use `useI18n()` for all labels and messages
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 9.7, 11.2_

  - [x] 12.2 Integrate `PricingSettingsPanel` into `SettingsPage.tsx`
    - Add as a new `Container` section in the Settings page
    - Only render for admin users (check via `useAuth()` hook)
    - Place after the existing Cross-Account section
    - _Requirements: 9.1, 9.6_

- [x] 13. Add internationalization keys
  - [x] 13.1 Add all `recommendations.*` and `tierPricing.*` keys to `frontend/src/locales/en.json`
    - Add keys for: tab title, table column headers, recommendation types (upgrade/downgrade), summary card labels, filter options, badge text, modal labels, pricing settings form labels, validation messages, loading/error/empty states, success notifications, setup prompt
    - Maintain alphabetical sort order
    - _Requirements: 11.1, 11.2, 11.3, 11.4_

  - [x] 13.2 Add all `recommendations.*` and `tierPricing.*` keys to `frontend/src/locales/pt-BR.json`
    - Translate all keys added in 13.1 to Brazilian Portuguese
    - Maintain identical key set and alphabetical sort order
    - _Requirements: 11.1, 11.2, 11.3, 11.4_

  - [x] 13.3 Regenerate `frontend/src/locales/keys.d.ts` by running the locale check script
    - Run `npx ts-node scripts/check-locales.ts` (or equivalent build step)
    - Verify both catalogs pass parity check
    - _Requirements: 11.4_

- [x] 14. Checkpoint — Verify full integration
  - Ensure all tests pass, ask the user if questions arise.

- [ ]* 15. Write frontend component tests
  - [ ]* 15.1 Write tests for `RecommendationsTab`
    - Test loading skeleton display
    - Test error alert with retry button
    - Test setup prompt when pricing not configured
    - Test table renders correct columns and data
    - Test filter by recommendation type works
    - Test recommendation count updates with filter
    - Test currency formatting uses locale-aware formatNumber
    - _Requirements: 7.2, 7.4, 7.5, 7.6, 7.7, 7.8, 11.1_

  - [ ]* 15.2 Write tests for `TierBadge`
    - Test renders nothing when recommendation is null
    - Test renders upgrade badge with correct text
    - Test renders downgrade badge with correct text
    - Test click handler fires
    - _Requirements: 8.1, 8.2_

  - [ ]* 15.3 Write tests for `RecommendationModal`
    - Test modal displays all detail fields
    - Test currency formatting
    - Test dismiss callback
    - _Requirements: 8.3, 8.4, 8.5_

  - [ ]* 15.4 Write tests for `PricingSettingsPanel`
    - Test loading state
    - Test form renders current config
    - Test client-side validation (empty name, negative price, non-ascending prices)
    - Test add/remove tier buttons
    - Test successful save shows notification
    - Test API error displays inline
    - _Requirements: 9.2, 9.3, 9.4, 9.5, 9.7_

  - [ ]* 15.5 Write fast-check property tests for pricing validation consistency
    - File: `frontend/src/components/__tests__/pricingValidation.property.test.ts`
    - Test: client-side validation accepts all configs that server-side validation accepts
    - Test: currency formatting always produces valid USD string for any non-negative Decimal
    - _Requirements: 9.3, 11.5_

- [x] 16. Final checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests (Hypothesis) validate all 13 correctness properties defined in the design
- The recommendation engine is a pure-function module with no I/O, enabling comprehensive property-based testing without mocks
- All monetary calculations use Python `Decimal` to avoid floating-point precision errors
- All UI strings go through `useI18n()` — no hardcoded text
- The recommendation API is admin-only; badges in the users table gracefully degrade if the API call fails
- Frontend uses Cloudscape components exclusively
