# Contributing to DevoNow CLI

Thanks for helping improve DevoNow CLI. Bug reports, feature proposals, documentation changes, tests, and code contributions are welcome.

Participation is governed by the project [Code of Conduct](../CODE_OF_CONDUCT.md).

## Before you start

1. Search the [issues](https://github.com/DEV0N0W/DevoNow-CLI/issues) to avoid duplicates.
2. For a significant feature or architecture change, open an issue before investing in an implementation.
3. Keep each pull request focused on one problem.
4. Never include credentials, tokens, private prompts, customer data, or generated local configuration.

## Development workflow

1. Fork the repository and clone your fork.
2. Create a topic branch from `master`, such as `feat/better-agent-routing` or `fix/windows-startup`.
3. Make the smallest complete change that solves the issue.
4. Add or update tests for behavior changes.
5. Update user documentation and snapshots when output or the terminal UI changes.
6. Run the checks that apply to the crates you changed.
7. Open a pull request describing what changed, why it changed, and how it was tested.

## Local Rust checks

Follow the [source build requirements](../README.md#requirements) before running checks. Run these commands from `devnow-rs`. Set `crate` to the Cargo package you changed.

```bash
crate=codex-tui
cargo test -p "$crate"
```

Install `just` for the formatting and lint recipes. The first two recipes can modify source files. Review their changes before committing. The argument-comment lint runs from the repository root and requires DotSlash and the pinned nightly toolchain. See the [lint setup guide](../tools/argument-comment-lint/README.md).

```bash
just fmt
just fix -p "$crate"
(cd .. && just argument-comment-lint)
```

For terminal UI changes, run the suite that covers the affected behavior. If both terminal UIs implement that behavior, run both suites.

```bash
cargo test -p codex-tui
cargo test -p codex-tui-app-server
```

If your change affects snapshots, install `cargo-insta` and review the pending snapshots for the affected package before accepting them.

```bash
cargo insta pending-snapshots -p "$crate"
```

## Pull-request expectations

- Explain the user-visible result.
- Link the related issue when one exists.
- Include focused tests and documentation.
- Keep commits understandable and free of unrelated formatting churn.
- Preserve the Apache 2.0 license and all applicable notices.
- Confirm that no secrets or sensitive data are included.

Maintainers may request revisions for correctness, scope, test coverage, documentation, or long-term maintainability.
