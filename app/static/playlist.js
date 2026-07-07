// Playlist panel: rundown rendering and virtualization, end-behavior
// cycling, reordering, and play/activate actions.

import { api } from './util.js';
import { DOM, Templates } from './dom.js';
import { getSelectedClip, playlistItemFromPosition, pruneNodeCache, state, viewedPlaylistPayload } from './store.js';
import { bindAsync, requestConfirm, requestText } from './dialogs.js';
import { syncMediaGridVisualState } from './media.js';
import { renderPreview } from './preview.js';
import { refresh } from './app.js';

export const PLAYLIST_VIRTUALIZATION_THRESHOLD = 150;

export const PLAYLIST_VIRTUALIZATION_BATCH = 80;

export const END_BEHAVIOR_LABELS = { next: 'AUTO', stop: 'STOP', hold: 'HOLD', loop: 'LOOP' };

export const END_BEHAVIOR_CYCLE = ['next', 'stop', 'hold', 'loop'];

export function playlistVirtualDatasetKey(items, playlistId) {
  return `${playlistId || 'none'}::${items.length}`;
}

export function ensurePlaylistRenderLimit(items, playlistId) {
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

export function maybeLoadMorePlaylist(force = false) {
  const items = viewedPlaylistPayload().items || [];
  if (!state.playlistVirtualEnabled) return false;
  if (state.playlistRenderLimit >= items.length) return false;
  const nearBottom = DOM.playlistItems.scrollTop + DOM.playlistItems.clientHeight >= DOM.playlistItems.scrollHeight - 400;
  if (!force && !nearBottom) return false;
  const nextLimit = Math.min(items.length, state.playlistRenderLimit + PLAYLIST_VIRTUALIZATION_BATCH);
  if (nextLimit === state.playlistRenderLimit) return false;
  state.playlistRenderLimit = nextLimit;
  renderPlaylist(viewedPlaylistPayload(), state.snapshot?.transport?.clip_id);
  return true;
}

export function schedulePlaylistVirtualizationCheck() {
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

export function getOrCreatePlaylistNode(playlistId, item) {
  const key = `${playlistId}:${item.position}`;
  if (!state.playlistNodeCache.has(key)) {
    state.playlistNodeCache.set(key, Templates.playlistItem.content.firstElementChild.cloneNode(true));
  }
  return state.playlistNodeCache.get(key);
}

export function updatePlaylistNode(node, item, activeClipId) {
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
  node.querySelector('.playlist-item-music').classList.toggle('is-on', Boolean(item.is_music));
  node.classList.toggle('active', item.clip_id === activeClipId);
  node.classList.toggle('selected', item.position === state.selectedPlaylistPosition);
}

export function currentPlaylistId() {
  return Number(DOM.playlistSelect.value || state.snapshot?.playlist?.playlist?.id || 0);
}

// The panel edits the playlist chosen in the dropdown, active or not. For a
// non-active playlist (no WebSocket push), fetch its items explicitly.
export async function refreshViewedPlaylist() {
  const playlistId = currentPlaylistId();
  const activeId = state.snapshot?.playlist?.playlist?.id;
  if (!playlistId || playlistId === activeId) {
    state.viewedPlaylist = null;
  } else {
    state.viewedPlaylist = await api(`/api/playlists/${playlistId}`);
  }
  renderPlaylist(viewedPlaylistPayload(), state.snapshot?.transport?.clip_id);
}

export async function playPlaylist() {
  const loop = Boolean(state.snapshot?.transport?.playlist_loop);
  const playlistId = currentPlaylistId();
  if (playlistId) {
    // Play the playlist being *viewed* (activating it if needed), not the
    // active one — otherwise PLAY on a browsed rundown fires another list.
    await api(`/api/playlists/${playlistId}/play-from`, {
      method: 'POST',
      body: JSON.stringify({ position: 1, loop })
    });
    return;
  }
  await api('/api/playlists/play', {
    method: 'POST',
    body: JSON.stringify({ loop })
  });
}

export async function playPlaylistFromSelection() {
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

export async function playNextPlaylistSelection() {
  const playlistId = currentPlaylistId();
  if (!playlistId) return;
  await api(`/api/playlists/${playlistId}/next`, { method: 'POST' });
}

export async function clearCurrentPlaylist() {
  const playlistId = currentPlaylistId();
  if (!playlistId) return;
  const confirmed = await requestConfirm({
    title: 'Clear Playlist',
    message: 'Remove every item from this playlist?',
    confirmLabel: 'CLEAR'
  });
  if (!confirmed) return;
  await api(`/api/playlists/${playlistId}/items`, { method: 'DELETE' });
  state.selectedPlaylistPosition = 1;
  await refreshViewedPlaylist();
  await refresh();
}

export async function addSelectedClipToPlaylist() {
  const clip = getSelectedClip();
  const playlistId = currentPlaylistId();
  if (!clip || !playlistId) return;
  await api(`/api/playlists/${playlistId}/items`, {
    method: 'POST',
    body: JSON.stringify({ clip_id: clip.deck_id })
  });
  await refreshViewedPlaylist();
  await refresh();
}

export function renderPlaylists() {
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

export function renderPlaylist(playlistPayload, activeClipId) {
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

export function syncPlaylistVisualState(activeClipId = state.snapshot?.transport?.clip_id) {
  if (state.playlistVirtualEnabled) {
    const items = viewedPlaylistPayload().items || [];
    const selectedIndex = items.findIndex((item) => item.position === state.selectedPlaylistPosition);
    const activeIndex = items.findIndex((item) => item.clip_id === activeClipId);
    const requiredLimit = Math.max(selectedIndex, activeIndex) + 1;
    if (requiredLimit > state.playlistRenderLimit) {
      state.playlistRenderLimit = Math.min(items.length, requiredLimit + 10);
      renderPlaylist(viewedPlaylistPayload(), activeClipId);
      return;
    }
  }
  const selectedPosition = String(state.selectedPlaylistPosition || '');
  DOM.playlistItems.querySelectorAll('.playlist-item').forEach((node) => {
    node.classList.toggle('active', node.dataset.clipId === String(activeClipId || ''));
    node.classList.toggle('selected', node.dataset.position === selectedPosition);
  });
}

DOM.playlistItems.addEventListener('scroll', () => {
  maybeLoadMorePlaylist();
});

bindAsync(DOM.playlistItems, 'click', async (event) => {
  const removeNode = event.target.closest('.playlist-item-remove');
  const endNode = event.target.closest('.playlist-item-end');
  const musicNode = event.target.closest('.playlist-item-music');
  const moveNode = event.target.closest('.playlist-item-move');
  const playlistNode = event.target.closest('.playlist-item');
  if (!playlistNode) return;
  const item = playlistItemFromPosition(playlistNode.dataset.position);
  if (!item) return;
  if (endNode) {
    event.stopPropagation();
    const playlistId = currentPlaylistId();
    if (!playlistId) return;
    const nextBehavior = END_BEHAVIOR_CYCLE[(END_BEHAVIOR_CYCLE.indexOf(item.end_behavior || 'next') + 1) % END_BEHAVIOR_CYCLE.length];
    await api(`/api/playlists/${playlistId}/items/${item.position}`, {
      method: 'PATCH',
      body: JSON.stringify({ end_behavior: nextBehavior }),
    });
    await refreshViewedPlaylist();
    return;
  }
  if (musicNode) {
    event.stopPropagation();
    const playlistId = currentPlaylistId();
    if (!playlistId) return;
    await api(`/api/playlists/${playlistId}/items/${item.position}`, {
      method: 'PATCH',
      body: JSON.stringify({ is_music: !item.is_music }),
    });
    await refreshViewedPlaylist();
    return;
  }
  if (moveNode) {
    event.stopPropagation();
    const playlistId = currentPlaylistId();
    if (!playlistId) return;
    const items = viewedPlaylistPayload().items || [];
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
    await refreshViewedPlaylist();
    return;
  }
  if (removeNode) {
    event.stopPropagation();
    const playlistId = currentPlaylistId();
    if (!playlistId) return;
    await api(`/api/playlists/${playlistId}/items/${item.position}`, { method: 'DELETE' });
    await refreshViewedPlaylist();
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
  const playlistId = currentPlaylistId();
  if (!item || !playlistId) return;
  state.selectedPlaylistPosition = item.position;
  syncPlaylistVisualState();
  // The server activates the playlist if needed; the panel then mirrors it.
  await api(`/api/playlists/${playlistId}/play-from`, {
    method: 'POST',
    body: JSON.stringify({ position: item.position })
  });
  state.viewedPlaylist = null;
  await refresh();
}, 'Playlist Error');

bindAsync(DOM.playlistSelect, 'change', async () => {
  state.selectedPlaylistPosition = 1;
  await refreshViewedPlaylist();
}, 'Playlist Error');

bindAsync(DOM.btnNewPlaylist, 'click', async () => {
  const name = await requestText({
    title: 'New Playlist',
    message: 'Nom de la playlist :',
    confirmLabel: 'CREATE'
  });
  if (!name) return;
  const created = await api('/api/playlists', {
    method: 'POST',
    body: JSON.stringify({ name, clip_ids: [], activate: false })
  });
  await refresh();
  // Jump straight into the new (empty) playlist so ADD SELECTED lands in it.
  if (created?.playlist?.id) {
    DOM.playlistSelect.value = String(created.playlist.id);
    await refreshViewedPlaylist();
  }
}, 'Playlist Error');

bindAsync(DOM.btnRenamePlaylist, 'click', async () => {
  const playlistId = currentPlaylistId();
  if (!playlistId) return;
  const playlist = state.playlists.find((entry) => entry.id === playlistId);
  const name = await requestText({
    title: 'Rename Playlist',
    message: 'Nouveau nom :',
    inputValue: playlist?.name || '',
    confirmLabel: 'RENAME'
  });
  if (!name || name === playlist?.name) return;
  await api(`/api/playlists/${playlistId}`, {
    method: 'PATCH',
    body: JSON.stringify({ name })
  });
  await refresh();
}, 'Playlist Error');

bindAsync(DOM.btnDeletePlaylist, 'click', async () => {
  const playlistId = currentPlaylistId();
  if (!playlistId) return;
  const playlist = state.playlists.find((entry) => entry.id === playlistId);
  const confirmed = await requestConfirm({
    title: 'Delete Playlist',
    message: `Supprimer la playlist "${playlist?.name || playlistId}" et son contenu ?`,
    confirmLabel: 'DELETE'
  });
  if (!confirmed) return;
  await api(`/api/playlists/${playlistId}`, { method: 'DELETE' });
  state.viewedPlaylist = null;
  await refresh();
}, 'Playlist Error');

bindAsync(DOM.btnActivatePlaylist, 'click', async () => {
  const playlistId = currentPlaylistId();
  if (!playlistId) return;
  await api(`/api/playlists/${playlistId}/activate`, { method: 'POST' });
  state.viewedPlaylist = null;
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
