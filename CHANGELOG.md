# Changelog

All notable changes to DeckPilot are documented here, in the
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) format.

## Versioning

DeckPilot follows [Semantic Versioning](https://semver.org) (`0.x` while alpha), tagged as `v0.x.y`.
To cut a release: bump `__version__` in `app/__init__.py`, move the `[Unreleased]` entries below it
into a new dated section, then `git tag v0.x.y`.

## [Unreleased]

### Added
- **Multi-playlist management**: the playlist panel now edits whichever playlist is selected
  in the dropdown — active or not — so rundowns can be prepared ahead of the show without
  touching what is on air. New RENAME and DELETE buttons alongside NEW/ACTIVATE (deleting the
  active playlist falls back to another one), and NEW jumps straight into the created playlist
  so ADD SELECTED lands in it. New API routes: `GET/PATCH/DELETE /api/playlists/{id}`.
- **Music flag (♪)**: mark a playlist item — or a whole clip from the library, next to the
  loop toggle — as music. The on-air countdown (`/countdown` overlay and the next-clip bar)
  then counts only the videos remaining before the first music item: fire a rundown that ends
  on a music bed and the presenter sees exactly how long until the videos are done, while the
  music itself shows no countdown. The flag survives library re-syncs and is included in
  JSON export/import (`is_music` on clips and playlist items, `countdown_seconds` on transport).
- **ADD LINK downloads video pages (YouTube & co)**: a link that is not a direct stream is
  probed with yt-dlp (real title and duration appear right away), then downloaded in the
  background — H.264 ≤ 1080p preferred, the Pi's hardware decode path — at idle CPU/IO
  priority so playout never stutters. When the download finishes, the link entry is replaced
  by the local file, ingested like any other clip. A dead or unsupported link now shows a red
  error badge with the reason instead of silently looking like a live stream. When a USB
  drive is connected, the ADD LINK dialog asks whether the download goes to internal storage
  or the drive. Direct streams (HLS, RTSP, SRT…) keep the previous streaming behavior.
  yt-dlp ships unpinned in requirements.txt and the updater's pip pass now runs with
  `--upgrade`, so it stays fresh (the Debian-packaged 2023 build is broken against YouTube).
- **Live links (Twitch, YouTube live…) play as streams**: a page link probed as live is
  never downloaded (recording a live until the timeout would fill the disk) — it stays a
  streaming link with its real title, resolved at fire time by mpv's ytdl hook. The hook is
  pointed at the venv's fresh yt-dlp instead of the stale Debian one, capped at 1080p H.264.
- **Music items look off-air to the ATEM**: while a music-flagged clip plays, the HyperDeck
  protocol reports `status: stopped` (speed 0) instead of `play`, so Companion triggers keyed
  on the play→stop transition fire before the music starts and stay put until real video
  resumes. A playlist with no music flags still reports `play` end to end. The web UI keeps
  showing the real transport state.

### Fixed
- **PLAY on a browsed playlist fired the wrong clip**: the main PLAY button always started
  the *active* playlist, so pressing it while viewing another rundown fired the active
  list's first item (e.g. a random library pad). PLAY now targets the playlist being
  viewed, activating it first — same behavior the per-item ▶ buttons already had.
- After a successful web update, the operator UI reloads itself (1.5 s after the
  "success" status) so the browser serves the freshly pulled frontend modules instead
  of the pre-update ones.
- **Web update left the deck offline** (stuck at step 1/4, then unreachable): on SIGTERM,
  uvicorn's graceful shutdown waited forever on the UI's always-open websockets — the old
  process never exited, so systemd never restarted the service and the updater reported
  "DeckPilot did not come back online". uvicorn now force-closes connections after 5 s
  (`timeout_graceful_shutdown`), and the update runner escalates to SIGKILL if the old
  server ignores SIGTERM for 20 s. Note: the fix takes effect on the *next* update after
  this one is installed; the update that installs it still needs a manual
  `sudo systemctl restart deckpilot`.
- Toggling the ♪ flag from the library while the clip is playing now takes effect immediately
  (countdown and HyperDeck status), even outside playlist mode.
- **Music flag ignored outside playlist mode**: a clip flagged ♪ in the library and played
  directly (not through the active playlist) still fed the `/countdown` overlay. The clip-level
  flag now mutes the countdown wherever the clip is launched from.
- **Playlists were unusable beyond the default one**: selecting another playlist in the
  dropdown still displayed (and edited) the active playlist's items, so anything added to a
  second playlist seemed to vanish. The panel now follows the selection, and every item
  action (reorder, remove, end behavior) targets the playlist being viewed.
- A deleted or deactivated active playlist could leave the deck with no active playlist at
  all (the default-playlist fallback only handled the very first boot).
- **Countdown overlay** (`/countdown`): a transparent page meant as an OBS browser source over
  the stage return. It shows the running clip's remaining time the whole way through — steady
  white above one minute (`h:mm:ss` for long clips), then blinking orange, red from 30 s,
  fast-blinking red from 10 s — fed by the existing `/ws` transport events and interpolated
  client-side between ticks. A looping clip never "ends", so instead of a countdown that would
  blink at every wrap, the overlay shows a discreet steady `∞`.
- **Connections modal**: the ATEM target chip in the header now opens a dialog listing every
  address to point gear at — HyperDeck target for the ATEM, web UI URL, countdown overlay URL
  for OBS, hostname, and all detected IPs (values are one-click selectable for copying).
- **SHUT DOWN button** (Settings, next to RESTART DECKPILOT): clean `systemctl poweroff`
  through a dedicated root helper, so the operator can power the Pi off properly and unplug
  without gambling with the SD card (a hard power cut during a write is the classic way a Pi
  stops booting). Ships as a separate single-verb helper + sudoers entry installed by
  `scripts/bootstrap.sh`; re-run it once on existing installs.
- **Safe-eject and drive repair** (Settings → Media Storage): every USB drive row gets an
  EJECT button (flush + strict unmount — refuses while a clip plays from the drive, never a
  lazy unmount) and a plugged-in drive that failed to mount now appears as *not mounted* with
  a REPAIR button that runs the right fsck tool (`ntfsfix` / `fsck.vfat` / `fsck.exfat` /
  `e2fsck`) and remounts. Both go through the bootstrap's root helper via a constrained
  sudoers entry; re-run `scripts/bootstrap.sh` once on existing installs to get the helper
  (the in-app updater says so when it applies this change).

### Changed
- **Updater**: no more silent minutes stuck on "Installing updated Python dependencies".
  The pip pass is now skipped entirely unless the pulled commits touched `requirements.txt`
  (the common case updates in seconds); when it does run, its output streams live into the
  status line with a step counter (`[2/4]`) and elapsed time in the UI. pip runs with
  `--no-input`, fewer retries and no PyPI self-check so a captive venue network fails fast
  instead of hanging, and a hard 15-minute kill covers a fully silent stall.

### Fixed
- **Updater**: a runner process that died mid-update (OOM during pip on a 1 GB Pi, crash)
  left the UI saying "Updating…" forever with no way to retry. A dead runner with no final
  status is now detected and surfaced as a failed update with the step it died on.
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
