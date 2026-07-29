# DropHound 0.6.0 release bundle

This repository is ready to upload to GitHub.

## Included local release packages

- Windows x64 installer and portable ZIP
- macOS Apple Silicon DMG
- Linux x86_64 Debian package and portable archive
- Complete source ZIP
- SHA-256 checksums

## GitHub automation

The `.github/workflows/build-release.yml` workflow builds:

- Windows x64
- macOS Apple Silicon
- macOS Intel
- Linux x86_64

Pushing a `v0.6.0` tag publishes the generated packages as a GitHub Release.

## Versions

- DropHound: 0.6.0
- Cyberdrop-DL backend: 10.3.0
- Python build target: 3.12

Cyberdrop-DL 10.3.0 was verified as the latest stable PyPI release on
July 29, 2026.

## Important

The local `.git` database is intentionally not included because it can contain
machine-specific history, remote addresses, or credentials. All files needed
to initialize and push a clean Git repository are included, along with the
GitHub Actions workflow.
