# Reporting Security Issues

We take all security reports seriously. If you believe you have found a security issue in this project, **please do not create a public GitHub issue**.

Instead, please report security issues to AWS/Amazon Security via our [vulnerability reporting page](https://aws.amazon.com/security/vulnerability-reporting/) or directly to aws-security@amazon.com. Please do **not** create a public GitHub issue.

When reporting, please include:

- A description of the issue and its potential impact
- Steps to reproduce, ideally with a minimal proof of concept
- The affected version(s) or commit hash
- Any suggested mitigations, if you have them

We will acknowledge your report within a reasonable timeframe and keep you informed of the resolution.

## Supported Versions

This project follows a rolling-release model on the `main` branch. Security fixes are applied to `main` and announced in [`docs/changelog.md`](docs/changelog.md). There are no long-term support branches at this time.

## Threat Model

This project follows a formal STRIDE threat model produced with [Threat Composer](https://github.com/awslabs/threat-composer). The model itself is maintained by the project maintainers and is not bundled in the public repository, but mitigations are reflected throughout the codebase and `template.yaml`. When reporting a security issue, describing the affected control (e.g., "API Gateway authorizer", "cross-account AssumeRole trust policy") helps us triage faster.

## Out of Scope

The following are not considered vulnerabilities for this project:

- Issues in third-party dependencies that are already publicly disclosed and waiting on an upstream fix
- Configuration choices made by the deploying account that weaken the defaults shipped in `template.yaml`
- Findings against the demo CloudFront distribution; this repository ships infrastructure-as-code, not a hosted service

## Disclosure Policy

We follow coordinated disclosure. Once a fix is available, we will publish details in the changelog and credit the reporter unless they prefer to remain anonymous.
