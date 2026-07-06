// Health / status panel: system health lines, safe mode and arming, the
// terminal log feed, and the connection / network indicators.

import { api, formatBytes, formatDateTime, formatEta, formatUptimeMinutes } from './util.js';
import { DOM } from './dom.js';
import { applyStateNow, state } from './store.js';
import { bindAsync } from './dialogs.js';
import { renderUploadProcessingStatus } from './media.js';

export function renderConnectionStatus(connections) {
  const clients = connections?.clients || [];
  if (clients.length) {
    DOM.atemStatus.classList.add('connected');
    DOM.atemStatus.querySelector('span').textContent = `${clients.length} CTRL CONN.`;
  } else {
    DOM.atemStatus.classList.remove('connected');
    DOM.atemStatus.querySelector('span').textContent = 'ATEM OFFLINE';
  }
}

export function renderNetwork(network) {
  const hyperdeckTarget = network?.hyperdeck_target || `${location.hostname}:9993`;
  const httpUrl = network?.http_url || location.origin;
  DOM.networkValue.textContent = hyperdeckTarget;
  DOM.connHyperdeck.textContent = hyperdeckTarget;
  DOM.connWeb.textContent = httpUrl;
  DOM.connCountdown.textContent = `${httpUrl}/countdown`;
  DOM.connHostname.textContent = network?.hostname || '--';
  DOM.connIps.textContent = (network?.ips || []).join('  ') || '--';
}

DOM.networkTarget.addEventListener('click', () => {
  DOM.connectionsModal.hidden = false;
});
DOM.networkTarget.addEventListener('keydown', (event) => {
  if (event.key === 'Enter' || event.key === ' ') DOM.connectionsModal.hidden = false;
});
DOM.btnConnectionsClose.addEventListener('click', () => {
  DOM.connectionsModal.hidden = true;
});
DOM.connectionsModal.addEventListener('click', (event) => {
  if (event.target === DOM.connectionsModal) DOM.connectionsModal.hidden = true;
});

export function renderLogs(logs) {
  if (!state.logsVisible) return;
  const logText = (logs || []).slice(-80).map((entry) => `[${entry.created_at.split('T')[1].substring(0, 8)}] ${entry.message}`).join('\n');
  DOM.terminalLogs.textContent = logText;
  DOM.terminalLogs.scrollTop = DOM.terminalLogs.scrollHeight;
}

// An ATEM polling the deck produces a log line per protocol command; batch
// the terminal rewrites instead of touching the DOM for every line.
export let logsRenderPending = false;

export function scheduleLogsRender() {
  if (logsRenderPending) return;
  logsRenderPending = true;
  window.setTimeout(() => {
    logsRenderPending = false;
    renderLogs(state.snapshot?.logs || []);
  }, 250);
}

export function setLogsVisible(enabled) {
  state.logsVisible = enabled;
  DOM.logsPanel.hidden = !enabled;
  DOM.btnToggleLogs.classList.toggle('active', enabled);
  DOM.btnToggleLogs.textContent = enabled ? 'LOGS ON' : 'LOGS OFF';
  DOM.panelRight.classList.toggle('logs-hidden', !enabled);
  if (enabled) renderLogs(state.snapshot?.logs || []);
}

export function renderHealth(health, safety) {
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

export function applySafetyState(safety) {
  if (!safety) return;
  applyStateNow(() => {
    if (!state.snapshot) state.snapshot = {};
    state.snapshot.safety = safety;
    renderHealth(state.snapshot.health, safety);
  });
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
