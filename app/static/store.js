// Shared UI state and the single ordered apply path. DOM-free on purpose so
// node tests can import it directly.

export const state = {
  snapshot: null,
  clipIndex: new Map(),
  mediaNodeCache: new Map(),
  playlistNodeCache: new Map(),
  folderNodeCache: new Map(),
  dragClipId: null,
  selectedClipId: null,
  // Bulk-select mode: keyed by filename (stable), unlike the positional deck_id.
  selectMode: false,
  selection: new Set(),
  selectedPlaylistPosition: 1,
  // Payload of a non-active playlist being viewed/edited in the panel;
  // null means the panel mirrors the active playlist from the snapshot.
  viewedPlaylist: null,
  folders: [],
  playlists: [],
  dialogResolver: null,
  logsVisible: true,
  mediaView: 'grid',
  updateStatus: null,
  updatePollTimer: null,
  updatePollInFlight: false,
  websocketReconnectTimer: null,
  websocketReconnectAttempts: 0,
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

// One ordered apply path for the shared snapshot. Every write — full fetches
// and incremental WebSocket messages alike — takes a ticket when it starts,
// and only lands if nothing newer landed first, so a slow fetch response can
// never overwrite fresher WebSocket state or an optimistic local write.
// Dropping a stale fetch is safe: the server broadcasts every change over the
// socket, so whatever superseded the fetch has already been applied.
let stateWriteSeq = 0;
let appliedWriteSeq = 0;
export function beginStateWrite() {
  return ++stateWriteSeq;
}
export function applyState(ticket, write) {
  if (ticket < appliedWriteSeq) return false;
  appliedWriteSeq = ticket;
  write();
  return true;
}
// Synchronous writes (WebSocket messages, optimistic UI updates) land
// immediately; taking a ticket invalidates any fetch already in flight.
export function applyStateNow(write) {
  applyState(beginStateWrite(), write);
}

export function reindexClips(clips) {
  state.clipIndex = new Map((clips || []).map((clip) => [clip.deck_id, clip]));
}

export function pruneNodeCache(cache, validKeys) {
  for (const key of [...cache.keys()]) {
    if (!validKeys.has(key)) {
      cache.delete(key);
    }
  }
}

export function viewedPlaylistPayload() {
  return state.viewedPlaylist || state.snapshot?.playlist || { playlist: null, items: [] };
}

export function normalizeSelection() {
  const clips = state.snapshot?.clips || [];
  const playlistItems = viewedPlaylistPayload().items || [];
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

export function clipFromDeckId(deckId) {
  return state.clipIndex.get(Number(deckId)) || null;
}

export function getSelectedClip() {
  return state.clipIndex.get(state.selectedClipId) || null;
}

export function playlistItemFromPosition(position) {
  const items = viewedPlaylistPayload().items || [];
  return items.find((item) => String(item.position) === String(position)) || null;
}

export function padEntries() {
  return state.snapshot?.pads || [];
}

export function liveActionBlocked() {
  const safety = state.snapshot?.safety;
  return Boolean(safety?.safe_mode_enabled && !safety?.live_controls_armed);
}
