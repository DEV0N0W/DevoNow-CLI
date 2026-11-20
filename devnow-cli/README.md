# DevoNow CLI npm package

The DevoNow CLI package is `@devn0w/devnow-agent`. Its public command is `devnow`.
This checkout uses a private development version; it is not a published release.

<!-- Begin ToC -->

- [Installation](#installation)
- [Release staging](#release-staging)
- [Verification](#verification)

<!-- End ToC -->

## Installation

Install a maintainer-approved published version with:

```sh
npm install -g @devn0w/devnow-agent@<version>
devnow --version
devnow --help
```

## Release staging

Release staging creates a wrapper and six platform payloads from this checkout.
Platform dependency aliases use the same package name with a platform suffix.
The underlying payload versions carry that suffix too. Native `codex` filenames
are retained for launcher and helper compatibility.

Use `scripts/stage_npm_packages.py --help` from the repository root to stage a
release. `--vendor-src` selects locally built native payloads without fetching
release artifacts. Staging does not publish. Each archive includes the original
root LICENSE and NOTICE. Upstream attribution is preserved.

## Verification

Run the offline packaging regression checks with:

```sh
python3 -B -m unittest discover -s devnow-cli/tests -v
```

Project source, issues, and support: <https://github.com/DEV0N0W/DevNow-CLI>.
