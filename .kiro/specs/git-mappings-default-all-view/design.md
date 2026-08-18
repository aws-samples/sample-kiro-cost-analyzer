# Design — Default All-Mappings View

## Overview

Backend: new `list_all_mappings` (paginated scan) in the shared `GitRepository` layer, `handle_list_all_mappings` handler, and a `GET /api/git/mappings` dispatcher branch (exact-path match, evaluated before the per-user regex). Frontend: `listAllGitMappings` client function; the page fetches the all-users view on load, keeps the user `Select` as an optional filter, and shows a "load more" button while a pagination token is present.

### Design Decisions

1. **Scan with `begins_with(SK, "GITMAP#")` filter**: mappings live under per-user PKs, so a cross-user listing requires a scan (same acceptable-scale trade-off as `list_repo_configs` and `get_all_mappings_for_provider`, documented for < ~100s of items; a GSI can come later without API changes thanks to the opaque token).
2. **Opaque base64 pagination token**: the DynamoDB `LastEvaluatedKey` is JSON→base64 encoded into `lastKey`. Clients never see key internals; malformed tokens are a 400. Note: DynamoDB applies `Limit` before the filter, so the repository loops scan pages internally until it accumulates `limit` matching items or exhausts the table — the HTTP `limit` bounds returned items, not scanned pages.
3. **Exact-path dispatch before regex**: `path == "/api/git/mappings"` cannot match `_GIT_MAPPING_USER_PATTERN` (`/api/git/mappings/([^/]+)`), but the new branch is still placed first for clarity, mirroring the create (POST) branch's exact-path style.
4. **Frontend: one table, two sources**: `fetchAllMappings(reset)` (accumulating pages) vs the existing `fetchMappings(userId)`; the active source is derived from `selectedMappingUser`. The "load more" button renders only in the all-users view when a token exists — reusing the existing table rather than the heavier `UsageTable` pagination machinery, which is tied to a different data shape.

## Architecture

```mermaid
sequenceDiagram
    participant P as GitSettingsPage
    participant A as gitApi.listAllGitMappings
    participant D as Dispatcher (handler.py)
    participant H as handle_list_all_mappings
    participant R as GitRepository.list_all_mappings

    P->>A: page load (no user selected)
    A->>D: GET /api/git/mappings?limit=50
    D->>H: admin-gated
    H->>R: scan pages until 50 GITMAP items or table end
    R-->>H: items + LastEvaluatedKey?
    H-->>P: { mappings, lastKey? }
    P->>P: render; show "Load more" if lastKey
    P->>A: user clicks Load more (lastKey)
    Note over P: selecting a user switches to the existing per-user fetch
```

## Components and Interfaces

### 1. Repository layer

**File:** `layers/shared/git_shared/git_repository.py`

```python
def list_all_mappings(self, limit: int = 50, last_key: dict | None = None) -> tuple[list[dict], dict | None]:
    """Paginated cross-user mapping scan (SK begins_with GITMAP#).

    Loops internal scan pages until `limit` matching items are gathered or
    the table is exhausted. Returns (items, last_evaluated_key or None).
    """
```

### 2. Handler

**File:** `backend/handlers/git_mapping_handler.py`

```python
def handle_list_all_mappings(query_params: dict, dynamodb_resource=None) -> dict:
    # limit: int(query_params.get("limit", 50)) clamped to [1, 100]
    # lastKey: base64(JSON) -> dict; malformed -> 400 ValidationError
    # returns {"mappings": [...], "lastKey": "<token>"} (lastKey omitted when done)
```

Mapping item shape mirrors `handle_list_mappings` items (`userId`, `provider`, `gitUsername`, `createdAt`).

### 3. Dispatcher

**File:** `backend/handler.py` — before the per-user GET block:

```python
# GET /api/git/mappings — list all mappings (paginated)
if http_method == "GET" and path == "/api/git/mappings":
    if not _is_admin(claims):
        return _build_response(403, {...})
    result = git_mapping_handler.handle_list_all_mappings(query_params or {})
    status_code = result.pop("_status_code", 200) if isinstance(result, dict) else 200
    return _build_response(status_code, result)
```

Plus a `GitMappingsListAll` API event in `template.yaml` (`GET /api/git/mappings`).

### 4. Frontend

**Files:** `frontend/src/api/gitApi.ts`, `frontend/src/pages/GitSettingsPage.tsx`

```typescript
export function listAllGitMappings(params?: { limit?: string; lastKey?: string }):
  Promise<{ mappings: GitUserMapping[]; lastKey?: string }> {
  return get('/api/git/mappings', params);
}
```

Page changes:
- `useEffect` on mount (admin): `fetchAllMappings(true)`
- `mappingsLastKey` state drives the "Load more" button (appends pages)
- User `Select` `onChange`: value → `fetchMappings(userId)`; cleared → `fetchAllMappings(true)`
- Empty state: all-users view gets `gitSettings.mappings.empty.noneAnywhere`; per-user keeps existing texts
- `handleDeleteMapping` refreshes whichever view is active

### 5. Translation keys

| Key | en | pt-BR |
|---|---|---|
| `gitSettings.mappings.empty.noneAnywhere` | No mappings configured yet | Nenhum mapeamento configurado ainda |
| `gitSettings.mappings.loadMore` | Load more | Carregar mais |
| `gitSettings.mappings.userSelector.all` | All users | Todos os usuários |

## Data Models

No schema changes. Response adds an optional `lastKey: string` (opaque token) alongside the existing `mappings` array shape.

## Correctness Properties

*A correctness property is a characteristic or behavior that must hold in all valid executions of a system.*

### Property 1: Pagination completeness

*For any* set of stored mappings, iterating `GET /api/git/mappings` pages until no `lastKey` remains SHALL yield every mapping exactly once.

**Validates: Requirements 1.1, 1.2**

### Property 2: Filter equivalence

*For any* user, the per-user route's results SHALL equal the subset of the all-mappings results with that `userId`.

**Validates: Requirements 1.4, 2.3**

### Property 3: Limit bound

*For any* request, the number of returned mappings SHALL be at most the effective limit (clamped to [1, 100]).

**Validates: Requirements 1.2**

## Error Handling

| Scenario | Component | Behavior |
|---|---|---|
| Malformed `lastKey` | handler | 400 `ValidationError` |
| Non-admin | dispatcher | 403 |
| Scan failure | handler | 500 (existing error pattern, logged with errorType only) |
| Empty table | handler | `{"mappings": []}`, no `lastKey` |

## Testing Strategy

Backend pytest + moto per `tests/test_git_mapping_handler.py` conventions; frontend per `GitSettingsPage.test.tsx` conventions (default fetch on load, filter switch, load-more).

| Property | Test File | Tag |
|---|---|---|
| Property 1: Pagination completeness | `tests/test_git_mapping_handler.py` | Feature: git-mappings-default-all-view, Property 1: Pagination completeness |
| Property 2: Filter equivalence | `tests/test_git_mapping_handler.py` | Feature: git-mappings-default-all-view, Property 2: Filter equivalence |
| Property 3: Limit bound | `tests/test_git_mapping_handler.py` | Feature: git-mappings-default-all-view, Property 3: Limit bound |
