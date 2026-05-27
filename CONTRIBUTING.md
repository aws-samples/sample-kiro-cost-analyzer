# Contributing Guidelines

Thank you for your interest in contributing to our project. Whether it's a bug report, new feature, correction, or additional
documentation, we greatly value feedback and contributions from our community.

Please read through this document before submitting any issues or pull requests to ensure we have all the necessary
information to effectively respond to your bug report or contribution.


## Reporting Bugs/Feature Requests

We welcome you to use the GitHub issue tracker to report bugs or suggest features.

When filing an issue, please check existing open, or recently closed, issues to make sure somebody else hasn't already
reported the issue. Please try to include as much information as you can. Details like these are incredibly useful:

* A reproducible test case or series of steps
* The version of our code being used
* Any modifications you've made relevant to the bug
* Anything unusual about your environment or deployment


## Contributing via Pull Requests
Contributions via pull requests are much appreciated. Before sending us a pull request, please ensure that:

1. You are working against the latest source on the *main* branch.
2. You check existing open, and recently merged, pull requests to make sure someone else hasn't addressed the problem already.
3. You open an issue to discuss any significant work - we would hate for your time to be wasted.

To send us a pull request, please:

1. Fork the repository.
2. Modify the source; please focus on the specific change you are contributing. If you also reformat all the code, it will be hard for us to focus on your change.
3. Ensure local tests pass.
4. Commit to your fork using clear commit messages.
5. Send us a pull request, answering any default questions in the pull request interface.
6. Pay attention to any automated CI failures reported in the pull request, and stay involved in the conversation.

GitHub provides additional document on [forking a repository](https://help.github.com/articles/fork-a-repo/) and
[creating a pull request](https://help.github.com/articles/creating-a-pull-request/).


## Finding contributions to work on
Looking at the existing issues is a great way to find something to contribute on. As our projects, by default, use the default GitHub issue labels (enhancement/bug/duplicate/help wanted/invalid/question/wontfix), looking at any 'help wanted' issues is a great place to start.


## Development Standards

Before contributing code, please skim [`.kiro/steering/development-standards.md`](.kiro/steering/development-standards.md). Highlights:

- **Languages**: Python 3.13 (backend, ETL), TypeScript/React (frontend), AWS SAM (infrastructure).
- **Code language**: English for variables, functions, classes, comments, log messages, commit messages, and PR descriptions.
- **UI strings**: never hardcoded — every user-facing string resolves through the i18n layer with parity between `en.json` and `pt-BR.json`. The build fails if catalogs diverge.
- **API responses**: English-only for human-readable fields. Stable machine codes (status slugs, enum values) are identifiers, not prose.
- **Tests**: pytest + moto + Hypothesis (Python); Vitest + Testing Library + fast-check (TypeScript). Property-based tests use a minimum of 100 iterations.
- **Documentation**: README and `docs/**` are part of the contribution. If your PR changes a deploy command, parameter name, schema, region default, cost driver, or project structure, the relevant doc is updated in the same PR. See section 8.5 of the steering file.

Validate your change locally before opening the PR:

- Backend: `python -m pytest tests/ -v`
- Frontend: `cd frontend && npm run test` and `cd frontend && npm run build` (the build also runs the locale parity check)
- Infrastructure: `sam validate` for any `template.yaml` change


## Using Kiro when contributing

This sample was built end-to-end with [Kiro](https://kiro.dev) in a spec-driven flow. We encourage contributors to use the same workflow — it tends to produce changes that fit the existing conventions and are easier to review. The notes below describe what we have found works and what does not.

### Spec-driven, vibe-coded, or no agent at all?

Pick the lightest mode the change can support.

| Change shape | Recommended mode | Why |
|---|---|---|
| New feature, new endpoint, new entity, new pipeline phase, security-sensitive change | **Spec-driven** under `.kiro/specs/{feature-name}/` | Three docs (`requirements.md`, `design.md`, `tasks.md`) make the design reviewable before code lands and give Kiro a stable plan to execute against |
| Refactor that touches more than ~3 files, new locale support, doc reorganization, threat-model change | **Spec-driven** | Same reason. The spec is the review artifact; the diff confirms the spec |
| Bug fix with an obvious cause, copy/translation tweak, single-file refactor, dependency bump | **Vibe coding** session in chat | Spec overhead is not worth it for a one-shot change |
| Typo fix, formatting, dead-code removal | **No agent** | Just open a PR |

If you are not sure, default to a spec. The cost of writing a one-page spec is small; the cost of a half-implemented feature without one is high.

### Spec workflow

Specs live under `.kiro/specs/{feature-name}/` and follow the same structure as everything already in the folder:

1. **`requirements.md`** — User stories. Acceptance criteria written as `THE {component} SHALL …`, `WHEN {condition} THEN …`, `IF {condition} THEN …`. Avoid implementation choices here.
2. **`design.md`** — Decisions and contracts. Component boundaries, interfaces, data models (PK/SK if it touches DynamoDB), error handling, correctness properties to be validated by property-based tests, and any rejected alternatives with the reason.
3. **`tasks.md`** — Ordered task list. Each task references the requirements it implements (e.g., `_Requirements: 1.1, 1.6_`). Mark optional test or polish tasks with `*`.

When opening the PR, link the spec folder in the description. Reviewers read the spec first.

### Working effectively with Kiro

A few patterns that consistently produce good output for this project:

- **Point at the steering file early.** The first prompt in a new session usually does well to call out `.kiro/steering/development-standards.md` and any related spec. This is what keeps generated code aligned with i18n rules, log conventions, and the dependency-injection pattern.
- **Separate plan from execution.** Ask Kiro to write or revise the spec first, review it, then ask it to generate or modify code. Mixing both in a single turn tends to produce code that the spec does not justify.
- **Use sub-agents for context gathering.** For "where does X live?" or "explain how the ETL writer works" questions, the `context-gatherer` sub-agent keeps your main session focused on the change.
- **Iterate via small turns.** Tight loops (one task at a time) catch drift early and let you steer Kiro before it commits to a wrong direction.
- **Treat tests as part of the spec.** If the spec says a property must hold (e.g., "every prompt produces exactly one category record"), have Kiro write the property-based test alongside the implementation.

### What to keep out of the agent loop

- **Final security review** of `template.yaml` changes, IAM policies, Cognito attributes, and threat-model entries. Kiro is good at drafting these; a human reviews them.
- **Cost decisions.** The Cost Estimate in the README is a human-curated artifact. Update it manually after Bedrock model swaps, schedule changes, or new always-on resources.
- **Public messaging.** README rewrites, public-facing copy, and aws-samples disclaimers — keep these as a manual review step. Kiro can draft; humans approve tone.

### Example prompts that work well

```
"I want to add a {feature}. Read .kiro/steering/development-standards.md
 and .kiro/specs/{nearest-similar-feature}/, then propose requirements.md,
 design.md, and tasks.md under .kiro/specs/{new-feature}/."
```

```
"Implement task 3.2 from .kiro/specs/{feature}/tasks.md. Apply the i18n
 rules from steering section 4.2 and the dependency-injection pattern
 from section 4.1. Update locales/en.json and locales/pt-BR.json with
 the new keys."
```

```
"Run pytest. If a test fails, propose a fix that does not loosen the
 assertion. Show me the diff before applying it."
```


## Code of Conduct
This project has adopted the [Amazon Open Source Code of Conduct](https://aws.github.io/code-of-conduct).
For more information see the [Code of Conduct FAQ](https://aws.github.io/code-of-conduct-faq) or contact
opensource-codeofconduct@amazon.com with any additional questions or comments.


## Security issue notifications
If you discover a potential security issue in this project we ask that you notify AWS/Amazon Security via our [vulnerability reporting page](http://aws.amazon.com/security/vulnerability-reporting/). Please do **not** create a public github issue.


## Licensing

See the [LICENSE](LICENSE) file for our project's licensing. We will ask you to confirm the licensing of your contribution.