// Media panel: library grid / folder cards, filters, bulk select, upload,
// drag & drop, and the clip label helpers other panels reuse.

import { api, formatEta } from './util.js';
import { DOM, Templates } from './dom.js';
import { clipFromDeckId, getSelectedClip, state } from './store.js';
import {
  bindAsync,
  ensureLiveActionAllowed,
  requestConfirm,
  requestSelect,
  requestText,
  showNotice,
} from './dialogs.js';
import { openPreviewModal, renderPreview } from './preview.js';
import { cueClip } from './transport.js';
import { refresh } from './app.js';

export const MEDIA_VIRTUALIZATION_THRESHOLD = 120;

export const MEDIA_VIRTUALIZATION_BATCH = 60;

export function currentFolder() {
  return DOM.folderFilter.value || 'All';
}

export function currentMediaTypeFilter() {
  return DOM.mediaTypeFilter.value || 'all';
}

export function currentMediaSearchTerm() {
  return (DOM.mediaSearch.value || '').trim().toLowerCase();
}

export function hasActiveMediaFilters() {
  return currentMediaTypeFilter() !== 'all' || Boolean(currentMediaSearchTerm());
}

export function filteredClips() {
  const clips = state.snapshot?.clips || [];
  const folder = currentFolder();
  const mediaType = currentMediaTypeFilter();
  const searchTerm = currentMediaSearchTerm();
  return clips.filter((clip) => {
    if (folder !== 'All' && clip.folder !== folder) return false;
    if (mediaType !== 'all' && clip.media_kind !== mediaType) return false;
    if (!searchTerm) return true;
    const sourceTokens = clip.available === false ? `${clip.source || ''} offline usb` : (clip.source || '');
    const haystack = `${clip.name} ${clip.filename} ${clip.folder} ${clip.codec} ${clip.media_kind} ${clip.tags || ''} ${sourceTokens}`.toLowerCase();
    return haystack.includes(searchTerm);
  });
}

export function buildFolderClipMap(clips) {
  const folderMap = new Map();
  (clips || []).forEach((clip) => {
    if (!folderMap.has(clip.folder)) {
      folderMap.set(clip.folder, []);
    }
    folderMap.get(clip.folder).push(clip);
  });
  return folderMap;
}

export function mediaVirtualDatasetKey(clips) {
  return `${currentFolder()}::${state.mediaView}::${clips.length}`;
}

export function ensureMediaRenderLimit(clips) {
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

export function maybeLoadMoreMedia(force = false) {
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

export function scheduleMediaVirtualizationCheck() {
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

export function thumbnailUrl(thumbnailPath) {
  if (!thumbnailPath) return null;
  return `/thumbs/${thumbnailPath.split('/').pop()}`;
}

export function mediaSourceUrl(clip) {
  return `/media/${encodeURIComponent(clip.filename)}`;
}

export function mediaArtworkUrl(clip) {
  if (clip.thumbnail_path) return thumbnailUrl(clip.thumbnail_path);
  if (clip.media_kind === 'image') return mediaSourceUrl(clip);
  return null;
}

export function mediaKindLabel(clip) {
  return clip.media_kind === 'image' ? 'IMAGE' : 'VIDEO';
}

export function clipResolutionLabel(clip) {
  if (!clip.width || !clip.height) return null;
  return `${clip.width}x${clip.height}`;
}

export function clipDurationLabel(clip) {
  if (clip.media_kind === 'image') {
    return `${Math.round(clip.duration_seconds || 0)}s still`;
  }
  return clip.duration_timecode.substring(0, 8);
}

export function clipProcessingLabel(clip) {
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

export function hideUploadOverlaySoon(delayMs = 900) {
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

export function renderUploadProcessingStatus(mediaProcessing) {
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

export function getOrCreateMediaNode(clip) {
  const key = String(clip.deck_id);
  if (!state.mediaNodeCache.has(key)) {
    state.mediaNodeCache.set(key, Templates.mediaItem.content.firstElementChild.cloneNode(true));
  }
  return state.mediaNodeCache.get(key);
}

export function updateMediaNode(node, clip, activeClipId, status) {
  const idNode = node.querySelector('.media-id');
  const img = node.querySelector('.thumb-img');
  const titleNode = node.querySelector('.media-title');
  const metaNode = node.querySelector('.media-meta');
  const loopButton = node.querySelector('.ctrl-btn.loop');
  const statusOverlay = node.querySelector('.status-overlay');
  const processingLabel = clipProcessingLabel(clip);
  const isOffline = clip.available === false;
  const playbackActive = clip.deck_id === activeClipId && status === 'play';
  const overlayLabel = playbackActive ? 'PLAYING' : (isOffline ? 'OFFLINE' : processingLabel);
  const sourceLabel = isOffline
    ? 'OFFLINE'
    : (clip.is_remote ? 'LINK' : (clip.source && clip.source !== 'Internal' ? `USB · ${clip.source}` : null));
  const metaParts = [
    clip.folder,
    mediaKindLabel(clip),
    clipDurationLabel(clip),
    clipResolutionLabel(clip),
    clip.media_kind === 'video' ? `${clip.framerate}fps` : null,
    clip.is_vertical ? 'vertical' : null,
    clip.tags ? `#${clip.tags}` : null,
    sourceLabel,
    processingLabel || null,
  ].filter(Boolean);

  // Nodes are reused across renders (getOrCreateMediaNode); a drag interrupted
  // without a matching dragend/dragleave (e.g. drag released outside the window)
  // would otherwise leave a stale inline opacity/transform on this node forever.
  node.style.opacity = '';
  node.style.transform = '';
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
  node.querySelector('.ctrl-btn.music').classList.toggle('active-music', Boolean(clip.is_music));
  node.classList.toggle('active', clip.deck_id === activeClipId);
  node.classList.toggle('selected', clip.deck_id === state.selectedClipId);
  node.classList.toggle('multi-selected', state.selection.has(clip.filename));
  node.classList.toggle('processing', ['pending', 'processing'].includes(clip.processing_state));
  node.classList.toggle('processing-error', clip.processing_state === 'error');
  node.classList.toggle('offline', isOffline);
  statusOverlay.textContent = overlayLabel || 'PLAYING';
  statusOverlay.classList.toggle('processing', !playbackActive && !isOffline && ['pending', 'processing'].includes(clip.processing_state));
  statusOverlay.classList.toggle('error', clip.processing_state === 'error');
  statusOverlay.classList.toggle('offline', !playbackActive && isOffline);
  statusOverlay.style.display = overlayLabel ? 'flex' : 'none';
  // On failure, hovering the clip (or its red badge) reveals why it errored.
  const errorReason = clip.processing_state === 'error' ? (clip.error_reason || 'Import failed') : '';
  node.title = errorReason;
  statusOverlay.title = errorReason;
}

export function getOrCreateFolderCard(folder) {
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

export function updateFolderCard(card, folder, folderClips) {
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

export function setMediaView(view) {
  if (state.mediaView === view) return;
  state.mediaView = view;
  DOM.dropzone.scrollTop = 0;
  renderMediaToolbar();
  if (state.snapshot) {
    renderMediaGrid(filteredClips(), state.snapshot.transport?.clip_id, state.snapshot.transport?.status);
  }
}

export function renderFolders() {
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

export function renderMediaToolbar() {
  const folder = currentFolder();
  const isFolderOverview = folder === 'All' && !hasActiveMediaFilters();
  DOM.btnBackAll.hidden = folder === 'All' && !hasActiveMediaFilters();
  DOM.btnBackAll.textContent = folder === 'All' ? 'RESET' : 'ALL';
  DOM.btnToggleMediaView.hidden = isFolderOverview;
  DOM.btnToggleMediaView.textContent = state.mediaView === 'grid' ? 'LIST' : 'GRID';
  DOM.btnToggleMediaView.classList.toggle('active', state.mediaView === 'list');

  // Bulk-select controls are hidden on the folder overview (no clips shown).
  DOM.btnSelectMode.hidden = isFolderOverview;
  DOM.btnSelectMode.textContent = state.selectMode ? 'CANCEL' : 'SELECT';
  DOM.btnSelectMode.classList.toggle('active', state.selectMode);
  DOM.btnSelectAll.hidden = isFolderOverview || !state.selectMode;
  const count = state.selection.size;
  DOM.btnDeleteSelected.hidden = isFolderOverview || !state.selectMode;
  DOM.btnDeleteSelected.textContent = count ? `DELETE (${count})` : 'DELETE';
  DOM.btnDeleteSelected.disabled = count === 0;
}

export function exitSelectMode() {
  state.selectMode = false;
  state.selection.clear();
  renderMediaToolbar();
  syncMediaGridVisualState();
}

export function renderMediaGrid(clips, activeClipId, status) {
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

export function renderFolderCards(clips) {
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

export function syncMediaGridVisualState(activeClipId = state.snapshot?.transport?.clip_id, status = state.snapshot?.transport?.status) {
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
    const clip = clipFromDeckId(node.dataset.deckId);
    node.classList.toggle('active', isActive);
    node.classList.toggle('selected', isSelected);
    node.classList.toggle('multi-selected', Boolean(clip && state.selection.has(clip.filename)));
    const overlay = node.querySelector('.status-overlay');
    if (overlay) {
      overlay.style.display = isActive && status === 'play' ? 'flex' : 'none';
    }
  });
}

export async function handleClipAction(clip, action) {
  if (action === 'play') {
    await api(`/api/clips/${clip.deck_id}/play`, { method: 'POST' });
  } else if (action === 'preview') {
    openPreviewModal(clip.deck_id);
    return;
  } else if (action === 'loop') {
    await api(`/api/clips/${clip.deck_id}/loop`, { method: 'PATCH', body: JSON.stringify({ enabled: !clip.loop_enabled }) });
  } else if (action === 'music') {
    await api(`/api/clips/${clip.deck_id}/music`, { method: 'PATCH', body: JSON.stringify({ enabled: !clip.is_music }) });
  } else if (action === 'rename') {
    const name = await requestText({
      title: 'Rename Clip',
      message: 'New clip name:',
      inputValue: clip.name,
      confirmLabel: 'SAVE'
    });
    if (name) await api(`/api/clips/${clip.deck_id}/rename`, { method: 'PATCH', body: JSON.stringify({ name }) });
  } else if (action === 'delete') {
    if (!await ensureLiveActionAllowed('Clip deletion')) return;
    const confirmed = await requestConfirm({
      title: 'Delete Clip',
      message: `Permanently delete ${clip.name}?`,
      confirmLabel: 'DELETE'
    });
    if (confirmed) {
      await api(`/api/clips/${clip.deck_id}`, { method: 'DELETE' });
    }
  }
  await refresh();
}

export async function uploadFiles(fileList) {
  if (!fileList || !fileList.length) return;
  const formData = new FormData();
  [...fileList].forEach((file) => formData.append('files', file));
  // Drop the upload into the folder currently in view (server ignores All / Library).
  formData.append('folder', currentFolder());
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
    await showNotice('Upload Error', error.message || 'Upload failed.');
    hideUploadOverlaySoon(300);
  } finally {
    if (shouldRefresh) {
      await refresh();
    }
  }
}

DOM.dropzone.addEventListener('dragover', (e) => {
  e.preventDefault();
  DOM.dropzone.classList.add('dragover');
});

DOM.dropzone.addEventListener('dragleave', () => DOM.dropzone.classList.remove('dragover'));

DOM.dropzone.addEventListener('scroll', () => {
  maybeLoadMoreMedia();
});

bindAsync(DOM.dropzone, 'drop', async (e) => {
  e.preventDefault();
  DOM.dropzone.classList.remove('dragover');
  await uploadFiles(e.dataTransfer.files);
}, 'Upload Error');

bindAsync(DOM.fileInput, 'change', async () => uploadFiles(DOM.fileInput.files), 'Upload Error');

bindAsync(DOM.btnRefreshMedia, 'click', refresh, 'Refresh Error');

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
  if (state.selectMode) {
    // In bulk mode a click toggles the clip in/out of the selection.
    event.stopPropagation();
    if (state.selection.has(clip.filename)) state.selection.delete(clip.filename);
    else state.selection.add(clip.filename);
    syncMediaGridVisualState();
    renderMediaToolbar();
    return;
  }
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
  if (state.selectMode) return;
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
  // dragend always fires on the source, even if the drop landed outside any
  // valid target — use it as a backstop to clear a pad's hover highlight that
  // a missed dragleave would otherwise leave stuck "on" indefinitely.
  DOM.padGrid.querySelectorAll('.pad-btn.drop-target').forEach((btn) => btn.classList.remove('drop-target'));
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

DOM.btnSelectMode.addEventListener('click', () => {
  if (state.selectMode) {
    exitSelectMode();
  } else {
    state.selectMode = true;
    state.selection.clear();
    renderMediaToolbar();
    syncMediaGridVisualState();
  }
});

DOM.btnSelectAll.addEventListener('click', () => {
  const visible = filteredClips();
  const allSelected = visible.length > 0 && visible.every((clip) => state.selection.has(clip.filename));
  if (allSelected) {
    visible.forEach((clip) => state.selection.delete(clip.filename));
  } else {
    visible.forEach((clip) => state.selection.add(clip.filename));
  }
  renderMediaToolbar();
  syncMediaGridVisualState();
});

bindAsync(DOM.btnDeleteSelected, 'click', async () => {
  const filenames = [...state.selection];
  if (!filenames.length) return;
  const confirmed = await requestConfirm({
    title: 'Delete clips',
    message: `Permanently delete ${filenames.length} selected clip(s)? Files on a connected disk are removed; entries for offline drives and links are removed from the library.`,
    confirmLabel: 'DELETE',
  });
  if (!confirmed) return;
  const result = await api('/api/clips/delete', { method: 'POST', body: JSON.stringify({ filenames }) });
  exitSelectMode();
  await refresh();
  await showNotice('Clips Deleted', `Removed ${result.deleted} clip(s).`);
}, 'Delete Error');

bindAsync(DOM.btnNewFolder, 'click', async () => {
  const name = await requestText({
    title: 'New Folder',
    message: 'Media folder name:',
    confirmLabel: 'CREATE'
  });
  if (!name) return;
  await api('/api/media/folders', { method: 'POST', body: JSON.stringify({ name }) });
  await refresh();
  DOM.folderFilter.value = name;
  DOM.dropzone.scrollTop = 0;
  renderMediaGrid(filteredClips(), state.snapshot.transport.clip_id, state.snapshot.transport.status);
}, 'Media Error');

bindAsync(DOM.btnAddLink, 'click', async () => {
  const url = await requestText({
    title: 'Add Network Link',
    message: 'Stream / video URL (http, https, rtsp, rtmp, hls…):',
    confirmLabel: 'ADD'
  });
  if (!url) return;
  await api('/api/clips/url', { method: 'POST', body: JSON.stringify({ url }) });
  await refresh();
  DOM.dropzone.scrollTop = 0;
}, 'Link Error');

bindAsync(DOM.btnMoveFolder, 'click', async () => {
  const clip = getSelectedClip();
  if (!clip) {
    await showNotice('Move Clip', 'Select a clip before moving it to another folder.');
    return;
  }
  const folderOptions = state.folders.filter((folder) => folder !== 'All');
  const targetFolder = await requestSelect({
    title: 'Move Clip',
    message: `Move "${clip.name}" to:`,
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
