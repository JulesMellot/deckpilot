from __future__ import annotations

import contextlib
import os

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
from app.services.standby_slate import StandbySlateService
from app.services.update_manager import UpdateManager
from app.services.watch_folder import WatchFolderService
from app.web.app import build_app


def create_application() -> tuple[AppConfig, object]:
    config = load_config()
    state = AppState(config)
    clip_store = ClipStore(config)
    playlist_store = PlaylistStore(config.db_path, clip_store)
    player = MPVController(config)
    output_manager = OutputManager()
    network_info = NetworkInfoService(config.http_port, config.hyperdeck_port)
    update_manager = UpdateManager(config, state)
    standby_slate = StandbySlateService(config, network_info)
    controller = DeckController(config, state, clip_store, playlist_store, output_manager, network_info, player, standby_slate)
    server = HyperDeckServer(config, state, controller)
    watch_folder = WatchFolderService(config, state, controller)
    app = build_app(controller, state, clip_store, playlist_store, update_manager)

    @app.on_event('startup')
    async def _startup() -> None:
        await clip_store.initialize()
        await clip_store.start_background_tasks(controller.schedule_media_refresh_publish)
        await playlist_store.initialize()
        await output_manager.initialize()
        selected_output = await output_manager.get_selected_output()
        if selected_output:
            await player.set_output_geometry(selected_output.width, selected_output.height)
            await player.set_output(selected_output.id)
        preload_player = bool(os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY'))
        if preload_player:
            with contextlib.suppress(FileNotFoundError):
                await player.start()
        await controller.start()
        await controller.refresh_clips()
        await server.start()
        await watch_folder.start()

    @app.on_event('shutdown')
    async def _shutdown() -> None:
        await watch_folder.stop()
        await server.stop()
        await clip_store.stop_background_tasks()
        await controller.stop()
        await player.stop_process()

    return config, app


def main() -> None:
    config, app = create_application()
    # No per-request access log: thumbnail/media traffic would otherwise spam
    # journald and burn SD-card writes on the Pi.
    uvicorn.run(
        app,
        host=config.http_host,
        port=config.http_port,
        access_log=False,
        log_level='warning',
    )


if __name__ == '__main__':
    main()
