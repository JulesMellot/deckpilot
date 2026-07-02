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
import {
  firePadClip,
  playAdjacentClip,
  renderPads,
  renderTransport,
  togglePlayPause,
  transportAffectsCollections,
} from './transport.js';

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
