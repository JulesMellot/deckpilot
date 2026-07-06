# Changelog

All notable changes to DeckPilot are documented here, in the
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) format.

## Versioning

DeckPilot follows [Semantic Versioning](https://semver.org) (`0.x` while alpha), tagged as `v0.x.y`.
To cut a release: bump `__version__` in `app/__init__.py`, move the `[Unreleased]` entries below it
into a new dated section, then `git tag v0.x.y`.

## [Unreleased]

### Added
- **Countdown overlay** (`/countdown`): a transparent page meant as an OBS browser source over
  the stage return. It shows the running clip's remaining time during its last minute — blinking
  orange, red from 30 s, fast-blinking red from 10 s — fed by the existing `/ws` transport events
  and interpolated client-side between ticks.
- **Connections modal**: the ATEM target chip in the header now opens a dialog listing every
  address to point gear at — HyperDeck target for the ATEM, web UI URL, countdown overlay URL
  for OBS, hostname, and all detected IPs (values are one-click selectable for copying).

### Changed
- **Web UI**: the ~2,900-line `app.js` monolith is now eleven native ES modules (`store`, `util`,
  `dom`, `dialogs`, and one per panel: `media`, `preview`, `playlist`, `transport`, `settings`,
  `health`), split one file per commit with the deck working at every step — still no framework,
  no build step, no runtime dependency. Sub-modules are served with `Cache-Control: no-cache` so
  browsers revalidate them after an update; a node smoke test (`tests/test_ui_modules.mjs`) loads
  the whole module graph in CI and fails on broken imports or startup errors. Removed the dead
  `nudgeTransport` helper.

### Fixed
- **Web UI**: all writes to the shared state snapshot (full fetches, WebSocket messages,
  optimistic volume/safety/display updates) now go through one ordered apply path with a
  sequence guard, so a slow `/api/state` response can no longer overwrite fresher WebSocket
  state (roadmap step 1 of the web UI split). Covered by `tests/test_apply_path.mjs`, run in CI.

## [0.1.0] - 2026-07-01

Initial alpha. DeckPilot emulates a Blackmagic HyperDeck over the Ethernet protocol and drives
mpv-based playout from a browser-based operator panel, targeting a Raspberry Pi 3B+.

### Added
- **HyperDeck protocol**: Ethernet Protocol server aligned with the official Blackmagic spec —
  `device info`, `transport info`, slot/clip/playrange commands, async `notify` subscriptions,
  watchdog handling, remote enable/disable, multi-line command assembly for Companion — plus a
  standalone protocol test bench script.
- **Web UI**: operator-grade control panel with transport controls, VU meter, assignable fire
  pads, drag-and-drop clip assignment, playlist/rundown builder with reordering and end-behavior
  per item, live clip/preview info, in/out marks and timeline scrubbing, speed control, and a
  live config editor.
- **Media library**: folders, bulk-select and mass delete, thumbnails, image and `.webm` support,
  watch-folder ingest, playback from USB and network-mounted drives, optional conform-to-project
  -format on import, storage level/device surfacing.
- **Audio**: independent HDMI/jack output routing and startup mixer boost so the analog jack
  isn't inaudibly quiet by default.
- **Pi optimization**: V4L2 hardware H.264 decode, `cage` + dmabuf-Wayland compositing for fluid
  1080p on a Pi 3B+, CPU yielded to playback during ingest, progressive media ingest.
- **Installer / updates**: interactive bootstrap CLI (bash + PowerShell) that installs systemd
  services, and a web-triggered automatic update flow (git pull, dependency install, restart or
  Pi reboot as needed) with safe-mode support.
- Standby slate on idle output, safe mode, and an arm-controls guard against accidental fires.
- Keyboard-friendly operation: `aria-label`s on the seek slider, volume fader, and refresh
  button, plus a `:focus-visible` outline.
- CI (GitHub Actions): full test suite on Python 3.9 and 3.12, JS syntax check, on every push
  and pull request.

### Fixed
- Numerous HyperDeck protocol conformance fixes for real-world controllers: `remote` returning
  the correct `210` info block, `clips count` support, and watchdog handling so the ATEM and
  Companion stop reconnecting or dropping the deck.
- USB storage churn on flapping/removed drives, and dotfiles no longer treated as media.
- mpv startup hardening and native-loop/audio-drop workarounds on the Pi.
- Modal dialogs kept inside the viewport; various web UI layout and English-copy fixes.
- Update/reboot recovery edge cases (systemd cgroup kill during restart, missing `_seatd`
  group, safe-mode interaction with web updates).
- HyperDeck server: no longer drops the connection on a malformed/oversized `clip id` or
  `slot id` (answers `102` instead of crashing), and resyncs cleanly after a line longer than
  the 64KB read buffer instead of tearing down the socket.
- HyperDeck server: `508` transport notifications now advertise the first clip id instead of
  `0`, matching the synchronous `transport info` behavior the ATEM relies on for auto-roll.
- mpv IPC reads now time out (10s) instead of blocking forever when mpv wedges (GPU/decoder
  hang), so a stuck command fails cleanly instead of freezing every transport control.
- Web UI: WebSocket reconnect backs off exponentially (1s -> 15s cap), a stale `/api/state`
  response can no longer clobber newer state (request-id guard), and drag visuals always
  reset even when a drag ends outside a valid drop target.
- Python 3.9 compatibility: asyncio primitives are created lazily inside the running loop.
