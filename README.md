# DeckPilot

DeckPilot est un emulateur open source de Blackmagic HyperDeck pense pour un usage ATEM, Companion et playout local.

Le projet fournit :

- un serveur TCP HyperDeck compatible ATEM/Companion sur le port `9993`
- une interface web de gestion media, playlists et playback
- un moteur de lecture `mpv` avec sortie plein ecran sur l'ecran choisi
- un stockage SQLite pour les clips, playlists et metadonnees
- un workflow leger, sans build step frontend

## Fonctionnalites

- compatibilite HyperDeck de base pour ATEM et Bitfocus Companion
- upload web de clips video
- lecture, stop, pause, cue et cut to black
- playlists persistantes avec lecture et boucle
- dossiers medias avec navigation par dossiers
- preview navigateur par clip
- thumbnails automatiques
- selection de sortie video
- choix du format video
- controle audio, mute et volume
- affichage de la cible reseau HyperDeck a renseigner dans l'ATEM
- detection des videos verticales avec fill flou cote playout
- logs HyperDeck consultables dans l'interface

## Stack

- Python 3.9+
- FastAPI + Uvicorn
- asyncio TCP pour le protocole HyperDeck
- SQLite
- `mpv` via IPC JSON
- `ffmpeg` / `ffprobe`
- HTML / CSS / JavaScript vanilla

## Structure Du Projet

- `app/core/` : configuration, modeles et etat global
- `app/hyperdeck/` : protocole texte HyperDeck et serveur multi-clients
- `app/media/` : clips, playlists, dossiers, ffprobe, thumbnails
- `app/player/` : pilotage `mpv` via socket IPC
- `app/services/` : orchestration playback, reseau, sorties video
- `app/web/` : API FastAPI et WebSocket temps reel
- `app/static/` : interface web vanilla
- `scripts/` : outils de test et installation
- `deploy/` : service `systemd`
- `docs/` : documentation d'installation

## Lancement Local

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python3 -m app.main
```

L'interface web est ensuite disponible sur `http://127.0.0.1:8080`.

## Test Rapide Du Protocole

```bash
python3 scripts/hyperdeck_test_client.py 127.0.0.1 9993
```

## Usage ATEM

- brancher la sortie video de DeckPilot sur une entree HDMI de l'ATEM
- ajouter DeckPilot dans l'onglet HyperDeck d'ATEM Software Control
- renseigner l'adresse affichee dans l'interface web
- activer le workflow HyperDeck / Auto Roll selon le setup voulu

## Statut

Le projet est utilisable, mais reste en phase alpha / early beta.
Il est recommande de le tester avec le materiel reel avant usage live.
