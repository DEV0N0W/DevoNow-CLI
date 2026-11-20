# PROPOSED U01 argument-validation acceptance matrix

**Status: superseded proposal.** The acceptance owner approved a narrower replacement specification on 2026-11-16. See `approved-u01-argument-acceptance.md`. This document remains as the original proposal record; it is not itself the active U01 acceptance specification.

## Historical-evidence search

The imported record in `suite/runner.py` says only “CLI input validation and prompt classification” and “Prior terminal: Phases 14.2.41/42A PASS.” The older `reports/latest-results.json` and `reports/latest-summary.md` repeat that description. The supplied acceptance prompts, repository documentation, release archive `devonow-acceptance-v1.zip`, available Codex session records, and Ubuntu guest acceptance files contain no original commands, input cases, expected diagnostics, or original source/binary identity for these phases. The historical PASS is therefore not enough to attest the current executable.

The proposed cases below come from the CLI parser in `devnow-rs/cli/src/main.rs`, the documented `PROMPT`/`-` semantics in `devnow-rs/exec/src/cli.rs`, and `resolve_prompt`/`decode_prompt_bytes` in `devnow-rs/exec/src/lib.rs`. They must not be described as recovered historical requirements.

## Current coverage against proposed criteria

| Proposed case | Expected behavior | Current evidence | Proposed disposition |
|---|---|---|---|
| Unknown root option | Nonzero exit and `unexpected argument` | `u01_argument_validation_current` PASS | Covered |
| Unknown `exec` option | Nonzero exit and `unexpected argument` | Same current check PASS | Covered |
| Invalid completion shell | Nonzero exit and `invalid value` | Same current check PASS | Covered |
| Missing `features enable` value | Nonzero exit and required-argument diagnostic | Same current check PASS | Covered |
| `exec` with no prompt and empty redirected stdin | Nonzero exit and `No prompt provided via stdin.` | Same current check PASS | Covered |
| `exec -` with empty redirected stdin | Nonzero exit and `No prompt provided via stdin.` | Same current check PASS | Covered |
| `exec` with no prompt on a TTY | Nonzero exit and “No prompt provided” guidance | Source behavior identified; no current executable check | PROPOSED additional case |
| Invalid UTF-8 or unsupported UTF-32 prompt bytes on stdin | Nonzero exit and explicit decode diagnostic, without an external request | Existing Rust unit tests cover decoding; no current CLI acceptance check | PROPOSED additional case |
| Nonempty positional prompt and nonempty stdin prompt | Correct source classification without external authentication or network access | Positional/`-` semantics documented; no safe current end-to-end acceptance fixture | PROPOSED fixture-dependent case |

The current PASS log is retained in `reports/evidence-2026-11-16/u01_argument_validation_current-tar6wyr8.log`. It records the command, exit code, and diagnostic for each covered case. The current result is bound to source SHA256 `948b053788ea11007efe7b846c2cd9e11f9df4e00dbe8915dde2421063392201` and executable SHA256 `f3ee5b14d75024c01931dce9cd8028000489800e87c4cf5d1aa8324d927aea4d` in `reports/current-results-2026-11-16.json`.

## Approval and execution boundary

The acceptance owner must confirm which proposed cases constitute the replacement criterion, including whether positive prompt routing requires an isolated fake endpoint or a parser-level fixture. After that decision, add only missing deterministic cases, increment `test_revision` for the changed check, run the harness regression tests, and use `pending` in `devonow-ubuntu2404`. The source and executable need no rebuild if unchanged; valid cached results for other checks remain reusable. Do not map `u01_argument_validation` to current evidence or mark U01 ACCEPTED before the agreed cases pass and the final Markdown, JSON, and terminal states agree.
