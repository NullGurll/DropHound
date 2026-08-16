# Changelog

## 0.6.2

- Added a pre-download image count for one link or a multi-link batch.
- Added a clear `Check images` control and live discovery status.
- Kept image scans isolated from normal downloads and download history.
- Invalidated stale counts automatically when the pasted links change.

## 0.6.1

- Fixed bulk downloads so every pasted link is handed to the downloader through a one-link-per-line batch file.
- Added an in-box example showing how to enter multiple links.
- Added regression coverage for two-link batches.

## 0.6.0

- Added a live `FILES  completed / discovered` counter to the Activity header.
- Added downloaded, queued, failed, and skipped status tiles.
- Added an About & Supported Links page backed by the bundled engine's site catalog.
- Connected file progress directly to Cyberdrop-DL's structured UI statistics.
- Made the main progress bar reflect file completion once the total is known.

## 0.5.0

- Added native macOS application and DMG packaging.
- Added Linux portable and Debian packages.
- Added three-platform GitHub Actions builds and tagged releases.
- Added platform-native settings directories and folder opening.
- Kept the bundled Cyberdrop-DL backend pinned to tested version 10.3.0.

## 0.4.0

- Added the DropHound hound-and-download-arrow brand mark.
- Integrated icons into the app, Windows executables, shortcuts, and installer.

## 0.3.0

- Renamed the application to DropHound.
- Added live network and disk activity visuals.
- Added current speed, peak speed, transferred data, and elapsed time.
