# DevoNow CLI — Incremental release acceptance harness v1

This is a **ready-to-run harness** for the existing `devonow-ubuntu2404` Lima Ubuntu 24.04 ARM64 VM. It does not change application source, commit, push, deploy, alter AppArmor, or authenticate to any AI service. It copies generated reports and logs into the harness `reports/` directory, which may be inside the checkout when run from this repository.

## Quick start (macOS Terminal)

1. Download `devonow-acceptance-v1.zip` to your `~/Downloads` folder.
2. Run:

```bash
cd ~/Downloads
unzip -q devonow-acceptance-v1.zip
cd devonow-acceptance-v1
./host-run.sh pending
```

The runner will automatically:

- Confirm that `devonow-ubuntu2404` is running and contains the existing source snapshot and built Linux executable.
- Copy only `suite/` into `$HOME/devonow-acceptance-suite` in the Ubuntu VM.
- Create an independent persisted state at `$HOME/.local/state/devonow-acceptance` in the Ubuntu VM.
- Carry forward previously completed checks with the explicit status `CARRIED_FORWARD` (historical evidence, **not rerun**).
- On a fresh state only, import the original Bubblewrap `RTM_NEWADDR` failure as historical evidence. Existing automated results remain in state.
- Execute **only new, safe U01 Linux checks**.
- Produce machine-readable JSON, a Markdown summary, and per-test logs.
- Copy the report to `devonow-acceptance-v1/reports/` on your Mac, outside your original repository.

### Modes

```bash
./host-run.sh pending          # New quick checks only; skip cached passes/unchanged failures
./host-run.sh report           # Rebuild the report; execute no tests
./host-run.sh retry-bubblewrap # Recheck default Bubblewrap execution and security checks
./host-run.sh extended         # Remaining quick checks + optional slow Cargo sandbox package tests
./host-run.sh build            # Native offline ARM64 build provenance, then current quick checks
```

Do not disable AppArmor or run as root simply to make a test pass.

## What is imported without rerunning

**U05/U06/U07:** previously accepted in the earlier testing workflow; those results are not validated or repeated by this harness.

**U01:** native ARM64 build, basic binary execution, CLI smoke/argument validation, interactive interface startup, Landlock `/usr/bin/id`, filesystem restrictions, and IPv4 loopback network restriction.

The prior chat transcripts did not capture cryptographic identities at the time the tests ran. Accordingly, imported checks are marked **`CARRIED_FORWARD`** and explicitly documented as non-attested. The harness pins that import to the current binary and source snapshot *as an operational assumption*, not as proof the original runs used identical bytes.

**Bubblewrap:** a fresh state imports the original `FAIL` blocker. A later automated result for the current fingerprint replaces that result without changing historical logs.

## New quick U01 checks run on first `pending`

- ELF shared library resolution using `ldd`.
- Offline locked Cargo workspace metadata validation (no compilation).
- Zsh and Fish shell completion generation (Bash was already tested).
- `mcp list` using a completely disposable HOME/CODEX_HOME.
- Offline `resume --help` and `fork --help` registration checks (not actual session resume/fork).
- Landlock default read-only working-directory protection.
- Landlock symlink-escape write prevention.
- IPv6 loopback HTTP isolation, if IPv6 loopback is available.
- Current binary startup, offline CLI smoke checks, invalid-option rejection, Landlock command execution, authorized write, and IPv4 isolation.
- Default Bubblewrap command execution, read-only and authorized-write boundaries, symlink escape prevention, and IPv4/IPv6 loopback isolation.

Every check has an actual assertion, timeout, status, and log. Independent tests continue when another fails. New tests may legitimately **FAIL, BLOCK, or SKIP** depending on your build and guest environment; the harness does not turn failures into a PASS.

The **automated mandatory gate** passes only when every quick check has a current automated `PASS` and source integrity passes. Missing, failed, blocked, stale, and skipped mandatory checks remain unresolved. The optional extended test does not block this gate. **Full U01 acceptance** additionally requires current evidence for every U01 criterion. The `build` mode forces a native CLI package rebuild, retains the prior binary, and records source, lockfile, toolchain, build log, status, and resulting executable identity. The quick lane verifies isolated PTY authentication selection. Current version/help/features/completion checks cover the named smoke requirements. The acceptance owner approved `approved-u01-argument-acceptance.md` as a replacement for the unrecoverable Phase 14.2.41/42A criterion. Both mandatory replacement checks must PASS before full U01 acceptance; the original imported record remains historical and separately labeled. The Markdown, JSON `acceptance` object, and terminal summary use the same evaluation.

The default `pending` lane **does not compile the CLI again** or repeat prior heavy tests. `extended` deliberately permits sandbox package Cargo tests (single build job, timeout); use it separately because the VM has 6 GiB RAM and no swap.

## How the cache works

- Every run computes a SHA-256 digest of the entire source snapshot (excluding generated `target`, `.git`, and caches), the compiled CLI binary, and relevant Ubuntu/kernel/AppArmor environment state.
- Matching automated PASS results from the same fingerprint, harness version, and test revision are reused, not rerun.
- Matching existing FAIL/BLOCKED/SKIPPED results are retained unless explicitly retried or the environment/build fingerprint changes.
- `retry-bubblewrap` explicitly reruns every default Bubblewrap check, including cached passes. Superseded result objects remain in state history and each run receives a new log file.
- Changed binary/source/environment or a changed test revision invalidates applicable stored quick-test passes. New test IDs start pending. Carried-forward Linux evidence becomes `STALE_PRIOR_EVIDENCE` rather than silently being accepted for a new build.
- State lives **outside the source checkout**. Running from the Mac again preserves prior state in the VM.
- Each run rehashes source files to detect accidental source modifications. It does not modify tracked or untracked files in the macOS repository.

## Report location

Inside VM:

```text
$HOME/.local/state/devonow-acceptance/
├── state.json
├── reports/
│   ├── latest-summary.md
│   └── latest-results.json
└── logs/
    └── u01_*.log
```

On macOS, after the host script copies the output:

```text
~/Downloads/devonow-acceptance-v1/reports/
├── latest-summary.md
├── latest-results.json
└── logs/
    └── u01_*.log
```

## Scope and release-signoff limits

- **This is incremental U01 Linux automation, not complete release certification.** It does not claim that U01 or the broader release is accepted.
- Default Bubblewrap remains a blocker until explicitly remedied and verified.
- U05/U06/U07 are historical, not re-proven by the harness.
- U02 Windows, U03 Intel macOS, U04 published packages, and A01–A10 cloud are tracked as pending/blocked only; no unsupported simulation is presented as passing evidence.
- All code is run on the *copied VM source snapshot*, not the macOS original. `cargo metadata` and opt-in Cargo tests may write standard Cargo caches/build output **inside the VM**; none of the quick tests edits source files.
- Network tests use only `::1`/IPv6 loopback; no external service or credentials are required.
- Test failures are informative and remain present in the final report. Only a release reviewer can grant final acceptance.

## Phase 14.2.71 cross-platform readiness

The [17-scenario dashboard](reports/phase-14-2-71/dashboard.md) and its [JSON view](reports/phase-14-2-71/dashboard.json) are generated together by `phase_14_2_71_dashboard.py`. They retain U01's 25/25 accepted mandatory checks under the approved replacement, identify U05–U07 as previously accepted, and distinguish preliminary work from scenario acceptance. Original detailed U02–U04 and A01–A10 criteria remain unavailable; their acceptance-check totals are therefore unknown, not inferred from these helpers.

`native_preflight.py` requires a real Windows 11 host for U02 or native Intel macOS 12+ for U03. It checks a supplied executable against an independently recorded SHA-256, then runs six isolated offline CLI checks. It rejects Rosetta as Intel evidence. A `PREFLIGHT_PASS` is preparation for the original scenario checklist, not U02/U03 acceptance. The current Apple Silicon host-readiness results are `BLOCKED` without executing any candidate.

```bash
python3 -B qa/release-acceptance/native_preflight.py \
  --scenario U02 --binary /path/to/native/devnow.exe \
  --expected-sha256 ACTUAL_INDEPENDENT_RELEASE_DIGEST \
  --output qa/release-acceptance/reports/phase-14-2-71/u02-native-preflight.json
```

For U03, use `--scenario U03`, a native Intel `devnow` executable, and `u03-native-preflight.json` on an Intel Mac. Record OS/toolchain, source and artifact provenance, then complete the recovered original security, TUI, configuration, and session checks before signoff.

`published_package_preflight.py` checks a supplied genuine npm `.tgz` against an independently recorded digest, package name/version, optional OS/CPU metadata, archive paths, and legal files. It does not prove publication, signing, installation, runtime behavior, or removal. The current U04 artifact-readiness result is `BLOCKED`; the 14/14 passing offline packaging tests use generated fixtures.

```bash
python3 -B qa/release-acceptance/published_package_preflight.py \
  --archive /path/to/published/devnow-agent-VERSION.tgz \
  --expected-sha256 ACTUAL_INDEPENDENT_RELEASE_DIGEST --version VERSION \
  --output qa/release-acceptance/reports/phase-14-2-71/u04-package-preflight.json
```

After evidence files are updated, run `python3 -B qa/release-acceptance/phase_14_2_71_dashboard.py` to regenerate both dashboard views. This command reads the retained U01 result; it does not rerun or invalidate U01. The Phase 14.2.71 [campaign report](reports/phase-14-2-71/campaign-report.md) records the present host, package, and cloud blockers.

## Phase 14.2.72 Track B

The [Track B report](reports/phase-14-2-72/track-b-report.md) assesses U04–U07 and the ten cloud scenarios. Its [Markdown dashboard](reports/phase-14-2-72/dashboard.md) and [JSON dashboard](reports/phase-14-2-72/dashboard.json) are generated together by `phase_14_2_72_dashboard.py` from the retained U01 result, Phase 14.2.71 readiness evidence, and the new bounded probe. The ten cloud JSON rows keep missing specifications explicit; no provider or scenario behavior is inferred from generic cloud-task mocks.

The package preflight accepts `--expected-target` alongside `--expected-os` and `--expected-cpu` to check the actual native executable path and POSIX execute permission. It also rejects unsafe archive members and duplicate paths. Use the exact target triple from the independently identified release artifact. A preflight PASS never proves publication or clean installation.

`bounded_offline_probe.py` runs a maximum of 20 repetitions of three offline CLI commands in a disposable HOME/CODEX_HOME. It requires an independent executable SHA-256 and retains every result. The recorded five-round macOS ARM64 debug-binary result is preliminary U06 evidence only. Run it against an identified current candidate only when its source and executable provenance are available.

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s qa/release-acceptance/tests -q
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s devnow-cli/tests -q
python3 -B qa/release-acceptance/phase_14_2_72_dashboard.py
```

## Phase 14.2.73 Track A

The [Track A report](reports/phase-14-2-73/track-a-report.md) and [dashboard](reports/phase-14-2-73/dashboard.md) record preparation for native Windows x64 and Intel macOS. The original U02 and U03 checklists remain missing; the separate [U02](proposed-u02-windows-acceptance.md) and [U03](proposed-u03-intel-macos-acceptance.md) matrices are **PROPOSED**, not approved.

The `.github/workflows/devonow-track-a-acceptance.yml` workflow has separate manually triggered `windows-2025` and `macos-15-intel` jobs. Each verifies its native architecture, hashes its checkout with the U01 source algorithm, builds `codex-cli` with `--locked`, checks executable architecture and SHA-256, runs eight isolated offline CLI checks and focused CLI unit tests, then uploads structured evidence and logs even on failure. A source mismatch fails the source-comparison step. The workflow contains no publication or cloud action. It was later pushed to `feature/UX` but has not been dispatched. The [testing-scope decision](reports/testing-scope-decision-2026-11-18.md) discontinued Windows and cloud testing for this branch without changing their acceptance statuses.

The [source identity record](reports/phase-14-2-73/source-identity.json) captures the earlier state: the working `devnow-rs` tree matched U01's accepted source digest, while committed `HEAD` did not. The source was subsequently committed to `feature/UX`; the historical record remains unchanged. The local Apple Silicon host-readiness records block U02 and U03 without running their binaries.

The following command is retained for reproducing the historical Track A dashboard; the current testing-scope decision does not call for a new Track A run:

```bash
python3 -B qa/release-acceptance/phase_14_2_73_dashboard.py
```
