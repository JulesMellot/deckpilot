import {
  api,
  formatBytes,
  formatClock,
  formatDateTime,
  formatEta,
  formatRemainingClock,
  formatUptimeMinutes,
  getErrorMessage,
} from './util.js';
import { DOM, Templates } from './dom.js';
import {
  applyState,
  applyStateNow,
  beginStateWrite,
  clipFromDeckId,
  getSelectedClip,
  liveActionBlocked,
  normalizeSelection,
  padEntries,
  playlistItemFromPosition,
  pruneNodeCache,
  reindexClips,
  state,
} from './store.js';
import {
  bindAsync,
  closeAppDialog,
  ensureLiveActionAllowed,
  openAppDialog,
  requestConfirm,
  requestSelect,
  requestText,
  runShortcut,
  showNotice,
  submitAppDialog,
} from './dialogs.js';
import {
  clipDurationLabel,
  clipResolutionLabel,
  filteredClips,
  mediaArtworkUrl,
  mediaKindLabel,
  mediaSourceUrl,
  renderFolders,
  renderMediaGrid,
  renderMediaToolbar,
  renderUploadProcessingStatus,
  setMediaView,
  syncMediaGridVisualState,
} from './media.js';
import { closePreviewModal, renderPreview } from './preview.js';
import {
  playPlaylist,
  renderPlaylist,
  renderPlaylists,
  syncPlaylistVisualState,
} from './playlist.js';

function updateClock() {
  DOM.systemClock.textContent = new Date().toLocaleTimeString('en-GB', { hour12: false });
}
setInterval(updateClock, 1000);
updateClock();

document.addEventListener('keydown', (e) => {
  if (e.code === 'Escape' && !DOM.appDialogBackdrop.hidden) {
    e.preventDefault();
    closeAppDialog(null);
    return;
  }
  if (e.code === 'Enter' && !DOM.appDialogBackdrop.hidden) {
    e.preventDefault();
    submitAppDialog();
    return;
  }
  if (e.code === 'Escape' && !DOM.previewModal.hidden) {
    e.preventDefault();
    closePreviewModal();
    return;
  }
  if (e.code === 'Escape' && !DOM.settingsModal.hidden) {
    e.preventDefault();
    closeSettingsModal();
    return;
  }
  if (['INPUT', 'TEXTAREA', 'SELECT'].includes(e.target.tagName)) return;
  switch (e.code) {
    case 'Space':
      e.preventDefault();
      void runShortcut(() => togglePlayPause(), 'Playback Error');
      break;
    case 'Escape':
      e.preventDefault();
      ensureLiveActionAllowed('Stop playback').then((allowed) => {
        if (allowed) {
          void runShortcut(() => api('/api/transport/stop', { method: 'POST' }), 'Playback Error');
        }
      });
      break;
    case 'Enter':
      e.preventDefault();
      ensureLiveActionAllowed('Cut to black').then((allowed) => {
        if (allowed) {
          void runShortcut(() => api('/api/system/black', { method: 'POST' }), 'Playback Error');
        }
      });
      break;
    case 'ArrowLeft':
      e.preventDefault();
      void runShortcut(() => playAdjacentClip(-1), 'Playback Error');
      break;
    case 'ArrowRight':
      e.preventDefault();
      void runShortcut(() => playAdjacentClip(1), 'Playback Error');
      break;
    case 'F1':
      e.preventDefault();
      setMediaView('grid');
      break;
    case 'F2':
      e.preventDefault();
      setMediaView('list');
      break;
    default: {
      const padMatch = /^(?:Digit|Numpad)([1-9])$/.exec(e.code);
      if (padMatch) {
        e.preventDefault();
        void runShortcut(() => firePadClip(Number(padMatch[1]), e.shiftKey), 'Playback Error');
      }
    }
  }
});

function firePadClip(padNumber, cueOnly) {
  const entry = padEntries().find((pad) => pad.pad === padNumber);
  if (!entry || !entry.clip_id) return Promise.resolve();
  state.selectedClipId = entry.clip_id;
  syncMediaGridVisualState();
  if (cueOnly) {
    return cueClip(entry.clip_id);
  }
  return api(`/api/clips/${entry.clip_id}/play`, { method: 'POST' });
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

export async function cueClip(clipId) {
  if (!clipId) return;
  await api(`/api/clips/${clipId}/goto`, { method: 'POST' });
}

async function togglePlayPause() {
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

async function playAdjacentClip(direction) {
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

function canSeekCurrentTransport(transport, clip) {
  return Boolean(transport?.clip_id && clip && clip.media_kind === 'video' && Number(transport.total_seconds) > 0);
}

function displayedTransportElapsed(transport) {
  if (state.transportSeekDragging && state.transportSeekValue !== null) {
    const max = Math.max(0, Number(transport?.total_seconds || 0));
    return Math.min(max, Math.max(0, Number(state.transportSeekValue || 0)));
  }
  return Math.max(0, Number(transport?.elapsed_seconds || 0));
}

async function commitTransportSeek(seconds) {
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

async function nudgeTransport(deltaSeconds) {
  if (!state.snapshot?.transport) return;
  const transport = state.snapshot.transport;
  const base = displayedTransportElapsed(transport);
  await commitTransportSeek(base + deltaSeconds);
}

function effectiveOutSeconds(transport) {
  const total = Math.max(0, Number(transport?.total_seconds || 0));
  const markOut = Number(transport?.mark_out_seconds || 0);
  return markOut > 0 ? Math.min(markOut, total) : total;
}

async function commitClipMarks({ markIn = null, markOut = null } = {}) {
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

function closeSettingsModal() {
  DOM.settingsModal.hidden = true;
}

function openSettingsModal() {
  DOM.settingsModal.hidden = false;
  void loadConfigEditor().catch((error) => console.error(error));
  void loadAudioDevices().catch((error) => console.error(error));
  void loadStorageDevices().catch((error) => console.error(error));
}

async function loadAudioDevices() {
  const payload = await api('/api/system/audio-devices');
  renderAudioDevices(payload.devices || []);
}

function renderAudioDevices(devices) {
  const fragment = document.createDocumentFragment();
  devices.forEach((device) => {
    const option = document.createElement('option');
    option.value = device.id;
    option.textContent = device.label;
    option.selected = device.selected;
    fragment.appendChild(option);
  });
  DOM.configAudio.replaceChildren(fragment);
}

async function loadStorageDevices() {
  const payload = await api('/api/system/storage-devices');
  renderStorageDevices(payload.devices || []);
}

function renderStorageDevices(devices) {
  state.storageDevices = devices;
  const fragment = document.createDocumentFragment();
  devices.forEach((device) => {
    const row = document.createElement('div');
    row.className = `storage-device${device.is_internal ? ' is-internal' : ''}`;
    const name = document.createElement('span');
    name.className = 'storage-device-name';
    name.textContent = device.is_internal ? 'Internal (SD card)' : `USB · ${device.label}`;
    const free = document.createElement('span');
    free.className = 'storage-device-free';
    const total = Number(device.total_bytes || 0);
    const percent = total > 0 ? ` (${Math.round((device.free_bytes / total) * 100)}%)` : '';
    free.textContent = `${formatBytes(device.free_bytes)} free / ${formatBytes(total)}${percent}`;
    row.append(name, free);
    fragment.appendChild(row);
  });
  if (!devices.length) {
    const row = document.createElement('div');
    row.className = 'storage-device';
    row.textContent = 'No drives detected — plug in a USB drive and press RESCAN.';
    fragment.appendChild(row);
  }
  DOM.storageDeviceList.replaceChildren(fragment);
}

async function loadConfigEditor() {
  const payload = await api('/api/system/config');
  state.configValues = payload.config || {};
  const fragment = document.createDocumentFragment();
  for (const [key, value] of Object.entries(state.configValues)) {
    const field = document.createElement('div');
    const isWide = Array.isArray(value) || key === 'app_name';
    field.className = `config-field${isWide ? ' span-2' : ''}`;
    const label = document.createElement('label');
    label.textContent = key.replaceAll('_', ' ');
    const input = document.createElement('input');
    input.className = 'select-box';
    input.type = 'text';
    input.dataset.key = key;
    input.value = Array.isArray(value) ? value.join(', ') : String(value);
    input.addEventListener('input', () => field.classList.add('is-dirty'));
    field.append(label, input);
    fragment.appendChild(field);
  }
  DOM.configEditor.replaceChildren(fragment);
}

function renderConnectionStatus(connections) {
  const clients = connections?.clients || [];
  if (clients.length) {
    DOM.atemStatus.classList.add('connected');
    DOM.atemStatus.querySelector('span').textContent = `${clients.length} CTRL CONN.`;
  } else {
    DOM.atemStatus.classList.remove('connected');
    DOM.atemStatus.querySelector('span').textContent = 'ATEM OFFLINE';
  }
}

function renderTransport(transport, clips) {
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

function renderLiveClipMeta(transport, clip) {
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

function renderNextClip(transport) {
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
  DOM.nextClipBar.hidden = false;
  if (transport.loop || behavior === 'stop' || behavior === 'hold') {
    DOM.nextClipBar.classList.add('is-terminal');
    DOM.nextClipName.textContent = transport.loop
      ? 'LOOPING CURRENT CLIP'
      : (behavior === 'hold' ? 'HOLD ON LAST FRAME' : 'STOP AT END');
    DOM.nextClipCountdown.textContent = transport.loop ? '∞' : formatRemainingClock(remaining);
    return;
  }
  if (nextItem) {
    DOM.nextClipBar.classList.remove('is-terminal');
    DOM.nextClipName.textContent = nextItem.clip_name;
  } else {
    DOM.nextClipBar.classList.add('is-terminal');
    DOM.nextClipName.textContent = 'END OF PLAYLIST';
  }
  DOM.nextClipCountdown.textContent = formatRemainingClock(remaining);
}

function ensureAudioLevels(clipId, clip) {
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

function renderVuMeter(transport, currentClip) {
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

function renderPads(transport = state.snapshot?.transport) {
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

function renderTransportSpeed(transport, canSeek) {
  const percent = Math.max(0, Number(transport.playback_speed_percent || 100));
  DOM.transportSpeedLabel.textContent = `SPEED ${percent}%`;
  DOM.transportSpeedLabel.classList.toggle('is-offspeed', percent !== 100);
  for (const button of DOM.transportSpeedButtons.children) {
    button.disabled = !canSeek;
    button.classList.toggle('active', Number(button.dataset.speed) === percent);
  }
}

function renderTransportMarks(transport, canSeek, total) {
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

function renderAudio(audio) {
  if (!audio) return;
  if (document.activeElement !== DOM.configVolume && state.pendingVolume === null) {
    DOM.configVolume.value = audio.volume;
  }
  DOM.volumeValue.textContent = `${state.pendingVolume ?? audio.volume}%`;
  DOM.btnMute.classList.toggle('muted', Boolean(audio.muted));
}

function renderNetwork(network) {
  if (network?.hyperdeck_target) {
    DOM.networkValue.textContent = network.hyperdeck_target;
  } else {
    DOM.networkValue.textContent = `${location.hostname}:9993`;
  }
}

function renderLogs(logs) {
  if (!state.logsVisible) return;
  const logText = (logs || []).slice(-80).map((entry) => `[${entry.created_at.split('T')[1].substring(0, 8)}] ${entry.message}`).join('\n');
  DOM.terminalLogs.textContent = logText;
  DOM.terminalLogs.scrollTop = DOM.terminalLogs.scrollHeight;
}

// An ATEM polling the deck produces a log line per protocol command; batch
// the terminal rewrites instead of touching the DOM for every line.
let logsRenderPending = false;
function scheduleLogsRender() {
  if (logsRenderPending) return;
  logsRenderPending = true;
  window.setTimeout(() => {
    logsRenderPending = false;
    renderLogs(state.snapshot?.logs || []);
  }, 250);
}

function renderPlaybackCollections() {
  normalizeSelection();
  renderPlaylist(state.snapshot?.playlist || { playlist: null, items: [] }, state.snapshot?.transport?.clip_id);
  renderMediaGrid(filteredClips(), state.snapshot?.transport?.clip_id, state.snapshot?.transport?.status);
  renderPads();
}

function syncPlaybackCollections() {
  syncPlaylistVisualState();
  syncMediaGridVisualState();
}

function renderCollections() {
  renderFolders();
  renderMediaToolbar();
  renderPlaylists();
  renderPlaybackCollections();
  renderPreview();
}

function transportAffectsCollections(previousTransport, nextTransport) {
  if (!previousTransport) return true;
  return previousTransport.clip_id !== nextTransport.clip_id
    || previousTransport.status !== nextTransport.status
    || previousTransport.paused !== nextTransport.paused
    || previousTransport.playlist_mode !== nextTransport.playlist_mode
    || previousTransport.playlist_loop !== nextTransport.playlist_loop;
}

function renderUpdateStatus(update) {
  state.updateStatus = update || null;
  if (!update) {
    DOM.updateStatusLine.textContent = 'Update status unavailable.';
    DOM.updateStatusLine.className = 'update-status-line is-error';
    DOM.updateChangelog.hidden = true;
    DOM.updateMeta.textContent = '';
    DOM.btnRunUpdate.disabled = true;
    DOM.btnRunUpdate.textContent = 'UPDATE NOW';
    DOM.btnRunUpdate.classList.remove('active');
    return;
  }

  const busy = ['running', 'restarting', 'rebooting'].includes(update.phase);
  let statusClass = 'update-status-line';
  let statusText;
  if (busy) {
    statusClass += ' is-busy';
    statusText = `Updating… ${update.message || ''}`;
  } else if (update.error) {
    statusClass += ' is-error';
    statusText = `Update failed: ${update.error}`;
  } else if (update.update_available) {
    statusClass += ' is-available';
    statusText = `Update available — ${update.current_commit || '?'} → ${update.remote_commit || '?'}`;
  } else if (update.update_available === false) {
    statusText = `Up to date — ${update.current_commit || '?'} on ${update.branch || '?'}`;
  } else {
    statusText = update.message || 'Update status unknown.';
  }
  DOM.updateStatusLine.className = statusClass;
  DOM.updateStatusLine.textContent = statusText;

  const changelog = update.changelog || [];
  DOM.updateChangelog.hidden = !changelog.length;
  if (changelog.length) {
    const fragment = document.createDocumentFragment();
    changelog.forEach((entry) => {
      const item = document.createElement('li');
      const space = entry.indexOf(' ');
      const hash = document.createElement('span');
      hash.className = 'commit-hash';
      hash.textContent = space > 0 ? entry.slice(0, space) : '';
      item.appendChild(hash);
      item.appendChild(document.createTextNode(space > 0 ? entry.slice(space + 1) : entry));
      fragment.appendChild(item);
    });
    DOM.updateChangelogList.replaceChildren(fragment);
  }

  const lines = [
    `Platform: ${(update.platform || 'unknown').toUpperCase()} | Install: ${(update.install_mode || 'manual').toUpperCase()} | Branch: ${update.branch || 'unknown'}`,
  ];
  if (update.restart_target === 'raspberry_pi') {
    lines.push('This update will reboot the Raspberry Pi.');
  } else if (update.restart_target === 'deckpilot') {
    lines.push('This update only restarts DeckPilot.');
  }
  if (update.restart_reason) {
    lines.push(`Why: ${update.restart_reason}`);
  }
  if (update.finished_at) {
    lines.push(`Last update: ${formatDateTime(update.finished_at)}`);
  }
  if (!update.can_update && update.reason) {
    lines.push(`Note: ${update.reason}`);
  }
  DOM.updateMeta.textContent = lines.join('\n');

  DOM.btnRunUpdate.disabled = busy || !update.can_update;
  DOM.btnRunUpdate.textContent = busy ? 'UPDATING…' : 'UPDATE NOW';
  DOM.btnRunUpdate.classList.toggle('active', Boolean(update.update_available) && !busy && update.can_update);
}

function renderHealth(health, safety) {
  const effectiveSafety = safety || state.snapshot?.safety || {};
  if (!health) {
    DOM.healthPlayer.textContent = 'UNKNOWN';
    DOM.healthOutput.textContent = 'UNKNOWN';
    DOM.healthStorage.textContent = 'UNKNOWN';
    DOM.healthRemote.textContent = 'UNKNOWN';
    DOM.healthMeta.textContent = 'System health unavailable.';
    return;
  }
  DOM.healthPlayer.textContent = health.player_available ? 'ONLINE' : 'OFFLINE';
  DOM.healthOutput.textContent = health.effective_output_width && health.effective_output_height
    ? `${health.effective_output_width}x${health.effective_output_height}`
    : (health.selected_output?.current_mode || health.selected_output?.label || 'DEFAULT');
  const freeBytes = Number(health.storage_free_bytes || 0);
  const totalBytes = Number(health.storage_total_bytes || 0);
  if (totalBytes > 0) {
    const freePercent = Math.round((freeBytes / totalBytes) * 100);
    DOM.healthStorage.textContent = `${formatBytes(freeBytes)} / ${formatBytes(totalBytes)} (${freePercent}%)`;
    DOM.healthStorage.classList.toggle('is-low', freePercent <= 10);
  } else {
    DOM.healthStorage.textContent = formatBytes(freeBytes);
    DOM.healthStorage.classList.remove('is-low');
  }
  DOM.healthRemote.textContent = health.remote_enabled ? 'ENABLED' : 'DISABLED';

  const lines = [
    `Clips: ${health.clip_count || 0} | Controllers: ${health.connected_controllers || 0}`,
    `Safe mode: ${effectiveSafety.safe_mode_enabled ? 'ON' : 'OFF'} | Armed: ${effectiveSafety.live_controls_armed ? `${effectiveSafety.armed_seconds_remaining || 0}s` : 'NO'}`,
  ];
  if (health.selected_output?.current_mode || health.effective_output_width) {
    const detected = health.selected_output?.current_mode || 'unknown';
    const canvas = health.effective_output_width && health.effective_output_height
      ? `${health.effective_output_width}x${health.effective_output_height}`
      : 'auto';
    lines.push(`Display: detected ${detected} | canvas ${canvas} | mode ${(health.output_canvas_mode || 'auto').toUpperCase()}`);
  }
  if (health.clips_last_synced_at) {
    lines.push(`Clip sync: ${formatDateTime(health.clips_last_synced_at)}`);
  }
  const mediaProcessing = health.media_processing || {};
  if (mediaProcessing.pending || mediaProcessing.processing || mediaProcessing.error) {
    const eta = mediaProcessing.eta_seconds == null ? 'ETA --' : formatEta(mediaProcessing.eta_seconds);
    const throughput = mediaProcessing.clips_per_second ? `${mediaProcessing.clips_per_second} clip/s` : 'warming up';
    lines.push(`Media processing: queued ${mediaProcessing.pending || 0} | running ${mediaProcessing.processing || 0} | errors ${mediaProcessing.error || 0} | ${eta} | ${throughput}`);
  }
  const vitals = health.system || {};
  const vitalsParts = [];
  if (vitals.cpu_temp_c != null) vitalsParts.push(`${vitals.cpu_temp_c}°C`);
  if (vitals.load_1m != null) vitalsParts.push(`load ${vitals.load_1m}`);
  if (vitals.mem_used_percent != null) vitalsParts.push(`RAM ${vitals.mem_used_percent}%`);
  if (health.uptime_minutes != null) vitalsParts.push(`up ${formatUptimeMinutes(health.uptime_minutes)}`);
  if (vitalsParts.length) {
    lines.push(`System: ${vitalsParts.join(' | ')}`);
  }
  const watchFolder = health.watch_folder || {};
  if (watchFolder.enabled) {
    const lastIngest = watchFolder.last_ingest_at ? formatDateTime(watchFolder.last_ingest_at) : 'none yet';
    const pending = watchFolder.pending_files ? ` | ${watchFolder.pending_files} incoming` : '';
    lines.push(`Watch folder: ON (${Math.round(watchFolder.interval_seconds)}s) | ${watchFolder.ingest_count} ingest(s) | last ${lastIngest}${pending}`);
  } else {
    lines.push('Watch folder: OFF');
  }
  DOM.watchfolderHint.hidden = !watchFolder.enabled;
  if (health.last_error) {
    lines.push(`Last error: ${health.last_error}`);
  } else if (health.player_error) {
    lines.push(`Player error: ${health.player_error}`);
  }
  DOM.healthMeta.textContent = lines.join('\n');
  renderUploadProcessingStatus(mediaProcessing);

  DOM.btnToggleSafeMode.textContent = effectiveSafety.safe_mode_enabled ? 'SAFE MODE ON' : 'SAFE MODE OFF';
  DOM.btnToggleSafeMode.classList.toggle('active', effectiveSafety.safe_mode_enabled);
  DOM.btnArmLive.textContent = effectiveSafety.live_controls_armed ? `ARMED ${effectiveSafety.armed_seconds_remaining || 0}s` : 'ARM LIVE';
  DOM.btnArmLive.classList.toggle('active', effectiveSafety.live_controls_armed);
}

function applySafetyState(safety) {
  if (!safety) return;
  applyStateNow(() => {
    if (!state.snapshot) state.snapshot = {};
    state.snapshot.safety = safety;
    renderHealth(state.snapshot.health, safety);
  });
}

function stopUpdatePolling() {
  if (!state.updatePollTimer) return;
  clearTimeout(state.updatePollTimer);
  state.updatePollTimer = null;
  state.updatePollInFlight = false;
}

function startUpdatePolling() {
  if (state.updatePollTimer) return;
  const poll = async () => {
    state.updatePollTimer = null;
    if (state.updatePollInFlight) return;
    state.updatePollInFlight = true;
    try {
      const update = await api('/api/system/update');
      renderUpdateStatus(update);
      const busy = ['running', 'restarting', 'rebooting'].includes(update.phase);
      if (!busy) {
        stopUpdatePolling();
        await refresh({ includeUpdate: false });
        return;
      }
    } catch (error) {
      DOM.updateMeta.textContent = 'Updating DeckPilot...\nWaiting for the service restart or Raspberry Pi reboot...';
    } finally {
      state.updatePollInFlight = false;
    }
    state.updatePollTimer = window.setTimeout(poll, 2000);
  };
  state.updatePollTimer = window.setTimeout(poll, 0);
}

function scheduleVolumeCommit(volume) {
  state.pendingVolume = volume;
  DOM.volumeValue.textContent = `${volume}%`;
  if (state.snapshot?.audio) {
    applyStateNow(() => {
      state.snapshot.audio.volume = volume;
    });
  }
  if (state.volumeCommitTimer) {
    clearTimeout(state.volumeCommitTimer);
  }
  state.volumeCommitTimer = window.setTimeout(() => {
    state.volumeCommitTimer = null;
    void commitVolumeChange();
  }, 160);
}

async function commitVolumeChange() {
  if (state.volumeCommitInFlight) return;
  const volume = state.pendingVolume;
  if (volume === null) return;
  state.volumeCommitInFlight = true;
  try {
    await api('/api/audio/volume', { method: 'POST', body: JSON.stringify({ volume }) });
    if (state.pendingVolume === volume) {
      state.pendingVolume = null;
    }
  } catch (error) {
    console.error(error);
    state.pendingVolume = null;
    if (state.snapshot?.audio) {
      DOM.configVolume.value = state.snapshot.audio.volume;
      DOM.volumeValue.textContent = `${state.snapshot.audio.volume}%`;
    }
    await showNotice('Volume Error', getErrorMessage(error));
  } finally {
    state.volumeCommitInFlight = false;
    if (state.pendingVolume !== null && state.pendingVolume !== volume && !state.volumeCommitTimer) {
      state.volumeCommitTimer = window.setTimeout(() => {
        state.volumeCommitTimer = null;
        void commitVolumeChange();
      }, 80);
    }
  }
}

function setLogsVisible(enabled) {
  state.logsVisible = enabled;
  DOM.logsPanel.hidden = !enabled;
  DOM.btnToggleLogs.classList.toggle('active', enabled);
  DOM.btnToggleLogs.textContent = enabled ? 'LOGS ON' : 'LOGS OFF';
  DOM.panelRight.classList.toggle('logs-hidden', !enabled);
  if (enabled) renderLogs(state.snapshot?.logs || []);
}

function renderState(snapshot) {
  state.snapshot = snapshot;
  state.folders = snapshot.folders || state.folders;
  state.playlists = snapshot.playlists || state.playlists;
  reindexClips(snapshot.clips || []);
  pruneNodeCache(state.mediaNodeCache, new Set((snapshot.clips || []).map((clip) => String(clip.deck_id))));
  pruneNodeCache(state.folderNodeCache, new Set((snapshot.folders || []).filter((folder) => folder !== 'All')));
  normalizeSelection();
  // Keep the IMPORT file picker in sync with the configured extensions, so a
  // format added in Settings (e.g. .webm) becomes selectable without a reload.
  if (Array.isArray(snapshot.allowed_extensions) && snapshot.allowed_extensions.length) {
    DOM.fileInput.accept = snapshot.allowed_extensions.join(',');
  }
  const { transport, clips, connections, logs, audio, outputs, network, health, safety, display } = snapshot;
  if (snapshot.app_name) {
    DOM.appName.textContent = String(snapshot.app_name).toUpperCase();
  }
  renderConnectionStatus(connections || {});
  renderTransport(transport, clips);
  renderAudio(audio || { volume: 100, muted: false });
  renderNetwork(network);
  renderOutputs(outputs || []);
  renderDisplaySettings(display || {});
  renderCollections();
  renderHealth(health, safety);
  setLogsVisible(state.logsVisible);
  renderLogs(logs || []);
}

function renderOutputs(outputs) {
  const previous = DOM.configOutput.value;
  const fragment = document.createDocumentFragment();
  outputs.forEach((output) => {
    const option = document.createElement('option');
    option.value = output.id;
    option.textContent = output.label;
    option.selected = output.selected;
    fragment.appendChild(option);
  });
  DOM.configOutput.replaceChildren(fragment);
  if (previous && outputs.some((output) => output.id === previous)) {
    DOM.configOutput.value = previous;
  }
}

function renderDisplaySettings(display) {
  const previous = DOM.configCanvas.value;
  const modes = display.available_canvas_modes || ['auto'];
  const fragment = document.createDocumentFragment();
  modes.forEach((mode) => {
    const option = document.createElement('option');
    option.value = mode;
    option.textContent = mode === 'auto' ? 'AUTO (DETECTION)' : mode;
    option.selected = mode === (display.canvas_mode || 'auto');
    fragment.appendChild(option);
  });
  DOM.configCanvas.replaceChildren(fragment);
  if (previous && modes.includes(previous)) {
    DOM.configCanvas.value = previous;
  } else {
    DOM.configCanvas.value = display.canvas_mode || 'auto';
  }
}

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
DOM.btnToggleLogs.addEventListener('click', () => setLogsVisible(!state.logsVisible));
DOM.btnOpenSettings.addEventListener('click', openSettingsModal);
bindAsync(DOM.btnToggleSafeMode, 'click', async () => {
  const enabled = !Boolean(state.snapshot?.safety?.safe_mode_enabled);
  const response = await api('/api/system/safe-mode', {
    method: 'POST',
    body: JSON.stringify({ enabled })
  });
  applySafetyState(response.safety);
}, 'Safety Error');
bindAsync(DOM.btnArmLive, 'click', async () => {
  const response = await api('/api/system/arm-controls', {
    method: 'POST',
    body: JSON.stringify({ seconds: 12 })
  });
  applySafetyState(response.safety);
}, 'Safety Error');
bindAsync(DOM.btnSaveConfig, 'click', async () => {
  const updates = {};
  for (const input of DOM.configEditor.querySelectorAll('input')) {
    const key = input.dataset.key;
    const original = state.configValues?.[key];
    const originalText = Array.isArray(original) ? original.join(', ') : String(original);
    if (input.value.trim() === originalText.trim()) continue;
    updates[key] = input.value.trim();
  }
  if (!Object.keys(updates).length) {
    await showNotice('Configuration', 'No changes to save.');
    return;
  }
  const result = await api('/api/system/config', { method: 'POST', body: JSON.stringify({ updates }) });
  await showNotice('Configuration Saved', `Updated: ${result.updated.join(', ')}.\nChanges are stored in config.json and apply after a restart — use RESTART DECKPILOT when ready.`);
  await loadConfigEditor();
}, 'Configuration Error');
bindAsync(DOM.btnRestartApp, 'click', async () => {
  const confirmed = await requestConfirm({
    title: 'Restart DeckPilot',
    message: 'Restart DeckPilot now? Playback stops and the deck is back in a few seconds (the service restarts automatically).',
    confirmLabel: 'RESTART',
  });
  if (!confirmed) return;
  await api('/api/system/restart', { method: 'POST' });
  await showNotice('Restarting', 'DeckPilot is restarting — the interface will reconnect automatically.');
}, 'Restart Error');
bindAsync(DOM.btnRunUpdate, 'click', async () => {
  const updateStatus = state.updateStatus;
  let updateMessage = 'DeckPilot will pull the latest version and restart automatically if needed. Continue?';
  if (updateStatus?.restart_target === 'raspberry_pi') {
    if (updateStatus.automatic_reboot_available) {
      updateMessage = 'This update changes appliance components and will reboot the Raspberry Pi automatically. Continue?';
    } else {
      updateMessage = 'This update requires a Raspberry Pi reboot. DeckPilot will update now and then ask for a manual reboot. Continue?';
    }
  } else if (updateStatus?.restart_target === 'deckpilot') {
    updateMessage = 'This update only restarts DeckPilot — no Raspberry Pi reboot needed. Continue?';
  } else if (updateStatus?.restart_notice) {
    updateMessage = `${updateStatus.restart_notice} Continue?`;
  }
  const confirmed = await requestConfirm({
    title: 'Update DeckPilot',
    message: updateMessage,
    confirmLabel: 'UPDATE'
  });
  if (!confirmed) return;
  try {
    const update = await api('/api/system/update', {
      method: 'POST',
      body: JSON.stringify({ confirm: true })
    });
    renderUpdateStatus(update);
    startUpdatePolling();
  } catch (error) {
    await showNotice('Update Error', error.message || 'Automatic update failed to start.');
  }
}, 'Update Error');
bindAsync(DOM.configFormat, 'change', async (e) => {
  if (!await ensureLiveActionAllowed('Video format change')) {
    DOM.configFormat.value = state.snapshot?.transport?.video_format || DOM.configFormat.value;
    return;
  }
  await api('/api/system/video-format', { method: 'POST', body: JSON.stringify({ video_format: e.target.value }) });
}, 'Display Error');
bindAsync(DOM.configOutput, 'change', async (e) => {
  if (!await ensureLiveActionAllowed('Video output change')) {
    renderOutputs(state.snapshot?.outputs || []);
    return;
  }
  await api('/api/system/output', { method: 'POST', body: JSON.stringify({ output_id: e.target.value }) });
}, 'Display Error');
bindAsync(DOM.configCanvas, 'change', async (e) => {
  if (!await ensureLiveActionAllowed('Video canvas change')) {
    renderDisplaySettings(state.snapshot?.display || {});
    return;
  }
  const response = await api('/api/system/output-canvas', { method: 'POST', body: JSON.stringify({ mode: e.target.value }) });
  if (state.snapshot && response?.display) {
    applyStateNow(() => {
      state.snapshot.display = response.display;
      renderDisplaySettings(state.snapshot.display);
    });
  }
}, 'Display Error');
bindAsync(DOM.configAudio, 'change', async (e) => {
  if (!await ensureLiveActionAllowed('Audio output change')) {
    void loadAudioDevices().catch(() => {});
    return;
  }
  const response = await api('/api/system/audio-device', { method: 'POST', body: JSON.stringify({ device: e.target.value }) });
  if (response?.devices) {
    renderAudioDevices(response.devices);
  }
}, 'Audio Error');
bindAsync(DOM.btnRescanStorage, 'click', async () => {
  const result = await api('/api/system/storage-rescan', { method: 'POST' });
  renderStorageDevices(result.devices || []);
  const usbCount = (result.devices || []).filter((device) => !device.is_internal).length;
  await showNotice('Media Storage', usbCount
    ? `Rescanned — ${usbCount} USB drive(s) connected. New clips appear in the library.`
    : 'Rescanned — no USB drive connected. Clips on the SD card are shown.');
}, 'Media Storage Error');
DOM.configVolume.addEventListener('input', (e) => {
  scheduleVolumeCommit(Number(e.target.value));
});
bindAsync(DOM.btnMute, 'click', async () => {
  const muted = DOM.btnMute.classList.contains('muted');
  await api('/api/audio/mute', { method: 'POST', body: JSON.stringify({ muted: !muted }) });
}, 'Audio Error');
DOM.settingsModal.addEventListener('click', (event) => {
  if (event.target === DOM.settingsModal) {
    closeSettingsModal();
  }
});
DOM.btnSettingsClose.addEventListener('click', closeSettingsModal);
DOM.btnExportLibrary.addEventListener('click', () => {
  window.open('/api/system/export', '_blank');
});
DOM.btnBackupDb.addEventListener('click', () => {
  window.open('/api/system/backup', '_blank');
});
DOM.btnImportLibrary.addEventListener('click', () => DOM.importFileInput.click());
bindAsync(DOM.importFileInput, 'change', async () => {
  const file = DOM.importFileInput.files?.[0];
  DOM.importFileInput.value = '';
  if (!file) return;
  const text = await file.text();
  let payload;
  try {
    payload = JSON.parse(text);
  } catch (error) {
    throw new Error('Invalid JSON file.');
  }
  const confirmed = await requestConfirm({
    title: 'Import Library',
    message: 'Apply the names, folders, marks, tags, and playlists from this file? Current settings of matching clips will be replaced.',
    confirmLabel: 'IMPORT',
  });
  if (!confirmed) return;
  const result = await api('/api/system/import', { method: 'POST', body: JSON.stringify(payload) });
  await showNotice('Import Complete', `${result.clips} clip(s) and ${result.playlists} playlist(s) updated.`);
  await refresh();
}, 'Import Error');

export async function refresh({ includeUpdate = true } = {}) {
  const ticket = beginStateWrite();
  const requests = [api('/api/state')];
  if (includeUpdate) {
    requests.push(api('/api/system/update'));
  }
  const [snapshot, updatePayload] = await Promise.all(requests);
  applyState(ticket, () => renderState(snapshot));
  if (updatePayload) {
    renderUpdateStatus(updatePayload);
    if (['running', 'restarting', 'rebooting'].includes(updatePayload.phase)) {
      startUpdatePolling();
    }
  }
}

function scheduleWebSocketReconnect() {
  if (state.websocketReconnectTimer) return;
  // Exponential backoff (1s, 2s, 4s... capped at 15s) so a downed server
  // during a multi-hour show doesn't get hammered with reconnect attempts.
  const attempt = state.websocketReconnectAttempts;
  const delay = Math.min(1000 * 2 ** attempt, 15000);
  state.websocketReconnectAttempts = attempt + 1;
  state.websocketReconnectTimer = window.setTimeout(() => {
    state.websocketReconnectTimer = null;
    setupWebSocket();
  }, delay);
}

function setupWebSocket() {
  const protocol = location.protocol === 'https:' ? 'wss' : 'ws';
  const socket = new WebSocket(`${protocol}://${location.host}/ws`);
  socket.addEventListener('open', () => {
    state.websocketConnected = true;
    state.websocketReconnectAttempts = 0;
  });
  socket.addEventListener('error', (event) => {
    console.error('WebSocket error', event);
  });
  socket.addEventListener('message', (event) => {
    let message;
    try {
      message = JSON.parse(event.data);
    } catch (error) {
      console.error('Invalid websocket payload', error);
      return;
    }
    applyStateNow(() => applyWebSocketMessage(message));
  });
  socket.addEventListener('close', () => {
    state.websocketConnected = false;
    scheduleWebSocketReconnect();
  });
}

function applyWebSocketMessage(message) {
  if (message.type === 'snapshot') {
    renderState(message.payload);
    return;
  }
  if (!state.snapshot) return;
  if (message.type === 'transport') {
    const previousTransport = state.snapshot.transport;
    state.snapshot.transport = message.payload;
    normalizeSelection();
    renderTransport(state.snapshot.transport, state.snapshot.clips);
    if (transportAffectsCollections(previousTransport, state.snapshot.transport)) {
      syncPlaybackCollections();
    }
    return;
  }
  if (message.type === 'clips') {
    state.snapshot.clips = message.payload.clips;
    reindexClips(state.snapshot.clips);
    normalizeSelection();
    renderTransport(state.snapshot.transport, state.snapshot.clips);
    renderPlaybackCollections();
    renderPreview();
    return;
  }
  if (message.type === 'folders') {
    state.folders = message.payload.folders || [];
    renderCollections();
    return;
  }
  if (message.type === 'playlists') {
    state.playlists = message.payload.playlists || [];
    renderPlaylists();
    return;
  }
  if (message.type === 'connections') {
    state.snapshot.connections = message.payload;
    renderConnectionStatus(message.payload);
    return;
  }
  if (message.type === 'audio') {
    state.snapshot.audio = message.payload;
    renderAudio(message.payload);
    return;
  }
  if (message.type === 'playlist') {
    state.snapshot.playlist = message.payload;
    normalizeSelection();
    renderPlaylists();
    renderPlaybackCollections();
    return;
  }
  if (message.type === 'pads') {
    state.snapshot.pads = message.payload.pads || [];
    renderPads();
    return;
  }
  if (message.type === 'outputs') {
    state.snapshot.outputs = message.payload.outputs;
    renderOutputs(state.snapshot.outputs);
    return;
  }
  if (message.type === 'health') {
    state.snapshot.health = message.payload;
    renderHealth(message.payload, state.snapshot.safety);
    return;
  }
  if (message.type === 'display') {
    state.snapshot.display = message.payload;
    renderDisplaySettings(message.payload);
    return;
  }
  if (message.type === 'safety') {
    applySafetyState(message.payload);
    return;
  }
  if (message.type === 'log') {
    const logs = state.snapshot.logs || [];
    logs.push(message.payload);
    if (logs.length > 200) logs.splice(0, logs.length - 200);
    state.snapshot.logs = logs;
    scheduleLogsRender();
    return;
  }
}

async function initializeApp() {
  try {
    await refresh();
    setupWebSocket();
  } catch (error) {
    console.error(error);
    await showNotice('Startup Error', getErrorMessage(error, 'DeckPilot failed to initialize.'));
    scheduleWebSocketReconnect();
  }
}

initializeApp();
