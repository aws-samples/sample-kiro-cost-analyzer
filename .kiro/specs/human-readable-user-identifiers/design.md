# Design — Human-Readable User Identifiers

## Overview

One backend change at the single choke point plus three targeted frontend fallbacks. No new hooks or endpoints: name resolution already happens server-side; the defect is that unresolved users ship `displayName: ""` and every consumer falls back to the raw UUID.

### Design Decisions

1. **Fix at `_lookup_user_metadata`** (`backend/handlers/usage_handler.py`): every `displayName` consumer flows through this helper, so applying `displayName = displayName or userName` here fixes usage listing, user detail, and recommendations at once (Req 1.2) with a one-line change.
2. **No shared frontend hook**: resolution is server-side; the frontend only needs a safer last-resort chain (`userName` → truncated UUID) in the two cells that render `displayName || userId`, plus the delete modal reusing the mappings-table lookup. A hook would add indirection for three call sites.
3. **Truncated UUID as terminal fallback**: `userId.slice(0, 8) + '…'` matches the existing `UsersPage` pattern (`kiroId.slice(0,12)…`) and keeps rows scannable; the full UUID remains available in intentional subtitle spots (unchanged, Req 2.3).

## Components and Interfaces

### 1. Backend — `_lookup_user_metadata`

```python
"displayName": display_name or user_name,  # fall back to userName (Req 1.1)
```
Applied where the item fields are read (`display_name = item.get(...)`, `user_name = item.get(...)`).

### 2. Frontend — fallback chain

- `UsageTable.tsx` primary cell: `item.displayName || item.userName || truncateId(item.userId)`
- `RecommendationsTab.tsx` primary cell: same chain
- `GitSettingsPage.tsx` delete modal: `userOptions.find((o) => o.value === mappingDeleteTarget?.userId)?.label ?? mappingDeleteTarget?.userId`
- `truncateId` helper: local, `(id) => id.slice(0, 8) + '…'`

## Correctness Properties

*A correctness property is a characteristic or behavior that must hold in all valid executions of a system.*

### Property 1: Non-empty display name with userName present

*For any* user metadata row with a non-empty `userName`, the returned `displayName` SHALL be non-empty.

**Validates: Requirements 1.1, 1.3**

### Property 2: No full raw UUID as primary identifier

*For any* user row rendered by `UsageTable`/`RecommendationsTab`, the primary cell SHALL never equal the full 36-character `userId`.

**Validates: Requirements 2.1**

## Error Handling

| Scenario | Behavior |
|---|---|
| UserNamesTable row missing / lookup error | Existing empty-metadata path; frontend chain renders truncated UUID |
| displayName and userName both empty | Truncated UUID (terminal fallback) |

## Testing Strategy

| Property | Test File | Tag |
|---|---|---|
| Property 1 | `tests/test_usage_handler.py` | Feature: human-readable-user-identifiers, Property 1: Non-empty display name with userName present |
| Property 2 | `frontend/src/components/UsageTable.test.tsx` (new, example-based) | Feature: human-readable-user-identifiers, Property 2: No full raw UUID as primary identifier |
