# PROPOSED U03 native Intel macOS acceptance matrix

The original U03 checklist was not recovered. This matrix is **PROPOSED**, not approved or historically verified. U03 remains **PENDING**. `README.md` documents macOS 12+; the Track A runner `macos-15-intel` can prove behavior on native Intel macOS 15, but does not establish behavior on macOS 12–14. The acceptance owner must decide required minimum-version coverage and approve a replacement specification.

| ID | Proposed mandatory behavior | Current automated evidence | Unresolved requirement |
|---|---|---|---|
| M1 | Release candidate source digest equals the accepted U01 source digest; record commit, lockfile digest, toolchain and native build log. | Track A CI prebuild, build, and source comparison prepared; no CI run. | The current committed `HEAD` source differs from the accepted snapshot. |
| M2 | Build on real Intel hardware yields an x86_64 Mach-O executable with recorded SHA-256. | Host gate rejects Rosetta; Mach-O parser and digest check prepared. | Native runner execution and build result. |
| M3 | CLI version, root, `exec`, `resume` and `fork` help, argument rejection, feature list and completion behave as documented. | Eight isolated offline checks prepared. | Native results. |
| M4 | Configuration and session paths are isolated from the real user home. | Disposable HOME and CODEX_HOME prepared. | Native evidence that the CLI respects isolation. |
| M5 | Applicable macOS process, filesystem, and sandbox restrictions follow their documented security contract. | No acceptance test prepared without original security cases; native CLI unit tests are technical evidence only. | Recover or approve concrete security expectations; run native checks. |
| M6 | Terminal interaction, keyboard navigation, session registration and clean termination work on supported Intel macOS. | Noninteractive help checks prepared. | Interactive terminal evidence and approved acceptance details. |

Optional robustness candidates, separate from mandatory acceptance: terminal size variation, malformed local configuration, repeated startup, and invalid stdin encoding if required by the CLI contract. Apple Silicon under Rosetta and Ubuntu security results do not prove this scenario.

Required owner decisions: approve this or another replacement matrix, define coverage for macOS 12–14, and identify the original or replacement security/TUI/session criteria. A green CI job alone does not accept U03.
