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

## Known finding, planned fix — `s3:ListBucket` wildcard on the source-bucket validation endpoint

`template.yaml`'s `ValidateSourceBucket` IAM statement grants `s3:ListBucket` on `Resource: "arn:aws:s3:::*"` so `PUT /api/config/bucket` (`backend/handlers/config_handler.handle_put_config_bucket`) can call `HeadBucket` against an admin-supplied bucket name before persisting it — `HeadBucket` has no narrower dedicated IAM action. This has been flagged repeatedly by security scans as excessive scope (an attacker with access to this Lambda could enumerate bucket existence account-wide, though never read or write object data).

**Planned fix (TODO, not yet implemented):** remove the "reconfigure source bucket" feature entirely — the Settings page's bucket field, the `PUT /api/config/bucket` route, `handle_put_config_bucket`, and the `ValidateSourceBucket` statement together. Changing the source bucket after initial deploy is expected to be rare; a redeploy with a new `SourceBucketName` template parameter is an acceptable path for the few who need it, and removing the hot-swap capability removes the wildcard grant rather than continuing to carry it as an accepted trade-off. Decided 2026-08-01.

## Threat model

The STRIDE threat model and its mitigations are tracked under `.threatmodel/` and the relevant specs in `.kiro/specs/` (for example, `custom-auth-cloudfront`, `remove-prompt-content-visibility`, and `user-tombstoning`).

## Reporting a vulnerability

See [SECURITY.md](../SECURITY.md). Do **not** open a public GitHub issue for security findings.
