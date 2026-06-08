const state = {
  snapshot: null,
  dragClipId: null,
  selectedClipId: null,
  selectedPlaylistPosition: 1,
  folders: [],
  playlists: [],
  dialogResolver: null,
  logsVisible: true,
  mediaView: 'grid',
  updateStatus: null,
  updatePollTimer: null,
};

const DOM = {
  appName: document.getElementById('app-name'),
  liveFormat: document.getElementById('live-format'),
  atemStatus: document.getElementById('atem-status'),
  networkValue: document.getElementById('network-value'),
  systemClock: document.getElementById('system-clock'),
  btnToggleLogs: document.getElementById('btn-toggle-logs'),
  btnOpenSettings: document.getElementById('btn-open-settings'),
  tallyBar: document.getElementById('tally-bar'),
  liveClipName: document.getElementById('live-clip-name'),
  liveTimecode: document.getElementById('live-timecode'),
  liveRemaining: document.getElementById('live-remaining'),
  liveDuration: document.getElementById('live-duration'),
  liveProgress: document.getElementById('live-progress'),
  btnPrev: document.getElementById('btn-prev'),
  btnStop: document.getElementById('btn-stop'),
  btnPlay: document.getElementById('btn-play'),
  btnNext: document.getElementById('btn-next'),
  btnBlack: document.getElementById('btn-black'),
  iconPlay: document.getElementById('icon-play'),
  iconPause: document.getElementById('icon-pause'),
  mediaGrid: document.getElementById('media-grid'),
  dropzone: document.getElementById('dropzone'),
  fileInput: document.getElementById('file-input'),
  uploadWrapper: document.getElementById('upload-wrapper'),
  uploadProgress: document.getElementById('upload-progress'),
  btnRefreshMedia: document.getElementById('btn-refresh-media'),
  folderFilter: document.getElementById('folder-filter'),
  btnBackAll: document.getElementById('btn-back-all'),
  btnToggleMediaView: document.getElementById('btn-toggle-media-view'),
  btnNewFolder: document.getElementById('btn-new-folder'),
  btnMoveFolder: document.getElementById('btn-move-folder'),
  previewModal: document.getElementById('preview-modal'),
  previewVideo: document.getElementById('preview-video'),
  previewTitle: document.getElementById('preview-title'),
  previewSubtitle: document.getElementById('preview-subtitle'),
  btnPreviewClose: document.getElementById('btn-preview-close'),
  btnPreviewPlay: document.getElementById('btn-preview-play'),
  btnPreviewCue: document.getElementById('btn-preview-cue'),
  btnPreviewAddPlaylist: document.getElementById('btn-preview-add-playlist'),
  playlistSelect: document.getElementById('playlist-select'),
  playlistCount: document.getElementById('playlist-count'),
  playlistItems: document.getElementById('playlist-items'),
  btnNewPlaylist: document.getElementById('btn-new-playlist'),
  btnActivatePlaylist: document.getElementById('btn-activate-playlist'),
  btnPlayPlaylist: document.getElementById('btn-play-playlist'),
  btnPlayPlaylistFrom: document.getElementById('btn-play-playlist-from'),
  btnNextPlaylist: document.getElementById('btn-next-playlist'),
  btnLoopPlaylist: document.getElementById('btn-loop-playlist'),
  btnAddSelectedPlaylist: document.getElementById('btn-add-selected-playlist'),
  btnClearPlaylist: document.getElementById('btn-clear-playlist'),
  configVolume: document.getElementById('config-volume'),
  volumeValue: document.getElementById('volume-value'),
  btnMute: document.getElementById('btn-mute'),
  configFormat: document.getElementById('config-format'),
  configOutput: document.getElementById('config-output'),
  healthPlayer: document.getElementById('health-player'),
  healthOutput: document.getElementById('health-output'),
  healthStorage: document.getElementById('health-storage'),
  healthRemote: document.getElementById('health-remote'),
  healthMeta: document.getElementById('health-meta'),
  btnToggleSafeMode: document.getElementById('btn-toggle-safe-mode'),
  btnArmLive: document.getElementById('btn-arm-live'),
  terminalLogs: document.getElementById('terminal-logs'),
  panelRight: document.querySelector('.panel-right'),
  logsPanel: document.querySelector('.logs-panel'),
  appDialogBackdrop: document.getElementById('app-dialog-backdrop'),
  appDialogTitle: document.getElementById('app-dialog-title'),
  appDialogMessage: document.getElementById('app-dialog-message'),
  appDialogInput: document.getElementById('app-dialog-input'),
  appDialogSelect: document.getElementById('app-dialog-select'),
  btnAppDialogClose: document.getElementById('btn-app-dialog-close'),
  btnAppDialogCancel: document.getElementById('btn-app-dialog-cancel'),
  btnAppDialogConfirm: document.getElementById('btn-app-dialog-confirm'),
  settingsModal: document.getElementById('settings-modal'),
  btnSettingsClose: document.getElementById('btn-settings-close'),
  updateMeta: document.getElementById('update-meta'),
  btnRunUpdate: document.getElementById('btn-run-update'),
};

const Templates = {
  mediaItem: document.getElementById('tpl-media-item'),
  playlistItem: document.getElementById('tpl-playlist-item')
};

function formatClock(seconds) {
  const total = Math.max(0, Math.round(seconds || 0));
  const hrs = Math.floor(total / 3600).toString().padStart(2, '0');
  const mins = Math.floor((total % 3600) / 60).toString().padStart(2, '0');
  const secs = (total % 60).toString().padStart(2, '0');
  return `${hrs}:${mins}:${secs}`;
}

function formatDateTime(timestampSeconds) {
  if (!timestampSeconds) return 'n/a';
  return new Date(timestampSeconds * 1000).toLocaleString('en-GB', { hour12: false });
}

function formatBytes(value) {
  const bytes = Number(value || 0);
  if (bytes <= 0) return 'n/a';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let amount = bytes;
  let unitIndex = 0;
  while (amount >= 1024 && unitIndex < units.length - 1) {
    amount /= 1024;
    unitIndex += 1;
  }
  return `${amount.toFixed(unitIndex >= 3 ? 1 : 0)} ${units[unitIndex]}`;
}

async function api(path, options = {}) {
  const isFormData = options.body instanceof FormData;
  const headers = isFormData ? (options.headers || {}) : { 'Content-Type': 'application/json', ...(options.headers || {}) };
  const response = await fetch(path, { ...options, headers });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || response.statusText);
  }
  return response.status === 204 ? null : response.json();
}

function updateClock() {
  DOM.systemClock.textContent = new Date().toLocaleTimeString('fr-FR', { hour12: false });
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
      togglePlayPause();
      break;
    case 'Escape':
      e.preventDefault();
      ensureLiveActionAllowed('Stop playback').then((allowed) => {
        if (allowed) api('/api/transport/stop', { method: 'POST' }).catch(console.error);
      });
      break;
    case 'Enter':
      e.preventDefault();
      ensureLiveActionAllowed('Cut to black').then((allowed) => {
        if (allowed) api('/api/system/black', { method: 'POST' }).catch(console.error);
      });
      break;
    case 'ArrowLeft':
      e.preventDefault();
      playAdjacentClip(-1);
      break;
    case 'ArrowRight':
      e.preventDefault();
      playAdjacentClip(1);
      break;
  }
});

function getSelectedClip() {
  return state.snapshot?.clips?.find((clip) => clip.deck_id === state.selectedClipId) || null;
}

function currentPlaylistId() {
  return Number(DOM.playlistSelect.value || state.snapshot?.playlist?.playlist?.id || 0);
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
    const clipId = state.snapshot.transport.clip_id || state.selectedClipId || state.snapshot.playlist?.items?.[0]?.clip_id || 1;
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

function filteredClips() {
  const clips = state.snapshot?.clips || [];
  const folder = DOM.folderFilter.value || 'All';
  if (folder === 'All') return clips;
  return clips.filter((clip) => clip.folder === folder);
}

function closeAppDialog(result) {
  if (DOM.appDialogBackdrop.hidden) return;
  const resolver = state.dialogResolver;
  state.dialogResolver = null;
  DOM.appDialogBackdrop.hidden = true;
  DOM.appDialogInput.hidden = true;
  DOM.appDialogSelect.hidden = true;
  DOM.appDialogInput.value = '';
  DOM.appDialogSelect.innerHTML = '';
  if (resolver) resolver(result);
}

function submitAppDialog() {
  if (!DOM.appDialogSelect.hidden) {
    closeAppDialog(DOM.appDialogSelect.value);
    return;
  }
  if (DOM.appDialogInput.hidden) {
    closeAppDialog(true);
    return;
  }
  closeAppDialog(DOM.appDialogInput.value);
}

function openAppDialog({
  title,
  message,
  confirmLabel = 'CONFIRM',
  cancelLabel = 'CANCEL',
  inputValue = '',
  showInput = false,
  selectOptions = [],
  selectValue = '',
  showSelect = false,
  showCancel = true,
}) {
  if (state.dialogResolver) {
    closeAppDialog(null);
  }
  DOM.appDialogTitle.textContent = title;
  DOM.appDialogMessage.textContent = message;
  DOM.appDialogInput.hidden = !showInput;
  DOM.appDialogInput.value = inputValue;
  DOM.appDialogSelect.hidden = !showSelect;
  DOM.appDialogSelect.innerHTML = '';
  if (showSelect) {
    selectOptions.forEach((optionValue) => {
      const option = document.createElement('option');
      option.value = optionValue;
      option.textContent = optionValue;
      DOM.appDialogSelect.appendChild(option);
    });
    if (selectValue && selectOptions.includes(selectValue)) {
      DOM.appDialogSelect.value = selectValue;
    } else if (selectOptions.length) {
      DOM.appDialogSelect.value = selectOptions[0];
    }
  }
  DOM.btnAppDialogConfirm.textContent = confirmLabel;
  DOM.btnAppDialogCancel.textContent = cancelLabel;
  DOM.btnAppDialogCancel.hidden = !showCancel;
  DOM.appDialogBackdrop.hidden = false;
  setTimeout(() => {
    if (showInput) {
      DOM.appDialogInput.focus();
      DOM.appDialogInput.select();
    } else if (showSelect) {
      DOM.appDialogSelect.focus();
    } else {
      DOM.btnAppDialogConfirm.focus();
    }
  }, 0);
  return new Promise((resolve) => {
    state.dialogResolver = resolve;
  });
}

async function requestText(options) {
  const value = await openAppDialog({ ...options, showInput: true });
  const normalized = typeof value === 'string' ? value.trim() : '';
  return normalized || null;
}

async function requestSelect(options) {
  const value = await openAppDialog({ ...options, showSelect: true });
  const normalized = typeof value === 'string' ? value.trim() : '';
  return normalized || null;
}

async function requestConfirm(options) {
  return Boolean(await openAppDialog(options));
}

async function showNotice(title, message) {
  await openAppDialog({
    title,
    message,
    confirmLabel: 'OK',
    showCancel: false,
  });
}

function closePreviewModal() {
  DOM.previewVideo.pause();
  DOM.previewModal.hidden = true;
}

function closeSettingsModal() {
  DOM.settingsModal.hidden = true;
}

function openSettingsModal() {
  DOM.settingsModal.hidden = false;
}

function renderUpdateStatus(update) {
  state.updateStatus = update || null;
  if (!update) {
    DOM.updateMeta.textContent = 'Update status unavailable.';
    DOM.btnRunUpdate.disabled = true;
    DOM.btnRunUpdate.textContent = 'UPDATE NOW';
    DOM.btnRunUpdate.classList.remove('active');
    return;
  }

  const lines = [
    `Platform: ${(update.platform || 'unknown').toUpperCase()} | Mode: ${(update.install_mode || 'manual').toUpperCase()}`,
    `Branch: ${update.branch || 'unknown'} | Local: ${update.current_commit || 'n/a'} | Remote: ${update.remote_commit || 'n/a'}`,
    `Status: ${(update.phase || 'idle').toUpperCase()} | ${update.message || 'Ready'}`,
  ];
  if (update.restart_target === 'raspberry_pi') {
    lines.push('Update action: RASPBERRY PI REBOOT');
  } else if (update.restart_target === 'deckpilot') {
    lines.push('Update action: DECKPILOT RESTART ONLY');
  } else {
    lines.push('Update action: AUTOMATIC DECISION DURING UPDATE');
  }
  if (update.restart_notice) {
    lines.push(`Restart policy: ${update.restart_notice}`);
  }
  if (update.restart_reason) {
    lines.push(`Reason: ${update.restart_reason}`);
  }
  if (update.finished_at) {
    lines.push(`Last run: ${formatDateTime(update.finished_at)}`);
  }
  if (update.error) {
    lines.push(`Error: ${update.error}`);
  }
  if (!update.can_update && update.reason) {
    lines.push(`Info: ${update.reason}`);
  }
  DOM.updateMeta.textContent = lines.join('\n');

  const busy = ['running', 'restarting', 'rebooting'].includes(update.phase);
  DOM.btnRunUpdate.disabled = busy || !update.can_update;
  DOM.btnRunUpdate.textContent = busy ? 'UPDATING...' : 'UPDATE NOW';
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
  DOM.healthOutput.textContent = health.selected_output?.label || 'DEFAULT';
  DOM.healthStorage.textContent = formatBytes(health.storage_free_bytes);
  DOM.healthRemote.textContent = health.remote_enabled ? 'ENABLED' : 'DISABLED';

  const lines = [
    `Clips: ${health.clip_count || 0} | Controllers: ${health.connected_controllers || 0}`,
    `Safe mode: ${effectiveSafety.safe_mode_enabled ? 'ON' : 'OFF'} | Armed: ${effectiveSafety.live_controls_armed ? `${effectiveSafety.armed_seconds_remaining || 0}s` : 'NO'}`,
  ];
  if (health.clips_last_synced_at) {
    lines.push(`Clip sync: ${formatDateTime(health.clips_last_synced_at)}`);
  }
  if (health.last_error) {
    lines.push(`Last error: ${health.last_error}`);
  } else if (health.player_error) {
    lines.push(`Player error: ${health.player_error}`);
  }
  DOM.healthMeta.textContent = lines.join('\n');

  DOM.btnToggleSafeMode.textContent = effectiveSafety.safe_mode_enabled ? 'SAFE MODE ON' : 'SAFE MODE OFF';
  DOM.btnToggleSafeMode.classList.toggle('active', effectiveSafety.safe_mode_enabled);
  DOM.btnArmLive.textContent = effectiveSafety.live_controls_armed ? `ARMED ${effectiveSafety.armed_seconds_remaining || 0}s` : 'ARM LIVE';
  DOM.btnArmLive.classList.toggle('active', effectiveSafety.live_controls_armed);
}

function applySafetyState(safety) {
  if (!safety) return;
  if (!state.snapshot) state.snapshot = {};
  state.snapshot.safety = safety;
  renderHealth(state.snapshot.health, safety);
}

function liveActionBlocked() {
  const safety = state.snapshot?.safety;
  return Boolean(safety?.safe_mode_enabled && !safety?.live_controls_armed);
}

async function ensureLiveActionAllowed(actionLabel) {
  if (!liveActionBlocked()) return true;
  await showNotice('Safe Mode', `${actionLabel} is locked while Safe Mode is enabled. Click ARM LIVE first.`);
  return false;
}

function stopUpdatePolling() {
  if (!state.updatePollTimer) return;
  clearInterval(state.updatePollTimer);
  state.updatePollTimer = null;
}

function startUpdatePolling() {
  if (state.updatePollTimer) return;
  const poll = async () => {
    try {
      const update = await api('/api/system/update');
      renderUpdateStatus(update);
      if (!['running', 'restarting', 'rebooting'].includes(update.phase)) {
        stopUpdatePolling();
        await refresh();
      }
    } catch (error) {
      DOM.updateMeta.textContent = 'Updating DeckPilot...\nWaiting for the service restart or Raspberry Pi reboot...';
    }
  };
  state.updatePollTimer = setInterval(poll, 2000);
  poll();
}

function setLogsVisible(enabled) {
  state.logsVisible = enabled;
  DOM.logsPanel.hidden = !enabled;
  DOM.btnToggleLogs.classList.toggle('active', enabled);
  DOM.btnToggleLogs.textContent = enabled ? 'LOGS ON' : 'LOGS OFF';
  DOM.panelRight.classList.toggle('logs-hidden', !enabled);
  if (enabled && state.snapshot?.logs) {
    const logText = state.snapshot.logs.slice(-80).map((entry) => `[${entry.created_at.split('T')[1].substring(0, 8)}] ${entry.message}`).join('\n');
    DOM.terminalLogs.textContent = logText;
    DOM.terminalLogs.scrollTop = DOM.terminalLogs.scrollHeight;
  }
}

function openPreviewModal(clipId) {
  state.selectedClipId = clipId;
  renderPreview();
  DOM.previewModal.hidden = false;
  DOM.previewVideo.currentTime = 0;
}

async function playPlaylist() {
  const loop = Boolean(state.snapshot?.transport?.playlist_loop);
  await api('/api/playlists/play', {
    method: 'POST',
    body: JSON.stringify({ loop })
  });
}

async function playPlaylistFromSelection() {
  const playlistId = currentPlaylistId();
  if (!playlistId) return;
  await api(`/api/playlists/${playlistId}/play-from`, {
    method: 'POST',
    body: JSON.stringify({
      position: state.selectedPlaylistPosition || 1,
      loop: Boolean(state.snapshot?.transport?.playlist_loop)
    })
  });
}

async function playNextPlaylistSelection() {
  const playlistId = currentPlaylistId();
  if (!playlistId) return;
  await api(`/api/playlists/${playlistId}/next`, { method: 'POST' });
}

async function clearCurrentPlaylist() {
  const playlistId = currentPlaylistId();
  if (!playlistId) return;
  const confirmed = await requestConfirm({
    title: 'Clear Playlist',
    message: 'Remove every item from the active playlist?',
    confirmLabel: 'CLEAR'
  });
  if (!confirmed) return;
  await api(`/api/playlists/${playlistId}/items`, { method: 'DELETE' });
  state.selectedPlaylistPosition = 1;
  await refresh();
}

function renderState(snapshot) {
  state.snapshot = snapshot;
  const { transport, clips, connections, logs, audio, outputs, playlist, network, health, safety } = snapshot;
  if (!state.selectedClipId && clips.length) {
    state.selectedClipId = clips[0].deck_id;
  }

  DOM.liveFormat.textContent = transport.video_format;
  if (snapshot.app_name) {
    DOM.appName.textContent = String(snapshot.app_name).toUpperCase();
  }
  const clients = connections.clients || [];
  if (clients.length) {
    DOM.atemStatus.classList.add('connected');
    DOM.atemStatus.querySelector('span').textContent = `${clients.length} CTRL CONN.`;
  } else {
    DOM.atemStatus.classList.remove('connected');
    DOM.atemStatus.querySelector('span').textContent = 'ATEM OFFLINE';
  }

  const isPlaying = transport.status === 'play';
  DOM.tallyBar.textContent = isPlaying ? 'ON AIR' : 'OFF AIR';
  DOM.tallyBar.className = `tally-indicator ${isPlaying ? 'live' : ''}`;
  DOM.iconPlay.style.display = isPlaying ? 'none' : 'block';
  DOM.iconPause.style.display = isPlaying ? 'block' : 'none';
  DOM.btnPlay.className = `hw-btn play-btn ${isPlaying ? 'active' : ''}`;

  DOM.liveTimecode.textContent = transport.display_timecode.substring(0, 8);
  DOM.liveRemaining.textContent = formatClock(transport.remaining_seconds);
  DOM.liveDuration.textContent = formatClock(transport.total_seconds);
  const currentClip = clips.find((clip) => clip.deck_id === transport.clip_id);
  DOM.liveClipName.textContent = currentClip ? currentClip.name : 'NO CLIP LOADED';
  const progress = transport.total_seconds > 0 ? (transport.elapsed_seconds / transport.total_seconds) * 100 : 0;
  DOM.liveProgress.style.width = `${progress}%`;

  if (document.activeElement !== DOM.configFormat) DOM.configFormat.value = transport.video_format;
  if (document.activeElement !== DOM.configVolume) DOM.configVolume.value = audio.volume;
  DOM.volumeValue.textContent = `${audio.volume}%`;
  DOM.btnMute.classList.toggle('muted', Boolean(audio.muted));
  DOM.btnPlayPlaylist.classList.toggle('active', Boolean(transport.playlist_mode && transport.status === 'play'));
  DOM.btnLoopPlaylist.classList.toggle('active', Boolean(transport.playlist_loop));
  DOM.btnLoopPlaylist.textContent = transport.playlist_loop ? 'LOOP ON' : 'LOOP';
  if (network?.hyperdeck_target) {
    DOM.networkValue.textContent = network.hyperdeck_target;
  } else {
    DOM.networkValue.textContent = `${location.hostname}:9993`;
  }

  renderOutputs(outputs || []);
  renderFolders();
  renderMediaToolbar();
  renderPlaylists();
  renderPlaylist(playlist || { playlist: null, items: [] }, transport.clip_id);
  renderMediaGrid(filteredClips(), transport.clip_id, transport.status);
  renderPreview();
  renderHealth(health, safety);
  setLogsVisible(state.logsVisible);

  const logText = (logs || []).slice(-80).map((entry) => `[${entry.created_at.split('T')[1].substring(0, 8)}] ${entry.message}`).join('\n');
  if (state.logsVisible) {
    DOM.terminalLogs.textContent = logText;
    DOM.terminalLogs.scrollTop = DOM.terminalLogs.scrollHeight;
  }
}

function renderOutputs(outputs) {
  const previous = DOM.configOutput.value;
  DOM.configOutput.innerHTML = '';
  outputs.forEach((output) => {
    const option = document.createElement('option');
    option.value = output.id;
    option.textContent = output.label;
    option.selected = output.selected;
    DOM.configOutput.appendChild(option);
  });
  if (previous && outputs.some((output) => output.id === previous)) {
    DOM.configOutput.value = previous;
  }
}

function renderFolders() {
  const previous = DOM.folderFilter.value || 'All';
  DOM.folderFilter.innerHTML = '';
  const values = ['All', ...state.folders.filter((folder) => folder !== 'All')];
  values.forEach((folder) => {
    const option = document.createElement('option');
    option.value = folder;
    option.textContent = folder;
    DOM.folderFilter.appendChild(option);
  });
  DOM.folderFilter.value = values.includes(previous) ? previous : 'All';
}

function renderMediaToolbar() {
  const currentFolder = DOM.folderFilter.value || 'All';
  const isAll = currentFolder === 'All';
  DOM.btnBackAll.hidden = isAll;
  DOM.btnToggleMediaView.hidden = isAll;
  DOM.btnToggleMediaView.textContent = state.mediaView === 'grid' ? 'LIST' : 'GRID';
  DOM.btnToggleMediaView.classList.toggle('active', state.mediaView === 'list');
}

function renderPlaylists() {
  const previous = DOM.playlistSelect.value;
  DOM.playlistSelect.innerHTML = '';
  state.playlists.forEach((playlist) => {
    const option = document.createElement('option');
    option.value = playlist.id;
    option.textContent = playlist.is_active ? `${playlist.name} *` : playlist.name;
    DOM.playlistSelect.appendChild(option);
  });
  const active = state.snapshot?.playlist?.playlist?.id;
  if (previous && state.playlists.some((playlist) => String(playlist.id) === previous)) {
    DOM.playlistSelect.value = previous;
  } else if (active) {
    DOM.playlistSelect.value = String(active);
  }
}

function renderPlaylist(playlistPayload, activeClipId) {
  const items = playlistPayload.items || [];
  if (!items.some((item) => item.position === state.selectedPlaylistPosition)) {
    state.selectedPlaylistPosition = items[0]?.position || 1;
  }
  DOM.playlistCount.textContent = `${items.length} items`;
  DOM.playlistItems.innerHTML = '';
  items.forEach((item) => {
    const node = Templates.playlistItem.content.firstElementChild.cloneNode(true);
    node.dataset.clipId = item.clip_id;
    node.dataset.position = item.position;
    node.querySelector('.playlist-item-pos').textContent = String(item.position).padStart(2, '0');
    node.querySelector('.playlist-item-name').textContent = item.clip_name;
    node.querySelector('.playlist-item-time').textContent = item.duration_timecode.substring(0, 8);
    if (item.clip_id === activeClipId) node.classList.add('active');
    if (item.position === state.selectedPlaylistPosition) node.classList.add('selected');
    node.addEventListener('click', async () => {
      state.selectedPlaylistPosition = item.position;
      state.selectedClipId = item.clip_id;
      renderPlaylist(playlistPayload, activeClipId);
      renderPreview();
      await api(`/api/clips/${item.clip_id}/goto`, { method: 'POST' });
    });
    node.addEventListener('dblclick', async () => {
      const playlistId = playlistPayload.playlist?.id;
      if (!playlistId) return;
      state.selectedPlaylistPosition = item.position;
      await api(`/api/playlists/${playlistId}/play-from`, {
        method: 'POST',
        body: JSON.stringify({ position: item.position })
      });
    });
    node.querySelector('.playlist-item-remove').addEventListener('click', async (event) => {
      event.stopPropagation();
      const playlistId = playlistPayload.playlist?.id;
      if (!playlistId) return;
      await api(`/api/playlists/${playlistId}/items/${item.position}`, { method: 'DELETE' });
      await refresh();
    });
    DOM.playlistItems.appendChild(node);
  });
}

function renderPreview() {
  const clip = getSelectedClip();
  if (!clip) {
    DOM.previewTitle.textContent = 'Aucun clip selectionne';
    DOM.previewSubtitle.textContent = 'Selectionne un clip pour le previsualiser dans le navigateur.';
    DOM.previewVideo.removeAttribute('src');
    DOM.previewVideo.load();
    return;
  }
  DOM.previewTitle.textContent = clip.name;
  const orientation = clip.is_vertical ? 'VERTICAL FILL' : 'STANDARD';
  DOM.previewSubtitle.textContent = `${clip.folder} | ${clip.duration_timecode.substring(0, 8)} | ${clip.framerate}fps | ${clip.codec} | ${orientation}`;
  const nextSrc = `/media/${encodeURIComponent(clip.filename)}`;
  if (DOM.previewVideo.getAttribute('src') !== nextSrc) {
    DOM.previewVideo.src = nextSrc;
    DOM.previewVideo.load();
  }
}

function renderMediaGrid(clips, activeClipId, status) {
  DOM.mediaGrid.innerHTML = '';
  const currentFolder = DOM.folderFilter.value || 'All';
  if (currentFolder === 'All') {
    DOM.mediaGrid.classList.remove('list-view');
    renderFolderCards(clips);
    return;
  }
  DOM.mediaGrid.classList.toggle('list-view', state.mediaView === 'list');
  clips.forEach((clip) => {
    const node = Templates.mediaItem.content.firstElementChild.cloneNode(true);
    node.dataset.deckId = clip.deck_id;
    node.querySelector('.media-id').textContent = String(clip.deck_id).padStart(2, '0');
    const img = node.querySelector('.thumb-img');
    if (clip.thumbnail_path) {
      img.src = `/thumbs/${clip.thumbnail_path.split('/').pop()}`;
    } else {
      img.style.display = 'none';
    }
    node.querySelector('.media-title').textContent = clip.name;
    node.querySelector('.media-meta').textContent = `${clip.folder} | ${clip.duration_timecode.substring(0, 8)} | ${clip.framerate}fps${clip.is_vertical ? ' | vertical' : ''}`;
    if (clip.loop_enabled) node.querySelector('.ctrl-btn.loop').classList.add('active-loop');
    if (clip.deck_id === activeClipId) {
      node.classList.add('active');
      if (status === 'play') node.querySelector('.status-overlay').style.display = 'flex';
    }
    if (clip.deck_id === state.selectedClipId) {
      node.style.boxShadow = 'inset 0 0 0 2px var(--color-accent)';
    }
    node.addEventListener('click', () => {
      state.selectedClipId = clip.deck_id;
      renderMediaGrid(filteredClips(), state.snapshot.transport.clip_id, state.snapshot.transport.status);
      renderPreview();
    });
    node.addEventListener('dragstart', () => {
      state.dragClipId = clip.deck_id;
      node.style.opacity = '0.4';
    });
    node.addEventListener('dragend', () => {
      node.style.opacity = '1';
    });
    node.addEventListener('dragover', (e) => {
      e.preventDefault();
      node.style.transform = 'scale(1.02)';
    });
    node.addEventListener('dragleave', () => {
      node.style.transform = 'none';
    });
    node.addEventListener('drop', async (e) => {
      e.preventDefault();
      node.style.transform = 'none';
      const from = state.dragClipId;
      const to = clip.deck_id;
      if (!from || from === to) return;
      const order = filteredClips().map((item) => item.deck_id);
      order.splice(order.indexOf(from), 1);
      order.splice(order.indexOf(to), 0, from);
      await api('/api/clips/reorder', { method: 'POST', body: JSON.stringify({ deck_ids: order }) });
      await refresh();
    });
    node.querySelectorAll('.ctrl-btn').forEach((button) => {
      button.addEventListener('click', async (event) => {
        event.stopPropagation();
        await handleClipAction(clip, button.dataset.action);
      });
    });
    node.addEventListener('dblclick', async () => {
      await api(`/api/clips/${clip.deck_id}/play`, { method: 'POST' });
    });
    DOM.mediaGrid.appendChild(node);
  });
}

function renderFolderCards(clips) {
  const folders = state.folders.filter((folder) => folder !== 'All');
  folders.forEach((folder) => {
    const folderClips = clips.filter((clip) => clip.folder === folder);
    const card = document.createElement('button');
    card.type = 'button';
    card.className = 'folder-card';
    card.dataset.folder = folder;

    const preview = document.createElement('div');
    preview.className = 'folder-card-preview';

    const thumbClips = folderClips.slice(0, 4);
    if (thumbClips.length) {
      thumbClips.forEach((clip) => {
        const thumb = document.createElement('div');
        thumb.className = 'folder-card-thumb';
        if (clip.thumbnail_path) {
          thumb.style.backgroundImage = `url(/thumbs/${clip.thumbnail_path.split('/').pop()})`;
        } else {
          thumb.classList.add('empty');
          thumb.textContent = clip.name.slice(0, 1).toUpperCase();
        }
        preview.appendChild(thumb);
      });
    } else {
      const emptyState = document.createElement('div');
      emptyState.className = 'folder-card-empty';
      emptyState.textContent = 'EMPTY';
      preview.appendChild(emptyState);
    }

    const info = document.createElement('div');
    info.className = 'folder-card-info';

    const title = document.createElement('div');
    title.className = 'folder-card-title';
    title.textContent = folder;

    const meta = document.createElement('div');
    meta.className = 'folder-card-meta';
    meta.textContent = `${folderClips.length} clip${folderClips.length > 1 ? 's' : ''}`;

    info.append(title, meta);
    card.append(preview, info);
    card.addEventListener('click', () => {
      DOM.folderFilter.value = folder;
      renderMediaToolbar();
      renderMediaGrid(filteredClips(), state.snapshot.transport.clip_id, state.snapshot.transport.status);
    });
    DOM.mediaGrid.appendChild(card);
  });
}

async function handleClipAction(clip, action) {
  if (action === 'play') {
    await api(`/api/clips/${clip.deck_id}/play`, { method: 'POST' });
  } else if (action === 'preview') {
    openPreviewModal(clip.deck_id);
    return;
  } else if (action === 'loop') {
    await api(`/api/clips/${clip.deck_id}/loop`, { method: 'PATCH', body: JSON.stringify({ enabled: !clip.loop_enabled }) });
  } else if (action === 'rename') {
    const name = await requestText({
      title: 'Rename Clip',
      message: 'Nouveau nom du clip :',
      inputValue: clip.name,
      confirmLabel: 'SAVE'
    });
    if (name) await api(`/api/clips/${clip.deck_id}/rename`, { method: 'PATCH', body: JSON.stringify({ name }) });
  } else if (action === 'delete') {
    if (!await ensureLiveActionAllowed('Clip deletion')) return;
    const confirmed = await requestConfirm({
      title: 'Delete Clip',
      message: `Supprimer définitivement ${clip.name} ?`,
      confirmLabel: 'DELETE'
    });
    if (confirmed) {
      await api(`/api/clips/${clip.deck_id}`, { method: 'DELETE' });
    }
  }
  await refresh();
}

DOM.dropzone.addEventListener('dragover', (e) => {
  e.preventDefault();
  DOM.dropzone.classList.add('dragover');
});
DOM.dropzone.addEventListener('dragleave', () => DOM.dropzone.classList.remove('dragover'));
DOM.dropzone.addEventListener('drop', async (e) => {
  e.preventDefault();
  DOM.dropzone.classList.remove('dragover');
  await uploadFiles(e.dataTransfer.files);
});
DOM.fileInput.addEventListener('change', async () => uploadFiles(DOM.fileInput.files));

async function uploadFiles(fileList) {
  if (!fileList || !fileList.length) return;
  const formData = new FormData();
  [...fileList].forEach((file) => formData.append('files', file));
  DOM.uploadWrapper.style.display = 'flex';
  DOM.uploadProgress.style.width = '10%';
  try {
    await api('/api/upload', { method: 'POST', body: formData });
    DOM.uploadProgress.style.width = '100%';
  } catch (error) {
    await showNotice('Upload Error', error.message || "Échec de l'upload.");
  } finally {
    setTimeout(() => {
      DOM.uploadWrapper.style.display = 'none';
      DOM.uploadProgress.style.width = '0%';
    }, 800);
    await refresh();
  }
}

DOM.btnPlay.addEventListener('click', togglePlayPause);
DOM.btnStop.addEventListener('click', async () => {
  if (!await ensureLiveActionAllowed('Stop playback')) return;
  await api('/api/transport/stop', { method: 'POST' });
});
DOM.btnPrev.addEventListener('click', () => playAdjacentClip(-1));
DOM.btnNext.addEventListener('click', () => playAdjacentClip(1));
DOM.btnBlack.addEventListener('click', async () => {
  if (!await ensureLiveActionAllowed('Cut to black')) return;
  await api('/api/system/black', { method: 'POST' });
});
DOM.btnRefreshMedia.addEventListener('click', refresh);
DOM.btnToggleLogs.addEventListener('click', () => setLogsVisible(!state.logsVisible));
DOM.btnOpenSettings.addEventListener('click', openSettingsModal);
DOM.btnToggleSafeMode.addEventListener('click', async () => {
  const enabled = !Boolean(state.snapshot?.safety?.safe_mode_enabled);
  const response = await api('/api/system/safe-mode', {
    method: 'POST',
    body: JSON.stringify({ enabled })
  });
  applySafetyState(response.safety);
});
DOM.btnArmLive.addEventListener('click', async () => {
  const response = await api('/api/system/arm-controls', {
    method: 'POST',
    body: JSON.stringify({ seconds: 12 })
  });
  applySafetyState(response.safety);
});
DOM.btnRunUpdate.addEventListener('click', async () => {
  const updateStatus = state.updateStatus;
  let updateMessage = 'DeckPilot will pull the latest version and restart automatically if needed. Continue?';
  if (updateStatus?.restart_target === 'raspberry_pi') {
    if (updateStatus.automatic_reboot_available) {
      updateMessage = 'Cette mise a jour redemarrera automatiquement le Raspberry Pi car elle modifie des composants appliance. Continuer ?';
    } else {
      updateMessage = 'Cette mise a jour necessitera un redemarrage du Raspberry Pi. DeckPilot se mettra a jour maintenant et indiquera ensuite qu un reboot manuel reste requis. Continuer ?';
    }
  } else if (updateStatus?.restart_target === 'deckpilot') {
    updateMessage = 'Cette mise a jour redemarrera seulement DeckPilot. Un reboot du Raspberry Pi nest pas obligatoire. Continuer ?';
  } else if (updateStatus?.restart_notice) {
    updateMessage = `${updateStatus.restart_notice} Continuer ?`;
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
});
DOM.configFormat.addEventListener('change', async (e) => {
  if (!await ensureLiveActionAllowed('Video format change')) {
    DOM.configFormat.value = state.snapshot?.transport?.video_format || DOM.configFormat.value;
    return;
  }
  await api('/api/system/video-format', { method: 'POST', body: JSON.stringify({ video_format: e.target.value }) });
});
DOM.configOutput.addEventListener('change', async (e) => {
  if (!await ensureLiveActionAllowed('Video output change')) {
    renderOutputs(state.snapshot?.outputs || []);
    return;
  }
  await api('/api/system/output', { method: 'POST', body: JSON.stringify({ output_id: e.target.value }) });
});
DOM.configVolume.addEventListener('input', async (e) => {
  await api('/api/audio/volume', { method: 'POST', body: JSON.stringify({ volume: Number(e.target.value) }) });
});
DOM.btnMute.addEventListener('click', async () => {
  const muted = DOM.btnMute.classList.contains('muted');
  await api('/api/audio/mute', { method: 'POST', body: JSON.stringify({ muted: !muted }) });
});
DOM.folderFilter.addEventListener('change', () => {
  renderMediaToolbar();
  renderMediaGrid(filteredClips(), state.snapshot.transport.clip_id, state.snapshot.transport.status);
});
DOM.btnBackAll.addEventListener('click', () => {
  DOM.folderFilter.value = 'All';
  renderMediaToolbar();
  renderMediaGrid(filteredClips(), state.snapshot.transport.clip_id, state.snapshot.transport.status);
});
DOM.btnToggleMediaView.addEventListener('click', () => {
  state.mediaView = state.mediaView === 'grid' ? 'list' : 'grid';
  renderMediaToolbar();
  renderMediaGrid(filteredClips(), state.snapshot.transport.clip_id, state.snapshot.transport.status);
});
DOM.btnNewFolder.addEventListener('click', async () => {
  const name = await requestText({
    title: 'New Folder',
    message: 'Nom du dossier media :',
    confirmLabel: 'CREATE'
  });
  if (!name) return;
  await api('/api/media/folders', { method: 'POST', body: JSON.stringify({ name }) });
  await refresh();
  DOM.folderFilter.value = name;
  renderMediaGrid(filteredClips(), state.snapshot.transport.clip_id, state.snapshot.transport.status);
});
DOM.btnMoveFolder.addEventListener('click', async () => {
  const clip = getSelectedClip();
  if (!clip) {
    await showNotice('Move Clip', 'Selectionne un clip avant de changer son dossier.');
    return;
  }
  const folderOptions = state.folders.filter((folder) => folder !== 'All');
  const targetFolder = await requestSelect({
    title: 'Move Clip',
    message: `Deplacer "${clip.name}" vers :`,
    selectOptions: folderOptions,
    selectValue: clip.folder,
    confirmLabel: 'MOVE'
  });
  if (!targetFolder) return;
  await api(`/api/clips/${clip.deck_id}/folder`, { method: 'PATCH', body: JSON.stringify({ folder: targetFolder }) });
  await refresh();
  DOM.folderFilter.value = targetFolder;
  renderMediaGrid(filteredClips(), state.snapshot.transport.clip_id, state.snapshot.transport.status);
});
DOM.previewModal.addEventListener('click', (event) => {
  if (event.target === DOM.previewModal) {
    closePreviewModal();
  }
});
DOM.settingsModal.addEventListener('click', (event) => {
  if (event.target === DOM.settingsModal) {
    closeSettingsModal();
  }
});
DOM.btnPreviewClose.addEventListener('click', closePreviewModal);
DOM.btnSettingsClose.addEventListener('click', closeSettingsModal);
DOM.btnPreviewPlay.addEventListener('click', async () => {
  const clip = getSelectedClip();
  if (!clip) return;
  await api(`/api/clips/${clip.deck_id}/play`, { method: 'POST' });
  closePreviewModal();
});
DOM.btnPreviewCue.addEventListener('click', async () => {
  const clip = getSelectedClip();
  if (!clip) return;
  await api(`/api/clips/${clip.deck_id}/goto`, { method: 'POST' });
});
DOM.btnPreviewAddPlaylist.addEventListener('click', async () => addSelectedClipToPlaylist());
DOM.btnNewPlaylist.addEventListener('click', async () => {
  const name = await requestText({
    title: 'New Playlist',
    message: 'Nom de la playlist :',
    confirmLabel: 'CREATE'
  });
  if (!name) return;
  await api('/api/playlists', {
    method: 'POST',
    body: JSON.stringify({ name, clip_ids: [], activate: false })
  });
  await refresh();
});
DOM.btnActivatePlaylist.addEventListener('click', async () => {
  const playlistId = currentPlaylistId();
  if (!playlistId) return;
  await api(`/api/playlists/${playlistId}/activate`, { method: 'POST' });
  await refresh();
});
DOM.btnPlayPlaylist.addEventListener('click', async () => {
  await playPlaylist();
});
DOM.btnPlayPlaylistFrom.addEventListener('click', async () => {
  await playPlaylistFromSelection();
});
DOM.btnNextPlaylist.addEventListener('click', async () => {
  await playNextPlaylistSelection();
});
DOM.btnLoopPlaylist.addEventListener('click', async () => {
  const enabled = !Boolean(state.snapshot?.transport?.playlist_loop);
  await api('/api/playlists/loop', {
    method: 'POST',
    body: JSON.stringify({ enabled })
  });
});
DOM.btnAddSelectedPlaylist.addEventListener('click', async () => addSelectedClipToPlaylist());
DOM.btnClearPlaylist.addEventListener('click', async () => {
  await clearCurrentPlaylist();
});
DOM.appDialogBackdrop.addEventListener('click', (event) => {
  if (event.target === DOM.appDialogBackdrop) {
    closeAppDialog(null);
  }
});
DOM.btnAppDialogClose.addEventListener('click', () => closeAppDialog(null));
DOM.btnAppDialogCancel.addEventListener('click', () => closeAppDialog(null));
DOM.btnAppDialogConfirm.addEventListener('click', submitAppDialog);

async function addSelectedClipToPlaylist() {
  const clip = getSelectedClip();
  const playlistId = currentPlaylistId();
  if (!clip || !playlistId) return;
  await api(`/api/playlists/${playlistId}/items`, {
    method: 'POST',
    body: JSON.stringify({ clip_id: clip.deck_id })
  });
  await refresh();
}

async function refresh() {
  const [snapshot, folderPayload, playlistPayload, updatePayload] = await Promise.all([
    api('/api/state'),
    api('/api/media/folders'),
    api('/api/playlists'),
    api('/api/system/update')
  ]);
  state.folders = folderPayload.folders || [];
  state.playlists = playlistPayload.playlists || [];
  snapshot.playlist = playlistPayload.active || snapshot.playlist;
  renderState(snapshot);
  renderUpdateStatus(updatePayload);
  if (['running', 'restarting'].includes(updatePayload.phase)) {
    startUpdatePolling();
  }
}

function setupWebSocket() {
  const protocol = location.protocol === 'https:' ? 'wss' : 'ws';
  const socket = new WebSocket(`${protocol}://${location.host}/ws`);
  socket.addEventListener('message', (event) => {
    const message = JSON.parse(event.data);
    if (message.type === 'snapshot') {
      renderState(message.payload);
      return;
    }
    if (!state.snapshot) return;
    if (message.type === 'transport') state.snapshot.transport = message.payload;
    if (message.type === 'clips') state.snapshot.clips = message.payload.clips;
    if (message.type === 'connections') state.snapshot.connections = message.payload;
    if (message.type === 'audio') state.snapshot.audio = message.payload;
    if (message.type === 'playlist') state.snapshot.playlist = message.payload;
    if (message.type === 'outputs') state.snapshot.outputs = message.payload.outputs;
    if (message.type === 'health') state.snapshot.health = message.payload;
    if (message.type === 'safety') state.snapshot.safety = message.payload;
    if (message.type === 'log') {
      state.snapshot.logs = [...(state.snapshot.logs || []), message.payload].slice(-200);
    }
    renderState(state.snapshot);
  });
  socket.addEventListener('close', () => setTimeout(setupWebSocket, 2000));
}

refresh().then(setupWebSocket);
