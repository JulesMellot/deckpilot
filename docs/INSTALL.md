# Installation Raspberry Pi

## Nom propose

- Nom du projet: DeckPilot
- Alternatives: HyperPi Deck, PiDeck Studio, OpenHyperPi

## OS recommande

- Raspberry Pi OS Lite 32 bits Bookworm pour un Pi 3B: empreinte memoire plus faible, meilleur confort sur 1 Go de RAM, aucun gain reel indispensable en 64 bits pour ce projet.
- Raspberry Pi OS Lite 64 bits reste valable sur Pi 3B+ et Pi 4 si tu prevois des traitements video plus lourds, mais ce n'est pas le meilleur compromis par defaut pour un 3B.

## Dependances systeme

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip ffmpeg mpv sqlite3 netcat-openbsd
```

## Installation du projet

```bash
git clone <ton-repo> /home/pi/pideck
cd /home/pi/pideck
chmod +x scripts/install.sh
./scripts/install.sh
```

## Configuration HDMI

Suivant l'OS, le fichier peut etre `/boot/config.txt` ou `/boot/firmware/config.txt`.

Exemple minimal pour forcer la sortie HDMI:

```ini
hdmi_force_hotplug=1
hdmi_group=1
hdmi_mode=33
config_hdmi_boost=7
```

Table utile pour 1080p:

- 1080p24 -> `hdmi_group=1`, `hdmi_mode=32`
- 1080p25 -> `hdmi_group=1`, `hdmi_mode=33`
- 1080p30 -> `hdmi_group=1`, `hdmi_mode=34`
- 1080p50 -> `hdmi_group=1`, `hdmi_mode=31`
- 1080p60 -> `hdmi_group=1`, `hdmi_mode=16`

L'ATEM ne scale pas les sources HDMI comme un scaler de production classique: le format du Pi doit matcher celui du projet ATEM.

## Service systemd

```bash
sudo systemctl status pideck-open.service
sudo journalctl -u pideck-open.service -f
```

## Acces web

- Trouver l'IP: `hostname -I`
- Interface: `http://IP_DU_PI:8080`
- HyperDeck TCP: `IP_DU_PI:9993`

## Connexion ATEM

- Brancher la sortie HDMI du Pi sur une entree HDMI de l'ATEM.
- Mettre le Pi et l'ATEM sur le meme reseau Ethernet.
- Dans ATEM Software Control, ouvrir la section HyperDeck.
- Ajouter un HyperDeck en indiquant l'IP du Pi et le port `9993`.
- Activer `Auto Roll` si tu veux que les medias partent automatiquement lors des macros/transitions.

## Companion et tests

- Bitfocus Companion peut se connecter au port `9993` comme a un HyperDeck.
- Test manuel netcat:

```bash
nc IP_DU_PI 9993
```

Puis envoyer:

```text
device info
clips get
goto: clip id: 1
play
stop
```

- Test client Python:

```bash
python3 scripts/hyperdeck_test_client.py IP_DU_PI 9993
```

## Splash screen boot

Option simple et robuste:

- Ajouter un service systemd annexe qui lance un petit script Python en framebuffer ou en X pour afficher `hostname -I` au boot.
- Variante plus simple: activer `agetty --autologin` sur la console locale et afficher automatiquement l'IP dans `/etc/profile`.

## Performance Pi 3B

- Preferer H.264 High/Main en `yuv420p`.
- Eviter les debits trop eleves et les GOP trop courts.
- Cible pratique: 1080p25/30, audio AAC, fichiers `.mp4`.
- Pour 1080p50/60, rester prudent sur le bitrate et tester sur le materiel final.
- Eviter les codecs intermediaires lourds type ProRes sur Pi 3B.

## Depannage

- Pas de sortie HDMI: verifier `hdmi_force_hotplug=1`, le bon `hdmi_mode`, puis redemarrer.
- L'ATEM ne voit pas le deck: verifier que le port `9993` ecoute avec `ss -ltnp | grep 9993`.
- L'interface web ne s'ouvre pas: verifier `sudo systemctl status pideck-open.service`.
- Pas de lecture video: tester `mpv --fs /chemin/vers/clip.mp4` directement sur le Pi.
- Mauvais format sur l'ATEM: aligner strictement le mode HDMI du Pi avec le standard video du projet ATEM.
