# Security

> Back to [README](../README.md)

This sample applies defense-in-depth controls aligned with a STRIDE threat model. The controls below are implemented in `template.yaml` and the sample code.

| Control | Implementation |
|---|---|
| Authentication | Cognito User Pool with SRP, password policy (8+ chars, upper/lower/numbers) |
| Authorization | API Gateway Cognito Authorizer + server-side admin group check |
| User-scoping | Non-admins restricted to own data via `custom:kiro_user_id` JWT claim |
| CORS | Restricted to CloudFront domain (no wildcard) |
| CSP | Content-Security-Policy, HSTS, X-Frame-Options: DENY via CloudFront |
| Token security | 1h ID/access token, 7-day refresh token, GlobalSignOut on logout |
| Secrets | Git PATs (GitHub and GitLab) in SSM SecureString (KMS), never exposed in API responses |
| Identity bridging | Cognito sub ↔ Kiro userId linked via custom attribute |
| Encryption | S3 AES-256 at rest. All AWS-managed connections use TLS in transit. The agent-to-GitLab connection follows the scheme configured for the GitLab instance (`https` recommended; `http` supported for a self-hosted instance served over plain HTTP per Requirement 10.3). Certificate verification is always enabled when `https` is used, with no opt-out — see [TLS certificate trust](deploy.md#tls-certificate-trust). The agent-to-GitHub connection is always `https`, with certificate verification always enabled. |

## Known `npm audit` finding — not applicable to this app

`npm audit` reports one advisory that cannot be silenced by upgrading, because no newer `react-router-dom` version exists yet:

- **GHSA-qwww-vcr4-c8h2** ("RSC Mode CSRF Bypass") — the advisory's affected range spans `react-router` `>=7.12.0 <7.18.2` and `>=8.0.0 <8.3.0`. `frontend/package.json` pins `react-router-dom@^7.18.2`, the latest published `react-router-dom` release and the patched floor of the 7.x line named in the advisory. `react-router` itself has since published `8.3.0`, but `react-router-dom` (the package this app depends on) has not — so `npm audit` still flags `7.18.2` because its own transitive `react-router` resolves inside the still-open `<8.3.0` upper bound of the *unpatched* 8.x range, not because a newer fix exists that this app is missing.
- **Not exploitable here.** The vulnerability only affects apps using React Router's `unstable_` RSC (React Server Components) APIs — `unstable_routeRSCServerRequest`, `unstable_RSCStaticRouter`, and related entry points. This app is a standard client-rendered SPA (Cognito + Cloudscape + `react-router-dom`'s `BrowserRouter`/`Routes` API in `frontend/src/App.tsx`); it does not import or reference any RSC or `unstable_` API. Verified via `grep -r "unstable_\|RSC" frontend/src` returning no matches.
- **Re-check when `react-router-dom@8.x` or a `7.18.x` re-release ships** — re-run `npm audit` after any future `react-router`/`react-router-dom` bump to confirm the advisory has cleared.

## Known finding, planned fix — `s3:ListBucket` wildcard on the source-bucket validation endpoint

`template.yaml`'s `ValidateSourceBucket` IAM statement grants `s3:ListBucket` on `Resource: "arn:aws:s3:::*"` so `PUT /api/config/bucket` (`backend/handlers/config_handler.handle_put_config_bucket`) can call `HeadBucket` against an admin-supplied bucket name before persisting it — `HeadBucket` has no narrower dedicated IAM action. This has been flagged repeatedly by security scans as excessive scope (an attacker with access to this Lambda could enumerate bucket existence account-wide, though never read or write object data).

**Planned fix (TODO, not yet implemented):** remove the "reconfigure source bucket" feature entirely — the Settings page's bucket field, the `PUT /api/config/bucket` route, `handle_put_config_bucket`, and the `ValidateSourceBucket` statement together. Changing the source bucket after initial deploy is expected to be rare; a redeploy with a new `SourceBucketName` template parameter is an acceptable path for the few who need it, and removing the hot-swap capability removes the wildcard grant rather than continuing to carry it as an accepted trade-off. Decided 2026-08-01.

## Threat model

The STRIDE threat model and its mitigations are tracked under `.threatmodel/` and the relevant specs in `.kiro/specs/` (for example, `custom-auth-cloudfront`, `remove-prompt-content-visibility`, and `user-tombstoning`).

## Reporting a vulnerability

See [SECURITY.md](../SECURITY.md). Do **not** open a public GitHub issue for security findings.
