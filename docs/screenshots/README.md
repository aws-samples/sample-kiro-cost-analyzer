# Screenshots — capture guidelines

This folder holds the UI screenshots referenced from the project [`README.md`](../../README.md). Read this before adding or replacing an image.

## Filenames in use

| File | Where it appears | What it shows |
|---|---|---|
| `dashboard.png` | Hero block in the root README | Account Overview cards, daily-usage timeline, and tier/client-type breakdowns |
| `users.png` | README → Capabilities → Dashboard and analytics | Per-user usage table with sort, filters, and pagination |
| `breakdown-by-tier.png` | README → Capabilities → Dashboard and analytics | Stacked breakdowns of credit consumption by subscription tier and by client type |
| `recommendations.png` | README → Capabilities → Tier optimization | Recommendations tab showing summary card, filterable table, and per-row upgrade/downgrade badges |
| `user-engagement.png` | README → Capabilities → User engagement and segmentation | Engagement funnel and Power/Active/Light/Idle/Dormant segmentation panel |
| `user-activity-report-1.png` | README → Capabilities → AI-powered analysis | Per-user productivity report with the Git-Kiro Impact Score |
| `insights.png` | README → Capabilities → AI-powered analysis | Bilingual AI-generated insights panel from the productivity report |

## Dimensions and format

- **Capture at 1600 × 900 or 1920 × 1080** (16:9, deterministic). GitHub renders at content width (~800–1100 px wide on desktop) and scales down cleanly from 1600+.
- **PNG, no further compression.** Avoid JPEG (compression artifacts on UI text).
- **Light theme** for the hero. Either theme is fine for the capability shots, but pick one and stay consistent across all four.
- **No browser chrome.** Use a "viewport-only" capture (e.g., DevTools device toolbar at a fixed size, or a screenshot tool's "capture this region"). Cropping the OS window frame in post is also fine.
- **No browser dev tools, browser tabs, OS dock, or notification bell** in the frame.

## Anonymization

The dashboard renders real user identities by design. Before committing:

- **Replace user names and emails** with realistic synthetic equivalents. `anna.silva@example.com` is fine; `vinibat@amazon.com` is not.
- **Replace AWS account IDs** if any leak into the UI (none should at this writing — confirm before merging).
- **Replace Git usernames and repository names** with neutral placeholders (`acme-corp/api-service`).
- **Avoid screenshots taken on production data.** Either run the seed script (`scripts/seed_test_data.py`) to populate a synthetic dataset, or post-process the image to redact.

If you cannot fully anonymize via the seed dataset, prefer **blurring** over **black bars** — blurring preserves the layout's readability for the reader. Use a 12 px Gaussian blur on names/emails; the result should be visibly redacted but the table structure remains legible.

## Replacing an existing screenshot

1. Take the new capture following the dimensions and anonymization rules above.
2. Save it under the canonical filename (see table above) — do not introduce a new name.
3. Open `README.md` and confirm the alt text still describes the new image accurately. Update the alt text in the same PR if the visible content materially changed.
4. Add a one-line entry under `Unreleased` in [`docs/changelog.md`](../changelog.md) noting the screenshot refresh.

## When to re-shoot

Re-take a screenshot when:

- A new top-level navigation item is added or removed.
- A capability's primary surface changes (the Recommendations tab gets a new chart, the Productivity page rearranges Impact Score).
- The brand strings under `frontend/src/locales/*.json` change.
- The image is more than ~12 months old and the UI has visibly drifted.

A version bump or a behind-the-scenes refactor that does not change the rendered UI is **not** a reason to re-shoot.
