const state = {
  snapshot: null,
  clipIndex: new Map(),
  mediaNodeCache: new Map(),
  playlistNodeCache: new Map(),
  folderNodeCache: new Map(),
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
  updatePollInFlight: false,
  websocketReconnectTimer: null,
  volumeCommitTimer: null,
  volumeCommitInFlight: false,
  pendingVolume: null,
  uploadHideTimer: null,
  uploadProcessingActive: false,
  transportSeekValue: null,
  transportSeekDragging: false,
  mediaRenderLimit: 0,
  mediaVirtualEnabled: false,
  mediaVirtualKey: null,
  mediaVirtualCheckScheduled: false,
  playlistRenderLimit: 0,
  playlistVirtualEnabled: false,
  playlistVirtualKey: null,
  playlistVirtualCheckScheduled: false,
  websocketConnected: false,
  audioLevels: new Map(),
  audioLevelsFetching: new Set(),
  vuPeakPct: 0,
  vuPeakAt: 0,
};

const MEDIA_VIRTUALIZATION_THRESHOLD = 120;
const MEDIA_VIRTUALIZATION_BATCH = 60;
const PLAYLIST_VIRTUALIZATION_THRESHOLD = 150;
const PLAYLIST_VIRTUALIZATION_BATCH = 80;

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
  nextClipBar: document.getElementById('next-clip-bar'),
  nextClipName: document.getElementById('next-clip-name'),
  nextClipCountdown: document.getElementById('next-clip-countdown'),
  vuMeter: document.getElementById('vu-meter'),
  vuMeterFill: document.getElementById('vu-meter-fill'),
  vuMeterPeak: document.getElementById('vu-meter-peak'),
  vuDb: document.getElementById('vu-db'),
  liveClipMeta: document.getElementById('live-clip-meta'),
  padGrid: document.getElementById('pad-grid'),
  watchfolderHint: document.getElementById('watchfolder-hint'),
  liveTimecode: document.getElementById('live-timecode'),
  liveRemaining: document.getElementById('live-remaining'),
  liveDuration: document.getElementById('live-duration'),
  liveProgress: document.getElementById('live-progress'),
  liveScrubCurrent: document.getElementById('live-scrub-current'),
  liveScrubTotal: document.getElementById('live-scrub-total'),
  transportSeek: document.getElementById('transport-seek'),
  btnSeekBack: document.getElementById('btn-seek-back'),
  btnSeekForward: document.getElementById('btn-seek-forward'),
  transportSpeedLabel: document.getElementById('transport-speed-label'),
  transportSpeedButtons: document.getElementById('transport-speed-buttons'),
  scrubMarkIn: document.getElementById('scrub-mark-in'),
  scrubMarkOut: document.getElementById('scrub-mark-out'),
  btnMarkIn: document.getElementById('btn-mark-in'),
  btnMarkOut: document.getElementById('btn-mark-out'),
  btnMarkClear: document.getElementById('btn-mark-clear'),
  markInValue: document.getElementById('mark-in-value'),
  markOutValue: document.getElementById('mark-out-value'),
  markTrimValue: document.getElementById('mark-trim-value'),
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
  uploadStatus: document.getElementById('upload-status'),
  uploadProgress: document.getElementById('upload-progress'),
  btnRefreshMedia: document.getElementById('btn-refresh-media'),
  folderFilter: document.getElementById('folder-filter'),
  mediaTypeFilter: document.getElementById('media-type-filter'),
  mediaSearch: document.getElementById('media-search'),
  btnBackAll: document.getElementById('btn-back-all'),
  btnToggleMediaView: document.getElementById('btn-toggle-media-view'),
  btnNewFolder: document.getElementById('btn-new-folder'),
  btnMoveFolder: document.getElementById('btn-move-folder'),
  previewModal: document.getElementById('preview-modal'),
  previewImage: document.getElementById('preview-image'),
  previewVideo: document.getElementById('preview-video'),
  previewTitle: document.getElementById('preview-title'),
  previewSubtitle: document.getElementById('preview-subtitle'),
  btnPreviewClose: document.getElementById('btn-preview-close'),
  btnPreviewPlay: document.getElementById('btn-preview-play'),
  btnPreviewCue: document.getElementById('btn-preview-cue'),
  btnPreviewAddPlaylist: document.getElementById('btn-preview-add-playlist'),
  previewMarks: document.getElementById('preview-marks'),
  previewMarksRange: document.getElementById('preview-marks-range'),
  previewMarkInTick: document.getElementById('preview-mark-in-tick'),
  previewMarkOutTick: document.getElementById('preview-mark-out-tick'),
  previewMarksPlayhead: document.getElementById('preview-marks-playhead'),
  btnPreviewMarkIn: document.getElementById('btn-preview-mark-in'),
  btnPreviewMarkOut: document.getElementById('btn-preview-mark-out'),
  btnPreviewMarkClear: document.getElementById('btn-preview-mark-clear'),
  previewMarkInValue: document.getElementById('preview-mark-in-value'),
  previewMarkOutValue: document.getElementById('preview-mark-out-value'),
  previewMarkTrimValue: document.getElementById('preview-mark-trim-value'),
  previewStillDuration: document.getElementById('preview-still-duration'),
  previewDurationInput: document.getElementById('preview-duration-input'),
  btnPreviewDuration: document.getElementById('btn-preview-duration'),
  previewTagsValue: document.getElementById('preview-tags-value'),
  btnPreviewTags: document.getElementById('btn-preview-tags'),
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
  configCanvas: document.getElementById('config-canvas'),
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
  btnExportLibrary: document.getElementById('btn-export-library'),
  btnImportLibrary: document.getElementById('btn-import-library'),
  btnBackupDb: document.getElementById('btn-backup-db'),
  importFileInput: document.getElementById('import-file-input'),
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

function formatRemainingClock(seconds) {
  return `-${formatClock(seconds)}`;
}

function formatEta(seconds) {
  if (seconds === null || seconds === undefined) return 'ETA --';
  return `ETA ${formatClock(seconds)}`;
}

function formatUptimeMinutes(minutes) {
  const total = Math.max(0, Number(minutes || 0));
  if (total < 60) return `${total}m`;
  const hours = Math.floor(total / 60);
  if (hours < 24) return `${hours}h ${total % 60}m`;
  return `${Math.floor(hours / 24)}d ${hours % 24}h`;
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

function getErrorMessage(error, fallback = 'Unexpected error.') {
  if (error instanceof Error && error.message) return error.message;
  if (typeof error === 'string' && error.trim()) return error;
  return fallback;
}

function bindAsync(target, eventName, handler, errorTitle = 'Operation Error') {
  target.addEventListener(eventName, (event) => {
    Promise.resolve(handler(event)).catch(async (error) => {
      console.error(error);
      await showNotice(errorTitle, getErrorMessage(error));
    });
  });
}

function reindexClips(clips) {
  state.clipIndex = new Map((clips || []).map((clip) => [clip.deck_id, clip]));
}

function currentFolder() {
  return DOM.folderFilter.value || 'All';
}

function currentMediaTypeFilter() {
  return DOM.mediaTypeFilter.value || 'all';
}

function currentMediaSearchTerm() {
  return (DOM.mediaSearch.value || '').trim().toLowerCase();
}

function hasActiveMediaFilters() {
  return currentMediaTypeFilter() !== 'all' || Boolean(currentMediaSearchTerm());
}

function buildFolderClipMap(clips) {
  const folderMap = new Map();
  (clips || []).forEach((clip) => {
    if (!folderMap.has(clip.folder)) {
      folderMap.set(clip.folder, []);
    }
    folderMap.get(clip.folder).push(clip);
  });
  return folderMap;
}

function pruneNodeCache(cache, validKeys) {
  for (const key of [...cache.keys()]) {
    if (!validKeys.has(key)) {
      cache.delete(key);
    }
  }
}

function mediaVirtualDatasetKey(clips) {
  return `${currentFolder()}::${state.mediaView}::${clips.length}`;
}

function playlistVirtualDatasetKey(items, playlistId) {
  return `${playlistId || 'none'}::${items.length}`;
}

function ensureMediaRenderLimit(clips) {
  const total = clips.length;
  const datasetKey = mediaVirtualDatasetKey(clips);
  const shouldVirtualize = currentFolder() !== 'All' && total > MEDIA_VIRTUALIZATION_THRESHOLD;
  if (state.mediaVirtualKey !== datasetKey) {
    state.mediaVirtualKey = datasetKey;
    state.mediaRenderLimit = shouldVirtualize ? MEDIA_VIRTUALIZATION_BATCH : total;
  }
  state.mediaVirtualEnabled = shouldVirtualize;
  if (!shouldVirtualize) {
    state.mediaRenderLimit = total;
    return clips;
  }

  const activeClipId = state.snapshot?.transport?.clip_id;
  const priorityIndex = clips.findIndex((clip) => clip.deck_id === (activeClipId || state.selectedClipId));
  if (priorityIndex >= 0) {
    state.mediaRenderLimit = Math.max(state.mediaRenderLimit, priorityIndex + 1);
  }
  state.mediaRenderLimit = Math.min(total, Math.max(state.mediaRenderLimit, MEDIA_VIRTUALIZATION_BATCH));
  return clips.slice(0, state.mediaRenderLimit);
}

function maybeLoadMoreMedia(force = false) {
  const clips = filteredClips();
  if (!state.mediaVirtualEnabled) return false;
  if (state.mediaRenderLimit >= clips.length) return false;
  const nearBottom = DOM.dropzone.scrollTop + DOM.dropzone.clientHeight >= DOM.dropzone.scrollHeight - 600;
  if (!force && !nearBottom) return false;
  const nextLimit = Math.min(clips.length, state.mediaRenderLimit + MEDIA_VIRTUALIZATION_BATCH);
  if (nextLimit === state.mediaRenderLimit) return false;
  state.mediaRenderLimit = nextLimit;
  renderMediaGrid(clips, state.snapshot?.transport?.clip_id, state.snapshot?.transport?.status);
  return true;
}

function scheduleMediaVirtualizationCheck() {
  if (!state.mediaVirtualEnabled || state.mediaVirtualCheckScheduled) return;
  state.mediaVirtualCheckScheduled = true;
  requestAnimationFrame(() => {
    state.mediaVirtualCheckScheduled = false;
    if (!state.mediaVirtualEnabled) return;
    const needsFill = DOM.dropzone.scrollHeight <= DOM.dropzone.clientHeight + 120;
    if (needsFill) {
      maybeLoadMoreMedia(true);
    }
  });
}

function ensurePlaylistRenderLimit(items, playlistId) {
  const total = items.length;
  const datasetKey = playlistVirtualDatasetKey(items, playlistId);
  const shouldVirtualize = total > PLAYLIST_VIRTUALIZATION_THRESHOLD;
  if (state.playlistVirtualKey !== datasetKey) {
    state.playlistVirtualKey = datasetKey;
    state.playlistRenderLimit = shouldVirtualize ? PLAYLIST_VIRTUALIZATION_BATCH : total;
    DOM.playlistItems.scrollTop = 0;
  }
  state.playlistVirtualEnabled = shouldVirtualize;
  if (!shouldVirtualize) {
    state.playlistRenderLimit = total;
    return items;
  }

  const activeClipId = state.snapshot?.transport?.clip_id;
  const selectedIndex = items.findIndex((item) => item.position === state.selectedPlaylistPosition);
  const activeIndex = items.findIndex((item) => item.clip_id === activeClipId);
  const priorityIndex = Math.max(selectedIndex, activeIndex);
  if (priorityIndex >= 0) {
    state.playlistRenderLimit = Math.max(state.playlistRenderLimit, priorityIndex + 1);
  }
  state.playlistRenderLimit = Math.min(total, Math.max(state.playlistRenderLimit, PLAYLIST_VIRTUALIZATION_BATCH));
  return items.slice(0, state.playlistRenderLimit);
}

function maybeLoadMorePlaylist(force = false) {
  const items = state.snapshot?.playlist?.items || [];
  if (!state.playlistVirtualEnabled) return false;
  if (state.playlistRenderLimit >= items.length) return false;
  const nearBottom = DOM.playlistItems.scrollTop + DOM.playlistItems.clientHeight >= DOM.playlistItems.scrollHeight - 400;
  if (!force && !nearBottom) return false;
  const nextLimit = Math.min(items.length, state.playlistRenderLimit + PLAYLIST_VIRTUALIZATION_BATCH);
  if (nextLimit === state.playlistRenderLimit) return false;
  state.playlistRenderLimit = nextLimit;
  renderPlaylist(state.snapshot?.playlist || { playlist: null, items: [] }, state.snapshot?.transport?.clip_id);
  return true;
}

function schedulePlaylistVirtualizationCheck() {
  if (!state.playlistVirtualEnabled || state.playlistVirtualCheckScheduled) return;
  state.playlistVirtualCheckScheduled = true;
  requestAnimationFrame(() => {
    state.playlistVirtualCheckScheduled = false;
    if (!state.playlistVirtualEnabled) return;
    const needsFill = DOM.playlistItems.scrollHeight <= DOM.playlistItems.clientHeight + 120;
    if (needsFill) {
      maybeLoadMorePlaylist(true);
    }
  });
}

function normalizeSelection() {
  const clips = state.snapshot?.clips || [];
  const playlistItems = state.snapshot?.playlist?.items || [];
  if (!clips.length) {
    state.selectedClipId = null;
    state.selectedPlaylistPosition = 1;
    return;
  }
  if (!state.clipIndex.has(state.selectedClipId)) {
    state.selectedClipId = state.snapshot?.transport?.clip_id || clips[0].deck_id;
  }
  if (!playlistItems.some((item) => item.position === state.selectedPlaylistPosition)) {
    state.selectedPlaylistPosition = playlistItems[0]?.position || 1;
  }
}

function clipFromDeckId(deckId) {
  return state.clipIndex.get(Number(deckId)) || null;
}

function playlistItemFromPosition(position) {
  const items = state.snapshot?.playlist?.items || [];
  return items.find((item) => String(item.position) === String(position)) || null;
}

function thumbnailUrl(thumbnailPath) {
  if (!thumbnailPath) return null;
  return `/thumbs/${thumbnailPath.split('/').pop()}`;
}

function mediaSourceUrl(clip) {
  return `/media/${encodeURIComponent(clip.filename)}`;
}

function mediaArtworkUrl(clip) {
  if (clip.thumbnail_path) return thumbnailUrl(clip.thumbnail_path);
  if (clip.media_kind === 'image') return mediaSourceUrl(clip);
  return null;
}

function mediaKindLabel(clip) {
  return clip.media_kind === 'image' ? 'IMAGE' : 'VIDEO';
}

function clipResolutionLabel(clip) {
  if (!clip.width || !clip.height) return null;
  return `${clip.width}x${clip.height}`;
}

function clipDurationLabel(clip) {
  if (clip.media_kind === 'image') {
    return `${Math.round(clip.duration_seconds || 0)}s still`;
  }
  return clip.duration_timecode.substring(0, 8);
}

function hideUploadOverlaySoon(delayMs = 900) {
  if (state.uploadHideTimer) {
    clearTimeout(state.uploadHideTimer);
  }
  state.uploadHideTimer = window.setTimeout(() => {
    DOM.uploadWrapper.style.display = 'none';
    DOM.uploadProgress.style.width = '0%';
    DOM.uploadStatus.textContent = 'IMPORTING MEDIA...';
    state.uploadHideTimer = null;
    state.uploadProcessingActive = false;
  }, delayMs);
}

function renderUploadProcessingStatus(mediaProcessing) {
  if (!state.uploadProcessingActive) return;
  const processing = mediaProcessing || {};
  const remaining = Number(processing.pending || 0) + Number(processing.processing || 0);
  const errors = Number(processing.error || 0);
  if (remaining > 0) {
    if (state.uploadHideTimer) {
      clearTimeout(state.uploadHideTimer);
      state.uploadHideTimer = null;
    }
    DOM.uploadWrapper.style.display = 'flex';
    DOM.uploadProgress.style.width = '65%';
    DOM.uploadStatus.textContent = `PROCESSING ${remaining} CLIP${remaining > 1 ? 'S' : ''} | ${formatEta(processing.eta_seconds)}${errors ? ` | ${errors} ERROR` : ''}`;
    return;
  }
  DOM.uploadProgress.style.width = '100%';
  DOM.uploadStatus.textContent = errors ? `IMPORT COMPLETE WITH ${errors} ERROR${errors > 1 ? 'S' : ''}` : 'IMPORT COMPLETE';
  hideUploadOverlaySoon();
}

function clipProcessingLabel(clip) {
  switch (clip.processing_state) {
    case 'pending':
      return 'QUEUED';
    case 'processing':
      return 'PROCESSING';
    case 'error':
      return 'ERROR';
    default:
      return '';
  }
}

function getOrCreateMediaNode(clip) {
  const key = String(clip.deck_id);
  if (!state.mediaNodeCache.has(key)) {
    state.mediaNodeCache.set(key, Templates.mediaItem.content.firstElementChild.cloneNode(true));
  }
  return state.mediaNodeCache.get(key);
}

function updateMediaNode(node, clip, activeClipId, status) {
  const idNode = node.querySelector('.media-id');
  const img = node.querySelector('.thumb-img');
  const titleNode = node.querySelector('.media-title');
  const metaNode = node.querySelector('.media-meta');
  const loopButton = node.querySelector('.ctrl-btn.loop');
  const statusOverlay = node.querySelector('.status-overlay');
  const processingLabel = clipProcessingLabel(clip);
  const playbackActive = clip.deck_id === activeClipId && status === 'play';
  const overlayLabel = playbackActive ? 'PLAYING' : processingLabel;
  const metaParts = [
    clip.folder,
    mediaKindLabel(clip),
    clipDurationLabel(clip),
    clipResolutionLabel(clip),
    clip.media_kind === 'video' ? `${clip.framerate}fps` : null,
    clip.is_vertical ? 'vertical' : null,
    clip.tags ? `#${clip.tags}` : null,
    processingLabel || null,
  ].filter(Boolean);

  node.dataset.deckId = clip.deck_id;
  node.dataset.mediaKind = clip.media_kind || 'video';
  node.dataset.processingState = clip.processing_state || 'ready';
  idNode.textContent = String(clip.deck_id).padStart(2, '0');
  titleNode.textContent = clip.name;
  metaNode.textContent = metaParts.join(' | ');

  const artworkSrc = mediaArtworkUrl(clip);
  if (artworkSrc) {
    img.loading = 'lazy';
    img.decoding = 'async';
    img.fetchPriority = 'low';
    img.alt = clip.name;
    img.draggable = false;
    if (img.getAttribute('src') !== artworkSrc) {
      img.src = artworkSrc;
    }
    img.style.display = '';
  } else {
    img.removeAttribute('src');
    img.removeAttribute('alt');
    img.style.display = 'none';
  }

  loopButton.classList.toggle('active-loop', Boolean(clip.loop_enabled));
  node.classList.toggle('active', clip.deck_id === activeClipId);
  node.classList.toggle('selected', clip.deck_id === state.selectedClipId);
  node.classList.toggle('processing', ['pending', 'processing'].includes(clip.processing_state));
  node.classList.toggle('processing-error', clip.processing_state === 'error');
  statusOverlay.textContent = overlayLabel || 'PLAYING';
  statusOverlay.classList.toggle('processing', !playbackActive && ['pending', 'processing'].includes(clip.processing_state));
  statusOverlay.classList.toggle('error', clip.processing_state === 'error');
  statusOverlay.style.display = overlayLabel ? 'flex' : 'none';
}

function getOrCreatePlaylistNode(playlistId, item) {
  const key = `${playlistId}:${item.position}`;
  if (!state.playlistNodeCache.has(key)) {
    state.playlistNodeCache.set(key, Templates.playlistItem.content.firstElementChild.cloneNode(true));
  }
  return state.playlistNodeCache.get(key);
}

const END_BEHAVIOR_LABELS = { next: 'AUTO', stop: 'STOP', hold: 'HOLD', loop: 'LOOP' };
const END_BEHAVIOR_CYCLE = ['next', 'stop', 'hold', 'loop'];

function updatePlaylistNode(node, item, activeClipId) {
  node.dataset.clipId = item.clip_id;
  node.dataset.position = item.position;
  node.querySelector('.playlist-item-pos').textContent = String(item.position).padStart(2, '0');
  node.querySelector('.playlist-item-name').textContent = item.clip_name;
  node.querySelector('.playlist-item-time').textContent = item.duration_timecode.substring(0, 8);
  const behavior = item.end_behavior || 'next';
  const endNode = node.querySelector('.playlist-item-end');
  endNode.textContent = END_BEHAVIOR_LABELS[behavior] || 'AUTO';
  endNode.classList.toggle('is-stop', behavior === 'stop');
  endNode.classList.toggle('is-hold', behavior === 'hold');
  endNode.classList.toggle('is-loop', behavior === 'loop');
  node.classList.toggle('active', item.clip_id === activeClipId);
  node.classList.toggle('selected', item.position === state.selectedPlaylistPosition);
}

function getOrCreateFolderCard(folder) {
  if (!state.folderNodeCache.has(folder)) {
    const card = document.createElement('button');
    card.type = 'button';
    card.className = 'folder-card';
    card.dataset.folder = folder;
    card.innerHTML = `
      <div class="folder-card-preview"></div>
      <div class="folder-card-info">
        <div class="folder-card-title"></div>
        <div class="folder-card-meta"></div>
      </div>
    `;
    state.folderNodeCache.set(folder, card);
  }
  return state.folderNodeCache.get(folder);
}

function updateFolderCard(card, folder, folderClips) {
  card.dataset.folder = folder;
  card.querySelector('.folder-card-title').textContent = folder;
  const imageCount = folderClips.filter((clip) => clip.media_kind === 'image').length;
  const videoCount = folderClips.length - imageCount;
  card.querySelector('.folder-card-meta').textContent = `${folderClips.length} item${folderClips.length > 1 ? 's' : ''} | ${videoCount} video${videoCount > 1 ? 's' : ''} | ${imageCount} image${imageCount > 1 ? 's' : ''}`;
  const preview = card.querySelector('.folder-card-preview');
  preview.replaceChildren();

  const thumbClips = folderClips.slice(0, 4);
  if (thumbClips.length) {
    const fragment = document.createDocumentFragment();
    thumbClips.forEach((clip) => {
      const thumb = document.createElement('div');
      thumb.className = 'folder-card-thumb';
      const artworkSrc = mediaArtworkUrl(clip);
      if (artworkSrc) {
        const image = document.createElement('img');
        image.className = 'folder-card-thumb-image';
        image.loading = 'lazy';
        image.decoding = 'async';
        image.fetchPriority = 'low';
        image.draggable = false;
        image.alt = clip.name;
        image.src = artworkSrc;
        thumb.appendChild(image);
      } else {
        thumb.classList.add('empty');
        thumb.textContent = clip.name.slice(0, 1).toUpperCase();
      }
      fragment.appendChild(thumb);
    });
    preview.appendChild(fragment);
    return;
  }

  const emptyState = document.createElement('div');
  emptyState.className = 'folder-card-empty';
  emptyState.textContent = 'EMPTY';
  preview.appendChild(emptyState);
}

async function runShortcut(action, errorTitle) {
  try {
    await action();
  } catch (error) {
    console.error(error);
    await showNotice(errorTitle, getErrorMessage(error));
  }
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
  const clips = state.snapshot?.clips || [];
  const clip = clips[padNumber - 1];
  if (!clip) return Promise.resolve();
  state.selectedClipId = clip.deck_id;
  syncMediaGridVisualState();
  if (cueOnly) {
    return cueClip(clip.deck_id);
  }
  return api(`/api/clips/${clip.deck_id}/play`, { method: 'POST' });
}

function setMediaView(view) {
  if (state.mediaView === view) return;
  state.mediaView = view;
  DOM.dropzone.scrollTop = 0;
  renderMediaToolbar();
  if (state.snapshot) {
    renderMediaGrid(filteredClips(), state.snapshot.transport?.clip_id, state.snapshot.transport?.status);
  }
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

function getSelectedClip() {
  return state.clipIndex.get(state.selectedClipId) || null;
}

async function cueClip(clipId) {
  if (!clipId) return;
  await api(`/api/clips/${clipId}/goto`, { method: 'POST' });
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

function filteredClips() {
  const clips = state.snapshot?.clips || [];
  const folder = currentFolder();
  const mediaType = currentMediaTypeFilter();
  const searchTerm = currentMediaSearchTerm();
  return clips.filter((clip) => {
    if (folder !== 'All' && clip.folder !== folder) return false;
    if (mediaType !== 'all' && clip.media_kind !== mediaType) return false;
    if (!searchTerm) return true;
    const haystack = `${clip.name} ${clip.filename} ${clip.folder} ${clip.codec} ${clip.media_kind} ${clip.tags || ''}`.toLowerCase();
    return haystack.includes(searchTerm);
  });
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
  DOM.previewVideo.removeAttribute('src');
  DOM.previewVideo.load();
  DOM.previewImage.hidden = true;
  DOM.previewImage.removeAttribute('src');
  DOM.previewImage.removeAttribute('alt');
  DOM.previewModal.hidden = true;
}

function closeSettingsModal() {
  DOM.settingsModal.hidden = true;
}

function openSettingsModal() {
  DOM.settingsModal.hidden = false;
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
  const clips = state.snapshot?.clips || [];
  if (!DOM.padGrid.childElementCount) {
    const fragment = document.createDocumentFragment();
    for (let pad = 1; pad <= 9; pad += 1) {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'pad-btn';
      button.dataset.pad = String(pad);
      button.innerHTML = '<span class="pad-btn-key"></span><span class="pad-btn-name"></span>';
      fragment.appendChild(button);
    }
    DOM.padGrid.appendChild(fragment);
  }
  const activeClipId = transport?.clip_id;
  const isPlaying = transport?.status === 'play';
  for (const button of DOM.padGrid.children) {
    const pad = Number(button.dataset.pad);
    const clip = clips[pad - 1] || null;
    const keyNode = button.firstElementChild;
    const nameNode = button.lastElementChild;
    keyNode.textContent = String(pad);
    nameNode.textContent = clip ? clip.name : '--';
    button.disabled = !clip;
    button.title = clip ? `${clip.name} — click to fire, Shift+click to cue` : 'Empty pad';
    const isActive = Boolean(clip && clip.deck_id === activeClipId);
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

function syncPlaylistVisualState(activeClipId = state.snapshot?.transport?.clip_id) {
  if (state.playlistVirtualEnabled) {
    const items = state.snapshot?.playlist?.items || [];
    const selectedIndex = items.findIndex((item) => item.position === state.selectedPlaylistPosition);
    const activeIndex = items.findIndex((item) => item.clip_id === activeClipId);
    const requiredLimit = Math.max(selectedIndex, activeIndex) + 1;
    if (requiredLimit > state.playlistRenderLimit) {
      state.playlistRenderLimit = Math.min(items.length, requiredLimit + 10);
      renderPlaylist(state.snapshot?.playlist || { playlist: null, items: [] }, activeClipId);
      return;
    }
  }
  const selectedPosition = String(state.selectedPlaylistPosition || '');
  DOM.playlistItems.querySelectorAll('.playlist-item').forEach((node) => {
    node.classList.toggle('active', node.dataset.clipId === String(activeClipId || ''));
    node.classList.toggle('selected', node.dataset.position === selectedPosition);
  });
}

function syncMediaGridVisualState(activeClipId = state.snapshot?.transport?.clip_id, status = state.snapshot?.transport?.status) {
  if (state.mediaVirtualEnabled) {
    const clips = filteredClips();
    const requiredIndex = clips.findIndex((clip) => clip.deck_id === (activeClipId || state.selectedClipId));
    if (requiredIndex >= 0 && requiredIndex + 1 > state.mediaRenderLimit) {
      state.mediaRenderLimit = Math.min(clips.length, requiredIndex + 10);
      renderMediaGrid(clips, activeClipId, status);
      return;
    }
  }
  const selectedClipId = String(state.selectedClipId || '');
  DOM.mediaGrid.querySelectorAll('.media-item').forEach((node) => {
    const isActive = node.dataset.deckId === String(activeClipId || '');
    const isSelected = node.dataset.deckId === selectedClipId;
    node.classList.toggle('active', isActive);
    node.classList.toggle('selected', isSelected);
    const overlay = node.querySelector('.status-overlay');
    if (overlay) {
      overlay.style.display = isActive && status === 'play' ? 'flex' : 'none';
    }
  });
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
  DOM.healthOutput.textContent = health.effective_output_width && health.effective_output_height
    ? `${health.effective_output_width}x${health.effective_output_height}`
    : (health.selected_output?.current_mode || health.selected_output?.label || 'DEFAULT');
  DOM.healthStorage.textContent = formatBytes(health.storage_free_bytes);
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
    state.snapshot.audio.volume = volume;
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

function openPreviewModal(clipId) {
  state.selectedClipId = clipId;
  renderPreview();
  DOM.previewModal.hidden = false;
  if (!DOM.previewVideo.hidden) {
    DOM.previewVideo.currentTime = 0;
  }
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
  state.folders = snapshot.folders || state.folders;
  state.playlists = snapshot.playlists || state.playlists;
  reindexClips(snapshot.clips || []);
  pruneNodeCache(state.mediaNodeCache, new Set((snapshot.clips || []).map((clip) => String(clip.deck_id))));
  pruneNodeCache(state.folderNodeCache, new Set((snapshot.folders || []).filter((folder) => folder !== 'All')));
  normalizeSelection();
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

function renderFolders() {
  const previous = DOM.folderFilter.value || 'All';
  const values = ['All', ...state.folders.filter((folder) => folder !== 'All')];
  const fragment = document.createDocumentFragment();
  values.forEach((folder) => {
    const option = document.createElement('option');
    option.value = folder;
    option.textContent = folder;
    fragment.appendChild(option);
  });
  DOM.folderFilter.replaceChildren(fragment);
  DOM.folderFilter.value = values.includes(previous) ? previous : 'All';
}

function renderMediaToolbar() {
  const folder = currentFolder();
  const isFolderOverview = folder === 'All' && !hasActiveMediaFilters();
  DOM.btnBackAll.hidden = folder === 'All' && !hasActiveMediaFilters();
  DOM.btnBackAll.textContent = folder === 'All' ? 'RESET' : 'ALL';
  DOM.btnToggleMediaView.hidden = isFolderOverview;
  DOM.btnToggleMediaView.textContent = state.mediaView === 'grid' ? 'LIST' : 'GRID';
  DOM.btnToggleMediaView.classList.toggle('active', state.mediaView === 'list');
}

function renderPlaylists() {
  const previous = DOM.playlistSelect.value;
  const fragment = document.createDocumentFragment();
  state.playlists.forEach((playlist) => {
    const option = document.createElement('option');
    option.value = playlist.id;
    option.textContent = playlist.is_active ? `${playlist.name} *` : playlist.name;
    fragment.appendChild(option);
  });
  DOM.playlistSelect.replaceChildren(fragment);
  const active = state.snapshot?.playlist?.playlist?.id;
  if (previous && state.playlists.some((playlist) => String(playlist.id) === previous)) {
    DOM.playlistSelect.value = previous;
  } else if (active) {
    DOM.playlistSelect.value = String(active);
  }
}

function renderPlaylist(playlistPayload, activeClipId) {
  const items = playlistPayload.items || [];
  const playlistId = playlistPayload.playlist?.id || 'none';
  if (!items.some((item) => item.position === state.selectedPlaylistPosition)) {
    state.selectedPlaylistPosition = items[0]?.position || 1;
  }
  DOM.playlistCount.textContent = `${items.length} items`;
  const visibleItems = ensurePlaylistRenderLimit(items, playlistId);
  const fragment = document.createDocumentFragment();
  const validKeys = new Set(items.map((item) => `${playlistId}:${item.position}`));
  visibleItems.forEach((item) => {
    const key = `${playlistId}:${item.position}`;
    const node = getOrCreatePlaylistNode(playlistId, item);
    updatePlaylistNode(node, item, activeClipId);
    fragment.appendChild(node);
  });
  pruneNodeCache(state.playlistNodeCache, validKeys);
  DOM.playlistItems.replaceChildren(fragment);
  schedulePlaylistVirtualizationCheck();
}

function renderPreview() {
  const clip = getSelectedClip();
  if (!clip) {
    DOM.previewTitle.textContent = 'Aucun clip selectionne';
    DOM.previewSubtitle.textContent = 'Selectionne un clip pour le previsualiser dans le navigateur.';
    DOM.previewStillDuration.hidden = true;
    DOM.previewTagsValue.textContent = '--';
    DOM.previewImage.hidden = true;
    DOM.previewImage.removeAttribute('src');
    DOM.previewVideo.removeAttribute('src');
    DOM.previewVideo.load();
    return;
  }
  DOM.previewTitle.textContent = clip.name;
  const orientation = clip.is_vertical ? 'VERTICAL FILL' : 'STANDARD';
  const subtitleParts = [
    clip.folder,
    mediaKindLabel(clip),
    clipDurationLabel(clip),
    clipResolutionLabel(clip),
    clip.codec,
    clip.media_kind === 'video' ? `${clip.framerate}fps` : null,
    orientation,
  ].filter(Boolean);
  DOM.previewSubtitle.textContent = subtitleParts.join(' | ');
  DOM.previewTagsValue.textContent = clip.tags || '--';
  const isImage = clip.media_kind === 'image';
  DOM.previewStillDuration.hidden = !isImage;
  if (isImage && document.activeElement !== DOM.previewDurationInput) {
    DOM.previewDurationInput.value = String(Math.round((clip.duration_seconds || 10) * 10) / 10);
  }
  const nextSrc = mediaSourceUrl(clip);
  if (clip.media_kind === 'image') {
    DOM.previewVideo.pause();
    DOM.previewVideo.removeAttribute('src');
    DOM.previewVideo.load();
    DOM.previewVideo.hidden = true;
    DOM.previewImage.hidden = false;
    DOM.previewImage.alt = clip.name;
    if (DOM.previewImage.getAttribute('src') !== nextSrc) {
      DOM.previewImage.src = nextSrc;
    }
    return;
  }
  DOM.previewImage.hidden = true;
  DOM.previewImage.removeAttribute('src');
  DOM.previewVideo.hidden = false;
  if (DOM.previewVideo.getAttribute('src') !== nextSrc) {
    DOM.previewVideo.src = nextSrc;
    DOM.previewVideo.load();
  }
  renderPreviewMarks();
}

function previewMarkDuration(clip) {
  return Math.max(0, Number(clip?.duration_seconds || DOM.previewVideo.duration || 0));
}

function renderPreviewMarks() {
  const clip = getSelectedClip();
  const isVideo = Boolean(clip && clip.media_kind === 'video');
  DOM.previewMarks.hidden = !isVideo;
  if (!isVideo) return;
  const duration = previewMarkDuration(clip);
  const markIn = Math.max(0, Number(clip.mark_in_seconds || 0));
  const rawOut = Math.max(0, Number(clip.mark_out_seconds || 0));
  const markOut = rawOut > 0 ? Math.min(rawOut, duration) : 0;
  const pct = (value) => (duration > 0 ? Math.min(100, Math.max(0, (value / duration) * 100)) : 0);
  const trimActive = markIn > 0 || markOut > 0;

  DOM.previewMarkInTick.hidden = !(markIn > 0);
  if (markIn > 0) DOM.previewMarkInTick.style.left = `${pct(markIn)}%`;
  DOM.previewMarkOutTick.hidden = !(markOut > 0);
  if (markOut > 0) DOM.previewMarkOutTick.style.left = `${pct(markOut)}%`;

  const rangeStart = pct(markIn);
  const rangeEnd = markOut > 0 ? pct(markOut) : 100;
  DOM.previewMarksRange.style.left = `${rangeStart}%`;
  DOM.previewMarksRange.style.width = `${Math.max(0, rangeEnd - rangeStart)}%`;
  DOM.previewMarksRange.classList.toggle('is-active', trimActive);

  DOM.previewMarkInValue.textContent = markIn > 0 ? formatClock(markIn) : '--';
  DOM.previewMarkOutValue.textContent = markOut > 0 ? formatClock(markOut) : '--';
  const effectiveOut = markOut > 0 ? markOut : duration;
  DOM.previewMarkTrimValue.textContent = trimActive ? formatClock(Math.max(0, effectiveOut - markIn)) : '--';
  DOM.previewMarkTrimValue.parentElement.classList.toggle('is-active', trimActive);
  DOM.btnPreviewMarkClear.disabled = !trimActive;
  updatePreviewPlayhead();
}

function updatePreviewPlayhead() {
  const clip = getSelectedClip();
  if (!clip || clip.media_kind !== 'video') return;
  const duration = previewMarkDuration(clip);
  const current = Number(DOM.previewVideo.currentTime || 0);
  const pct = duration > 0 ? Math.min(100, Math.max(0, (current / duration) * 100)) : 0;
  DOM.previewMarksPlayhead.style.left = `${pct}%`;
}

async function commitPreviewMark(kind) {
  const clip = getSelectedClip();
  if (!clip || clip.media_kind !== 'video') return;
  const duration = previewMarkDuration(clip);
  const position = Math.max(0, Math.min(Number(DOM.previewVideo.currentTime || 0), duration));
  let body;
  if (kind === 'in') body = { mark_in_seconds: position };
  else if (kind === 'out') body = { mark_out_seconds: position };
  else body = { mark_in_seconds: 0, mark_out_seconds: 0 };
  await api(`/api/clips/${clip.deck_id}/marks`, { method: 'PATCH', body: JSON.stringify(body) });
  if (kind === 'in') clip.mark_in_seconds = position;
  else if (kind === 'out') clip.mark_out_seconds = position;
  else { clip.mark_in_seconds = 0; clip.mark_out_seconds = 0; }
  renderPreviewMarks();
}

function renderMediaGrid(clips, activeClipId, status) {
  const folder = currentFolder();
  if (folder === 'All' && !hasActiveMediaFilters()) {
    state.mediaVirtualEnabled = false;
    state.mediaVirtualKey = null;
    state.mediaRenderLimit = 0;
    DOM.mediaGrid.classList.remove('list-view');
    renderFolderCards(clips);
    return;
  }
  DOM.mediaGrid.classList.toggle('list-view', state.mediaView === 'list');
  const visibleClips = ensureMediaRenderLimit(clips);
  const fragment = document.createDocumentFragment();
  visibleClips.forEach((clip) => {
    const node = getOrCreateMediaNode(clip);
    updateMediaNode(node, clip, activeClipId, status);
    fragment.appendChild(node);
  });
  DOM.mediaGrid.replaceChildren(fragment);
  scheduleMediaVirtualizationCheck();
}

function renderFolderCards(clips) {
  const folders = state.folders.filter((folder) => folder !== 'All');
  const folderMap = buildFolderClipMap(clips);
  const fragment = document.createDocumentFragment();
  folders.forEach((folder) => {
    const folderClips = folderMap.get(folder) || [];
    const card = getOrCreateFolderCard(folder);
    updateFolderCard(card, folder, folderClips);
    fragment.appendChild(card);
  });
  DOM.mediaGrid.replaceChildren(fragment);
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
DOM.dropzone.addEventListener('scroll', () => {
  maybeLoadMoreMedia();
});
DOM.playlistItems.addEventListener('scroll', () => {
  maybeLoadMorePlaylist();
});
bindAsync(DOM.dropzone, 'drop', async (e) => {
  e.preventDefault();
  DOM.dropzone.classList.remove('dragover');
  await uploadFiles(e.dataTransfer.files);
}, 'Upload Error');
bindAsync(DOM.fileInput, 'change', async () => uploadFiles(DOM.fileInput.files), 'Upload Error');

async function uploadFiles(fileList) {
  if (!fileList || !fileList.length) return;
  const formData = new FormData();
  [...fileList].forEach((file) => formData.append('files', file));
  state.uploadProcessingActive = true;
  if (state.uploadHideTimer) {
    clearTimeout(state.uploadHideTimer);
    state.uploadHideTimer = null;
  }
  DOM.uploadWrapper.style.display = 'flex';
  DOM.uploadProgress.style.width = '10%';
  DOM.uploadStatus.textContent = `UPLOADING ${fileList.length} FILE${fileList.length > 1 ? 'S' : ''}...`;
  let shouldRefresh = !state.websocketConnected;
  try {
    const response = await api('/api/upload', { method: 'POST', body: formData });
    if (response?.processing === 'background') {
      DOM.uploadProgress.style.width = '65%';
      renderUploadProcessingStatus(response.media_processing);
    } else {
      DOM.uploadProgress.style.width = '100%';
      DOM.uploadStatus.textContent = 'IMPORT COMPLETE';
      hideUploadOverlaySoon();
    }
  } catch (error) {
    shouldRefresh = true;
    state.uploadProcessingActive = false;
    await showNotice('Upload Error', error.message || "Échec de l'upload.");
    hideUploadOverlaySoon(300);
  } finally {
    if (shouldRefresh) {
      await refresh();
    }
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
  if (!button || button.disabled) return;
  await firePadClip(Number(button.dataset.pad), event.shiftKey);
}, 'Playback Error');
bindAsync(DOM.btnPrev, 'click', async () => playAdjacentClip(-1), 'Playback Error');
bindAsync(DOM.btnNext, 'click', async () => playAdjacentClip(1), 'Playback Error');
bindAsync(DOM.btnBlack, 'click', async () => {
  if (!await ensureLiveActionAllowed('Cut to black')) return;
  await api('/api/system/black', { method: 'POST' });
}, 'Playback Error');
bindAsync(DOM.btnRefreshMedia, 'click', refresh, 'Refresh Error');
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
bindAsync(DOM.btnRunUpdate, 'click', async () => {
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
    state.snapshot.display = response.display;
    renderDisplaySettings(state.snapshot.display);
  }
}, 'Display Error');
DOM.configVolume.addEventListener('input', (e) => {
  scheduleVolumeCommit(Number(e.target.value));
});
bindAsync(DOM.btnMute, 'click', async () => {
  const muted = DOM.btnMute.classList.contains('muted');
  await api('/api/audio/mute', { method: 'POST', body: JSON.stringify({ muted: !muted }) });
}, 'Audio Error');
bindAsync(DOM.playlistItems, 'click', async (event) => {
  const removeNode = event.target.closest('.playlist-item-remove');
  const endNode = event.target.closest('.playlist-item-end');
  const moveNode = event.target.closest('.playlist-item-move');
  const playlistNode = event.target.closest('.playlist-item');
  if (!playlistNode) return;
  const item = playlistItemFromPosition(playlistNode.dataset.position);
  if (!item) return;
  if (endNode) {
    event.stopPropagation();
    const playlistId = state.snapshot?.playlist?.playlist?.id;
    if (!playlistId) return;
    const nextBehavior = END_BEHAVIOR_CYCLE[(END_BEHAVIOR_CYCLE.indexOf(item.end_behavior || 'next') + 1) % END_BEHAVIOR_CYCLE.length];
    await api(`/api/playlists/${playlistId}/items/${item.position}`, {
      method: 'PATCH',
      body: JSON.stringify({ end_behavior: nextBehavior }),
    });
    return;
  }
  if (moveNode) {
    event.stopPropagation();
    const playlistId = state.snapshot?.playlist?.playlist?.id;
    if (!playlistId) return;
    const items = state.snapshot?.playlist?.items || [];
    const positions = items.map((entry) => entry.position);
    const index = positions.indexOf(item.position);
    const target = index + (moveNode.dataset.role === 'move-up' ? -1 : 1);
    if (index < 0 || target < 0 || target >= positions.length) return;
    [positions[index], positions[target]] = [positions[target], positions[index]];
    state.selectedPlaylistPosition = target + 1;
    await api(`/api/playlists/${playlistId}/items/reorder`, {
      method: 'POST',
      body: JSON.stringify({ positions }),
    });
    return;
  }
  if (removeNode) {
    event.stopPropagation();
    const playlistId = state.snapshot?.playlist?.playlist?.id;
    if (!playlistId) return;
    await api(`/api/playlists/${playlistId}/items/${item.position}`, { method: 'DELETE' });
    await refresh();
    return;
  }
  state.selectedPlaylistPosition = item.position;
  state.selectedClipId = item.clip_id;
  syncPlaylistVisualState();
  syncMediaGridVisualState();
  renderPreview();
  await api(`/api/clips/${item.clip_id}/goto`, { method: 'POST' });
}, 'Playlist Error');
bindAsync(DOM.playlistItems, 'dblclick', async (event) => {
  if (event.target.closest('.playlist-item-remove')) return;
  const playlistNode = event.target.closest('.playlist-item');
  if (!playlistNode) return;
  const item = playlistItemFromPosition(playlistNode.dataset.position);
  const playlistId = state.snapshot?.playlist?.playlist?.id;
  if (!item || !playlistId) return;
  state.selectedPlaylistPosition = item.position;
  syncPlaylistVisualState();
  await api(`/api/playlists/${playlistId}/play-from`, {
    method: 'POST',
    body: JSON.stringify({ position: item.position })
  });
}, 'Playlist Error');
bindAsync(DOM.mediaGrid, 'click', async (event) => {
  const folderCard = event.target.closest('.folder-card');
  if (folderCard) {
    DOM.folderFilter.value = folderCard.dataset.folder || 'All';
    renderMediaToolbar();
    renderMediaGrid(filteredClips(), state.snapshot.transport.clip_id, state.snapshot.transport.status);
    return;
  }
  const mediaItem = event.target.closest('.media-item');
  if (!mediaItem) return;
  const controlButton = event.target.closest('.ctrl-btn');
  const clip = clipFromDeckId(mediaItem.dataset.deckId);
  if (!clip) return;
  if (controlButton) {
    event.stopPropagation();
    await handleClipAction(clip, controlButton.dataset.action);
    return;
  }
  state.selectedClipId = clip.deck_id;
  syncMediaGridVisualState();
  await cueClip(clip.deck_id);
  renderPreview();
}, 'Media Error');
bindAsync(DOM.mediaGrid, 'dblclick', async (event) => {
  if (event.target.closest('.ctrl-btn') || event.target.closest('.folder-card')) return;
  const mediaItem = event.target.closest('.media-item');
  if (!mediaItem) return;
  const clip = clipFromDeckId(mediaItem.dataset.deckId);
  if (!clip) return;
  await api(`/api/clips/${clip.deck_id}/play`, { method: 'POST' });
}, 'Media Error');
DOM.mediaGrid.addEventListener('dragstart', (event) => {
  const mediaItem = event.target.closest('.media-item');
  if (!mediaItem) return;
  state.dragClipId = Number(mediaItem.dataset.deckId);
  mediaItem.style.opacity = '0.4';
});
DOM.mediaGrid.addEventListener('dragend', (event) => {
  const mediaItem = event.target.closest('.media-item');
  if (!mediaItem) return;
  mediaItem.style.opacity = '1';
  mediaItem.style.transform = 'none';
  state.dragClipId = null;
});
DOM.mediaGrid.addEventListener('dragover', (event) => {
  const mediaItem = event.target.closest('.media-item');
  if (!mediaItem) return;
  event.preventDefault();
  mediaItem.style.transform = 'scale(1.02)';
});
DOM.mediaGrid.addEventListener('dragleave', (event) => {
  const mediaItem = event.target.closest('.media-item');
  if (!mediaItem || mediaItem.contains(event.relatedTarget)) return;
  mediaItem.style.transform = 'none';
});
bindAsync(DOM.mediaGrid, 'drop', async (event) => {
  const mediaItem = event.target.closest('.media-item');
  if (!mediaItem) return;
  event.preventDefault();
  mediaItem.style.transform = 'none';
  const from = state.dragClipId;
  const to = Number(mediaItem.dataset.deckId);
  if (!from || from === to) return;
  const order = filteredClips().map((item) => item.deck_id);
  order.splice(order.indexOf(from), 1);
  order.splice(order.indexOf(to), 0, from);
  await api('/api/clips/reorder', { method: 'POST', body: JSON.stringify({ deck_ids: order }) });
  await refresh();
}, 'Media Error');
DOM.folderFilter.addEventListener('change', () => {
  DOM.dropzone.scrollTop = 0;
  renderMediaToolbar();
  renderMediaGrid(filteredClips(), state.snapshot.transport.clip_id, state.snapshot.transport.status);
});
DOM.mediaTypeFilter.addEventListener('change', () => {
  DOM.dropzone.scrollTop = 0;
  renderMediaToolbar();
  renderMediaGrid(filteredClips(), state.snapshot.transport.clip_id, state.snapshot.transport.status);
});
DOM.mediaSearch.addEventListener('input', () => {
  DOM.dropzone.scrollTop = 0;
  renderMediaToolbar();
  renderMediaGrid(filteredClips(), state.snapshot.transport.clip_id, state.snapshot.transport.status);
});
DOM.btnBackAll.addEventListener('click', () => {
  DOM.folderFilter.value = 'All';
  DOM.mediaTypeFilter.value = 'all';
  DOM.mediaSearch.value = '';
  DOM.dropzone.scrollTop = 0;
  renderMediaToolbar();
  renderMediaGrid(filteredClips(), state.snapshot.transport.clip_id, state.snapshot.transport.status);
});
DOM.btnToggleMediaView.addEventListener('click', () => {
  setMediaView(state.mediaView === 'grid' ? 'list' : 'grid');
});
bindAsync(DOM.btnNewFolder, 'click', async () => {
  const name = await requestText({
    title: 'New Folder',
    message: 'Nom du dossier media :',
    confirmLabel: 'CREATE'
  });
  if (!name) return;
  await api('/api/media/folders', { method: 'POST', body: JSON.stringify({ name }) });
  await refresh();
  DOM.folderFilter.value = name;
  DOM.dropzone.scrollTop = 0;
  renderMediaGrid(filteredClips(), state.snapshot.transport.clip_id, state.snapshot.transport.status);
}, 'Media Error');
bindAsync(DOM.btnMoveFolder, 'click', async () => {
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
  DOM.dropzone.scrollTop = 0;
  renderMediaGrid(filteredClips(), state.snapshot.transport.clip_id, state.snapshot.transport.status);
}, 'Media Error');
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
bindAsync(DOM.btnPreviewPlay, 'click', async () => {
  const clip = getSelectedClip();
  if (!clip) return;
  await api(`/api/clips/${clip.deck_id}/play`, { method: 'POST' });
  closePreviewModal();
}, 'Preview Error');
bindAsync(DOM.btnPreviewCue, 'click', async () => {
  const clip = getSelectedClip();
  if (!clip) return;
  await cueClip(clip.deck_id);
}, 'Preview Error');
bindAsync(DOM.btnPreviewAddPlaylist, 'click', async () => addSelectedClipToPlaylist(), 'Playlist Error');
bindAsync(DOM.btnPreviewDuration, 'click', async () => {
  const clip = getSelectedClip();
  if (!clip || clip.media_kind !== 'image') return;
  const seconds = Number(DOM.previewDurationInput.value || 0);
  if (!(seconds > 0)) {
    await showNotice('Still Duration', 'La durée doit être un nombre de secondes positif.');
    return;
  }
  await api(`/api/clips/${clip.deck_id}/duration`, { method: 'PATCH', body: JSON.stringify({ seconds }) });
}, 'Media Error');
bindAsync(DOM.btnPreviewTags, 'click', async () => {
  const clip = getSelectedClip();
  if (!clip) return;
  const value = await openAppDialog({
    title: 'Edit Tags',
    message: `Tags de "${clip.name}" (séparés par des virgules, vide pour effacer) :`,
    inputValue: clip.tags || '',
    showInput: true,
    confirmLabel: 'SAVE',
  });
  if (typeof value !== 'string') return;
  await api(`/api/clips/${clip.deck_id}/tags`, { method: 'PATCH', body: JSON.stringify({ tags: value }) });
}, 'Media Error');
bindAsync(DOM.btnPreviewMarkIn, 'click', async () => commitPreviewMark('in'), 'Marks Error');
bindAsync(DOM.btnPreviewMarkOut, 'click', async () => commitPreviewMark('out'), 'Marks Error');
bindAsync(DOM.btnPreviewMarkClear, 'click', async () => commitPreviewMark('clear'), 'Marks Error');
DOM.previewVideo.addEventListener('timeupdate', updatePreviewPlayhead);
DOM.previewVideo.addEventListener('loadedmetadata', renderPreviewMarks);
bindAsync(DOM.btnNewPlaylist, 'click', async () => {
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
}, 'Playlist Error');
bindAsync(DOM.btnActivatePlaylist, 'click', async () => {
  const playlistId = currentPlaylistId();
  if (!playlistId) return;
  await api(`/api/playlists/${playlistId}/activate`, { method: 'POST' });
  await refresh();
}, 'Playlist Error');
bindAsync(DOM.btnPlayPlaylist, 'click', async () => {
  await playPlaylist();
}, 'Playlist Error');
bindAsync(DOM.btnPlayPlaylistFrom, 'click', async () => {
  await playPlaylistFromSelection();
}, 'Playlist Error');
bindAsync(DOM.btnNextPlaylist, 'click', async () => {
  await playNextPlaylistSelection();
}, 'Playlist Error');
bindAsync(DOM.btnLoopPlaylist, 'click', async () => {
  const enabled = !Boolean(state.snapshot?.transport?.playlist_loop);
  await api('/api/playlists/loop', {
    method: 'POST',
    body: JSON.stringify({ enabled })
  });
}, 'Playlist Error');
bindAsync(DOM.btnAddSelectedPlaylist, 'click', async () => addSelectedClipToPlaylist(), 'Playlist Error');
bindAsync(DOM.btnClearPlaylist, 'click', async () => {
  await clearCurrentPlaylist();
}, 'Playlist Error');
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
    throw new Error('Fichier JSON invalide.');
  }
  const confirmed = await requestConfirm({
    title: 'Import Library',
    message: 'Appliquer les noms, dossiers, marks, tags et playlists de ce fichier ? Les réglages actuels des clips correspondants seront remplacés.',
    confirmLabel: 'IMPORT',
  });
  if (!confirmed) return;
  const result = await api('/api/system/import', { method: 'POST', body: JSON.stringify(payload) });
  await showNotice('Import Complete', `${result.clips} clip(s) et ${result.playlists} playlist(s) mis à jour.`);
  await refresh();
}, 'Import Error');
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

async function refresh({ includeUpdate = true } = {}) {
  const requests = [api('/api/state')];
  if (includeUpdate) {
    requests.push(api('/api/system/update'));
  }
  const [snapshot, updatePayload] = await Promise.all(requests);
  renderState(snapshot);
  if (updatePayload) {
    renderUpdateStatus(updatePayload);
    if (['running', 'restarting', 'rebooting'].includes(updatePayload.phase)) {
      startUpdatePolling();
    }
  }
}

function scheduleWebSocketReconnect() {
  if (state.websocketReconnectTimer) return;
  state.websocketReconnectTimer = window.setTimeout(() => {
    state.websocketReconnectTimer = null;
    setupWebSocket();
  }, 2000);
}

function setupWebSocket() {
  const protocol = location.protocol === 'https:' ? 'wss' : 'ws';
  const socket = new WebSocket(`${protocol}://${location.host}/ws`);
  socket.addEventListener('open', () => {
    state.websocketConnected = true;
  });
  socket.addEventListener('message', (event) => {
    let message;
    try {
      message = JSON.parse(event.data);
    } catch (error) {
      console.error('Invalid websocket payload', error);
      return;
    }
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
  });
  socket.addEventListener('close', () => {
    state.websocketConnected = false;
    scheduleWebSocketReconnect();
  });
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
