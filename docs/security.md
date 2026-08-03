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

## Resolved finding — source-bucket reconfiguration feature removed

`template.yaml`'s `ValidateSourceBucket` IAM statement, which granted `s3:ListBucket` on `Resource: "arn:aws:s3:::*"` so `PUT /api/config/bucket` could validate an admin-supplied bucket name via `HeadBucket`, has been removed. The Settings page's bucket/prefix/prompts-prefix fields are now read-only, and `PUT /api/config/bucket`/`PUT /api/config/prompts-prefix` no longer exist. Changing the source bucket, source prefix, or prompts prefix after initial deployment now requires a redeploy with updated `SourceBucketName`, `SourcePrefix`, and `PromptsPrefix` template parameters (all three are required parameters — see `docs/deploy.md`).

## Threat model

The STRIDE threat model and its mitigations are tracked under `.threatmodel/` and the relevant specs in `.kiro/specs/` (for example, `custom-auth-cloudfront`, `remove-prompt-content-visibility`, and `user-tombstoning`).

## Reporting a vulnerability

See [SECURITY.md](../SECURITY.md). Do **not** open a public GitHub issue for security findings.
