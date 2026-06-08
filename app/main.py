from __future__ import annotations

import contextlib

import uvicorn

from app.core.config import AppConfig, load_config
from app.core.state import AppState
from app.hyperdeck.server import HyperDeckServer
from app.media.clip_store import ClipStore
from app.media.playlist_store import PlaylistStore
from app.player.mpv_controller import MPVController
from app.services.deck_controller import DeckController
from app.services.network_info import NetworkInfoService
from app.services.output_manager import OutputManager
from app.web.app import build_app


def create_application() -> tuple[AppConfig, object]:
    config = load_config()
    state = AppState(config)
    clip_store = ClipStore(config)
    playlist_store = PlaylistStore(config.db_path, clip_store)
    player = MPVController(config)
    output_manager = OutputManager()
    network_info = NetworkInfoService(config.http_port, config.hyperdeck_port)
    controller = DeckController(config, state, clip_store, playlist_store, output_manager, network_info, player)
    server = HyperDeckServer(config, state, controller)
    app = build_app(controller, state, clip_store, playlist_store)

    @app.on_event('startup')
    async def _startup() -> None:
        await clip_store.initialize()
        await playlist_store.initialize()
        await output_manager.initialize()
        selected_output = await output_manager.get_selected_output()
        if selected_output:
            await player.set_output(selected_output.id)
        with contextlib.suppress(FileNotFoundError):
            await player.start()
        await controller.start()
        await controller.refresh_clips()
        await server.start()

    @app.on_event('shutdown')
    async def _shutdown() -> None:
        await server.stop()
        await controller.stop()
        await player.stop_process()

    return config, app


def main() -> None:
    config, app = create_application()
    uvicorn.run(app, host=config.http_host, port=config.http_port)


if __name__ == '__main__':
    main()
