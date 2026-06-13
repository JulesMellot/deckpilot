from __future__ import annotations

import asyncio
import json
import signal
import sqlite3
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
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


class SeekRequest(BaseModel):
    seconds: float


class SpeedRequest(BaseModel):
    percent: float


class TagsRequest(BaseModel):
    tags: str


class DurationRequest(BaseModel):
    seconds: float


class EndBehaviorRequest(BaseModel):
    end_behavior: str


class PlaylistReorderRequest(BaseModel):
    positions: list[int]


class PadAssignRequest(BaseModel):
    clip_id: int | None = None


class ConfigUpdateRequest(BaseModel):
    updates: dict[str, Any]


# Settings exposed in the web UI; everything else stays file-only.
EDITABLE_CONFIG_KEYS = (
    'app_name',
    'http_port',
    'hyperdeck_port',
    'default_video_format',
    'default_framerate',
    'ws_tick_seconds',
    'watch_folder_seconds',
    'default_image_duration_seconds',
    'media_enrichment_workers',
    'mpv_binary',
    'ffmpeg_binary',
    'ffprobe_binary',
    'allowed_upload_extensions',
)


def _write_config_updates(config_path: Path, updates: dict[str, Any]) -> None:
    existing: dict[str, Any] = {}
    if config_path.exists():
        try:
            existing = json.loads(config_path.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError):
            existing = {}
    existing.update(updates)
    config_path.write_text(json.dumps(existing, indent=2) + '\n', encoding='utf-8')


class MarksRequest(BaseModel):
    mark_in_seconds: float | None = None
    mark_out_seconds: float | None = None


class OutputSelectionRequest(BaseModel):
    output_id: str


class OutputCanvasRequest(BaseModel):
    mode: str


class AudioDeviceRequest(BaseModel):
    device: str


class RemoteClipRequest(BaseModel):
    url: str
    name: str | None = None


class BulkDeleteRequest(BaseModel):
    filenames: list[str]


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

    @app.middleware('http')
    async def immutable_asset_cache(request, call_next):
        response = await call_next(request)
        path = request.url.path
        # Static assets are mtime-versioned and thumbnails are content-
        # fingerprinted, so browsers can cache them forever.
        if path.startswith('/thumbs/') or (path.startswith('/static/') and 'v' in request.query_params):
            response.headers['Cache-Control'] = 'public, max-age=31536000, immutable'
        return response

    def _asset_version(name: str) -> int:
        try:
            return int((static_dir / name).stat().st_mtime)
        except OSError:
            return 0

    @app.get('/')
    async def index() -> HTMLResponse:
        # Stamp static asset links with their file mtime so browsers always
        # pull fresh CSS/JS after an update instead of serving stale cache.
        html = (static_dir / 'index.html').read_text(encoding='utf-8')
        for asset in ('styles.css', 'app.js'):
            html = html.replace(f'/static/{asset}', f'/static/{asset}?v={_asset_version(asset)}')
        return HTMLResponse(html, headers={'Cache-Control': 'no-cache'})

    @app.get('/media/{filename}')
    async def get_media(filename: str) -> FileResponse:
        # Resolve by known clip rather than serving a directory: a clip may live
        # on the SD card or a USB drive, and only registered files are exposed.
        safe_name = Path(filename).name
        filepath = await clip_store.path_for_filename(safe_name)
        if not filepath or not Path(filepath).is_file():
            raise HTTPException(status_code=404, detail='Media not found')
        return FileResponse(filepath)

    @app.get('/thumbs/{thumb_name}')
    async def get_thumbnail(thumb_name: str) -> FileResponse:
        safe_name = Path(thumb_name).name
        thumb_path = Path(controller.config.thumbnails_dir) / safe_name
        if not thumb_path.exists() or not thumb_path.is_file():
            raise HTTPException(status_code=404, detail='Thumbnail not found')
        return FileResponse(
            thumb_path,
            headers={
                'Cache-Control': 'public, max-age=31536000, immutable',
            },
        )

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

    @app.patch('/api/playlists/{playlist_id}/items/{position}')
    async def set_playlist_item_behavior(playlist_id: int, position: int, payload: EndBehaviorRequest) -> dict[str, Any]:
        ok_flag = await playlist_store.set_item_end_behavior(playlist_id, position, payload.end_behavior)
        if not ok_flag:
            raise HTTPException(status_code=400, detail='Invalid item or end behavior')
        await controller.refresh_clips()
        return {'ok': True}

    @app.post('/api/playlists/{playlist_id}/items/reorder')
    async def reorder_playlist_items(playlist_id: int, payload: PlaylistReorderRequest) -> dict[str, Any]:
        ok_flag = await playlist_store.reorder_items(playlist_id, payload.positions)
        if not ok_flag:
            raise HTTPException(status_code=400, detail='Invalid position list')
        await controller.refresh_clips()
        return {'ok': True}

    @app.post('/api/playlists/loop')
    async def set_playlist_loop(payload: LoopRequest) -> dict[str, Any]:
        await controller.set_playlist_loop(payload.enabled)
        return {'ok': True}

    @app.get('/api/system/outputs')
    async def get_outputs() -> dict[str, Any]:
        return {'outputs': await controller.list_outputs()}

    @app.get('/api/system/audio-devices')
    async def get_audio_devices() -> dict[str, Any]:
        return {'devices': await controller.list_audio_devices()}

    @app.get('/api/system/storage-devices')
    async def get_storage_devices() -> dict[str, Any]:
        return await controller.list_storage_devices()

    @app.post('/api/system/storage-rescan')
    async def rescan_storage() -> dict[str, Any]:
        return {'ok': True, **await controller.rescan_media()}

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

    @app.post('/api/pads/{pad}')
    async def assign_pad(pad: int, payload: PadAssignRequest) -> dict[str, Any]:
        if pad < 1 or pad > 9:
            raise HTTPException(status_code=400, detail='Pad must be between 1 and 9')
        ok_flag = await controller.set_pad(pad, payload.clip_id)
        if not ok_flag:
            raise HTTPException(status_code=404, detail='Clip not found')
        return {'ok': True, 'pads': await controller.pads_snapshot()}

    @app.get('/api/system/config')
    async def get_config() -> dict[str, Any]:
        values = {key: getattr(controller.config, key) for key in EDITABLE_CONFIG_KEYS}
        return {
            'config': values,
            'config_path': controller.config.config_path,
            'restart_required': True,
        }

    @app.post('/api/system/config')
    async def save_config(payload: ConfigUpdateRequest) -> dict[str, Any]:
        updates: dict[str, Any] = {}
        for key, value in payload.updates.items():
            if key not in EDITABLE_CONFIG_KEYS:
                raise HTTPException(status_code=400, detail=f'Unknown setting: {key}')
            current = getattr(controller.config, key)
            try:
                if isinstance(current, bool):
                    coerced: Any = bool(value)
                elif isinstance(current, int):
                    coerced = int(value)
                elif isinstance(current, float):
                    coerced = float(value)
                elif isinstance(current, list):
                    if isinstance(value, str):
                        coerced = [item.strip() for item in value.split(',') if item.strip()]
                    else:
                        coerced = [str(item).strip() for item in value if str(item).strip()]
                else:
                    coerced = str(value).strip()
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail=f'Invalid value for {key}')
            updates[key] = coerced

        config_path = Path(controller.config.config_path or 'config.json')
        await asyncio.to_thread(_write_config_updates, config_path, updates)
        await state.add_log('info', 'system', f'Configuration updated ({", ".join(updates)}). Restart required.')
        return {'ok': True, 'updated': list(updates), 'restart_required': True}

    @app.post('/api/system/restart')
    async def restart_application() -> dict[str, Any]:
        async def shutdown_soon() -> None:
            await asyncio.sleep(0.6)
            signal.raise_signal(signal.SIGTERM)

        await state.add_log('info', 'system', 'Restart requested from the web UI.')
        asyncio.create_task(shutdown_soon())
        return {'ok': True}

    @app.get('/api/system/export')
    async def export_library() -> JSONResponse:
        payload = await controller.export_snapshot()
        return JSONResponse(
            payload,
            headers={'Content-Disposition': 'attachment; filename="deckpilot-export.json"'},
        )

    @app.post('/api/system/import')
    async def import_library(payload: dict[str, Any]) -> dict[str, Any]:
        try:
            applied = await controller.import_snapshot(payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        return {'ok': True, **applied}

    @app.get('/api/system/backup')
    async def backup_database() -> FileResponse:
        backup_path = Path(controller.config.data_dir) / 'deckpilot-backup.db'

        def make_backup() -> None:
            source = sqlite3.connect(controller.config.db_path)
            try:
                target = sqlite3.connect(backup_path)
                try:
                    source.backup(target)
                finally:
                    target.close()
            finally:
                source.close()

        await asyncio.to_thread(make_backup)
        return FileResponse(backup_path, filename='deckpilot-backup.db', media_type='application/octet-stream')

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
        try:
            for item in files:
                suffix = Path(item.filename or '').suffix.lower()
                if suffix not in controller.config.allowed_upload_extensions:
                    allowed = ', '.join(controller.config.allowed_upload_extensions)
                    raise HTTPException(
                        status_code=400,
                        detail=f'Unsupported file type: {suffix or "(none)"} — allowed: {allowed}',
                    )
            await clip_store.save_upload_streams(files)
            await controller.refresh_clips()
            return {
                'uploaded': len(files),
                'processing': 'background',
                'media_processing': await clip_store.processing_status(),
            }
        finally:
            for item in files:
                await item.close()

    @app.post('/api/clips/url')
    async def add_clip_url(payload: RemoteClipRequest) -> dict[str, Any]:
        try:
            key = await controller.add_remote_clip(payload.url, payload.name)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        await state.add_log('info', 'media', f'Added network link: {payload.url}')
        return {'ok': True, 'clip': key}

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

    @app.post('/api/transport/seek')
    async def seek_clip(payload: SeekRequest) -> dict[str, Any]:
        ok_flag = await controller.seek_current_clip(payload.seconds)
        if not ok_flag:
            detail = controller.player.last_error or controller._last_error or 'Seek unavailable'
            raise HTTPException(status_code=503, detail=detail)
        return {'ok': True}

    @app.post('/api/transport/speed')
    async def set_speed(payload: SpeedRequest) -> dict[str, Any]:
        ok_flag = await controller.set_playback_speed(payload.percent)
        if not ok_flag:
            detail = controller.player.last_error or controller._last_error or 'Speed unavailable'
            raise HTTPException(status_code=503, detail=detail)
        return {'ok': True}

    @app.patch('/api/clips/{deck_id}/marks')
    async def set_clip_marks(deck_id: int, payload: MarksRequest) -> dict[str, Any]:
        ok_flag = await controller.set_clip_marks(deck_id, payload.mark_in_seconds, payload.mark_out_seconds)
        if not ok_flag:
            raise HTTPException(status_code=400, detail=controller._last_error or 'Unable to set marks')
        return {'ok': True}

    @app.patch('/api/clips/{deck_id}/tags')
    async def set_clip_tags(deck_id: int, payload: TagsRequest) -> dict[str, Any]:
        ok_flag = await controller.set_tags(deck_id, payload.tags)
        if not ok_flag:
            raise HTTPException(status_code=404, detail='Clip not found')
        return {'ok': True}

    @app.patch('/api/clips/{deck_id}/duration')
    async def set_clip_duration(deck_id: int, payload: DurationRequest) -> dict[str, Any]:
        ok_flag = await controller.set_still_duration(deck_id, payload.seconds)
        if not ok_flag:
            raise HTTPException(status_code=400, detail=controller._last_error or 'Unable to set duration')
        return {'ok': True}

    @app.get('/api/clips/{deck_id}/levels')
    async def get_clip_levels(deck_id: int) -> dict[str, Any]:
        return {'levels': await clip_store.get_audio_levels(deck_id)}

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

    @app.post('/api/clips/delete')
    async def delete_clips(payload: BulkDeleteRequest) -> dict[str, Any]:
        deleted = await controller.delete_clips(payload.filenames)
        return {'ok': True, 'deleted': deleted}

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

    @app.post('/api/system/audio-device')
    async def set_audio_device(payload: AudioDeviceRequest) -> dict[str, Any]:
        await controller.select_audio_device(payload.device)
        config_path = Path(controller.config.config_path or 'config.json')
        await asyncio.to_thread(_write_config_updates, config_path, {'audio_device': controller.config.audio_device})
        await state.add_log('info', 'system', f'Audio output set to {controller.config.audio_device}.')
        return {'ok': True, 'devices': await controller.list_audio_devices()}

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
                # Every connected browser receives the same event object; the
                # first sender encodes it once and the others reuse the text.
                text = event.get('_encoded')
                if text is None:
                    text = json.dumps(
                        {'type': event['type'], 'payload': event['payload']},
                        separators=(',', ':'),
                        default=str,
                    )
                    event['_encoded'] = text
                await websocket.send_text(text)
        except WebSocketDisconnect:
            pass
        finally:
            await state.unsubscribe(queue)

    return app
