from __future__ import annotations

import asyncio
from dataclasses import dataclass

from app.core.config import AppConfig
from app.core.state import AppState
from app.hyperdeck.protocol import (
    FAIL_CLIP_NOT_FOUND,
    FAIL_INVALID_STATE,
    FAIL_INVALID_VALUE,
    FAIL_REMOTE_DISABLED,
    FAIL_SYNTAX_ERROR,
    FAIL_TIMELINE_EMPTY,
    boolish,
    failure,
    ok,
    parse_command,
    response,
    timecode_to_seconds,
)
from app.services.deck_controller import DeckController

SOFTWARE_VERSION = '1.0'


@dataclass
class HyperDeckSession:
    key: str
    writer: asyncio.StreamWriter
    host: str
    port: int
    # Per the protocol spec, asynchronous notifications are disabled until the
    # controller enables them with the `notify` command.
    notify_transport: bool = False
    notify_slot: bool = False
    notify_clips: bool = False
    notify_remote: bool = False
    remote_enabled: bool = True
    # Seconds of silence after which the deck drops the socket (0 = disabled).
    # Companion arms this on connect, then pings to keep it fed.
    watchdog_period: int = 0


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
                try:
                    raw = await asyncio.wait_for(
                        reader.readline(),
                        timeout=session.watchdog_period or None,
                    )
                except asyncio.TimeoutError:
                    await self.state.add_log('info', 'hyperdeck', f'{key} watchdog timeout')
                    break
                if not raw:
                    break
                line = raw.decode('utf-8', errors='ignore').strip('\r\n')
                if not line:
                    continue
                # Multi-line command block: a header ending in ':' is followed
                # by "key: value" lines until a blank line. Companion uses this
                # form, so fold it back into the inline "cmd: k: v" shape.
                if line.endswith(':'):
                    parts = [line]
                    while True:
                        try:
                            more = await asyncio.wait_for(
                                reader.readline(),
                                timeout=session.watchdog_period or None,
                            )
                        except asyncio.TimeoutError:
                            more = b''
                        if not more:
                            break
                        chunk = more.decode('utf-8', errors='ignore').strip('\r\n')
                        if not chunk:
                            break
                        parts.append(chunk)
                    if len(parts) > 1:
                        line = parts[0] + ' ' + ' '.join(parts[1:])
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

    async def _effective_clip_id(self) -> int:
        """First clip id, or 0 when the timeline is empty."""
        clips = await self.controller.list_clips()
        return clips[0].deck_id if clips else 0

    def _greeting(self) -> bytes:
        return response(
            500,
            'connection info:',
            f'protocol version: {self.config.protocol_version}',
            f'model: {self.config.protocol_model}',
        )

    async def _dispatch(self, session: HyperDeckSession, line: str) -> bytes | None:
        command, params = parse_command(line)
        controlled_commands = {'play', 'stop', 'goto', 'playrange set', 'playrange clear', 'clips add', 'clips clear'}
        if command in controlled_commands and (not self.state.remote_enabled or not session.remote_enabled):
            return failure(FAIL_REMOTE_DISABLED)
        if command == 'device info':
            return response(
                204,
                'device info:',
                f'protocol version: {self.config.protocol_version}',
                f'model: {self.config.protocol_model}',
                f'unique id: {self.config.app_name}',
                'slot count: 1',
                f'software version: {SOFTWARE_VERSION}',
            )
        if command == 'clips add':
            clip_id = int(params.get('clip id', '0') or 0)
            name = params.get('name')
            if not clip_id and not name:
                return failure(FAIL_SYNTAX_ERROR)
            success = await self.controller.protocol_clips_add(clip_id=clip_id or None, name=name)
            return ok() if success else failure(FAIL_CLIP_NOT_FOUND)
        if command == 'clips clear':
            success = await self.controller.protocol_clips_clear()
            return ok() if success else failure(FAIL_TIMELINE_EMPTY)
        if command == 'clips count':
            clips = await self.controller.list_clips()
            return response(214, 'clips count:', f'clip count: {len(clips)}')
        if command == 'clips get':
            clips = await self.controller.list_clips()
            lines = [f'clip count: {len(clips)}']
            for clip in clips:
                # Spec line format: {id}: {name} {start timecode} {duration}.
                lines.append(f'{clip.deck_id}: {clip.name} 00:00:00:00 {clip.duration_timecode}')
            return response(205, 'clips info:', *lines)
        if command == 'transport info':
            t = self.state.transport
            # A real HyperDeck with a loaded timeline always reports a current
            # clip (>= 1). When nothing is cued yet, advertise the first clip so
            # the ATEM treats the deck as ready and will auto-roll it.
            clip_id = t.clip_id or await self._effective_clip_id()
            return response(
                208,
                'transport info:',
                f'status: {t.status}',
                f'speed: {t.speed}',
                f'slot id: {t.slot_id}',
                f'clip id: {clip_id}',
                f'single clip: {str(t.single_clip).lower()}',
                f'display timecode: {t.display_timecode}',
                f'timecode: {t.timecode}',
                f'video format: {t.video_format}',
                f'loop: {str(t.loop).lower()}',
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
            return ok() if slot_id == 1 else failure(FAIL_INVALID_VALUE)
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
            speed: float | None = None
            if 'speed' in params:
                try:
                    speed = float(params['speed'])
                except ValueError:
                    return failure(FAIL_INVALID_VALUE)
                if speed == 0:
                    await self.controller.pause()
                    return ok()
                if speed < 0:
                    return failure(FAIL_INVALID_VALUE)
            target_clip_id = self.state.playrange_clip_id or self.state.transport.clip_id or await self._effective_clip_id() or None
            success = await self.controller.play(clip_id=target_clip_id, loop=loop, single_clip=single_clip, speed=speed)
            return ok() if success else failure(FAIL_INVALID_STATE)
        if command == 'stop':
            await self.controller.stop_playback()
            return ok()
        if command == 'goto':
            clip_target = (params.get('clip') or '').strip().lower()
            if clip_target == 'start':
                success = await self.controller.goto_clip(self.state.transport.clip_id)
                return ok() if success else failure(FAIL_CLIP_NOT_FOUND)
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
                return ok() if success else failure(FAIL_CLIP_NOT_FOUND)
            if 'timecode' in params:
                clip = await self.controller.clip_store.get_clip(self.state.transport.clip_id)
                if not clip:
                    return failure(FAIL_CLIP_NOT_FOUND)
                offset = timecode_to_seconds(params['timecode'], clip.framerate)
                if offset is None:
                    return failure(FAIL_INVALID_VALUE)
                raw = params['timecode'].strip()
                target = offset
                if raw.startswith(('+', '-')):
                    target = float(self.state.transport.elapsed_seconds or 0.0) + offset
                success = await self.controller.seek_current_clip(target)
                return ok() if success else failure(FAIL_INVALID_STATE)
            raw_clip_id = (params.get('clip id') or '').strip()
            if not raw_clip_id:
                return failure(FAIL_SYNTAX_ERROR)
            try:
                value = int(raw_clip_id)
            except ValueError:
                return failure(FAIL_INVALID_VALUE)
            # `goto: clip id: +1` / `-1` are relative moves from the current clip.
            if raw_clip_id.startswith(('+', '-')):
                clip_id = (self.state.transport.clip_id or 0) + value
            else:
                clip_id = value
            if not await self.controller.clip_store.get_clip(clip_id):
                return failure(FAIL_CLIP_NOT_FOUND)
            success = await self.controller.goto_clip(clip_id)
            return ok() if success else failure(FAIL_INVALID_STATE)
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
            if not params:
                # A bare `notify` query returns the current subscription flags.
                return response(
                    209,
                    'notify:',
                    f'transport: {str(session.notify_transport).lower()}',
                    f'slot: {str(session.notify_slot).lower()}',
                    f'remote: {str(session.notify_remote).lower()}',
                    'configuration: false',
                    f'clips: {str(session.notify_clips).lower()}',
                )
            session.notify_transport = boolish(params.get('transport'), session.notify_transport)
            session.notify_slot = boolish(params.get('slot'), session.notify_slot)
            session.notify_clips = boolish(params.get('clips'), session.notify_clips)
            session.notify_remote = boolish(params.get('remote'), session.notify_remote)
            return ok()
        if command == 'remote':
            # `remote` (bare, or with enable/override) always answers with the
            # 210 remote info block — never 200 ok, or Companion errors out.
            if 'enable' in params:
                enabled = boolish(params.get('enable'), self.state.remote_enabled)
                session.remote_enabled = enabled
                await self.controller.set_remote_enabled(enabled)
            return response(
                210,
                'remote info:',
                f'enabled: {str(self.state.remote_enabled).lower()}',
                'override: false',
            )
        if command == 'remote info':
            return response(
                210,
                'remote info:',
                f'enabled: {str(self.state.remote_enabled).lower()}',
                'override: false',
            )
        if command == 'watchdog':
            try:
                session.watchdog_period = max(int(params.get('period', '0') or 0), 0)
            except ValueError:
                return failure(FAIL_INVALID_VALUE)
            return ok()
        if command == 'ping':
            return ok()
        if command == 'help':
            return response(
                211,
                'help:',
                'device info',
                'clips get',
                'clips add: clip id: <n>',
                'clips add: name: <clip name>',
                'clips clear',
                'transport info',
                'slot info',
                'slot select: slot id: 1',
                'configuration',
                'play',
                'play: speed: <10-200> loop: <true|false> single clip: <true|false>',
                'stop',
                'goto: clip id: <n>',
                'goto: clip id: +/-<n>',
                'goto: clip: <start|end>',
                'goto: timecode: <hh:mm:ss:ff>',
                'goto: timecode: +/-<hh:mm:ss:ff>',
                'playrange set: clip id: <n>',
                'playrange clear',
                'preview: enable: <true|false>',
                'preview info',
                'notify',
                'notify: transport: <true|false> slot: <true|false> remote: <true|false> clips: <true|false>',
                'remote: enable: <true|false>',
                'remote info',
                'watchdog: period: <seconds>',
                'ping',
                'quit',
            )
        if command == 'quit':
            session.writer.write(ok())
            await session.writer.drain()
            session.writer.close()
            return None
        return failure(FAIL_SYNTAX_ERROR)

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
                    f"single clip: {str(payload['single_clip']).lower()}",
                    f"display timecode: {payload['display_timecode']}",
                    f"timecode: {payload['timecode']}",
                    f"video format: {payload['video_format']}",
                    f"loop: {str(payload['loop']).lower()}",
                )
                targets = [s for s in self.sessions.values() if s.notify_transport]
            elif event_type == 'clips':
                clips = payload['clips']
                lines = [f"clip count: {len(clips)}"]
                for clip in clips:
                    lines.append(f"{clip['deck_id']}: {clip['name']} 00:00:00:00 {clip['duration_timecode']}")
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
                packet = response(
                    510,
                    'remote info:',
                    f"enabled: {str(payload['enabled']).lower()}",
                    'override: false',
                )
                targets = [s for s in self.sessions.values() if s.notify_remote]
            else:
                continue
            for session in list(targets):
                try:
                    session.writer.write(packet)
                    await session.writer.drain()
                except ConnectionError:
                    self.sessions.pop(session.key, None)
