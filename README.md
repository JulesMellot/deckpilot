# DeckPilot

DeckPilot is an open-source HyperDeck-style playout system built for ATEM, Companion, and lightweight live playback workflows.

It is designed to behave like a network-controlled video deck while providing a modern web interface for clip management, playlists, preview, and playback control.

## What It Does

DeckPilot provides:

- a HyperDeck-compatible TCP server on port `9993`
- a FastAPI web interface for media management and playback
- `mpv`-based fullscreen output on the selected display
- SQLite storage for clips, playlists, folders, and metadata
- a lightweight frontend with no build step

## Current Features

- HyperDeck protocol support for ATEM and Bitfocus Companion
- web upload for video clips
- play, stop, pause, cue, and cut-to-black controls
- persistent playlists with playback and loop mode
- media folders with folder-based navigation
- browser preview per clip
- automatic thumbnail generation
- selectable video output
- selectable video format
- audio volume and mute control
- visible HyperDeck network target for ATEM setup
- vertical video detection with blurred background fill on playout
- real-time HyperDeck logs in the UI
- media grid and list views

## Technology Stack

- Python 3.9+
- FastAPI + Uvicorn
- asyncio TCP server for the HyperDeck protocol
- SQLite
- `mpv` via JSON IPC
- `ffmpeg` / `ffprobe`
- HTML / CSS / JavaScript (vanilla)

## One-Command Install

DeckPilot now ships with bootstrap installers that detect the host platform, install missing dependencies, clone or update the repository, create the Python environment, generate `config.json`, and optionally install a system service on Linux.

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

### Platform Notes

- Linux: supported
- macOS: supported for local setup and development
- Windows: bootstrap is available, but runtime support is still experimental because the current `mpv` IPC layer is not fully adapted yet

## Project Structure

- `app/core/` - configuration, models, and shared state
- `app/hyperdeck/` - HyperDeck protocol parsing and multi-client server
- `app/media/` - clips, playlists, folders, metadata, thumbnails
- `app/player/` - `mpv` control layer
- `app/services/` - playback orchestration, networking, outputs
- `app/web/` - FastAPI routes and WebSocket layer
- `app/static/` - frontend assets
- `scripts/` - install and test helpers
- `deploy/` - `systemd` service files
- `docs/` - installation documentation

## Local Run

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python3 -m app.main
```

The web UI is then available at [http://127.0.0.1:8080](http://127.0.0.1:8080).

If you already cloned the repository and want the guided installer instead of doing setup manually:

```bash
./scripts/bootstrap.sh
```

## Quick Protocol Test

```bash
python3 scripts/hyperdeck_test_client.py 127.0.0.1 9993
```

## ATEM Usage

1. Connect DeckPilot video output to an HDMI input on your ATEM.
2. Add DeckPilot in the HyperDeck tab of ATEM Software Control.
3. Use the HyperDeck target shown in the DeckPilot web UI.
4. Enable the workflow you want, including Auto Roll if needed.

When properly configured, ATEM can control DeckPilot over the network like a standard HyperDeck-style deck.

## Status

DeckPilot is currently in alpha / early beta.

It is already usable for testing and real-world validation, but it should still be treated as a work in progress until it has gone through broader hardware and production testing.

## Roadmap

### Near Term

- improve ATEM real-world validation and protocol coverage
- refine playback reliability and error handling
- polish playlist workflow and operator UX
- improve browser preview and media browsing
- add clearer health/status indicators for player, output, and storage
- improve documentation and setup guides
- strengthen the cross-platform installer and first-run experience

### Mid Term

- stronger cross-platform output handling
- better logging and operator diagnostics
- safer operational controls for live use
- expanded automated test coverage for protocol and services
- packaging and release workflow improvements
- improve Windows runtime support for `mpv` IPC and playback

### Long Term

- advanced playlist and rundown workflow
- richer operator views and status dashboards
- tighter live production ergonomics
- better deployment options for SBC and desktop systems

## Future Features

These are not committed yet, but they are strong candidates for future versions:

- playlist duplication and easier playlist reordering
- optional clip tags and smarter media search
- more advanced transport diagnostics
- configurable operator profiles or locked-down UI modes
- richer ATEM debugging tools
- improved multi-display and fullscreen output control
- better production-ready monitoring and fault reporting
- native installer packages for desktop platforms
- a more complete first-run setup wizard

## Contributing

Contributions, testing feedback, and real ATEM validation reports are welcome.

If you are testing DeckPilot with live hardware, protocol traces and setup notes are especially useful.
