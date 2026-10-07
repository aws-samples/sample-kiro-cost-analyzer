# Requirements — Claude Code on Amazon Bedrock Ingestion

Organizations that run Kiro often also have developers using **Claude Code pointed at Amazon Bedrock**. That spend is invisible to Kiro Cost Analyzer (KCA) today. This spec adds one new ETL source adapter that ingests **Amazon Bedrock model invocation logs** delivered to Amazon S3 and records the activity as `clientType=CLAUDE_CODE`. Identity is resolved deterministically through AWS IAM Identity Center (IdC), so a developer's Kiro and Claude Code activity land under the same `USER#{userId}`. Cost is an estimate in USD, computed at ingest from a versioned price table. Credits and USD are never summed.

The adapter plugs into the source-adapter seam delivered by issue #55 (`.kiro/specs/etl-source-adapter/`). The pipeline today assumes one source bucket, one role and one client. This spec makes the bucket, role and client belong to the adapter, and Kiro behavior does not change.

v1 ingests **metadata only**: token counts, model, identity, timestamp, region, operation and error code. Request and response bodies are never read or stored.

Issue: #56. Precedents: `.kiro/specs/etl-source-adapter/`, `.kiro/specs/gitlab-provider-support/`, `.kiro/specs/cross-account-s3-access/`, `.kiro/specs/s3-source-config-readonly/`.

## Premises and prerequisites

These are deployment preconditions. KCA documents them and checks what it can. It does not provide fallbacks for deployments that do not meet them.

- **P1 — IAM Identity Center is mandatory.** Developers run Claude Code with credentials from an IdC permission set: an `AWS_PROFILE` created by `aws configure sso`, with `CLAUDE_CODE_USE_BEDROCK=1`. The invocation-log principal is then `arn:aws:sts::{account}:assumed-role/AWSReservedSSO_{PermissionSet}_{suffix}/{UserName}`. The session name is the IdC `UserName`. The spike (Requirement 1.7) records which IdC identity sources (IdC directory, external IdP with SCIM, Active Directory) are confirmed to satisfy this; unconfirmed sources are listed as unsupported in `docs/deploy.md`. A user renamed in IdC between sign-in and ingestion cannot be resolved and is recorded as unattributed (Requirement 6.9).
- **P2 — Same Identity Store as Kiro.** The IdC instance that provisions the Claude Code permission set uses the same Identity Store that KCA is configured with (`IdentityStoreId`, and `IdentityStoreRoleArn` when cross-account). Kiro `userId` values are UserIds from this Identity Store. The Identity Store is called in the IdC home Region (Requirement 6.8).
- **P3 — Invocation logging to S3 in every Region used.** Bedrock model invocation logging is enabled with S3 delivery in each Region where Claude Code calls Bedrock, including the Region set by `ANTHROPIC_SMALL_FAST_MODEL_AWS_REGION` when used. Each Region's log bucket is in the same account and Region as that Region's logging configuration. The recommended body-delivery setting is the least delivery that still produces invocation records; the spike decides whether that is metadata-only (every body-delivery flag off) or Text delivery with a lifecycle policy (Requirement 1.6). KCA never reads bodies either way.
- **P4 — Recommended account topology.** Claude Code runs in a dedicated AWS account, which is the enterprise norm and what Anthropic recommends. KCA reads the log buckets through an optional cross-account role. A log bucket in the KCA account is also supported (no role). v1 reads the logs of **one** Claude Code account per deployment: the log-role account, or the KCA account when no role is configured (Requirement 2.8).
- **P5 — Recommended Claude Code configuration.** `ANTHROPIC_MODEL`, `ANTHROPIC_DEFAULT_OPUS_MODEL`, `ANTHROPIC_DEFAULT_SONNET_MODEL` and `ANTHROPIC_DEFAULT_HAIKU_MODEL` (or `modelOverrides` covering every version in use) point at tagged application inference profiles (AIPs). AIP-only use can be enforced with the `bedrock:InferenceProfileArn` IAM condition in the permission-set policy. Bedrock API keys and access keys are not used for Claude Code.
- **P6 — bedrock-runtime endpoint only.** Claude Code uses the Bedrock Invoke API on `bedrock-runtime`. Traffic through the Mantle endpoint (`CLAUDE_CODE_USE_MANTLE`) produces no invocation logs and is not visible to KCA.

## Glossary

- **Invocation log**: an Amazon Bedrock model invocation log record. Logs are delivered to S3 as gzipped newline-delimited JSON batches.
- **Log location**: one `(bucket, optional prefix, region)` triple where invocation logs for one Region are delivered.
- **Log role**: an optional IAM role, assumed by KCA, that can read every log location and resolve AIPs in the Claude Code account. `NONE` means KCA's own Lambda roles read the buckets directly.
- **Reader account**: the AWS account whose logs v1 ingests. It is the account of the log-role ARN, or the KCA account when the log role is `NONE`.
- **Qualified key**: the Bedrock adapter's wire key, `s3://{bucket}/{objectKey}`. It carries the location through the existing Step Functions envelope.
- **IdC principal**: an invocation-log `identity.arn` of the form `arn:aws:sts::{account}:assumed-role/AWSReservedSSO_{PermissionSet}_{suffix}/{sessionName}`.
- **Permission-set name**: the `{PermissionSet}` part of an IdC role name. The trailing `{suffix}` is ignored when matching.
- **Model reference (modelRef)**: the normalized `modelId` of an invocation. It is a base model ID, a system inference-profile ID (`us.`, `eu.`, `apac.`, `global.`, …), an application inference profile ID (`aip-{id}`) or a provisioned-model reference.
- **Price key**: `(baseModelId, scope, sourceRegion)`, where scope is `in-region`, `geo` or `global`.
- **Price version**: an immutable, effective-dated price table stored in DynamoDB and identified by `versionId`.
- **Usage aggregate**: one normalized record per `(userId, UTC date, region, modelRef)` per log file. It holds summed tokens, invocation counters and estimated cost.
- **Pseudo-user**: a URL-safe synthetic `userId` of the form `unmapped-{account}-{permissionSetSlug}`. Usage whose IdC session name has no matching Identity Store user is recorded under it.
- **Kiro credit activity**: rows of the existing `STATS#DAILY#` family. All Kiro writers write `totalCredits`, and Claude Code never writes these rows.
- **Source counters**: per-run counts of read, included, dropped, failed, unpriced and unmapped invocations, kept per reason. A drop reason `x` (for example `notIdcRole`) is reported as the counter `dropped{X}` (`droppedNotIdcRole`), an unpriced reason `y` as `unpriced{Y}` (`unpricedNoPriceEntry`), malformed lines as `malformedRecords` and unmapped invocations as `unmappedInvocations` (design §15).
- **Retry ledger**: the set of Bedrock qualified keys whose processing failed and that have not yet been processed successfully.

## Requirement 1: Spike and sanitized fixtures precede implementation

**User Story.** As the maintainer, I want real invocation-log samples before freezing the parser, so that field names and edge cases are not guessed from secondary sources.

### Acceptance Criteria

1.1. BEFORE any adapter code is merged, THE repository SHALL contain sanitized fixtures captured from a real Claude Code session using IdC credentials. The fixtures SHALL cover:
- an `InvokeModelWithResponseStream` record;
- a record delivered with the recommended body-delivery setting of Requirement 1.6;
- a record whose `modelId` is an AIP ARN;
- a record whose `modelId` is a system inference-profile ID;
- a record with non-zero cache read and cache write token counts;
- a record with a non-null `errorCode`, including a throttled request;
- a client-cancelled `InvokeModelWithResponseStream` (Esc in Claude Code);
- the object-key layout as a listing fixture (key names only), including a `permission-check` object and the key name of a body object under the large-data prefix. No body-object content SHALL be committed.

1.2. THE fixtures SHALL replace account IDs, user names, request IDs and ARNs with placeholder values. A test SHALL fail if a fixture contains a 12-digit account ID outside an allowlist of placeholder IDs, or any body field.

1.3. THE spike SHALL record in `design.md` the confirmed field paths for token counts (including `input.cacheReadInputTokenCount` and `input.cacheWriteInputTokenCount`), `errorCode`, `inferenceRegion`, `operation` and `timestamp` (including its offset format). It SHALL also confirm:
- that the IdC session name equals the IdC `UserName`;
- the IdC role-name format, including the suffix length and alphabet, with a fixture-driven assertion that the captured principal is classified as IdC;
- whether a `requestId` can appear in more than one delivered object over a capture window;
- whether failed and client-cancelled records carry token counts.

1.4. THE spike SHALL record `bedrock:GetInferenceProfile` responses for AIPs created from a foundation model, a geographic system profile and a global system profile. The design's AIP scope rule SHALL be confirmed or amended from these responses, including whether a Region-less foundation-model ARN (`arn:aws:bedrock:::foundation-model/{id}`) identifies a global AIP.

1.5. THE spike SHALL record the list prices used for the seed price version, with the source URL and the date of capture.

1.6. THE spike SHALL determine whether invocation records (with token counts and identity) are delivered when every body-delivery flag is off. IF they are not THEN the recommended configuration SHALL be Text delivery with a lifecycle policy on the data prefix, and `docs/deploy.md` SHALL state the storage cost and the privacy warning of Requirement 20.2. This item gates checkpoint 2.

1.7. THE spike SHALL record, for each IdC identity source available to the maintainer (IdC directory, external IdP with SCIM, Active Directory), whether the session name equals the Identity Store `UserName`. Sources that are not confirmed SHALL be listed as unsupported.

## Requirement 2: Log locations and cross-account access belong to the adapter

**User Story.** As an operator with Claude Code in a dedicated account and several Regions, I want KCA to read every Regional log bucket through one optional role, so that I do not have to replicate logs into the Kiro bucket.

### Acceptance Criteria

2.1. THE stack SHALL accept a list of log locations, each with a bucket, an optional prefix and a Region, and an optional log-role ARN. THE log-role ARN SHALL be stored with the existing `NONE` sentinel when empty.

2.2. WHEN a log role is configured THEN ListFiles and Parse SHALL read log locations and call `bedrock:GetInferenceProfile` with credentials obtained by assuming that role. WHEN no log role is configured THEN they SHALL use their own execution roles.

2.3. THE Bedrock adapter SHALL obtain S3 clients per `(roleArn, region)` and SHALL NOT use the Kiro source bucket, `SourceBucketRoleArn` or the Kiro cross-account client.

2.4. THE Kiro adapters SHALL keep using the event bucket and the client built from `SourceBucketRoleArn`, unchanged.

2.5. THE Step Functions state-machine definition SHALL NOT require a change to carry Bedrock locations. The location SHALL travel inside the qualified key.

2.6. IF an AssumeRole call for the log role fails THEN the client factory SHALL raise. The ETL SHALL NOT fall back to the Lambda's own credentials. In discovery the error is contained per location (Requirement 2.9); in Parse it fails the file.

2.7. THE repository SHALL provide a separate CloudFormation template and Makefile target for the log role in the Claude Code account. The role SHALL grant read access to the configured log buckets, optional KMS decrypt and `bedrock:GetInferenceProfile` on that account's application inference profiles. It SHALL trust only the KCA account.

2.8. THE Bedrock adapter SHALL list only the reader account's log prefix in each location. Records whose `accountId` differs from the reader account SHALL be dropped and counted as `foreignAccount`. A multi-account (log-archive) topology is out of scope for v1.

2.9. IF Bedrock discovery fails for a location (AssumeRole, `ListObjectsV2`, a wrong Region, a deleted bucket, or a DynamoDB error while reading the retry ledger or materializing the seed) THEN the adapter SHALL log the error, record it in the discovery status (Requirement 3.11), return no keys for that location and continue. ListFiles SHALL NOT fail because of a Bedrock discovery error, and the Kiro `newFiles` output SHALL be unchanged.

## Requirement 3: Discovery lists invocation-log objects incrementally

**User Story.** As an operator, I want each ETL run to list only recent log partitions, so that listing cost does not grow with months of history.

### Acceptance Criteria

3.1. THE Bedrock adapter SHALL claim only qualified keys whose object key matches `{prefix}AWSLogs/{account}/BedrockModelInvocationLogs/{region}/{YYYY}/{MM}/{DD}/{HH}/{file}.json.gz` for a configured location.

3.2. THE Bedrock adapter SHALL NOT claim keys that contain a `data` path segment under the log layout, `permission-check` objects, or keys outside every configured location.

3.3. THE Bedrock adapter's claims SHALL be disjoint from the Kiro adapters' claims for every possible key.

3.4. FOR each location, discovery SHALL list date partitions from `max(backfillStartDate, watermark − overlapDays)` through the current UTC date, with `overlapDays = 2`. The watermark is the latest partition date among already-processed keys for that location.

3.5. WHEN a location has no processed keys THEN discovery SHALL start at `backfillStartDate`. Its default SHALL be 30 days before the current run's UTC date (a sliding default). Re-enabling after a disabled period therefore back-fills at most the last 30 days, or from an explicit `BedrockBackfillStartDate`.

3.6. ListFiles SHALL emit Bedrock files with `fileType=bedrock_invocation_log` and the qualified key, and SHALL apply the existing processed-key filter to qualified keys.

3.7. ListFiles SHALL cap each batch by both the existing `MAX_BATCH_SIZE` and a serialized-size budget that keeps the List result under the Step Functions payload limit.

3.8. WHEN Bedrock ingestion is disabled THEN the Bedrock adapter SHALL list no keys, and the ListFiles output SHALL be byte-identical to the pre-feature output.

3.9. WHEN a Bedrock file fails (Parse or Writer error, or child timeout) THEN its qualified key SHALL be recorded in the retry ledger, and every later enabled discovery SHALL emit it as a candidate, regardless of the watermark, until it is processed. Ledger entries SHALL carry the attempt count, the first and last failure time and the last error class. Entries for processed keys SHALL be removed. A failed file SHALL never leave the listing window silently.

3.10. WITHIN one execution, each Bedrock qualified key SHALL be dispatched at most once, so that persistently failing files cannot keep the `hasMore` loop running.

3.11. THE adapter SHALL persist a discovery status per location: last successful listing time, last error time and class, retry-ledger size, and the active `configError`, if any. `GET /api/config` SHALL expose it.

## Requirement 4: Parsing reads metadata only

**User Story.** As a security reviewer, I want the parser to read only invocation metadata, so that prompt and response content never enters KCA.

### Acceptance Criteria

4.1. THE parser SHALL decompress gzip content and parse one JSON record per non-blank line. The required fields SHALL be `timestamp`, `requestId`, `accountId`, `region`, `modelId`, `identity.arn` and `operation`. A line that cannot be decoded, or that lacks a required field, SHALL be counted as malformed and skipped without failing the file.

4.2. THE parser SHALL extract:
- `timestamp`, `requestId`, `accountId`, `region`, `operation`, `modelId`, `identity.arn` and `errorCode`;
- `inferenceRegion`, when present;
- `input.inputTokenCount`, `input.cacheReadInputTokenCount`, `input.cacheWriteInputTokenCount` and `output.outputTokenCount`, using the field paths confirmed in Requirement 1.3.

4.3. THE parser SHALL NOT read or retain `input.inputBodyJson`, `output.outputBodyJson`, body S3 references or `requestMetadata`. No normalized record SHALL contain body content.

4.4. THE parser SHALL treat `input.inputTokenCount` as non-cached input, and SHALL NOT subtract cache counts from it.

4.5. WHEN a cache-count field is absent THEN the parser SHALL use zero for pricing and SHALL count the occurrence as `cacheFieldsAbsent`.

4.6. THE parser SHALL derive the UTC activity date from the record's `timestamp`, not from the object key's hour partition. A timestamp without an offset SHALL be treated as UTC.

4.7. THE parser SHALL accept operations `InvokeModel`, `InvokeModelWithResponseStream`, `Converse` and `ConverseStream`. Records with any other operation SHALL be dropped and counted as `unsupportedOperation`.

4.8. WITHIN one file, duplicate `requestId` values SHALL be counted once and the duplicates counted as `duplicateRecords`. Cross-file duplication SHALL be handled as the spike result of Requirement 1.3 decides (documented limitation or cross-file de-duplication).

4.9. WHEN `errorCode` is non-null THEN the invocation SHALL be counted as a failed invocation and SHALL NOT be priced. Its tokens SHALL be excluded unless the spike (Requirement 1.3) shows that failed or cancelled records carry billable token counts, in which case the design SHALL be amended before checkpoint 2.

4.10. WHEN a successful record lacks `input.inputTokenCount` or `output.outputTokenCount` THEN the invocation SHALL be included with zero for the missing bucket and counted as unpriced with reason `tokenCountsAbsent`. No cost SHALL be written for it.

4.11. A record whose timestamp is more than 15 minutes later than the run's current time SHALL be counted as malformed.

## Requirement 5: Only Identity Center principals are ingested

**User Story.** As an administrator, I want only developer IdC sessions counted as Claude Code, so that service roles, this stack's own model calls and long-term API keys are not attributed to people.

### Acceptance Criteria

5.1. THE adapter SHALL include an invocation only when `identity.arn` is an STS assumed-role ARN whose role name matches `AWSReservedSSO_{PermissionSet}_{suffix}`, using the suffix format confirmed in Requirement 1.3.

5.2. Invocations by IAM users (including Bedrock long-term API keys), root, federated users, non-IdC assumed roles, unparseable ARNs or a foreign account SHALL be dropped and counted per reason (`notAssumedRole`, `notIdcRole`, `unparseablePrincipal`, `foreignAccount`).

5.3. WHERE the administrator configures permission-set name patterns, THE adapter SHALL include only IdC principals whose permission-set name matches at least one pattern. Other principals SHALL be dropped as `permissionSetFilter`.

5.4. WHERE the administrator configures an application-inference-profile allowlist, THE adapter SHALL include only invocations whose raw `modelId` equals an allowlisted AIP ARN or AIP ID. Other invocations SHALL be dropped as `inferenceProfileFilter`.

5.5. Pattern matching SHALL ignore the IdC role suffix, so that re-provisioned permission-set roles keep matching.

5.6. Every parsed invocation SHALL receive exactly one outcome: included, or dropped with exactly one reason.

5.7. THE stack SHALL NOT maintain a self-invocation exclusion list. KCA's own Bedrock callers are excluded by Requirement 5.1.

## Requirement 6: Identity is resolved deterministically to the IdC UserId

**User Story.** As a cost owner, I want a developer's Claude Code usage under the same user as their Kiro usage, so that per-person views show the whole AI-assistant footprint.

### Acceptance Criteria

6.1. FOR an included invocation, THE adapter SHALL resolve the session name to an Identity Store UserId with `identitystore:GetUserId` on the `userName` attribute path only. No other attribute path and no persistent identity cache SHALL be used.

6.2. THE resolved UserId SHALL be the same identifier Kiro activity uses, so both sources write under the same `USER#{userId}` partition.

6.3. Resolutions SHALL be cached in the Lambda container for the run, including negative results. A user resolved through `GetUserId` SHALL be name-enriched and cached through the existing `UserNamesTable` path.

6.4. A lookup SHALL be treated as "no such user" only when `GetUserId` raises `ResourceNotFoundException` with `ResourceType = USER` and no `Reason`. Every other `ResourceNotFoundException` variant (for example `IDENTITY_STORE`, or a `Reason` for an unavailable customer-managed KMS key) SHALL be treated as a configuration error.

6.5. WHEN the Identity Store definitively reports that no user matches (Requirement 6.4) THEN the invocation SHALL be attributed to the pseudo-user for its `(account, permissionSet)` and counted as `unmapped`.

6.6. IF an identity lookup fails for any other reason (a configuration error, AccessDenied, throttling after retries, or a network error) THEN Parse SHALL fail the file, so it is retried through the retry ledger (Requirement 3.9) and never permanently misattributed.

6.7. THE feature SHALL NOT provide admin identity mappings, a static mapping mode, a raw per-principal ledger or a re-attribution job.

6.8. THE identity client SHALL be built for the IdC home Region (an optional setting; the default is the Lambda's Region). BEFORE accepting any "no such user" result, Parse SHALL run a once-per-container preflight (`ListUsers` with `MaxResults=1` on the configured store). IF the preflight fails THEN every Bedrock file in that container SHALL fail as a configuration error.

6.9. `docs/deploy.md` SHALL document that a user renamed in IdC between sign-in and ingestion, and an identity source whose session name differs from `UserName`, produce unattributed usage, and that a reused user name is attributed to its current holder.

## Requirement 7: Pseudo-users keep unattributed cost visible without distorting people counts

**User Story.** As an administrator, I want unattributed Claude Code cost visible but not counted as a person, so that totals stay complete and per-person metrics stay honest.

### Acceptance Criteria

7.1. Pseudo-user IDs SHALL have the form `unmapped-{12-digit account}-{permissionSetSlug}`. They SHALL contain only `[a-z0-9-]`, be at most 128 characters long and be deterministic for a given `(account, permissionSet)`.

7.2. THE shared layer SHALL provide `is_pseudo_user(user_id)`, which returns true exactly for IDs produced by the pseudo-user builder.

7.3. Pseudo-users SHALL be excluded from user counts, engagement segmentation, funnel, dormant detection, tier recommendations, averages per user, the Git-mapping user picker and the Productivity user picker.

7.4. Pseudo-user usage SHALL be included in USD and token totals. It SHALL also be reported as a separate unattributed total.

7.5. Parse SHALL NOT call the Identity Store for pseudo-users, and SHALL NOT write pseudo-users to `UserNamesTable`.

7.6. Pseudo-user rows SHALL be visible only to administrators. The UI SHALL label them with a localized "unattributed" label that names the permission set and account. The user page SHALL hide the Productivity tab for pseudo-users and default to the Usage tab.

## Requirement 8: Bedrock prices are versioned and forward-only

**User Story.** As an administrator, I want to maintain the Bedrock price table and know which table priced each day, so that cost estimates are auditable and can be recomputed later.

### Acceptance Criteria

8.1. THE system SHALL store price versions as immutable DynamoDB items. Each version SHALL have a `versionId`, an `effectiveFrom` UTC date, metadata about its creation and a list of price entries.

8.2. Each price entry SHALL define `baseModelId`, `scope`, an optional `region` (default `*`) and USD rates per million tokens for input, output, cache read, 5-minute cache write and 1-hour cache write. It MAY define long-context rates with an input-token threshold.

8.3. Each version SHALL declare a `cacheWriteTtlAssumption` (`5m` or `1h`, default `5m`). That rate SHALL be applied to cache-write tokens, because the log does not split them by TTL.

8.4. WHEN Bedrock ingestion is enabled and no seed version exists THEN the Bedrock adapter's discovery SHALL materialize the bundled seed version once, idempotently, under a fixed seed sort key with `effectiveFrom = 1970-01-01`, whether or not admin versions already exist.

8.5. An administrator SHALL be able to list versions and create a version through Admins-guarded `/api/config/bedrock-pricing` routes. They SHALL be able to delete a version only while its `effectiveFrom` is still in the future.

8.6. A new version SHALL have `effectiveFrom` strictly later than the current UTC date, and no existing version SHALL have the same `effectiveFrom`. As a result, each UTC day is priced by exactly one version, and edits never reprice ingested usage.

8.7. Validation SHALL reject negative or non-numeric rates, unknown scopes, duplicate `(baseModelId, scope, region)` entries, malformed dates and a duplicate `effectiveFrom`. The validator SHALL be a pure function.

8.8. Non-admin callers SHALL receive 403 on every pricing route.

## Requirement 9: Cost is estimated at ingest with Decimal arithmetic

**User Story.** As a cost owner, I want each invocation priced by the correct model, scope and Region, so that the USD estimate is as close to list price as the log allows.

### Acceptance Criteria

9.1. THE adapter SHALL classify each `modelId` as a base model, a system inference profile, an application inference profile, a provisioned model or unknown.

9.2. System inference-profile prefixes SHALL set the scope: `global.` sets `global`, and every other geographic prefix sets `geo`. A base model ID SHALL have scope `in-region`.

9.3. AIP ARNs SHALL be resolved to their base model and scope with `bedrock:GetInferenceProfile`, cached per `(account, region, profileId)` in the Lambda container.

9.4. WHEN an AIP lookup returns `ResourceNotFoundException` or `ValidationException` THEN its invocations SHALL be unpriced with reason `aipUnresolved`. WHEN an AIP ARN's account differs from the reader account THEN its invocations SHALL be unpriced with reason `aipForeignAccount`, without calling the API. IF the lookup fails for any other reason THEN Parse SHALL fail the file.

9.5. THE price lookup SHALL use the version effective on the invocation's UTC date. It SHALL match `(baseModelId, scope, region)` first and `(baseModelId, scope, *)` second.

9.6. Invocation cost SHALL be the sum, over token buckets, of tokens × rate ÷ 1,000,000, computed in `decimal.Decimal`. WHEN a long-context threshold is defined and an invocation's total input exceeds it THEN the long-context rates SHALL apply to that invocation.

9.7. Aggregate cost SHALL be the sum of the per-invocation costs. It SHALL be quantized to 8 decimal places with `ROUND_HALF_EVEN` and serialized as a decimal string.

9.8. Invocations without a matching price entry (`noPriceEntry`), without an applicable price version (`noPriceVersion`), on provisioned models (`provisioned`), with unresolved or foreign AIPs (`aipUnresolved`, `aipForeignAccount`) or with absent token counts (`tokenCountsAbsent`) SHALL be counted as unpriced with that reason. Their tokens SHALL still be recorded. No zero cost SHALL be written for them.

9.9. Every aggregate SHALL record the `priceVersion` consulted, including when all its invocations are unpriced. It SHALL be null only for `noPriceVersion`.

## Requirement 10: Usage is pre-aggregated and persisted per user, day and model

**User Story.** As the maintainer, I want one write per user, day and model per file, so that large log batches fit the Step Functions payload and DynamoDB write budget, and tokens remain available for a later recompute.

### Acceptance Criteria

10.1. `normalize` SHALL emit one usage aggregate per `(userId, UTC date, region, modelRef)` per file. Each aggregate SHALL include the summed token buckets, `invocations`, `failedInvocations`, `unpricedInvocations` per reason, the estimated cost when present, `priceVersion`, `baseModelId`, `scope` and `rawModelId`. WHEN long-context rates applied to any invocation THEN the aggregate SHALL also carry `longContextInvocations` and the long-context subset of each token bucket, plus the threshold used.

10.2. For any input, aggregate token and counter sums SHALL equal the sums over the included, de-duplicated invocations.

10.3. THE Writer SHALL persist each aggregate to `USER#{userId}` / `STATS#TOKENS#CLAUDE_CODE#{date}#{region}#{modelRefSk}`, and per-file global sums to `GLOBAL` / the same sort key. `modelRefSk` SHALL be an SK-safe, collision-free encoding of `modelRef`, and the aggregation key in `normalize` SHALL use it, so distinct model references never share a sort key.

10.4. Writes SHALL be idempotent per file: re-running Writer for a file already applied to an item SHALL NOT change that item's counters. The idempotency marker SHALL NOT grow the aggregate items.

10.5. THE Bedrock adapter SHALL NOT write `STATS#DAILY#`, `STATS#MODEL#`, `STATS#CLIENT#`, `PROMPT#` or the Kiro `ACTIVITY_SUMMARY` item. Claude Code activity dates SHALL be kept in `USER#{userId}` / `ACTIVITY_SUMMARY#CLAUDE_CODE`, updated only from aggregates with at least one successful invocation.

10.6. Parse output for a Bedrock file SHALL stay under 200 KB inline. WHEN the serialized aggregates exceed that budget THEN Parse SHALL spill them to the data bucket and return a single reference record that the Writer resolves. Tests SHALL cover a file of at least 5,000 invocations and a file with at least 1,000 distinct aggregate keys.

10.7. Idempotency SHALL assume identical `normalize` output for a file. THE design SHALL document the residual double-count window when a partially written file is re-parsed after an identity change, and a test SHALL pin that behavior.

10.8. Recomputing an aggregate's cost from its stored fields and its price version SHALL equal the ingest cost.

## Requirement 11: Kiro behavior is unchanged

**User Story.** As an operator of a Kiro-only deployment, I want this feature to change nothing I can observe, so that upgrading carries no risk.

### Acceptance Criteria

11.1. WITH no Bedrock locations configured and no Claude Code data, the following SHALL be byte-identical to pre-feature behavior for the same inputs: ListFiles, Parse and Writer outputs; DynamoDB items; RecordStatus outputs; API responses; CSV/JSON exports; and the rendered UI. WITH locations configured and ingestion disabled, the ETL outputs SHALL also be byte-identical; only the read-model outputs listed in Requirement 11.3 MAY differ.

11.2. THE Kiro adapters SHALL pass the existing golden-model equivalence tests without weakening an assertion.

11.3. API responses SHALL omit every Claude Code field (`claudeCode`, `sources`, `isPseudoUser`, `pseudo*`, `segmentationByClient`, `claudeCodeIngestion` and the export's Claude Code columns) when the deployment has neither Bedrock locations configured nor Claude Code data for the requested window. `GET /api/usage` SHALL also omit them unless the caller passes `includeClaudeCode=true`.

11.4. ListFiles SHALL emit Kiro wire types and fields unchanged. Parse SHALL omit `counters` from its output when the adapter reports none.

11.5. A Bedrock file failure SHALL NOT prevent Kiro prompt categorization or ReconcileUsers from running in the same execution, and SHALL NOT change the outcome of the execution's Kiro error check.

## Requirement 12: Run observability covers every dropped or degraded invocation

**User Story.** As an operator, I want to see what the Bedrock adapter read, kept and dropped in each run, so that a misconfigured filter or missing price is noticed.

### Acceptance Criteria

12.1. `ParsedSource` SHALL carry a counters map. Parse SHALL return it as `counters` when it is non-empty.

12.2. RecordStatus SHALL sum counters across all child results and persist them on `ETL_STATUS` / `EXEC#{executionName}` as `sourceCounters`, keyed by source type. `sourceCounters` SHALL include `filesFailed` per source type.

12.3. Counters SHALL include records read, malformed, duplicates, included, failed, each drop reason, each unpriced reason, unmapped, and `cacheFieldsAbsent`. `includedInvocations` SHALL count every included invocation, successful or failed, and `failedInvocations` SHALL be the failed subset.

12.4. `GET /api/etl/executions` SHALL expose `sourceCounters`, and the ETL execution history UI SHALL show them for runs that have them.

12.5. Session names that cannot be resolved SHALL be logged at most once per container per run, truncated to 64 characters.

12.6. Configuration errors and discovery errors SHALL be surfaced through the discovery status of Requirement 3.11 and `GET /api/config`, and in the logs. They SHALL NOT depend on the ListFiles result reaching RecordStatus.

## Requirement 13: The usage API exposes Claude Code usage separately from credits

**User Story.** As an administrator, I want per-user Claude Code cost and tokens next to Kiro credits but never combined with them, so that I can compare spend without mixing units.

### Acceptance Criteria

13.1. WHEN the caller passes `includeClaudeCode=true` THEN `GET /api/usage` SHALL include CLAUDE_CODE-only users and pseudo-users as rows. Each row with Claude Code usage in the window SHALL carry a `claudeCode` object with: `estimatedCostUsd`, `estimatedCostUsdExact`, the four token buckets, `invocations`, `failedInvocations`, `unpricedInvocations`, `activeDays` (distinct UTC days in the window with at least one successful invocation), `lastActiveDate` (the latest such day in the window) and `priceVersions`. Without the parameter the response SHALL be unchanged.

13.2. Each row SHALL carry `sources` (a subset of `KIRO` and `CLAUDE_CODE`) and `isPseudoUser`. `CLAUDE_CODE ∈ sources` SHALL require at least one successful invocation in the window.

13.3. Existing row fields (`totalCredits`, `averageDailyCredits`, `subscriptionTier`, `lastActiveDate`, `daysSinceLastActive` and the rest) SHALL be computed from Kiro data only.

13.4. THE summary SHALL keep `totalUsers`, `totalCredits`, `totalOverageCredits` and `averageCreditsPerUser` computed over Kiro rows only. It SHALL add a `claudeCode` block with `users`, `bothUsers`, `people` (distinct non-pseudo users across both sources), `estimatedCostUsd`, `unattributedCostUsd`, token totals, `unpricedInvocations` and `priceVersions`. Every summary field SHALL be computed over the full filtered population, before pagination.

13.5. `clientType=CLAUDE_CODE` SHALL filter rows to users with `CLAUDE_CODE ∈ sources` or pseudo-users with usage, sorted by Claude Code estimated cost descending. Every other `clientType` value SHALL keep only rows with `KIRO ∈ sources` and SHALL otherwise keep its current behavior.

13.6. Single-user access (`userId` parameter) SHALL include the caller's own `claudeCode` object. A user with Claude Code usage and no Kiro daily stats SHALL receive one row with Kiro fields at zero. Non-admins SHALL never receive pseudo-user rows.

13.7. No API field SHALL hold a sum of credits and USD.

13.8. THE union scan SHALL be tested at a stated large-organization size (500 users × 90 days × 3 models), and the account-level Claude Code totals SHALL come from the `GLOBAL` items, not from the per-user scan.

## Requirement 14: Account, user-detail and export views show Claude Code usage

**User Story.** As an administrator, I want the account overview, the user page and the export to include Claude Code cost, so that the data is usable outside the users table.

### Acceptance Criteria

14.1. `GET /api/usage/account` SHALL add a `claudeCode` block with:
- totals;
- a timeline at the requested granularity (`estimatedCostUsd`, tokens, invocations);
- a breakdown by model (`modelRef`, `baseModelId`, display name, USD, tokens, USD percentage);
- `unattributedCostUsd`, `unpricedInvocations` and `priceVersions`.

14.2. THE existing `totals`, `timeline`, `breakdownByTier` and `breakdownByClientType` SHALL remain credit-based and unchanged.

14.3. `GET /api/usage/{userId}/details` SHALL add a `claudeCode` block with a summary, daily usage, a model breakdown and `priceVersions`. It SHALL return 404 only when the user has no Kiro daily stats, no prompts and no Claude Code aggregates in the window.

14.4. WHEN the export population contains Claude Code usage, or ingestion is configured, THEN the export SHALL request `includeClaudeCode=true`, and:
- the CSV export SHALL append these columns: `Sources`, `ClaudeCodeEstimatedCostUsd`, `ClaudeCodeInputTokens`, `ClaudeCodeOutputTokens`, `ClaudeCodeCacheReadTokens`, `ClaudeCodeCacheWriteTokens`, `ClaudeCodeInvocations`, `ClaudeCodeUnpricedInvocations` and `ClaudeCodePriceVersions`, with existing columns and their order unchanged;
- the JSON export SHALL contain the rows as returned by `GET /api/usage`, including the nested `claudeCode` object, `sources` and `isPseudoUser`.

14.5. Exported USD values SHALL be the exact 8-decimal string (`claudeCode.estimatedCostUsdExact`), computed from the Decimal sum before any float conversion.

## Requirement 15: Tier recommendations and dormant detection use Kiro credit activity only

**User Story.** As a Kiro seat owner, I want tier and idle-seat recommendations unaffected by Claude Code usage, so that a developer who switches tools for a week is not told to downgrade.

### Acceptance Criteria

15.1. THE tier projection SHALL use `daysActive` counted from Kiro credit activity only. For a mixed user, the projection SHALL equal the Kiro-only projection.

15.2. Inactive-subscriber detection SHALL use the Kiro `ACTIVITY_SUMMARY.lastActiveDate`. Claude Code activity SHALL NOT update it.

15.3. Users without a Kiro subscription tier, including CLAUDE_CODE-only users and pseudo-users, SHALL produce no tier recommendation and no inactive-subscriber entry.

15.4. Regression tests SHALL cover a mixed user, a CLAUDE_CODE-only user and a pseudo-user against tier recommendations and inactive subscribers.

## Requirement 16: Claude Code engagement has its own signal

**User Story.** As an enablement lead, I want Claude Code adoption segmented by its own activity, so that Claude Code users are not classified as idle Kiro users.

### Acceptance Criteria

16.1. Kiro engagement segmentation, funnel and derived metrics SHALL be computed over the Kiro population only: users with Kiro credit activity, plus the Kiro `ACTIVITY_SUMMARY` population.

16.2. THE engagement response SHALL add `segmentationByClient.CLAUDE_CODE`. It SHALL classify non-pseudo Claude Code users by `activeDays` (distinct UTC days with at least one successful invocation) AND successful `invocations`, using AND logic and the priority power > active > light > idle > dormant.

16.3. Claude Code thresholds SHALL be configurable under an optional `claudeCode` key of the existing engagement-thresholds parameter. Configurations without it SHALL remain valid and use the defaults. THE `claudeCode` block SHALL be validated and parsed separately from the Kiro thresholds: an invalid `claudeCode` block SHALL fall back to the Claude Code defaults only and SHALL NOT change the Kiro thresholds.

16.4. A Claude Code user with no usage in the window SHALL be `idle`. They SHALL become `dormant` when the days since `ACTIVITY_SUMMARY#CLAUDE_CODE.lastActiveDate` reach `dormantDaysThreshold`.

16.5. `totalMessages` SHALL NOT be used as a Claude Code engagement input.

16.6. `PUT /api/config/engagement-thresholds` SHALL preserve a stored `claudeCode` block when the request body omits it. v1 provides no UI editor for the Claude Code thresholds; `docs/features.md` SHALL document the key.

16.7. Failed-only activity SHALL NOT count as Claude Code activity for `activeDays`, `lastActiveDate`, `sources`, `claudeCodeUsers` or dormant detection.

## Requirement 17: The UI presents USD as a separate, labeled estimate

**User Story.** As a dashboard user, I want Claude Code cost clearly labeled as an estimate in USD, with the price table named, so that I do not compare it naively with credits or the AWS bill.

### Acceptance Criteria

17.1. Claude Code sections SHALL render only when the API returns Claude Code data or reports ingestion as configured. Kiro-only deployments SHALL render unchanged.

17.2. THE dashboard SHALL show Claude Code estimated cost, tokens, users, unattributed cost and a partial-estimate indicator when `unpricedInvocations > 0`. They SHALL appear in cards and charts separate from credit cards and charts, and SHALL be taken from the population-wide summary, not from table rows.

17.3. THE users table SHALL show a Claude Code USD column and source badges when any row has Claude Code usage. Pseudo-user rows SHALL use the unattributed label. User links SHALL URL-encode the `userId`.

17.4. THE user page and account page SHALL show Claude Code panels with daily USD, tokens and model breakdowns.

17.5. Every USD figure SHALL be labeled as an estimate at standard on-demand list price that excludes discounts, service tiers and credits and is not reconciled with the AWS bill. Each view SHALL name the price version(s) used, and SHALL state that price edits apply forward only.

17.6. THE Settings page SHALL provide an admin Bedrock pricing editor and a read-only view of the ingestion configuration (locations, role configured, filters, backfill start) with the discovery status of Requirement 3.11.

17.7. Every new string SHALL exist in `en.json` and `pt-BR.json`, sorted, with parity enforced by the existing locale check. "Claude Code" and "Amazon Bedrock" SHALL be untranslated `brand.*` keys.

17.8. The dashboard's client-type filter SHALL offer `CLAUDE_CODE` only when ingestion is configured.

17.9. THE engagement view SHALL render `segmentationByClient.CLAUDE_CODE` when present, separately from the Kiro segmentation.

17.10. WHEN Claude Code data is present THEN the users table's existing frequency, last-active and days-ago columns SHALL be labeled as Kiro activity, and a separate Claude Code last-active value SHALL be shown.

17.11. THE existing summary cards SHALL keep their Kiro meaning. The cross-source people count and per-source user counts SHALL appear only in the Claude Code section.

17.12. A test SHALL assert that every counter name the ETL can emit has an `etl.counters.*` key in both catalogs, and the UI SHALL render a fallback label for unknown counter names.

## Requirement 18: Infrastructure and IAM are least-privilege and conditional

**User Story.** As a security reviewer, I want every new permission scoped and present only when the feature is configured, so that Kiro-only stacks gain no access.

### Acceptance Criteria

18.1. THE template SHALL add these optional parameters:
- `BedrockIngestionEnabled` (default `false`);
- `BedrockLogBuckets`, `BedrockLogPrefixes` and `BedrockLogRegions` (parallel lists);
- `BedrockLogRoleArn`;
- `BedrockPermissionSetPatterns`;
- `BedrockInferenceProfileAllowlist`;
- `BedrockBackfillStartDate`;
- `BedrockIdentityStoreRegion`.

THE template SHALL store them in one SSM parameter, `/kiro-cost-analyzer/bedrock-ingestion`.

18.2. WHEN no log role is configured AND buckets are configured THEN ListFiles SHALL receive `s3:ListBucket` on the configured bucket ARNs. In the same case, Parse SHALL receive `s3:GetObject` on their objects and `bedrock:GetInferenceProfile` on the KCA account's application inference profiles.

18.3. WHEN a log role is configured THEN ListFiles and Parse SHALL receive `sts:AssumeRole` on that role ARN only.

18.4. WHEN buckets are configured (`HasBedrockLogBuckets`) THEN:
- Parse SHALL receive `identitystore:GetUserId` in a statement separate from the existing `IdentityCenterAccess` statement;
- Parse SHALL receive `dynamodb:Query` on `AnalyticsTable`, conditioned through `dynamodb:LeadingKeys` to the `CONFIG#BEDROCK_PRICING` partition;
- ListFiles SHALL receive `dynamodb:Query`, `dynamodb:PutItem` and `dynamodb:DeleteItem` on `AnalyticsTable`, conditioned to the `CONFIG#BEDROCK_PRICING`, `BEDROCK#RETRY` and `BEDROCK#DISCOVERY` partitions;
- RecordStatus SHALL receive `dynamodb:UpdateItem` on `AnalyticsTable`, conditioned to the `BEDROCK#RETRY` partition;
- Writer SHALL receive `s3:GetObject` on the data bucket's spill prefix.

Without configured buckets none of these statements SHALL exist.

18.5. `identity-store-role.yaml` SHALL add `identitystore:GetUserId` only under a new parameter that defaults to off. The changelog SHALL tell cross-account IdC installations that use Claude Code ingestion to redeploy that role with the parameter on.

18.6. No IAM statement SHALL grant S3 access on a wildcard bucket ARN.

18.7. THE existing `SourceBucketRoleArn`, `source-account-role.yaml` and Kiro IAM statements SHALL be unchanged.

18.8. ListFiles and Parse SHALL receive the `ANALYTICS_TABLE` environment variable, and ListFiles, Parse and Backend the `SSM_BEDROCK_INGESTION` environment variable.

18.9. Template-structure tests SHALL assert the conditions per parameter combination, the absence of wildcard bucket ARNs, the unchanged Kiro statements, the unchanged state-machine definition, the environment variables of Requirement 18.8 wherever the new statements are granted, and the default action set of `identity-store-role.yaml`.

## Requirement 19: The feature-flag lifecycle is defined

**User Story.** As an operator, I want to know exactly what turning the feature on and off does, so that I can roll it out and back safely.

### Acceptance Criteria

19.1. THE adapter SHALL always be registered. `BedrockIngestionEnabled` and the presence of locations SHALL gate discovery only.

19.2. THE default SHALL be disabled. THE feature SHALL be enabled in a deployment only after checkpoints 0–5 and tasks 6.1–6.8 are merged and deployed.

19.3. WHEN ingestion is disabled while a Bedrock file is in flight AND its location is still configured THEN Parse and Writer SHALL process the file normally.

19.4. IF a Bedrock file's location is no longer configured THEN Parse SHALL fail the file rather than return empty records, so the file is never marked processed unread. The key SHALL stay in the retry ledger and be retried only if the location is configured again.

19.5. Data ingested before disabling SHALL remain visible in the read model. `GET /api/config` SHALL report the ingestion state so the UI can show "ingestion disabled; showing historical data".

19.6. Rolling-deploy safety: the new wire type SHALL be emitted only after a deploy that already contains the Bedrock-capable Parse and Writer. This holds because discovery stays disabled until a later parameter change.

## Requirement 20: Documentation covers prerequisites, deployment and limits

**User Story.** As an operator, I want one guide that takes me from a Claude Code account to KCA dashboards, so that I can configure the prerequisites correctly the first time.

### Acceptance Criteria

20.1. `docs/deploy.md` SHALL add a Claude Code on Amazon Bedrock section that recommends or describes:
- the dedicated account, and that v1 reads one Claude Code account (log-archive buckets with several accounts are not supported);
- an IdC permission set for Claude Code and `aws configure sso`, the supported IdC identity sources, and the rename limitation of Requirement 6.9;
- the IdC home Region setting and the KMS key-policy requirement for an IdC instance encrypted with a customer-managed key;
- invocation logging to S3 in every used Region, including the small/fast-model Region, with the body-delivery setting decided in Requirement 1.6;
- the bucket policy and KMS key policy;
- pinning `ANTHROPIC_MODEL` and all three `ANTHROPIC_DEFAULT_*_MODEL` variables (or `modelOverrides` for every version) to tagged AIPs, optionally with `availableModels` and `enforceAvailableModels` in managed settings;
- a complete optional AIP-only policy: allow `application-inference-profile/*` and `foundation-model/*` with the `bedrock:InferenceProfileArn` `ArnLike` application-inference-profile condition, grant no `inference-profile/*`, and keep `bedrock:ListInferenceProfiles` and `bedrock:GetInferenceProfile`;
- denying `iam:CreateServiceSpecificCredential` (Bedrock API keys) in the Claude Code account, and that a high `notAssumedRole` count signals their use;
- an SCP that denies creating roles named `AWSReservedSSO_*`, because the inclusion filter trusts the role name;
- the log-role deployment and the stack parameters;
- enabling and disabling;
- the Mantle limitation.

20.2. `docs/deploy.md` SHALL warn that enabling invocation logging with body delivery in KCA's own account and Region copies Kiro prompt text processed by KCA into that log bucket.

20.3. `docs/architecture.md`, `docs/cost.md`, `docs/security.md`, `docs/features.md`, the steering document's key-schema and SSM tables, and the README spec count SHALL be updated.

20.4. `docs/changelog.md` SHALL record the feature under `## Unreleased`.

20.5. `docs/deploy.md` SHALL correct the claim that `IdentityStoreId` is Region-agnostic: the Identity Store is a Regional service in the IdC home Region.

20.6. WHEN the invocation logs are in the KCA account rather than a dedicated Claude Code account THEN `docs/deploy.md` SHALL state that `BedrockPermissionSetPatterns` is required, not only recommended, because other IdC usage in that account would otherwise be counted as Claude Code.

## Requirement 21: Verification

**User Story.** As a reviewer, I want correctness backed by property tests and golden tests, so that the pure parts are proven and the integration is regression-guarded.

### Acceptance Criteria

21.1. Every correctness property in `design.md` SHALL have a Hypothesis (Python) or fast-check (TypeScript) test with at least 100 examples.

21.2. Fixture-driven tests SHALL run the adapter on every spike fixture.

21.3. Moto-backed tests SHALL cover Writer idempotency, Kiro item invariance and mixed-user read paths.

21.4. Backend tests SHALL cover the 403 path for every new admin route.

21.5. THE full backend suite, the frontend build (including the locale check), the frontend tests and `sam build` SHALL pass.

21.6. THE golden baselines used by the Kiro-invariance tests SHALL be generated from the pre-feature commit and committed before any code they protect is changed.

## Out of scope

- **Request/response bodies, `PROMPT#` records and categorization of Claude Code prompts.** These belong to a separate follow-up issue, which covers the definition of a human turn, opt-in categorization per `clientType`, a privacy and threat-model update, and a cost scenario.
- **Non-IdC identity:** IAM users, shared roles, long-term Bedrock API keys, `requestMetadata` or header-based attribution, and admin identity mappings.
- **A re-attribution or repricing job.** Tokens and `priceVersion` are persisted so a later job is possible.
- **Several Claude Code accounts per deployment** (a per-account role map or a log-archive bucket). v1 reads one reader account.
- **CUR 2.0 reconciliation and OpenTelemetry metrics** as data sources.
- **The Bedrock Mantle endpoint.** It is not covered by invocation logging, and a CUR-based adapter is the likely follow-up.
- **A team or cost-center dimension from AIP tags.**
- **Priority, Flex and batch service tiers, and discounts.** USD stays a standard on-demand list-price estimate.
- **Editing ingestion locations, role or filters from the UI.** These are redeploy-only, following `s3-source-config-readonly`.
- **Kiro-side changes and pre-existing bugs.** This covers the dashboard's ignored Kiro `clientType` and `overageOnly` filters (beyond the source-level row filter of Requirement 13.5), the export's 50-row cap, ReconcileUsers ignoring `IdentityStoreRoleArn`, the full `ProcessedFilesTable` Scan, the `hasMore` loop for persistently failing Kiro files, and relabeling "Kiro User ID". Each is a separate issue.
- **Making the Git-correlation agent aware of Claude Code.** Claude Code writes no `STATS#DAILY#` or `PROMPT#` items, so the agent's inputs do not change.
