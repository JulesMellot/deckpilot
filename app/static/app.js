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
import {
  closeSettingsModal,
  renderAudio,
  renderDisplaySettings,
  renderOutputs,
  renderUpdateStatus,
  startUpdatePolling,
} from './settings.js';

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

DOM.btnToggleLogs.addEventListener('click', () => setLogsVisible(!state.logsVisible));
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
