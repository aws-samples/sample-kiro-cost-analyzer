# Design — Release Automation and Version Display

## Overview

Three small, decoupled pieces: (1) a `VERSION` file injected into the frontend bundle at build time and rendered as a header utility; (2) a `workflow_dispatch` release workflow that bumps VERSION, promotes the changelog, and opens a Release PR; (3) a push-triggered publish workflow that tags and creates the GitHub Release when the VERSION change lands on `main`. A PR-title lint rounds it out. The human-curated changelog (steering §8.4) remains the release-notes source — no generation from commit messages.

### Design Decisions

1. **Custom workflow over release-please**: release-please generates changelog content from conventional-commit subjects, which would replace the repository's narrative, security-detailed changelog or force maintaining two changelogs. The mechanical parts (bump, promote, tag, publish) are ~150 lines of workflow + script; the curated content pipeline stays untouched.
2. **VERSION file as the single source**: plain text, trivially readable from Vite config, shell, and Python. The changelog heading, git tag, GitHub Release, and UI badge all derive from it.
3. **Two-phase release (PR → merge → tag)**: the Release PR keeps a human in the loop (title/entry review) and respects the protected `main`; the publish phase triggers on `push` to `main` filtered to `VERSION` changes, making tag + Release creation automatic and idempotent.
4. **Promotion script in Python**: `scripts/promote_changelog.py` handles VERSION bump + changelog rewrite; runnable locally (dry-run) and from CI. Python over Node because it has zero dependency needs and matches the repo's script conventions (`scripts/`).
5. **Header utility over footer**: the app is a Cloudscape `AppLayout` without a native footer; `TopNavigation.utilities` accepts a plain link/text slot rendered small and right-aligned on every page, including the login layout. Clicking opens the changelog on GitHub.
6. **Version is brand-like**: rendered as `v3.4` verbatim in every locale — no i18n key needed for the value itself (mirrors the `brand.*` no-translation rule).

## Architecture

```mermaid
sequenceDiagram
    participant M as Maintainer
    participant W1 as release.yml (workflow_dispatch)
    participant S as scripts/promote_changelog.py
    participant PR as Release PR
    participant W2 as publish-release.yml (push: main, VERSION)
    participant GH as Git tag + GitHub Release

    M->>W1: run with bump=minor, title="..."
    W1->>S: python scripts/promote_changelog.py --bump minor --title "..."
    S->>S: VERSION 3.4 -> 3.5; Unreleased -> "## v3.5 — ... (date)"; fresh Unreleased
    W1->>PR: open Release PR (branch release/v3.5)
    M->>PR: review + merge
    PR->>W2: push to main touching VERSION
    W2->>GH: tag v3.5 + Release (notes = promoted section)
```

## Components and Interfaces

### 1. VERSION file

**File:** `VERSION` (root) — content: `3.4` (no `v` prefix, trailing newline).

### 2. Vite injection + UI badge

**Files:** `frontend/vite.config.ts`, `frontend/src/vite-env.d.ts` (or `src/types`), `frontend/src/App.tsx`

```typescript
// vite.config.ts — read at config-eval time; throws if missing (Req 1.3)
import { readFileSync } from 'node:fs'
const appVersion = readFileSync(new URL('../VERSION', import.meta.url), 'utf-8').trim()
// in the returned config:
define: { global: 'globalThis', __APP_VERSION__: JSON.stringify(appVersion) },
```

```typescript
// global declaration
declare const __APP_VERSION__: string;
```

```tsx
// App.tsx — appended to the utilities array of BOTH TopNavigation instances
const versionUtility = {
  type: 'button' as const,
  text: `v${__APP_VERSION__}`,
  href: 'https://github.com/aws-samples/sample-kiro-cost-analyzer/blob/main/docs/changelog.md',
  external: true,
  externalIconAriaLabel: t('nav.versionAriaLabel'),
};
```

Vitest note: `__APP_VERSION__` is also defined in the `test` config block so component tests render.

### 3. Promotion script

**File:** `scripts/promote_changelog.py`

```
usage: promote_changelog.py --bump {major,minor,patch} --title TITLE [--date YYYY-MM-DD] [--dry-run]
```

- Reads `VERSION`, computes next (major: X+1.0; minor: X.Y+1; patch: X.Y.Z+1 — a two-part version gains `.1`).
- Rewrites `docs/changelog.md`: asserts `## Unreleased` exists and is non-empty (Req 3.4), replaces the heading with `## v{next} — {title} ({date})`, inserts `## Unreleased` + blank line above.
- Writes `VERSION`; prints the new version to stdout (consumed by the workflow).

### 4. Release workflow

**File:** `.github/workflows/release.yml` — `workflow_dispatch` with inputs `bump` (choice) and `title` (string). Steps: checkout → run script → `peter-evans/create-pull-request` to open `release/v{next}` with a `chore: release v{next}` commit.

### 5. Publish workflow

**File:** `.github/workflows/publish-release.yml` — `on: push: branches: [main], paths: [VERSION]`. Steps: read VERSION → skip if tag exists (Req 4.3) → extract the version's changelog section via the script's `--extract` mode → `git tag -a v{X}` + `gh release create v{X} --notes-file`.

### 6. PR title lint

**File:** `.github/workflows/pr-title.yml` — `amannn/action-semantic-pull-request` on `pull_request` events (opened, edited, synchronize).

## Data Models

None. The VERSION string grammar: `MAJOR.MINOR` or `MAJOR.MINOR.PATCH` (matches historical `v3.1.2` / `v3.3` style).

## Correctness Properties

*A correctness property is a characteristic or behavior that must hold in all valid executions of a system.*

### Property 1: Bump arithmetic

*For any* valid version string, bumping SHALL produce: major → `{X+1}.0`; minor → `{X}.{Y+1}`; patch → `{X}.{Y}.{Z+1}` (with `Z=0` assumed when absent), and the result SHALL parse as a valid version.

**Validates: Requirements 3.2**

### Property 2: Changelog conservation

*For any* promotion, the promoted document SHALL contain every line of the previous Unreleased section under the new version heading, a fresh empty Unreleased section above it, and all prior version sections unchanged.

**Validates: Requirements 3.3**

### Property 3: Empty-release refusal

*For any* changelog whose Unreleased section contains no content lines, the script SHALL exit non-zero and leave both files unmodified.

**Validates: Requirements 3.4**

## Error Handling

| Scenario | Component | Behavior |
|---|---|---|
| VERSION missing at build | vite.config.ts | Build throws (fail-loud) |
| Empty Unreleased | promote script | Exit 1, no writes |
| Malformed VERSION | promote script | Exit 1 with parse error |
| Tag already exists | publish workflow | Skip tag/release creation, succeed |
| Release PR closed unmerged | — | Nothing published (publish keys on VERSION change reaching main) |

## Testing Strategy

Script tested with pytest (pure functions extracted: `bump_version`, `promote_text`). UI badge asserted in an existing App-level test if present, otherwise via build verification.

| Property | Test File | Tag |
|---|---|---|
| Property 1: Bump arithmetic | `tests/test_promote_changelog.py` | Feature: release-automation, Property 1: Bump arithmetic |
| Property 2: Changelog conservation | `tests/test_promote_changelog.py` | Feature: release-automation, Property 2: Changelog conservation |
| Property 3: Empty-release refusal | `tests/test_promote_changelog.py` | Feature: release-automation, Property 3: Empty-release refusal |
