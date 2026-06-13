# DeckPilot

**Turn a Raspberry Pi into a video deck your ATEM thinks is a real HyperDeck.**

DeckPilot is an open-source, network-controlled playout deck. Plug its HDMI output into your switcher, point ATEM Software Control or Bitfocus Companion at it, and it behaves like a Blackmagic HyperDeck — while giving the operator a fast, dark, broadcast-style web interface for clips, rundowns, trimming, and one-key playback.

No build step. One SQLite file. Runs comfortably on a Raspberry Pi 3B+.

```bash
curl -fsSL https://raw.githubusercontent.com/JulesMellot/deckpilot/main/scripts/bootstrap.sh | bash
```

That's the whole install. The bootstrap detects your platform, installs `mpv`/`ffmpeg`, sets up the Python environment, and (on a Pi) registers a systemd service plus an HDMI boot screen that displays the deck's IP. Open `http://<your-pi>:8080` and you're on air.

---

## Why this exists

A HyperDeck is a wonderful machine — and an expensive one if all you need is "play this clip when the director says go." DeckPilot speaks enough of the HyperDeck protocol that an ATEM or Companion controls it like the real thing, and it layers on the parts a solo operator actually misses in the heat of a live show: fire pads, a NEXT countdown, hold-on-last-frame, safe mode, and a panic button.

It is **alpha / early beta**: already used for real-world validation, still in the hardening phase. Protocol traces and ATEM test reports are gold — see [Contributing](#contributing).

## What it feels like to operate

**One keystroke to air.** Keys `1`–`9` fire the first nine clips instantly (`Shift` cues instead). `Space` toggles play/pause, `Esc` stops, `Enter` cuts to black. The same pads exist on screen, lit red when on air, green when cued.

**A rundown that thinks ahead.** Each playlist item carries its own end behavior — AUTO-advance, STOP, HOLD on the last frame, or LOOP — and the NEXT bar shows what's coming with a live countdown to the change point. Reorder items while the show is running; the engine re-reads the rundown at every boundary. The output never flashes black between decisions.

**Trim without an editor.** Set in/out marks from the live transport or while scrubbing the browser preview. Playback starts at the in mark, stops (or advances) at the out mark, and the big remaining timer counts down to *your* out point, turning amber then red as the end approaches.

**Hard to take down by accident.** Safe mode arms live actions for a short window before they fire. A branded standby slate (deck name + network targets) holds the output when idle instead of a black screen. If the player process dies mid-show, DeckPilot relaunches it and re-seeks to where it was.

**A library that fills itself.** Drag-and-drop upload, or just copy files into the clips folder over SMB/USB — the watch folder ingests anything whose copy has finished, then thumbnails, probes, and computes audio levels in the background while playback keeps priority. Videos and stills (PNG/JPG/WebP/GIF with per-still duration), folders, tags, search. **ADD LINK** drops a network stream straight into the library — paste an `http`/`https`/`HLS`/`RTSP`/`RTMP` URL and mpv plays it like any clip; DeckPilot probes it in the background for duration and a thumbnail (a live or slow source just becomes an open-ended clip).

**Clips from the SD card and USB drives, together.** Full-resolution clips fill an SD card fast, so DeckPilot reads from the internal card *and* any USB drive at the same time — drop video files on a drive's top level and they appear in the library, tagged with their source. On a Pi appliance the installer wires up **USB auto-mount** (a udev rule + systemd unit that mounts any plugged-in drive under `/media/deckpilot/<label>`, including NTFS/exFAT), so even on headless Raspberry Pi OS Lite — which has no desktop automounter — a drive plugged in **after boot** just appears (or hit **Settings → Media Storage → Rescan**, which also lists every drive and its free space). Unplug it and its clips stay in the library marked **OFFLINE** — names, in/out marks, folders and playlist references are preserved (they all live in the SQLite file on the SD card) and come back online when the drive returns. Firing an offline clip is blocked rather than silently failing. The **STORAGE** tile on the health panel shows free / total of the internal disk.

**Send sound wherever you need it.** Video and audio outputs are independent: keep the picture on HDMI to the switcher while the sound leaves through the analog jack or a USB interface. **Settings → Audio Output** probes the Pi's sound cards and collapses ALSA's raw PCM list — hardware variants, dmix, software plugins, the lot — down to plain choices: **Auto / HDMI / Jack / USB** (numbered when there are two of a kind). The change applies live and is saved to `config.json`, so it survives an mpv relaunch and a reboot. Because the Pi's headphone jack is quiet by design, DeckPilot also lifts the card's ALSA mixer to full level at startup so the on-screen volume slider works from a real signal.

**Numbers an operator trusts.** Live timecode with mark-aware countdown, a real VU meter driven by precomputed loudness envelopes (zero CPU cost during playback), CPU temperature / load / RAM on the health panel, and the HyperDeck protocol log streaming in green-on-black like it should.

## What the ATEM sees: the HyperDeck protocol

DeckPilot implements the **[Blackmagic HyperDeck Ethernet Protocol](https://documents.blackmagicdesign.com/DeveloperManuals/HyperDeckEthernetProtocol.pdf)** (text over TCP `9993`, announced as protocol `1.11`) and has been audited line-by-line against the official specification — response codes, parameter names, and message formats included.

**The wire format, exactly as a real deck speaks it:**

- on connect: `500 connection info:` with protocol version and model
- success: `200 ok`; informational replies in the `2xx` range (`204 device info:`, `205 clips info:`, `208 transport info:`, `209 notify:`, `210 remote info:`, `211 configuration:`)
- failures use the official `1xx` codes: `100 syntax error`, `102 invalid value`, `107 timeline empty`, `111 remote control disabled`, `112 clip not found`, `150 invalid state`
- asynchronous notifications in the `5xx` range (`508 transport info:`, `502 slot info:`, `510 remote info:`), **disabled by default per the spec** — controllers opt in with `notify:`

**Implemented commands** — the set ATEM and Companion actually use:

| Group | Commands |
|---|---|
| Identity | `device info` (slot count, software version), `configuration`, `ping`, `help`, `quit` |
| Clips | `clips get` (spec format: `id: name start duration`), `clips add` by id or name, `clips clear` — remote rundown building |
| Transport | `play` (`speed: 10–200`, `loop`, `single clip`), `stop`, `transport info` (incl. `single clip` and `loop` flags) |
| Cueing | `goto: clip id: N`, **relative `goto: clip id: +1/-1`**, `goto: clip: start/end`, `goto: timecode:` (absolute and `+/-` relative), `playrange set/clear` |
| Sessions | `notify` (query + set, per-connection flags), `remote` / `remote info`, `preview` |
| Slots | `slot info`, `slot select` (one virtual slot) |

**Honest deviations from a real deck:** DeckPilot is playout-only — `record`, disk formatting, and multi-slot commands are not implemented (a controller asking gets a clean `100`/`102` failure, never a hang). Clip start timecodes are reported as `00:00:00:00` since files have no embedded timecode track. Reverse and >2× speeds return `102 invalid value` (the Pi's decoder can't honor them, and lying to the switcher would desync its UI).

The deck's network target is displayed in the web UI so ATEM setup is copy-paste, and the protocol log streams live in the operator interface — protocol traces from real ATEM hardware are the most valuable contribution you can make right now.

## How it works

Three cooperating pieces in one process:

```
ATEM / Companion ──TCP 9993──┐
                             ├──> DeckController ──IPC──> mpv ──> HDMI / display
Browser UI ──REST + WS 8080──┘         │
                                       └──> SQLite (clips, playlists, folders, marks)
```

State flows one way: the UI and the HyperDeck protocol both call into a single playback controller, which updates shared state and pushes incremental updates to every browser over WebSocket. `ffmpeg`/`ffprobe` handle thumbnails, metadata, and loudness in the background.

**Built lean on purpose** — the reference target is a Raspberry Pi 3B+:

- steady state never touches SQLite (write-invalidated in-memory caches) and never forks processes
- broadcasts only happen when state actually changed; one JSON encode serves every browser
- SQLite runs in WAL mode and HTTP access logs are off — SD cards live longer
- mpv's demuxer cache is bounded for 1 GB boards; imports use single-frame thumbnail extraction and capped workers so playout always keeps headroom
- frontend is vanilla HTML/CSS/JS with DOM reuse and virtualization — no framework, no build

**Stack:** Python 3.9+ · FastAPI + Uvicorn · asyncio TCP · SQLite · mpv (JSON IPC) · ffmpeg.

## Install

### Linux / macOS

```bash
curl -fsSL https://raw.githubusercontent.com/JulesMellot/deckpilot/main/scripts/bootstrap.sh | bash
```

### Windows (experimental)

```powershell
irm https://raw.githubusercontent.com/JulesMellot/deckpilot/main/scripts/bootstrap.ps1 | iex
```

The mpv IPC layer uses named pipes on Windows; runtime validation on real hardware is still pending.

### Manual

```bash
git clone https://github.com/JulesMellot/deckpilot.git && cd deckpilot
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python3 -m app.main
```

Web UI at [http://127.0.0.1:8080](http://127.0.0.1:8080). Configuration lives in `config.json` (see `config.json.example`). Useful environment overrides:

| Variable | Purpose |
|---|---|
| `PIDECK_HTTP_PORT` / `PIDECK_HYPERDECK_PORT` | Change the web / protocol ports |
| `PIDECK_CONFIG` | Point to a custom `config.json` |
| `PIDECK_WATCH_FOLDER_SECONDS` | Watch-folder scan interval (`0` disables) |
| `PIDECK_DEFAULT_IMAGE_DURATION_SECONDS` | Default playout duration for stills |
| `PIDECK_MEDIA_ENRICHMENT_WORKERS` | Background import workers (default 2) |
| `PIDECK_AUDIO_DEVICE` | Force the audio output device (`auto`, or an mpv device name); usually set from Settings → Audio Output |

### Hook it to an ATEM

1. Connect DeckPilot's HDMI output to an ATEM input.
2. In ATEM Software Control → HyperDeck tab, add the target shown in DeckPilot's web UI.
3. Enable Auto Roll if you want the switcher to roll clips on cut.

A protocol test bench ships in `scripts/hyperdeck_test_client.py` — it works against DeckPilot **and real HyperDecks**, so you can compare behaviors side by side:

```bash
python3 scripts/hyperdeck_test_client.py <deck-ip> --check          # spec-conformance suite (read-only)
python3 scripts/hyperdeck_test_client.py <deck-ip> --check --allow-transport  # + cue/play/stop checks
python3 scripts/hyperdeck_test_client.py <deck-ip> --monitor        # stream async notifications live
python3 scripts/hyperdeck_test_client.py <deck-ip>                  # interactive REPL with operator aliases
```

## Control surface

- **REST** — `/api/state`, `/api/clips*` (goto, play, marks, rename, loop, folder, tags, duration, levels), `/api/transport/*` (stop, pause, resume, seek, speed), `/api/playlists*` (incl. per-item end behavior and reorder), `/api/system/*` (outputs, video format, audio devices, black, safe mode, update, export, import, backup), `/api/audio/*` (volume, mute), `/api/upload`
- **WebSocket** — `/ws` streams transport, media, playlists, audio, health, safety, and logs as incremental events
- **Backup** — one-click JSON export/import of the whole library state (names, folders, marks, tags, playlists) and a consistent SQLite snapshot download

## Roadmap

**Near term** — real-world ATEM validation, broader protocol coverage, operator UX polish, import diagnostics, first-run docs.

**Mid term** — multi-display control, Windows runtime validation, structured logging/fault reporting, protocol test coverage, packaged releases.

**Exploring** — SRT contribution output via the Pi's hardware H.264 encoder (full-bandwidth NDI was evaluated and ruled out on the 3B+ — 100 Mbps NIC — but remains a candidate Pi 5 module via GStreamer `ndisink`), richer dashboards, operator profiles/authentication, recording from a capture input.

## Contributing

Contributions, testing feedback, and especially **real ATEM validation reports** are welcome. If you test DeckPilot with live hardware, protocol traces and setup notes are the most useful thing you can send. Run the test suite with:

```bash
python3 -m unittest discover -s tests
```
