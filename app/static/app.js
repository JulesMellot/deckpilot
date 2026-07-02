// Entry point and orchestrator: fetch/WebSocket state application, the
// cross-panel render paths, keyboard shortcuts, clock, and startup. Panels
// import refresh() back from here — the one intentional cycle in the graph.

import { api, getErrorMessage } from './util.js';
import { DOM } from './dom.js';
import {
  applyState,
  applyStateNow,
  beginStateWrite,
  normalizeSelection,
  pruneNodeCache,
  reindexClips,
  state,
} from './store.js';
import {
  closeAppDialog,
  ensureLiveActionAllowed,
  runShortcut,
  showNotice,
  submitAppDialog,
} from './dialogs.js';
import {
  filteredClips,
  renderFolders,
  renderMediaGrid,
  renderMediaToolbar,
  setMediaView,
  syncMediaGridVisualState,
} from './media.js';
import { closePreviewModal, renderPreview } from './preview.js';
import {
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
import {
  applySafetyState,
  renderConnectionStatus,
  renderHealth,
  renderLogs,
  renderNetwork,
  scheduleLogsRender,
  setLogsVisible,
} from './health.js';

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
