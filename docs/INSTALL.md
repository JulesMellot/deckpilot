# Raspberry Pi Installation

## Quick Bootstrap

For a guided install that detects the platform, installs missing dependencies, prepares Python, writes the local config, and can enable a service automatically:

```bash
curl -fsSL https://raw.githubusercontent.com/JulesMellot/deckpilot/main/scripts/bootstrap.sh | bash
```

Run the installer from your normal user account. Do not switch to a root shell with `sudo su` first.

If the repository is already cloned locally:

```bash
./scripts/bootstrap.sh
```

## Project Name

- Project name: DeckPilot
- Alternative names: HyperPi Deck, PiDeck Studio, OpenHyperPi

## Recommended OS

- Raspberry Pi OS Lite 32-bit Bookworm is the recommended default for a Pi 3B. It keeps the memory footprint lower, is more comfortable on 1 GB of RAM, and does not lose anything essential for this project.
- Raspberry Pi OS Lite 64-bit is still valid on Pi 3B+ and Pi 4 if you expect heavier video workloads, but it is not the best default trade-off for a Pi 3B.

## System Dependencies

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip ffmpeg mpv sqlite3 netcat-openbsd
```

## Project Installation

```bash
git clone <your-repo> /home/pi/pideck
cd /home/pi/pideck
chmod +x scripts/install.sh
./scripts/install.sh
```

The `scripts/install.sh` script is now a Raspberry Pi wrapper that runs the shared bootstrap installer with `/home/pi/pideck` as the target directory and enables a `systemd` service.

On supported Linux SBC installs, the bootstrap also installs an HDMI boot info service that keeps the local screen updated with the current IP address, Web UI URL, and HyperDeck endpoint after boot.

## HDMI Configuration

Depending on the OS image, the file is usually either `/boot/config.txt` or `/boot/firmware/config.txt`.

Minimal example to force HDMI output:

```ini
hdmi_force_hotplug=1
hdmi_group=1
hdmi_mode=33
config_hdmi_boost=7
```

Useful values for 1080p:

- 1080p24 -> `hdmi_group=1`, `hdmi_mode=32`
- 1080p25 -> `hdmi_group=1`, `hdmi_mode=33`
- 1080p30 -> `hdmi_group=1`, `hdmi_mode=34`
- 1080p50 -> `hdmi_group=1`, `hdmi_mode=31`
- 1080p60 -> `hdmi_group=1`, `hdmi_mode=16`

ATEM does not scale HDMI sources like a traditional production scaler. The Raspberry Pi output format must match the ATEM project video standard.

## Service systemd

```bash
sudo systemctl status deckpilot.service
sudo journalctl -u deckpilot.service -f
```

HDMI boot info service:

```bash
sudo systemctl status deckpilot-boot-info.service
sudo journalctl -u deckpilot-boot-info.service -f
```

## Web Access

- Find the IP address: `hostname -I`
- Web interface: `http://PI_IP:8080`
- HyperDeck TCP endpoint: `PI_IP:9993`

## ATEM Connection

- Connect the Raspberry Pi HDMI output to an HDMI input on the ATEM.
- Put the Raspberry Pi and the ATEM on the same Ethernet network.
- In ATEM Software Control, open the HyperDeck section.
- Add a HyperDeck using the Raspberry Pi IP address and port `9993`.
- Enable `Auto Roll` if you want clips to start automatically during macros or transitions.

## Companion And Tests

- Bitfocus Companion can connect to port `9993` as if it were a standard HyperDeck.
- Manual netcat test:

```bash
nc PI_IP 9993
```

Then send:

```text
device info
clips get
goto: clip id: 1
play
stop
```

- Python test client:

```bash
python3 scripts/hyperdeck_test_client.py PI_IP 9993
```

## Boot HDMI Info Screen

DeckPilot now installs a secondary `systemd` service on supported Linux SBC targets that continuously renders the following information on the local HDMI console:

- hostname
- primary IP address
- Web UI URL
- HyperDeck TCP endpoint

This makes first boot and reboot recovery easier because the operator can immediately see where to connect from another device on the network.

## Pi 3B Performance

- Prefer H.264 High/Main in `yuv420p`.
- Avoid very high bitrates and very short GOP structures.
- Practical target: 1080p25 or 1080p30, AAC audio, `.mp4` files.
- For 1080p50 or 1080p60, be conservative with bitrate and test on final hardware.
- Avoid heavy intermediate codecs such as ProRes on a Pi 3B.

## Troubleshooting

- No HDMI output: verify `hdmi_force_hotplug=1`, check the correct `hdmi_mode`, then reboot.
- ATEM cannot see the deck: verify that port `9993` is listening with `ss -ltnp | grep 9993`.
- Web UI does not open: check `sudo systemctl status deckpilot.service`.
- No video playback: test `mpv --fs /path/to/clip.mp4` directly on the Raspberry Pi.
- Wrong format on ATEM: make sure the Raspberry Pi HDMI mode strictly matches the ATEM project video standard.
