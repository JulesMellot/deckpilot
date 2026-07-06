// Transport panel: play/stop/seek/speed, in-out marks, fire pads, VU meter,
// next-clip bar, and the live clip metadata line.

import { api, formatClock, formatRemainingClock } from './util.js';
import { DOM } from './dom.js';
import { padEntries, state } from './store.js';
import { bindAsync, ensureLiveActionAllowed } from './dialogs.js';
import { clipResolutionLabel, filteredClips, syncMediaGridVisualState } from './media.js';
import { playPlaylist } from './playlist.js';

export async function cueClip(clipId) {
  if (!clipId) return;
  await api(`/api/clips/${clipId}/goto`, { method: 'POST' });
}

export async function togglePlayPause() {
  if (!state.snapshot) return;
  if (state.snapshot.transport.status === 'play' && !state.snapshot.transport.paused) {
    await api('/api/transport/pause', { method: 'POST' });
  } else if (state.snapshot.transport.paused) {
    await api('/api/transport/resume', { method: 'POST' });
  } else if (state.snapshot.transport.playlist_mode) {
    await playPlaylist();
  } else {
    const clipId = state.snapshot.transport.clip_id || state.selectedClipId || state.snapshot.playlist?.items?.[0]?.clip_id;
    if (!clipId) return;
    await api(`/api/clips/${clipId}/play`, { method: 'POST' });
  }
}

export async function playAdjacentClip(direction) {
  const clips = filteredClips();
  if (!clips.length) return;
  const currentId = state.snapshot.transport.clip_id || clips[0].deck_id;
  const currentIndex = clips.findIndex((clip) => clip.deck_id === currentId);
  if (currentIndex === -1) return;
  let targetIndex = currentIndex + direction;
  if (targetIndex < 0) targetIndex = clips.length - 1;
  if (targetIndex >= clips.length) targetIndex = 0;
  await api(`/api/clips/${clips[targetIndex].deck_id}/play`, { method: 'POST' });
}

export function firePadClip(padNumber, cueOnly) {
  const entry = padEntries().find((pad) => pad.pad === padNumber);
  if (!entry || !entry.clip_id) return Promise.resolve();
  state.selectedClipId = entry.clip_id;
  syncMediaGridVisualState();
  if (cueOnly) {
    return cueClip(entry.clip_id);
  }
  return api(`/api/clips/${entry.clip_id}/play`, { method: 'POST' });
}

export function canSeekCurrentTransport(transport, clip) {
  return Boolean(transport?.clip_id && clip && clip.media_kind === 'video' && Number(transport.total_seconds) > 0);
}

export function displayedTransportElapsed(transport) {
  if (state.transportSeekDragging && state.transportSeekValue !== null) {
    const max = Math.max(0, Number(transport?.total_seconds || 0));
    return Math.min(max, Math.max(0, Number(state.transportSeekValue || 0)));
  }
  return Math.max(0, Number(transport?.elapsed_seconds || 0));
}

export async function commitTransportSeek(seconds) {
  if (!state.snapshot?.transport) return;
  const transport = state.snapshot.transport;
  const clip = state.clipIndex.get(transport.clip_id) || null;
  if (!canSeekCurrentTransport(transport, clip)) return;
  const clamped = Math.min(Math.max(0, Number(seconds || 0)), Number(transport.total_seconds || 0));
  state.transportSeekDragging = false;
  state.transportSeekValue = clamped;
  try {
    await api('/api/transport/seek', {
      method: 'POST',
      body: JSON.stringify({ seconds: clamped }),
    });
  } catch (error) {
    state.transportSeekValue = null;
    throw error;
  } finally {
    state.transportSeekDragging = false;
  }
}

export function effectiveOutSeconds(transport) {
  const total = Math.max(0, Number(transport?.total_seconds || 0));
  const markOut = Number(transport?.mark_out_seconds || 0);
  return markOut > 0 ? Math.min(markOut, total) : total;
}

export async function commitClipMarks({ markIn = null, markOut = null } = {}) {
  if (!state.snapshot?.transport) return;
  const transport = state.snapshot.transport;
  const clip = state.clipIndex.get(transport.clip_id) || null;
  if (!canSeekCurrentTransport(transport, clip)) return;
  const body = {};
  if (markIn !== null) body.mark_in_seconds = Math.max(0, Number(markIn || 0));
  if (markOut !== null) body.mark_out_seconds = Math.max(0, Number(markOut || 0));
  await api(`/api/clips/${transport.clip_id}/marks`, {
    method: 'PATCH',
    body: JSON.stringify(body),
  });
}

export function transportAffectsCollections(previousTransport, nextTransport) {
  if (!previousTransport) return true;
  return previousTransport.clip_id !== nextTransport.clip_id
    || previousTransport.status !== nextTransport.status
    || previousTransport.paused !== nextTransport.paused
    || previousTransport.playlist_mode !== nextTransport.playlist_mode
    || previousTransport.playlist_loop !== nextTransport.playlist_loop;
}

export function renderTransport(transport, clips) {
  if (!transport) return;
  DOM.liveFormat.textContent = transport.video_format;
  if (!state.transportSeekDragging) {
    state.transportSeekValue = null;
  }

  const isPlaying = transport.status === 'play';
  const currentClip = state.clipIndex.get(transport.clip_id) || (clips || []).find((clip) => clip.deck_id === transport.clip_id);
  const canSeek = canSeekCurrentTransport(transport, currentClip);
  const total = Math.max(0, Number(transport.total_seconds || 0));
  const elapsed = displayedTransportElapsed(transport);
  const markIn = Math.max(0, Number(transport.mark_in_seconds || 0));
  const outPoint = effectiveOutSeconds(transport);
  const remaining = Math.max(0, outPoint - elapsed);
  const trimmedDuration = Math.max(0, outPoint - markIn);

  DOM.tallyBar.textContent = isPlaying ? 'ON AIR' : 'OFF AIR';
  DOM.tallyBar.className = `tally-indicator ${isPlaying ? 'live' : ''}`;
  DOM.iconPlay.style.display = isPlaying ? 'none' : 'block';
  DOM.iconPause.style.display = isPlaying ? 'block' : 'none';
  DOM.btnPlay.className = `hw-btn play-btn ${isPlaying ? 'active' : ''}`;

  DOM.liveTimecode.textContent = formatRemainingClock(remaining);
  DOM.liveRemaining.textContent = formatClock(remaining);
  DOM.liveDuration.textContent = formatClock(transport.trim_active ? trimmedDuration : total);
  DOM.liveScrubCurrent.textContent = formatClock(elapsed);
  DOM.liveScrubTotal.textContent = formatClock(total);
  DOM.liveClipName.textContent = currentClip ? currentClip.name : 'NO CLIP LOADED';
  const progress = total > 0 ? (elapsed / total) * 100 : 0;
  DOM.liveProgress.style.width = `${progress}%`;
  DOM.transportSeek.max = String(total);
  DOM.transportSeek.value = String(elapsed);
  DOM.transportSeek.disabled = !canSeek;
  DOM.btnSeekBack.disabled = !canSeek;
  DOM.btnSeekForward.disabled = !canSeek;
  renderTransportSpeed(transport, canSeek);
  renderTransportMarks(transport, canSeek, total);
  renderNextClip(transport);
  renderVuMeter(transport, currentClip);
  renderPads(transport);
  renderLiveClipMeta(transport, currentClip);
  DOM.liveTimecode.classList.remove('warning', 'danger', 'blink');
  if (isPlaying && transport.total_seconds > 0) {
    if (remaining <= 5) {
      DOM.liveTimecode.classList.add('danger', 'blink');
    } else if (remaining <= 10) {
      DOM.liveTimecode.classList.add('warning', 'blink');
    }
  }

  if (document.activeElement !== DOM.configFormat) DOM.configFormat.value = transport.video_format;
  DOM.btnPlayPlaylist.classList.toggle('active', Boolean(transport.playlist_mode && transport.status === 'play'));
  DOM.btnLoopPlaylist.classList.toggle('active', Boolean(transport.playlist_loop));
  DOM.btnLoopPlaylist.textContent = transport.playlist_loop ? 'LOOP ON' : 'LOOP';
}

export function renderLiveClipMeta(transport, clip) {
  if (!clip) {
    DOM.liveClipMeta.textContent = 'STANDBY';
    return;
  }
  const playlistTotal = (state.snapshot?.playlist?.items || []).length;
  const parts = [
    `PAD ${clip.deck_id}`,
    clipResolutionLabel(clip),
    clip.media_kind === 'video' ? `${clip.framerate}fps` : 'STILL',
    clip.codec && clip.codec !== 'unknown' ? clip.codec.toUpperCase() : null,
    Number(transport.playback_speed_percent || 100) !== 100 ? `SPEED ${transport.playback_speed_percent}%` : null,
    transport.loop ? 'LOOP' : null,
    transport.playlist_mode && transport.playlist_position ? `ITEM ${transport.playlist_position}/${playlistTotal}` : null,
    clip.tags ? `#${clip.tags}` : null,
  ].filter(Boolean);
  DOM.liveClipMeta.textContent = parts.join(' · ');
}

export function renderNextClip(transport) {
  const items = state.snapshot?.playlist?.items || [];
  const isRunning = Boolean(transport.playlist_mode) && transport.status === 'play';
  if (!isRunning || !items.length) {
    DOM.nextClipBar.hidden = true;
    return;
  }
  const current = items.find((item) => item.clip_id === transport.clip_id) || null;
  const behavior = current?.end_behavior || 'next';
  const position = current?.position || Number(transport.playlist_position || 0);
  let nextItem = items.find((item) => item.position === position + 1) || null;
  if (!nextItem && transport.playlist_loop) nextItem = items[0] || null;
  const remaining = Math.max(0, effectiveOutSeconds(transport) - displayedTransportElapsed(transport));
  // Countdown musique : cumul des vidéos restantes jusqu'au premier item ♪.
  const countdown = Math.max(0, Number(transport.countdown_seconds != null ? transport.countdown_seconds : remaining));
  DOM.nextClipBar.hidden = false;
  if (transport.loop || behavior === 'stop' || behavior === 'hold') {
    DOM.nextClipBar.classList.add('is-terminal');
    DOM.nextClipName.textContent = transport.loop
      ? 'LOOPING CURRENT CLIP'
      : (behavior === 'hold' ? 'HOLD ON LAST FRAME' : 'STOP AT END');
    DOM.nextClipCountdown.textContent = transport.loop ? '∞' : formatRemainingClock(countdown);
    return;
  }
  if (nextItem) {
    DOM.nextClipBar.classList.remove('is-terminal');
    DOM.nextClipName.textContent = nextItem.is_music ? `♪ ${nextItem.clip_name}` : nextItem.clip_name;
  } else {
    DOM.nextClipBar.classList.add('is-terminal');
    DOM.nextClipName.textContent = 'END OF PLAYLIST';
  }
  DOM.nextClipCountdown.textContent = current?.is_music ? '♪' : formatRemainingClock(countdown);
}

export function ensureAudioLevels(clipId, clip) {
  if (!clipId || !clip?.has_audio_levels) return null;
  if (state.audioLevels.has(clipId)) return state.audioLevels.get(clipId);
  if (!state.audioLevelsFetching.has(clipId)) {
    state.audioLevelsFetching.add(clipId);
    api(`/api/clips/${clipId}/levels`)
      .then((payload) => {
        if (state.audioLevels.size > 8) {
          state.audioLevels.delete(state.audioLevels.keys().next().value);
        }
        state.audioLevels.set(clipId, payload.levels || []);
      })
      .catch(() => {})
      .finally(() => state.audioLevelsFetching.delete(clipId));
  }
  return null;
}

export function renderVuMeter(transport, currentClip) {
  const playing = transport.status === 'play' && !transport.paused;
  DOM.vuMeter.classList.toggle('muted', Boolean(state.snapshot?.audio?.muted));
  let pct = 0;
  let effectiveDb = null;
  if (playing && currentClip) {
    const levels = ensureAudioLevels(transport.clip_id, currentClip);
    if (levels && levels.length) {
      const index = Math.min(levels.length - 1, Math.max(0, Math.floor(Number(transport.elapsed_seconds || 0))));
      const db = Number(levels[index]);
      const volume = Number(state.snapshot?.audio?.volume ?? 100);
      const gainDb = volume > 0 ? 20 * Math.log10(volume / 100) : -60;
      effectiveDb = Math.max(-60, Math.min(0, db + gainDb));
      pct = ((effectiveDb + 60) / 60) * 100;
    }
  }
  DOM.vuMeterFill.style.clipPath = `inset(0 ${100 - pct}% 0 0)`;

  const now = Date.now();
  if (pct >= state.vuPeakPct || now - state.vuPeakAt > 2000) {
    state.vuPeakPct = pct;
    state.vuPeakAt = now;
  }
  DOM.vuMeterPeak.hidden = state.vuPeakPct <= 0.5;
  if (!DOM.vuMeterPeak.hidden) {
    DOM.vuMeterPeak.style.left = `calc(${state.vuPeakPct}% - 1px)`;
  }

  if (effectiveDb === null) {
    DOM.vuDb.textContent = playing && currentClip?.has_audio_levels ? '...' : '-- dB';
    DOM.vuDb.classList.remove('is-hot', 'is-clip');
  } else {
    DOM.vuDb.textContent = `${effectiveDb.toFixed(0)} dB`;
    DOM.vuDb.classList.toggle('is-clip', effectiveDb > -3);
    DOM.vuDb.classList.toggle('is-hot', effectiveDb > -9 && effectiveDb <= -3);
  }
}

export function renderPads(transport = state.snapshot?.transport) {
  const entries = padEntries();
  if (!DOM.padGrid.childElementCount) {
    const fragment = document.createDocumentFragment();
    for (let pad = 1; pad <= 9; pad += 1) {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'pad-btn';
      button.dataset.pad = String(pad);
      button.innerHTML = '<span class="pad-btn-key"></span><span class="pad-btn-name"></span><span class="pad-btn-unpin" data-role="unpin" title="Unpin (back to automatic)">×</span>';
      fragment.appendChild(button);
    }
    DOM.padGrid.appendChild(fragment);
  }
  const activeClipId = transport?.clip_id;
  const isPlaying = transport?.status === 'play';
  for (const button of DOM.padGrid.children) {
    const pad = Number(button.dataset.pad);
    const entry = entries.find((item) => item.pad === pad) || { clip_id: null, name: null, pinned: false };
    const keyNode = button.querySelector('.pad-btn-key');
    const nameNode = button.querySelector('.pad-btn-name');
    keyNode.textContent = String(pad);
    nameNode.textContent = entry.name || '--';
    // Not `disabled`: empty pads must still receive drag & drop events.
    button.classList.toggle('is-empty', !entry.clip_id);
    button.title = entry.clip_id
      ? `${entry.name} — click to fire, Shift+click to cue, drop a clip to pin`
      : 'Empty pad — drop a clip from the media pool to pin it';
    button.classList.toggle('pinned', Boolean(entry.pinned));
    const isActive = Boolean(entry.clip_id && entry.clip_id === activeClipId);
    button.classList.toggle('active', isActive && isPlaying);
    button.classList.toggle('cued', isActive && !isPlaying);
  }
}

export function renderTransportSpeed(transport, canSeek) {
  const percent = Math.max(0, Number(transport.playback_speed_percent || 100));
  DOM.transportSpeedLabel.textContent = `SPEED ${percent}%`;
  DOM.transportSpeedLabel.classList.toggle('is-offspeed', percent !== 100);
  for (const button of DOM.transportSpeedButtons.children) {
    button.disabled = !canSeek;
    button.classList.toggle('active', Number(button.dataset.speed) === percent);
  }
}

export function renderTransportMarks(transport, canSeek, total) {
  const markIn = Math.max(0, Number(transport.mark_in_seconds || 0));
  const markOut = Math.max(0, Number(transport.mark_out_seconds || 0));
  const positionPercent = (value) => (total > 0 ? Math.min(100, Math.max(0, (value / total) * 100)) : 0);

  DOM.scrubMarkIn.hidden = !(markIn > 0 && total > 0);
  if (!DOM.scrubMarkIn.hidden) DOM.scrubMarkIn.style.left = `${positionPercent(markIn)}%`;
  DOM.scrubMarkOut.hidden = !(markOut > 0 && total > 0);
  if (!DOM.scrubMarkOut.hidden) DOM.scrubMarkOut.style.left = `${positionPercent(markOut)}%`;

  DOM.markInValue.textContent = markIn > 0 ? formatClock(markIn) : '--';
  DOM.markOutValue.textContent = markOut > 0 ? formatClock(markOut) : '--';
  const trimmed = Math.max(0, (markOut > 0 ? Math.min(markOut, total) : total) - markIn);
  DOM.markTrimValue.textContent = transport.trim_active ? formatClock(trimmed) : '--';
  DOM.markTrimValue.parentElement.classList.toggle('is-active', Boolean(transport.trim_active));

  DOM.btnMarkIn.disabled = !canSeek;
  DOM.btnMarkOut.disabled = !canSeek;
  DOM.btnMarkClear.disabled = !canSeek || !transport.trim_active;
}

DOM.transportSeek.addEventListener('input', (event) => {
  state.transportSeekDragging = true;
  state.transportSeekValue = Number(event.target.value || 0);
  if (state.snapshot?.transport) {
    renderTransport(state.snapshot.transport, state.snapshot.clips || []);
  }
});

bindAsync(DOM.transportSeek, 'change', async (event) => {
  await commitTransportSeek(Number(event.target.value || 0));
}, 'Playback Error');

DOM.transportSeek.addEventListener('pointerup', () => {
  DOM.transportSeek.blur();
});

bindAsync(DOM.btnPlay, 'click', togglePlayPause, 'Playback Error');

bindAsync(DOM.btnStop, 'click', async () => {
  if (!await ensureLiveActionAllowed('Stop playback')) return;
  await api('/api/transport/stop', { method: 'POST' });
}, 'Playback Error');

bindAsync(DOM.btnSeekBack, 'click', async () => {
  await commitTransportSeek(displayedTransportElapsed(state.snapshot?.transport) - 10);
}, 'Playback Error');

bindAsync(DOM.btnSeekForward, 'click', async () => {
  await commitTransportSeek(displayedTransportElapsed(state.snapshot?.transport) + 10);
}, 'Playback Error');

bindAsync(DOM.transportSpeedButtons, 'click', async (event) => {
  const button = event.target.closest('.speed-btn');
  if (!button || button.disabled) return;
  await api('/api/transport/speed', {
    method: 'POST',
    body: JSON.stringify({ percent: Number(button.dataset.speed) }),
  });
}, 'Playback Error');

bindAsync(DOM.btnMarkIn, 'click', async () => {
  await commitClipMarks({ markIn: displayedTransportElapsed(state.snapshot?.transport) });
}, 'Marks Error');

bindAsync(DOM.btnMarkOut, 'click', async () => {
  await commitClipMarks({ markOut: displayedTransportElapsed(state.snapshot?.transport) });
}, 'Marks Error');

bindAsync(DOM.btnMarkClear, 'click', async () => {
  await commitClipMarks({ markIn: 0, markOut: 0 });
}, 'Marks Error');

bindAsync(DOM.padGrid, 'click', async (event) => {
  const button = event.target.closest('.pad-btn');
  if (!button) return;
  if (event.target.closest('.pad-btn-unpin')) {
    event.stopPropagation();
    await api(`/api/pads/${button.dataset.pad}`, { method: 'POST', body: JSON.stringify({ clip_id: null }) });
    return;
  }
  if (button.classList.contains('is-empty')) return;
  await firePadClip(Number(button.dataset.pad), event.shiftKey);
}, 'Playback Error');

DOM.padGrid.addEventListener('dragover', (event) => {
  const button = event.target.closest('.pad-btn');
  if (!button || !state.dragClipId) return;
  event.preventDefault();
  button.classList.add('drop-target');
});

DOM.padGrid.addEventListener('dragleave', (event) => {
  const button = event.target.closest('.pad-btn');
  if (!button || button.contains(event.relatedTarget)) return;
  button.classList.remove('drop-target');
});

bindAsync(DOM.padGrid, 'drop', async (event) => {
  const button = event.target.closest('.pad-btn');
  if (!button) return;
  event.preventDefault();
  button.classList.remove('drop-target');
  const clipId = state.dragClipId;
  if (!clipId) return;
  await api(`/api/pads/${button.dataset.pad}`, { method: 'POST', body: JSON.stringify({ clip_id: clipId }) });
}, 'Pads Error');

bindAsync(DOM.btnPrev, 'click', async () => playAdjacentClip(-1), 'Playback Error');

bindAsync(DOM.btnNext, 'click', async () => playAdjacentClip(1), 'Playback Error');

bindAsync(DOM.btnBlack, 'click', async () => {
  if (!await ensureLiveActionAllowed('Cut to black')) return;
  await api('/api/system/black', { method: 'POST' });
}, 'Playback Error');
