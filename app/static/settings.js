// Settings panel: the settings modal, live config editor, output / display /
// audio device pickers, storage devices, volume, library export/import, and
// the self-update flow.

import { api, formatBytes, formatDateTime } from './util.js';
import { DOM } from './dom.js';
import { applyStateNow, state } from './store.js';
import { bindAsync, ensureLiveActionAllowed, requestConfirm, showNotice } from './dialogs.js';
import { refresh } from './app.js';

export function openSettingsModal() {
  DOM.settingsModal.hidden = false;
  void loadConfigEditor().catch((error) => console.error(error));
  void loadAudioDevices().catch((error) => console.error(error));
  void loadStorageDevices().catch((error) => console.error(error));
}

export function closeSettingsModal() {
  DOM.settingsModal.hidden = true;
}

export async function loadAudioDevices() {
  const payload = await api('/api/system/audio-devices');
  renderAudioDevices(payload.devices || []);
}

export function renderAudioDevices(devices) {
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

export async function loadStorageDevices() {
  const payload = await api('/api/system/storage-devices');
  renderStorageDevices(payload.devices || []);
}

export function renderStorageDevices(devices) {
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

export async function loadConfigEditor() {
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

export function renderOutputs(outputs) {
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

export function renderDisplaySettings(display) {
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

export function renderAudio(audio) {
  if (!audio) return;
  if (document.activeElement !== DOM.configVolume && state.pendingVolume === null) {
    DOM.configVolume.value = audio.volume;
  }
  DOM.volumeValue.textContent = `${state.pendingVolume ?? audio.volume}%`;
  DOM.btnMute.classList.toggle('muted', Boolean(audio.muted));
}

export function scheduleVolumeCommit(volume) {
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

export async function commitVolumeChange() {
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

export function renderUpdateStatus(update) {
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

export function stopUpdatePolling() {
  if (!state.updatePollTimer) return;
  clearTimeout(state.updatePollTimer);
  state.updatePollTimer = null;
  state.updatePollInFlight = false;
}

export function startUpdatePolling() {
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

DOM.btnOpenSettings.addEventListener('click', openSettingsModal);

DOM.settingsModal.addEventListener('click', (event) => {
  if (event.target === DOM.settingsModal) {
    closeSettingsModal();
  }
});

DOM.btnSettingsClose.addEventListener('click', closeSettingsModal);

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
