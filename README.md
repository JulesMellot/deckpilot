# DeckPilot

DeckPilot is an open-source HyperDeck-style playout system built for ATEM, Bitfocus Companion, and lightweight live playback workflows.

It behaves like a network-controlled video deck (a Blackmagic HyperDeck) while providing a modern web interface for clip management, trimming, playlists, preview, and playback control. There is no build step on the frontend and storage is a single SQLite file, so it runs comfortably on an SBC (Raspberry Pi class) as well as on a desktop.

## How It Works

DeckPilot runs three cooperating pieces in one process:

- a **HyperDeck-compatible TCP server** (port `9993`) that an ATEM or Companion talks to as if it were a real deck
- a **FastAPI web app** (port `8080`) that serves the operator UI, a REST API, and a WebSocket for live state
- an **`mpv` playback engine** driven over JSON IPC, rendering fullscreen on the selected display

State flows one way: the UI and the HyperDeck protocol both call into a single playback controller, which updates shared state and pushes incremental updates to every connected browser over WebSocket. `ffmpeg`/`ffprobe` handle thumbnailing and metadata in the background.

```
ATEM / Companion ──TCP 9993──┐
                             ├──> DeckController ──IPC──> mpv ──> HDMI / display
Browser UI ──REST + WS 8080──┘         │
                                       └──> SQLite (clips, playlists, folders, marks)
```

## What's Implemented

### Playback & transport
- play, stop, pause/resume, cue (load-and-hold on the first frame), and cut-to-black
- warm `mpv` reuse: cue then play resumes the loaded clip without reloading, and stop keeps the player process warm for the next take
- automatic player recovery if the `mpv` IPC connection drops mid-playback (re-launch and re-seek to the current position)
- loop mode kept in sync between app state and `mpv`
- live timecode with remaining-time countdown and warning/danger states as a clip nears its end

### Trim marks (in / out)
- per-clip **in/out marks** persisted in SQLite, used to trim the playable region
- cue and play start at the in mark; playback auto-stops (or advances the playlist) at the out mark; looping stays inside the `[in, out]` window
- the **remaining timer counts down to the out mark** and the UI shows the trimmed clip duration
- set marks two ways: from the **live transport** (SET IN / SET OUT / CLEAR at the current playhead) or directly from the **browser preview** while scrubbing the clip, with green/red mark ticks and a live playhead

### Timeline scrubbing
- seek the live clip with a position slider and ±10s nudge buttons, backed by `mpv` `time-pos` seeking
- mark ticks rendered on the scrub bar for quick orientation

### Media library
- web upload for video clips, streamed to disk to keep memory low on large imports
- background enrichment: fast placeholder insertion, then deferred metadata + thumbnail generation with per-clip processing states and a live ETA during import
- media folders with folder-based navigation, grid and list views, search and type filtering
- rename, reorder (drag), move between folders, delete
- automatic thumbnails (versioned and cache-friendly), vertical-video detection with blurred-background fill on playout
- built-in `Black` and `Test Pattern` clips generated on first run

### Playlists
- persistent playlists with activate, add/remove/reorder items, play, play-from-position, next, and loop mode
- single-clip vs playlist playback modes

### Output & audio
- selectable video output (display) and video format
- output canvas mode (auto / fixed resolution) for letterboxing control
- master volume and mute
- branded **standby slate** on the playout output when idle (grey radial-gradient background with the deck name and live network targets) instead of a black screen, regenerated when the IP changes

### HyperDeck protocol (ATEM / Companion)
- multi-client TCP server implementing the commands ATEM and Companion use: `device info`, `configuration`, `clips get`, `transport info`, `slot info`/`slot select`, `play`, `stop`, `goto`/`start`/`end`, `playrange set`/`playrange clear`, `preview`, `notify`, `remote`, `ping`, `help`, `quit`
- async notifications (transport / slot / clips) to subscribed controllers
- the HyperDeck network target is shown in the web UI for easy ATEM setup
- real-time HyperDeck logs streamed into the UI

### Operator safety
- **safe mode** is on by default: live actions (play / stop / cut) must be **armed** for a short window before they fire, to avoid accidental on-air changes
- preview-enable and remote-enable toggles
- system health panel: player status, storage, controller count, sync timestamps

### UI & performance
- WebSocket-driven incremental updates instead of full rerenders
- DOM node reuse, event delegation, and light virtualization for large media/playlist views
- static assets are cache-busted by file mtime, so a browser always loads fresh CSS/JS after an update (no manual hard-refresh needed beyond the first time)

## Control Surface

- **REST**: `/api/state`, `/api/clips*`, `/api/clips/{id}/{goto,play,marks,rename,loop,folder}`, `/api/transport/{stop,pause,resume,seek}`, `/api/playlists*`, `/api/system/{outputs,output,output-canvas,video-format,black,safe-mode,arm-controls,update}`, `/api/audio/{volume,mute}`, `/api/upload`
- **WebSocket**: `/ws` streams transport, clips, folders, playlists, audio, outputs, health, logs, and safety snapshots
- **HyperDeck TCP**: port `9993` (see commands above)

## Technology Stack

- Python 3.9+
- FastAPI + Uvicorn
- asyncio TCP server for the HyperDeck protocol
- SQLite (single-file storage, schema migrated in place on startup)
- `mpv` via JSON IPC
- `ffmpeg` / `ffprobe`
- HTML / CSS / vanilla JavaScript (no build step)

## One-Command Install

DeckPilot ships with bootstrap installers that detect the host platform, install missing dependencies, clone or update the repository, create the Python environment, generate `config.json`, and optionally install a system service on Linux.

### Linux / macOS

```bash
curl -fsSL https://raw.githubusercontent.com/JulesMellot/deckpilot/main/scripts/bootstrap.sh | bash
```

### Windows PowerShell

```powershell
irm https://raw.githubusercontent.com/JulesMellot/deckpilot/main/scripts/bootstrap.ps1 | iex
```

### What The Bootstrap Does

- detects the operating system
- installs missing system dependencies
- clones or updates DeckPilot
- creates `.venv`
- installs Python requirements
- writes a local `config.json`
- optionally installs and enables a `systemd` service on Linux
- installs an HDMI boot info screen service automatically on supported Linux SBC targets

### Platform Notes

- Linux: supported
- macOS: supported for local setup and development
- Windows: bootstrap is available, but runtime support is still experimental because the current `mpv` IPC layer is not fully adapted yet

## Local Run

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python3 -m app.main
```

The web UI is then available at [http://127.0.0.1:8080](http://127.0.0.1:8080).

Useful environment overrides for local profiling or custom installs:

- `PIDECK_HTTP_PORT` - change the FastAPI port
- `PIDECK_HYPERDECK_PORT` - change the HyperDeck TCP port
- `PIDECK_CONFIG` - point to a custom `config.json`
- `PIDECK_MEDIA_ENRICHMENT_WORKERS` - tune concurrent background media enrichment workers

Configuration lives in `config.json` (see `config.json.example`): ports, media/data directories, `mpv`/`ffmpeg` binaries, default video format and framerate, WebSocket tick rate, and allowed upload extensions.

If you already cloned the repository and want the guided installer instead of doing setup manually:

```bash
./scripts/bootstrap.sh
```

## Quick Protocol Test

```bash
python3 scripts/hyperdeck_test_client.py 127.0.0.1 9993
```

The test client supports a scripted batch run and an interactive mode for exercising transport and `playrange` (in/out) commands by hand.

## ATEM Usage

1. Connect DeckPilot video output to an HDMI input on your ATEM.
2. Add DeckPilot in the HyperDeck tab of ATEM Software Control.
3. Use the HyperDeck target shown in the DeckPilot web UI.
4. Enable the workflow you want, including Auto Roll if needed.

When properly configured, ATEM can control DeckPilot over the network like a standard HyperDeck-style deck.

## Status

DeckPilot is in **alpha / early beta**. It is already usable for testing and real-world validation, but it should still be treated as a work in progress until it has gone through broader hardware and production testing.

## Roadmap

### Done
- playback core: cue / play resume / stop with warm `mpv`, loop sync, automatic player recovery
- timeline scrubbing (seek slider + ±10s nudge) backed by `mpv time-pos`
- per-clip in/out marks: persisted, mark-aware playback (start at in, stop/advance at out, loop in window), mark-aware remaining timer
- set marks from the live transport and from the browser preview (with mini-timeline, ticks, and live playhead)
- media library: streamed uploads, background metadata/thumbnail enrichment with live ETA, folders, grid/list, search, rename/reorder/move/delete
- playlists: persistent, activate/add/remove/reorder/play/next/loop
- output & audio: selectable display, video format, canvas mode, volume/mute, branded standby slate on idle output
- HyperDeck protocol coverage for ATEM/Companion with async notifications and visible network target
- operator safety: safe mode + arm-to-fire live controls
- UI/perf: incremental WebSocket rendering, virtualization, cache-busted static assets
- preview video sizing fix (no longer overflows the modal)
- targeted automated tests for state handling, cue/loop/seek/marks behavior, and media ingestion

### In progress / Near term
- real-world ATEM validation and broader HyperDeck protocol coverage
- polish the playlist workflow and overall operator UX
- clearer import queue / processing diagnostics for operators
- better ETA accuracy across mixed clip sizes and longer import batches
- documentation and first-run setup improvements

### Planned (mid term)
- stronger cross-platform output handling and multi-display control
- improved Windows runtime support for `mpv` IPC and playback
- better logging, monitoring, and fault reporting for live use
- expanded automated test coverage for the protocol and services
- packaging / release workflow and native installer packages

### Exploring (long term)
- advanced playlist and rundown workflow
- richer operator dashboards and status views
- optional clip tags and smarter media search
- configurable operator profiles or locked-down UI modes
- richer ATEM debugging tools

## Contributing

Contributions, testing feedback, and real ATEM validation reports are welcome. If you are testing DeckPilot with live hardware, protocol traces and setup notes are especially useful.
