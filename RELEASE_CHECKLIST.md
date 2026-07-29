# Release checklist

1. Update the version in `cyberdrop_desk/__init__.py`, `pyproject.toml`,
   `installer.iss`, `CyberdropDesk.spec`, and the platform build scripts.
2. Confirm the pinned Cyberdrop-DL version in `requirements-dev.txt` and
   `cyberdrop_desk/core.py`.
3. Run all tests.
4. Build and smoke-test Windows, macOS, and Linux packages.
5. Verify each packaged `DropHoundEngine --version`.
6. Update `CHANGELOG.md`.
7. Commit and push the source.
8. Create and push a matching version tag, for example `v0.6.0`.
9. Confirm all GitHub Actions jobs pass and inspect the published assets.
10. Publish SHA-256 checksums with the release notes.
