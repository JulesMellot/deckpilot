from __future__ import annotations

import asyncio
from dataclasses import dataclass

from app.core.config import AppConfig
from app.core.state import AppState
from app.hyperdeck.protocol import boolish, error, ok, parse_command, response
from app.services.deck_controller import DeckController


@dataclass
class HyperDeckSession:
    key: str
    writer: asyncio.StreamWriter
    host: str
    port: int
    notify_transport: bool = True
    notify_slot: bool = True
    notify_clips: bool = True
    remote_enabled: bool = True


class HyperDeckServer:
    def __init__(self, config: AppConfig, state: AppState, controller: DeckController) -> None:
        self.config = config
        self.state = state
        self.controller = controller
        self.server: asyncio.AbstractServer | None = None
        self.sessions: dict[str, HyperDeckSession] = {}
        self._broadcast_task: asyncio.Task | None = None
        self._queue: asyncio.Queue | None = None

    async def start(self) -> None:
        self._queue = await self.state.subscribe()
        self._broadcast_task = asyncio.create_task(self._broadcast_events())
        self.server = await asyncio.start_server(
            self._handle_client,
            host=self.config.hyperdeck_host,
            port=self.config.hyperdeck_port,
        )
        await self.state.add_log('info', 'hyperdeck', f'Listening on {self.config.hyperdeck_host}:{self.config.hyperdeck_port}')

    async def stop(self) -> None:
        if self.server:
            self.server.close()
            await self.server.wait_closed()
        if self._broadcast_task:
            self._broadcast_task.cancel()
        if self._queue:
            await self.state.unsubscribe(self._queue)

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        peer = writer.get_extra_info('peername') or ('unknown', 0)
        host, port = peer[0], peer[1]
        key = f'{host}:{port}'
        session = HyperDeckSession(key=key, writer=writer, host=host, port=port)
        self.sessions[key] = session
        await self.state.add_controller(key, host, port)
        await self.state.add_log('info', 'hyperdeck', f'Client connected: {key}')
        writer.write(self._greeting())
        await writer.drain()
        try:
            while not reader.at_eof():
                raw = await reader.readline()
                if not raw:
                    break
                line = raw.decode('utf-8', errors='ignore').strip('\r\n')
                if not line:
                    continue
                await self.state.add_log('info', 'hyperdeck', f'{key} -> {line}')
                reply = await self._dispatch(session, line)
                if reply is not None:
                    writer.write(reply)
                    await writer.drain()
        finally:
            self.sessions.pop(key, None)
            writer.close()
            await writer.wait_closed()
            await self.state.remove_controller(key)
            await self.state.add_log('info', 'hyperdeck', f'Client disconnected: {key}')

    def _greeting(self) -> bytes:
        return response(
            500,
            'connection info:',
            f'protocol version: {self.config.protocol_version}',
            f'model: {self.config.protocol_model}',
        )

    async def _dispatch(self, session: HyperDeckSession, line: str) -> bytes | None:
        command, params = parse_command(line)
        controlled_commands = {'play', 'stop', 'goto', 'playrange set', 'playrange clear'}
        if command in controlled_commands and (not self.state.remote_enabled or not session.remote_enabled):
            return error('remote disabled')
        if command == 'device info':
            clips = await self.controller.list_clips()
            return response(
                204,
                'device info:',
                f'model: {self.config.protocol_model}',
                f'protocol version: {self.config.protocol_version}',
                f'unique id: {self.config.app_name}',
                'video inputs: 1',
                'audio inputs: 1',
                f'clip count: {len(clips)}',
            )
        if command == 'clips get':
            clips = await self.controller.list_clips()
            lines = [f'clip count: {len(clips)}']
            for clip in clips:
                lines.append(f'{clip.deck_id}: {clip.name} {clip.duration_timecode} {clip.framerate:.2f}')
            return response(205, 'clips info:', *lines)
        if command == 'transport info':
            t = self.state.transport
            return response(
                208,
                'transport info:',
                f'status: {t.status}',
                f'speed: {t.speed}',
                f'slot id: {t.slot_id}',
                f'clip id: {t.clip_id}',
                f'display timecode: {t.display_timecode}',
                f'timecode: {t.timecode}',
                f'video format: {t.video_format}',
            )
        if command == 'slot info':
            slot = await self.controller.slot_snapshot()
            return response(
                202,
                'slot info:',
                f"slot id: {slot['slot_id']}",
                f"status: {slot['status']}",
                f"volume name: {slot['volume_name']}",
                f"clip count: {slot['clip_count']}",
                f"video format: {slot['video_format']}",
            )
        if command == 'slot select':
            slot_id = int(params.get('slot id', '1') or 1)
            return ok() if slot_id == 1 else error('unknown slot id')
        if command == 'configuration':
            return response(
                211,
                'configuration:',
                'audio input: embedded',
                'video input: SDI',
                f'preview: {str(self.state.preview_enabled).lower()}',
                f'remote: {str(self.state.remote_enabled).lower()}',
            )
        if command == 'play':
            loop = boolish(params.get('loop'), self.state.transport.loop)
            single_clip = boolish(params.get('single clip'), self.state.transport.single_clip)
            target_clip_id = self.state.playrange_clip_id or self.state.transport.clip_id or None
            success = await self.controller.play(clip_id=target_clip_id, loop=loop, single_clip=single_clip)
            return ok() if success else error(self.controller.player.last_error or 'playback unavailable')
        if command == 'stop':
            await self.controller.stop_playback()
            return ok()
        if command == 'goto':
            clip_target = (params.get('clip') or '').strip().lower()
            if clip_target == 'start':
                success = await self.controller.goto_clip(self.state.transport.clip_id)
                return ok() if success else error('unknown clip id')
            if clip_target == 'end':
                success = await self.controller.goto_clip(self.state.transport.clip_id)
                if success:
                    clip = await self.controller.clip_store.get_clip(self.state.transport.clip_id)
                    if clip:
                        await self.state.set_transport(
                            elapsed_seconds=clip.duration_seconds,
                            remaining_seconds=0.0,
                            total_seconds=clip.duration_seconds,
                            timecode=clip.duration_timecode,
                            display_timecode=clip.duration_timecode,
                        )
                return ok() if success else error('unknown clip id')
            clip_id = int(params.get('clip id', '0') or 0)
            success = await self.controller.goto_clip(clip_id)
            return ok() if success else error('unknown clip id')
        if command == 'playrange set':
            clip_id = int(params.get('clip id', '0') or 0)
            self.state.playrange_clip_id = clip_id
            if clip_id > 0:
                await self.controller.goto_clip(clip_id)
            return ok()
        if command == 'playrange clear':
            self.state.playrange_clip_id = None
            return ok()
        if command == 'preview':
            enabled = boolish(params.get('enable'), self.state.preview_enabled)
            await self.controller.set_preview_enabled(enabled)
            return ok()
        if command == 'preview info':
            return response(212, 'preview:', f'enabled: {str(self.state.preview_enabled).lower()}')
        if command == 'notify':
            session.notify_transport = boolish(params.get('transport'), session.notify_transport)
            session.notify_slot = boolish(params.get('slot'), session.notify_slot)
            session.notify_clips = boolish(params.get('clips'), session.notify_clips)
            return ok()
        if command == 'remote':
            enabled = boolish(params.get('enable'), True)
            session.remote_enabled = enabled
            await self.controller.set_remote_enabled(enabled)
            return ok()
        if command == 'remote info':
            return response(213, 'remote:', f'enabled: {str(self.state.remote_enabled).lower()}')
        if command == 'ping':
            return ok()
        if command == 'help':
            return response(
                211,
                'help:',
                'device info',
                'clips get',
                'transport info',
                'slot info',
                'slot select: slot id: 1',
                'configuration',
                'play',
                'stop',
                'goto: clip id: <n>',
                'goto: clip: <start|end>',
                'playrange set: clip id: <n>',
                'playrange clear',
                'preview: enable: <true|false>',
                'preview info',
                'notify: transport: <true|false> slot: <true|false> clips: <true|false>',
                'remote: enable: <true|false>',
                'remote info',
                'ping',
                'quit',
            )
        if command == 'quit':
            session.writer.write(ok())
            await session.writer.drain()
            session.writer.close()
            return None
        return error('unsupported command')

    async def _broadcast_events(self) -> None:
        assert self._queue is not None
        while True:
            event = await self._queue.get()
            event_type = event['type']
            payload = event['payload']
            if event_type == 'transport':
                packet = response(
                    508,
                    'transport info:',
                    f"status: {payload['status']}",
                    f"speed: {payload['speed']}",
                    f"slot id: {payload['slot_id']}",
                    f"clip id: {payload['clip_id']}",
                    f"display timecode: {payload['display_timecode']}",
                    f"timecode: {payload['timecode']}",
                    f"video format: {payload['video_format']}",
                )
                targets = [s for s in self.sessions.values() if s.notify_transport]
            elif event_type == 'clips':
                clips = payload['clips']
                lines = [f"clip count: {len(clips)}"]
                for clip in clips:
                    lines.append(f"{clip['deck_id']}: {clip['name']} {clip['duration_timecode']} {clip['framerate']:.2f}")
                packet = response(505, 'clips info:', *lines)
                targets = [s for s in self.sessions.values() if s.notify_clips]
            elif event_type == 'slot':
                packet = response(
                    502,
                    'slot info:',
                    f"slot id: {payload['slot_id']}",
                    f"status: {payload['status']}",
                    f"volume name: {payload['volume_name']}",
                    f"clip count: {payload['clip_count']}",
                    f"video format: {payload['video_format']}",
                )
                targets = [s for s in self.sessions.values() if s.notify_slot]
            elif event_type == 'preview':
                packet = response(506, 'preview:', f"enabled: {str(payload['enabled']).lower()}")
                targets = [s for s in self.sessions.values() if s.notify_transport]
            elif event_type == 'remote':
                packet = response(511, 'remote:', f"enabled: {str(payload['enabled']).lower()}")
                targets = list(self.sessions.values())
            else:
                continue
            for session in list(targets):
                try:
                    session.writer.write(packet)
                    await session.writer.drain()
                except ConnectionError:
                    self.sessions.pop(session.key, None)
