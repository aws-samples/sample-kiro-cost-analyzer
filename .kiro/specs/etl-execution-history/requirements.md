# Requirements — ETL Execution History

The ETL tab in Settings shows a single aggregate card describing the *latest* ETL run, read from the SSM parameter `/kiro-cost-analyzer/etl-status`. That parameter is overwritten on every run, so an administrator has no way to answer basic operational questions from the UI: did the ETL run last night, how long did it take, and has it been getting slower or failing repeatedly?

The data needed to answer those questions already exists but is not exposed. The ETL state machine is a Standard type, so Step Functions retains its execution history — start time, stop time and terminal status — for 90 days. What Step Functions does *not* know is how many files a run processed; that number is computed by the `RecordStatus` Lambda and today is written only to the overwritten SSM parameter.

There is also a wording problem. The success message after a manual run says the ETL was "disparado" / "triggered". In an operations screen, "trigger" reads as a fire-and-forget signal, when what actually happened is that a long-running execution *started* and is now in progress.

## Glossary

- **Execution**: one Step Functions execution of the ETL state machine, identified by its execution name.
- **Terminal status**: a Step Functions execution status that will not change again — `SUCCEEDED`, `FAILED`, `ABORTED`, `TIMED_OUT`. `RUNNING` is the only non-terminal status.
- **Elapsed time**: stop time minus start time for a finished execution; time since start for a running one.
- **Execution record**: a DynamoDB item under `PK=ETL_STATUS`, `SK=EXEC#{executionName}`, holding the per-run counters (`filesProcessed`, `recordsWritten`) that Step Functions itself does not track.
- **History window**: the trailing period the history table covers, in whole days, counted back from the moment of the request.

## Requirement 1: Wording of the manual-run feedback

**User Story.** As an administrator running the ETL by hand, I want the confirmation message to tell me the run *started*, so that I understand a long execution is now in progress rather than a signal having been sent.

### Acceptance Criteria

1.1. WHEN a manual ETL run is accepted THEN the confirmation message SHALL state that the execution started and is in progress, in both supported locales.

1.2. THE pt-BR catalog SHALL NOT use the term "disparado" (or any inflection of "disparar") to describe an ETL run being started.

1.3. THE empty-state message shown when no execution has been recorded SHALL use the same "start" vocabulary as the confirmation message in both locales.

1.4. WHEN either catalog changes THEN the key sets of `en.json` and `pt-BR.json` SHALL remain identical and both files SHALL remain alphabetically sorted.

## Requirement 2: Persist per-execution counters

**User Story.** As an administrator, I want the file and record counts of each ETL run to survive the next run, so that the history table can show how much work each execution actually did.

### Acceptance Criteria

2.1. WHEN the `RecordStatus` Lambda finishes computing a run summary THEN it SHALL write an execution record to the analytics table under `PK=ETL_STATUS`, `SK=EXEC#{executionName}`.

2.2. THE execution record SHALL contain `status`, `filesProcessed`, `recordsWritten`, `timestamp` and `executionArn`.

2.3. THE execution name SHALL be derived from the execution ARN passed to the Lambda, taking the segment after the last `:`.

2.4. IF the execution ARN is absent or malformed THEN the Lambda SHALL skip the execution-record write, log the omission, and still complete its SSM write successfully.

2.5. IF the execution-record write fails THEN the Lambda SHALL log the failure and still complete its SSM write successfully, so that a history-persistence problem never fails an otherwise successful ETL run.

2.6. THE existing SSM parameter write SHALL keep its current payload shape and semantics, so the aggregate status card is unaffected.

## Requirement 3: Execution history endpoint

**User Story.** As an administrator, I want an API that returns the recent ETL executions with their timings and outcomes, so that the Settings page can render a history table.

### Acceptance Criteria

3.1. THE API SHALL expose `GET /api/etl/executions`, restricted to callers in the `Admins` group.

3.2. THE endpoint SHALL accept an optional `days` query parameter and SHALL default it to 5 when absent.

3.3. THE endpoint SHALL clamp `days` to the range 1..30 inclusive, and SHALL treat a non-numeric value as absent.

3.4. THE endpoint SHALL list executions of the ETL state machine whose start time falls within the history window, and SHALL return them ordered most recent first.

3.5. EACH returned execution SHALL carry `executionName`, `startDate`, `stopDate`, `elapsedSeconds`, `status`, `filesProcessed` and `recordsWritten`.

3.6. WHEN an execution has not finished THEN `stopDate` SHALL be null, `elapsedSeconds` SHALL be null, and `status` SHALL be `RUNNING`.

3.7. WHEN no execution record exists for an execution THEN `filesProcessed` and `recordsWritten` SHALL be null, distinguishing "not known" from a genuine zero.

3.8. THE endpoint SHALL read every execution record for the history window with a single query against `PK=ETL_STATUS`, not one lookup per execution.

3.9. IF the state machine ARN is not configured THEN the endpoint SHALL return an empty execution list rather than an error.

3.10. IF Step Functions denies or throttles the request THEN the error SHALL propagate to the existing API error handling, and SHALL NOT be reported as an empty history.

3.11. THE response SHALL be English-only in every human-readable field; status values SHALL be returned as stable uppercase Step Functions slugs for the frontend to translate.

## Requirement 4: Execution history table in the ETL tab

**User Story.** As an administrator, I want a table of the last few days of ETL runs under the status card, so that I can see the pattern of runs without leaving the Settings page.

### Acceptance Criteria

4.1. THE ETL tab SHALL render an execution history table below the ETL status card.

4.2. THE table SHALL have the columns start date, end date, elapsed time, file count and status, in that order.

4.3. THE table SHALL cover the trailing 5 days.

4.4. WHILE the history is loading THE table SHALL show a loading state, and it SHALL NOT block or delay the ETL status card.

4.5. WHEN the history is empty THE table SHALL show an empty state explaining that no execution ran in the window.

4.6. WHEN a value is unknown or not applicable THE cell SHALL render an em dash rather than a zero or an empty cell.

4.7. THE elapsed time SHALL be rendered in a compact human form derived from `elapsedSeconds`, and SHALL be stable across locales.

4.8. THE status cell SHALL use a Cloudscape status indicator whose semantics match the execution outcome, and its label SHALL resolve through the i18n catalog.

4.9. ALL dates and numbers in the table SHALL be rendered with the locale-aware formatters from `useI18n()`.

4.10. WHEN a manual run is started from this tab THEN the history SHALL be refreshed so the new execution appears.

4.11. THE table SHALL NOT introduce any hardcoded user-facing string.

## Requirement 5: Deployment and permissions

**User Story.** As an operator of this stack, I want the new endpoint to work after a normal deploy, with no permission granted beyond what it needs.

### Acceptance Criteria

5.1. THE backend function SHALL be granted `states:ListExecutions` on the ETL state machine, and SHALL NOT be granted broader Step Functions permissions.

5.2. THE `RecordStatus` function SHALL be granted `dynamodb:PutItem` on the analytics table only, together with the KMS permissions that table's encryption key requires, and SHALL receive the table name through an environment variable.

5.3. THE feature SHALL deploy through the existing `make deploy` flow with no new manual step.
