# Security Policy

## Supported versions

DeepSeek AgentGuard is currently an early-stage research project. Security fixes are applied only to the latest revision of the `main` branch. No released version is considered production-ready.

## Reporting a vulnerability

Please do not publish API keys, personal data, unredacted logs, or working exploits against real systems in a public issue.

When GitHub private vulnerability reporting is available for this repository, use a private security advisory. Otherwise, contact the repository owner through their GitHub profile without including sensitive details in the first message.

A useful report should include:

- A concise description of the issue and its impact.
- The affected commit or version.
- Reproduction steps using synthetic data.
- The expected and observed behavior.
- Suggested mitigation, if known.

Reports that concern DeepSeek itself, another model provider, or a third-party dependency should be submitted to the corresponding vendor or maintainer.

## Research safety boundaries

This repository is intended for defensive research and authorized testing only.

Allowed activities include:

- Running attacks against the local simulated tools and synthetic datasets in this repository.
- Adding prompt-injection cases that use reserved domains such as `example.test`.
- Measuring model behavior, policy decisions and false positives in the provided test environment.
- Improving authorization, validation, logging and evaluation controls.

Out-of-scope activities include:

- Connecting the project to a real mailbox, payment system, cloud account or production database without explicit authorization and a separate security review.
- Collecting or publishing real credentials, personal data or confidential documents.
- Sending unsolicited messages or attempting to access third-party systems.
- Publishing instructions whose primary purpose is unauthorized exploitation.

## API keys and secrets

- Store local credentials only in `.env` or operating-system environment variables.
- Never place a real key in `.env.example`, source code, test fixtures, documentation, screenshots, logs or evaluation results.
- Never commit `.env`, even to a private repository.
- Use a dedicated development key with limited balance whenever possible.
- Revoke and replace a key immediately if it appears in Git history, terminal output, an issue or a shared artifact.
- Redact authorization headers, tool payloads and model traces before publishing them.

Before each push, verify that `.env` is ignored and untracked:

```powershell
git check-ignore -v .env
git ls-files .env
```

The second command must produce no output.

## Synthetic data requirements

Committed datasets must be fictional and safe to publish. Use reserved domains such as `example.com`, `example.net` or `example.test`. Synthetic secrets must be clearly recognizable as test values and must not grant access to any system.

## Safe tool execution

The reference implementation must keep external side effects disabled by default. Tools that simulate sending, deleting, writing memory or accessing confidential resources must operate only on local test state unless an explicitly reviewed integration is added later.

Model-generated tool calls are untrusted input. Tool names must be selected from an explicit allowlist, arguments must be validated against a strict schema, and high-risk actions must pass an independent policy decision before execution.

## Disclosure expectations

The maintainer should acknowledge a valid report, assess its impact, prepare a fix and credit the reporter when requested. Public disclosure should wait until a mitigation is available and sensitive information has been removed.

## Disclaimer

This software is provided for research and educational purposes. It is not a security boundary by itself and must not be treated as production authorization infrastructure.
