# DevoNow CLI distribution

The CLI package identity is `@devn0w/devnow-agent`, with the public `devnow`
command. The SDK and proxy packages use `@devn0w/devnow-agent-sdk` and
`@devn0w/devnow-agent-responses-api-proxy`. Package metadata and first-party
release downloads point to `DEV0N0W/DevNow-CLI`.

The checkout stays private at its development version. Explicit versioned
staging removes the private flag; staging never publishes. The release owner
must verify registry namespace ownership, OIDC trusted publishing, signing
credentials and release permissions before publication.

## Offline staging

Build native payloads from the candidate checkout, then arrange them under
`<vendor>/<target>/codex/codex` (or `codex.exe`), with ripgrep under `path/rg`
(or `rg.exe`). Windows payloads also need the existing sandbox helper binaries.
Native filenames, Rust crate names and protocol identifiers retain compatibility
with the upstream implementation.

```sh
python3 -B scripts/stage_npm_packages.py \
  --release-version <version> --package codex \
  --vendor-src <vendor> --output-dir <output>
python3 -B -m unittest discover -s devnow-cli/tests -v
```

The wrapper archive is `devnow-npm-<version>.tgz`. Payload archives are
`devnow-npm-<platform>-<version>.tgz`. Platform dependency aliases append the
platform to the CLI package name and resolve the matching platform-suffixed
version of that package. The SDK and proxy archive names start with
`devnow-sdk-npm-` and `devnow-responses-api-proxy-npm-` respectively.

Without `--vendor-src`, staging requires an explicitly selected or resolved
DevoNow release workflow run. Foreign project workflow URLs are rejected.
CI tests fixture payload selection and archives offline; fixtures do not certify
native execution on another platform. Native Rust CI and release jobs remain
responsible for compiling and validating actual candidate binaries.

## Attribution and installation

Staged npm packages, native tar/zip bundles and macOS CLI disk images include
unmodified root LICENSE and NOTICE documents. Raw compressed executables cannot
contain extra files; LICENSE and NOTICE are also separate release assets.
The installers retain documents in `devnow-licenses` beneath the installation
directory. Ripgrep payloads also retain their original license documents, and their downloads
are checked against the configured archive size and digest before extraction.
Source npm directories carry exact copies, checked by the packaging tests.
When attribution changes, update those copies from the root documents.

The shell and PowerShell installers fetch the matching DevoNow npm payload and
install `devnow` or `devnow.exe`. `DEVNOW_INSTALL_DIR` overrides the destination;
`CODEX_INSTALL_DIR` remains a compatibility fallback. Verify an approved release
version and artifact provenance before installation. The optional upstream
desktop integration is a separate product and is not a DevoNow CLI disk image.

## Optional publication integrations

WinGet publication requires the release owner's configured repository variables
`DEVNOW_WINGET_PACKAGE_ID` and `DEVNOW_WINGET_FORK_USER`, plus its publishing
credential. No upstream publisher identity is used by default. The owner must
register and verify the intended DevoNow identity before enabling it.

The website hook runs only with `DEVNOW_WEBSITE_DEPLOY_ENABLED=true` and the
`DEVNOW_WEBSITE_DEPLOY_HOOK_URL` secret. Configure it for a controlled DevoNow
site. These integrations do not replace any build, lint or package validation.
