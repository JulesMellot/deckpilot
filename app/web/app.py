from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.core.state import AppState
from app.media.clip_store import ClipStore
from app.media.playlist_store import PlaylistStore
from app.services.deck_controller import DeckController
from app.services.update_manager import UpdateManager


class RenameRequest(BaseModel):
    name: str


class LoopRequest(BaseModel):
    enabled: bool


class ReorderRequest(BaseModel):
    deck_ids: list[int]


class VideoFormatRequest(BaseModel):
    video_format: str


class VolumeRequest(BaseModel):
    volume: int


class MuteRequest(BaseModel):
    muted: bool


class OutputSelectionRequest(BaseModel):
    output_id: str


class OutputCanvasRequest(BaseModel):
    mode: str


class FolderRequest(BaseModel):
    folder: str


class FolderCreateRequest(BaseModel):
    name: str


class PlaylistCreateRequest(BaseModel):
    name: str
    clip_ids: list[int] = []
    activate: bool = False


class PlaylistItemRequest(BaseModel):
    clip_id: int


class PlaylistPlayRequest(BaseModel):
    loop: bool = False


class PlaylistPositionRequest(BaseModel):
    position: int
    loop: bool | None = None


class UpdateTriggerRequest(BaseModel):
    confirm: bool = True


class SafeModeRequest(BaseModel):
    enabled: bool


class ArmControlsRequest(BaseModel):
    seconds: int = 10


def build_app(
    controller: DeckController,
    state: AppState,
    clip_store: ClipStore,
    playlist_store: PlaylistStore,
    update_manager: UpdateManager,
) -> FastAPI:
    app = FastAPI(title='DeckPilot')
    app.add_middleware(
        CORSMiddleware,
        allow_origins=['*'],
        allow_credentials=True,
        allow_methods=['*'],
        allow_headers=['*'],
    )

    static_dir = Path(__file__).resolve().parent.parent / 'static'
    app.mount('/static', StaticFiles(directory=static_dir), name='static')
    app.mount('/thumbs', StaticFiles(directory=controller.config.thumbnails_dir), name='thumbs')
    app.mount('/media', StaticFiles(directory=controller.config.clips_dir), name='media')

    @app.get('/')
    async def index() -> FileResponse:
        return FileResponse(static_dir / 'index.html')

    @app.get('/api/state')
    async def get_state() -> dict[str, Any]:
        return await controller.snapshot()

    @app.get('/api/clips')
    async def get_clips() -> dict[str, Any]:
        clips = await clip_store.list_clips()
        return {'clips': [clip.to_dict() for clip in clips]}

    @app.get('/api/media/folders')
    async def get_folders() -> dict[str, Any]:
        return {'folders': await clip_store.list_folders()}

    @app.post('/api/media/folders')
    async def create_folder(payload: FolderCreateRequest) -> dict[str, Any]:
        name = await clip_store.create_folder(payload.name)
        return {'ok': True, 'name': name, 'folders': await clip_store.list_folders()}

    @app.get('/api/playlists')
    async def get_playlists() -> dict[str, Any]:
        return {
            'playlists': await playlist_store.list_playlists(),
            'active': await playlist_store.get_active_playlist(),
        }

    @app.post('/api/playlists')
    async def create_playlist(payload: PlaylistCreateRequest) -> dict[str, Any]:
        created = await playlist_store.create_playlist(payload.name, payload.clip_ids, payload.activate)
        return {'playlist': created, 'playlists': await playlist_store.list_playlists(), 'active': await playlist_store.get_active_playlist()}

    @app.post('/api/playlists/{playlist_id}/activate')
    async def activate_playlist(playlist_id: int) -> dict[str, Any]:
        await playlist_store.activate_playlist(playlist_id)
        return {'ok': True, 'playlists': await playlist_store.list_playlists(), 'active': await playlist_store.get_active_playlist()}

    @app.post('/api/playlists/{playlist_id}/items')
    async def add_playlist_item(playlist_id: int, payload: PlaylistItemRequest) -> dict[str, Any]:
        await playlist_store.add_clip_to_playlist(playlist_id, payload.clip_id)
        return {'ok': True, 'active': await playlist_store.get_active_playlist()}

    @app.delete('/api/playlists/{playlist_id}/items/{position}')
    async def remove_playlist_item(playlist_id: int, position: int) -> dict[str, Any]:
        await playlist_store.remove_item_from_playlist(playlist_id, position)
        return {'ok': True, 'active': await playlist_store.get_active_playlist()}

    @app.post('/api/playlists/play')
    async def play_active_playlist(payload: PlaylistPlayRequest) -> dict[str, Any]:
        ok_flag = await controller.play_playlist(loop=payload.loop)
        return {'ok': ok_flag}

    @app.post('/api/playlists/{playlist_id}/play-from')
    async def play_playlist_from_position(playlist_id: int, payload: PlaylistPositionRequest) -> dict[str, Any]:
        active = await playlist_store.get_active_playlist()
        if active.get('playlist', {}).get('id') != playlist_id:
            await playlist_store.activate_playlist(playlist_id)
        ok_flag = await controller.play_playlist_from_position(payload.position, loop=payload.loop)
        return {'ok': ok_flag}

    @app.post('/api/playlists/{playlist_id}/next')
    async def play_next_playlist_item(playlist_id: int) -> dict[str, Any]:
        active = await playlist_store.get_active_playlist()
        if active.get('playlist', {}).get('id') != playlist_id:
            await playlist_store.activate_playlist(playlist_id)
        ok_flag = await controller.play_next_playlist_item()
        return {'ok': ok_flag}

    @app.delete('/api/playlists/{playlist_id}/items')
    async def clear_playlist(playlist_id: int) -> dict[str, Any]:
        await playlist_store.clear_playlist(playlist_id)
        return {'ok': True, 'active': await playlist_store.get_active_playlist()}

    @app.post('/api/playlists/loop')
    async def set_playlist_loop(payload: LoopRequest) -> dict[str, Any]:
        await controller.set_playlist_loop(payload.enabled)
        return {'ok': True}

    @app.get('/api/system/outputs')
    async def get_outputs() -> dict[str, Any]:
        return {'outputs': await controller.list_outputs()}

    @app.get('/api/system/update')
    async def get_update_status() -> dict[str, Any]:
        return await update_manager.get_status()

    @app.post('/api/system/update')
    async def run_update(payload: UpdateTriggerRequest) -> dict[str, Any]:
        if not payload.confirm:
            raise HTTPException(status_code=400, detail='Update confirmation is required')
        try:
            return await update_manager.trigger_update()
        except RuntimeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post('/api/system/safe-mode')
    async def set_safe_mode(payload: SafeModeRequest) -> dict[str, Any]:
        await state.set_safe_mode(payload.enabled)
        return {'ok': True, 'safety': state.safety_snapshot()}

    @app.post('/api/system/arm-controls')
    async def arm_controls(payload: ArmControlsRequest) -> dict[str, Any]:
        await state.arm_live_controls(payload.seconds)
        return {'ok': True, 'safety': state.safety_snapshot()}

    @app.post('/api/upload')
    async def upload(files: list[UploadFile] = File(...)) -> dict[str, Any]:
        uploads: list[tuple[str, bytes]] = []
        for item in files:
            suffix = Path(item.filename or '').suffix.lower()
            if suffix not in controller.config.allowed_upload_extensions:
                raise HTTPException(status_code=400, detail=f'Unsupported file type: {suffix}')
            uploads.append((item.filename or 'clip.bin', await item.read()))
        await clip_store.save_uploads(uploads)
        await controller.refresh_clips()
        return {'uploaded': len(uploads)}

    @app.post('/api/clips/{deck_id}/goto')
    async def goto_clip(deck_id: int) -> dict[str, Any]:
        ok_flag = await controller.goto_clip(deck_id)
        if not ok_flag:
            clip = await clip_store.get_clip(deck_id)
            if not clip:
                raise HTTPException(status_code=404, detail='Clip not found')
            detail = controller.player.last_error or controller._last_error or 'Cue unavailable'
            raise HTTPException(status_code=503, detail=detail)
        return {'ok': True}

    @app.post('/api/clips/{deck_id}/play')
    async def play_clip(deck_id: int) -> dict[str, Any]:
        ok_flag = await controller.play_single_clip(deck_id)
        if not ok_flag:
            clip = await clip_store.get_clip(deck_id)
            if not clip:
                raise HTTPException(status_code=404, detail='Clip not found')
            detail = controller.player.last_error or controller._last_error or 'Playback unavailable'
            raise HTTPException(status_code=503, detail=detail)
        return {'ok': True}

    @app.post('/api/transport/stop')
    async def stop_clip() -> dict[str, Any]:
        await controller.stop_playback()
        return {'ok': True}

    @app.post('/api/transport/pause')
    async def pause_clip() -> dict[str, Any]:
        await controller.pause()
        return {'ok': True}

    @app.post('/api/transport/resume')
    async def resume_clip() -> dict[str, Any]:
        await controller.resume()
        return {'ok': True}

    @app.patch('/api/clips/{deck_id}/rename')
    async def rename_clip(deck_id: int, payload: RenameRequest) -> dict[str, Any]:
        await controller.rename_clip(deck_id, payload.name)
        return {'ok': True}

    @app.patch('/api/clips/{deck_id}/loop')
    async def set_loop(deck_id: int, payload: LoopRequest) -> dict[str, Any]:
        await controller.set_loop(deck_id, payload.enabled)
        return {'ok': True}

    @app.patch('/api/clips/{deck_id}/folder')
    async def set_folder(deck_id: int, payload: FolderRequest) -> dict[str, Any]:
        await clip_store.set_folder(deck_id, payload.folder)
        await controller.refresh_clips()
        return {'ok': True}

    @app.delete('/api/clips/{deck_id}')
    async def delete_clip(deck_id: int) -> dict[str, Any]:
        await controller.delete_clip(deck_id)
        return {'ok': True}

    @app.post('/api/clips/reorder')
    async def reorder(payload: ReorderRequest) -> dict[str, Any]:
        await controller.reorder(payload.deck_ids)
        return {'ok': True}

    @app.post('/api/system/output')
    async def set_output(payload: OutputSelectionRequest) -> dict[str, Any]:
        await controller.select_output(payload.output_id)
        return {'ok': True}

    @app.post('/api/system/output-canvas')
    async def set_output_canvas(payload: OutputCanvasRequest) -> dict[str, Any]:
        await controller.set_output_canvas_mode(payload.mode)
        return {'ok': True, 'display': await controller.display_snapshot()}

    @app.post('/api/system/black')
    async def cut_black() -> dict[str, Any]:
        ok_flag = await controller.cut_to_black()
        if not ok_flag:
            detail = controller.player.last_error or controller._last_error or 'Black screen unavailable'
            raise HTTPException(status_code=503, detail=detail)
        return {'ok': True}

    @app.post('/api/system/video-format')
    async def set_video_format(payload: VideoFormatRequest) -> dict[str, Any]:
        await controller.set_video_format(payload.video_format)
        return {'ok': True}

    @app.post('/api/audio/volume')
    async def set_volume(payload: VolumeRequest) -> dict[str, Any]:
        await controller.set_volume(payload.volume)
        return {'ok': True}

    @app.post('/api/audio/mute')
    async def set_mute(payload: MuteRequest) -> dict[str, Any]:
        await controller.set_mute(payload.muted)
        return {'ok': True}

    @app.websocket('/ws')
    async def websocket_endpoint(websocket: WebSocket) -> None:
        await websocket.accept()
        queue = await state.subscribe()
        try:
            await websocket.send_json({'type': 'snapshot', 'payload': await controller.snapshot()})
            while True:
                event = await queue.get()
                await websocket.send_json(event)
        except WebSocketDisconnect:
            pass
        finally:
            await state.unsubscribe(queue)

    return app
