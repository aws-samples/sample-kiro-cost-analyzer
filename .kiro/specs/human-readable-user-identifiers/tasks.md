# Implementation Plan: Human-Readable User Identifiers

## Overview

Issue #18 (F3): backend `displayName or userName` fallback at the single resolution choke point + frontend fallback chain in 3 spots.

## Tasks

- [x] 1. Backend fallback
  - [x] 1.1 `_lookup_user_metadata`: `displayName = displayName or userName` (`backend/handlers/usage_handler.py`)
    - _Requirements: 1.1, 1.2, 1.3_
  - [x]* 1.2 Test: Property 1 in `tests/test_usage_handler.py`
    - **Validates: Requirements 1.1, 1.3**

- [x] 2. Frontend fallback chain
  - [x] 2.1 `UsageTable.tsx` + `RecommendationsTab.tsx`: `displayName || userName || truncateId(userId)`
    - _Requirements: 2.1, 2.3_
  - [x] 2.2 Git settings delete modal: resolve name via `userOptions` lookup
    - _Requirements: 2.2_
  - [x]* 2.3 Test: Property 2 (no full UUID as primary cell)
    - **Validates: Requirements 2.1**

- [x] 3. Checkpoint — pytest + frontend build/tests + full deploy + user validation

## Notes

- Tasks marked with `*` are optional and can be skipped for a faster MVP
- Backend change → full `make deploy`
