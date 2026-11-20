# U01 argument validation — approved replacement specification

**Acceptance-owner approval:** 2026-11-16. This specification replaces the unrecoverable historical Phase 14.2.41/14.2.42A criterion for U01 signoff. It does not establish that the original historical tests or their requirements were recovered.

The six retained rejection cases derive from current CLI argument parsing and the `exec` prompt contract. The additional TTY and positive-routing cases derive from `resolve_prompt` in `devnow-rs/exec/src/lib.rs` and the `PROMPT`/`-` interface in `devnow-rs/exec/src/cli.rs`.

| Required case | Expected result | Automated check |
|---|---|---|
| Unknown root option | Nonzero exit; unexpected-argument diagnostic | `u01_argument_validation_current` |
| Invalid completion shell | Nonzero exit; invalid-value diagnostic | `u01_argument_validation_current` |
| Missing `features enable` value | Nonzero exit; required-argument diagnostic | `u01_argument_validation_current` |
| Unknown `exec` option | Nonzero exit; unexpected-argument diagnostic | `u01_argument_validation_current` |
| `exec` without prompt, empty redirected stdin | Nonzero exit; no-prompt diagnostic | `u01_argument_validation_current` |
| `exec -`, empty redirected stdin | Nonzero exit; no-prompt diagnostic | `u01_argument_validation_current` |
| `exec` without prompt on an interactive TTY | Exit 1; explicit missing-prompt guidance, without a network request | `u01_argument_validation_current` |
| Nonempty positional prompt | Exact user text appears in one request to an isolated local Responses endpoint; command succeeds | `u01_prompt_routing_current` |
| Nonempty `-` stdin prompt | Exact stdin text appears in one request to the same isolated local endpoint; command succeeds | `u01_prompt_routing_current` |

The local endpoint binds only to `127.0.0.1`, uses a disposable HOME/CODEX_HOME and a dummy provider key, and records the user-message text without storing authorization headers. No external AI service is part of this test. Both checks are mandatory. A missing, stale, failed, blocked, or skipped result prevents the approved replacement from passing.

Invalid stdin encoding remains **additional robustness coverage**, outside this replacement's mandatory gate. Existing Rust `decode_prompt_bytes` unit tests cover invalid UTF-8 and unsupported UTF-32 BOMs; the acceptance harness does not claim a current executable-level result for those cases.

The imported `u01_argument_validation` record remains separately labeled as historical evidence. U01 may be ACCEPTED under this replacement only after both current checks PASS for the current source, executable, environment fingerprint, and test revisions, and all other mandatory U01 requirements remain satisfied.
