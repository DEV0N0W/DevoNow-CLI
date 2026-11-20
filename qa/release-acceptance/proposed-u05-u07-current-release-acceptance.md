# U05–U07 current-release replacement matrices — PROPOSED

The original U05, U06, and U07 checklists, run logs, thresholds, and execution fingerprints were not recovered in Phase 14.2.72 or 14.2.75. Their **PREVIOUSLY ACCEPTED** historical labels remain intact. The matrices below describe new candidate-bound criteria based on the documented CLI and current implementation. They are **not historically verified or acceptance-owner approved**. The Phase 14.2.75 probe is preliminary evidence, not signoff.

## U05 — terminal accessibility

| Proposed requirement | Priority | Evidence needed |
|---|---|---|
| TUI starts in an isolated TTY at normal, narrow, and wide sizes without crash or hang | Mandatory | Captured terminal output and process state at each size |
| Keyboard changes selection/focus; activation, back/escape, menu/overlay return, and clean exit work | Mandatory | Keystroke trace and visible state transitions |
| Errors and notifications remain visible after navigation and resizing | Mandatory | Controlled error and notification trace |
| Readability, contrast, and assistive technology behavior | Manual mandatory for an accessibility claim | Human review with supported terminals and assistive technology |

Automated output capture cannot prove readability, contrast, or screen-reader support. The current auth screen is a suitable offline navigation target; no real authentication is needed.

## U06 — extended stability

| Proposed requirement | Priority | Evidence needed |
|---|---|---|
| Repeated startup, help, features, configuration, invalid input, and sandbox execution | Mandatory | At least 100 total process executions over at least 10 minutes on the accepted Ubuntu binary; command/exit log |
| No crashes, unexpected exit codes, timed-out processes, or leaked child processes | Mandatory | Per-command deadline 20 seconds, process inventory before/after |
| Memory, CPU, and file descriptors remain bounded | Mandatory | Per-run peak RSS and CPU, periodic FD counts; no increasing trend that persists across the final 20% of repetitions |
| Temporary state cleans up | Mandatory | Isolated HOME/CODEX_HOME removal and no surviving test process |

The 100-run/10-minute duration is proposed to sample repeated process lifecycle behavior, not a recovered historical target. The 20-second per-command limit is a safety bound. A numeric memory ceiling needs owner approval after reviewing baseline measurements and VM capacity. The Phase 14.2.75 25-command probe does not meet this proposed extended workload.

## U07 — session resume and fork

| Proposed requirement | Priority | Evidence needed |
|---|---|---|
| Create a session against a loopback Responses endpoint and persist it in disposable CODEX_HOME | Mandatory | Rollout file, session ID, captured local request |
| Discover and resume after process exit; retain original history and append a new prompt | Mandatory | Same session ID, distinct request, persisted parent and resume markers |
| Fork via supported interactive CLI; child ID differs; parent history is copied; subsequent child changes do not alter parent | Mandatory | Two rollout files and structured parent/child content comparison |
| Missing ID and corrupt rollout fail with clear diagnostic and no accidental new session | Mandatory | Exit codes, diagnostics, session inventory |
| All processes and temporary state clean up | Mandatory | Process inventory and disposable directory removal |

The loopback endpoint must reject all paths except `/v1/responses`; no external service or personal credentials are needed. A fork blocked at workspace trust or terminal negotiation is **unverified**, not a pass.

## Decision rule

The acceptance owner must approve each replacement matrix, including workload and resource thresholds, before it can supersede the missing historical specification. Current-build revalidation requires every mandatory requirement to pass on the accepted candidate. Historical **PREVIOUSLY ACCEPTED** and current-build **INCOMPLETE** remain separate fields.
