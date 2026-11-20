# PROPOSED U02 Windows x64 acceptance matrix

The original U02 checklist was not recovered. This matrix is **PROPOSED**, not approved or historically verified. U02 remains **PENDING**. `README.md` documents Windows 11 as the minimum supported Windows system; the Track A CI runner `windows-2025` is Windows Server 2025 and can supply technical evidence but cannot by itself prove Windows 11 desktop behavior. The acceptance owner must decide the required Windows 11 execution coverage and approve any replacement specification.

| ID | Proposed mandatory behavior | Current automated evidence | Unresolved requirement |
|---|---|---|---|
| W1 | Release candidate source digest equals the accepted U01 source digest; record commit, lockfile digest, toolchain and native build log. | Track A CI prebuild, build, and source comparison prepared; no CI run. | The current committed `HEAD` source differs from the accepted snapshot. |
| W2 | Native x64 Windows build yields an AMD64 PE executable with a recorded SHA-256. | Track A CI binary architecture parser and digest check prepared. | Native runner execution and build result. |
| W3 | On a supported Windows 11 host, CLI version, root, `exec`, `resume` and `fork` help, argument rejection, feature list and completion behave as documented. | Eight isolated offline checks prepared for Windows Server 2025. | Native results and Windows 11 desktop execution or explicit owner-approved equivalence. |
| W4 | Configuration and user session paths are isolated from the real user profile. | Disposable HOME, USERPROFILE, APPDATA and LOCALAPPDATA prepared. | Native evidence that the CLI respects isolation. |
| W5 | Applicable Windows process, filesystem, and sandbox restrictions behave according to their documented security contract. | No acceptance test prepared without the original security checklist; native CLI unit tests are technical evidence only. | Recover or approve concrete protected and permitted operations; run native checks. |
| W6 | Terminal interaction, keyboard navigation, session registration and clean termination work on Windows 11. | Noninteractive help checks prepared. | Interactive terminal evidence and approved acceptance details. |

Optional robustness candidates, separate from mandatory acceptance: unsupported-terminal diagnostics, malformed local configuration, repeat execution, and invalid stdin encoding if the CLI contract requires it. No Linux Landlock or Bubblewrap result substitutes for Windows security evidence.

Required owner decisions: approve this or another replacement matrix, define Windows 11 coverage versus Windows Server 2025 technical coverage, and identify the original or replacement security/TUI/session criteria. A green CI job alone does not accept U02.
