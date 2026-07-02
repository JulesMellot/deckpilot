// Preview modal: in-browser playback, in/out marks, tags, still duration.

import { api, formatClock } from './util.js';
import { DOM } from './dom.js';
import { getSelectedClip, state } from './store.js';
import { bindAsync, openAppDialog, showNotice } from './dialogs.js';
import {
  clipDurationLabel,
  clipResolutionLabel,
  mediaArtworkUrl,
  mediaKindLabel,
  mediaSourceUrl,
} from './media.js';
import { addSelectedClipToPlaylist, cueClip } from './app.js';

export function openPreviewModal(clipId) {
  state.selectedClipId = clipId;
  renderPreview();
  DOM.previewModal.hidden = false;
  if (!DOM.previewVideo.hidden) {
    DOM.previewVideo.currentTime = 0;
  }
}

export function closePreviewModal() {
  DOM.previewVideo.pause();
  DOM.previewVideo.removeAttribute('src');
  DOM.previewVideo.load();
  DOM.previewImage.hidden = true;
  DOM.previewImage.removeAttribute('src');
  DOM.previewImage.removeAttribute('alt');
  DOM.previewModal.hidden = true;
}

export function renderPreview() {
  const clip = getSelectedClip();
  if (!clip) {
    DOM.previewTitle.textContent = 'No clip selected';
    DOM.previewSubtitle.textContent = 'Select a clip to preview it in the browser.';
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
  if (clip.is_remote) {
    // The browser cannot reliably stream the link (CORS / HLS); it plays on the
    // program output instead. Show the captured thumbnail, or a placeholder.
    DOM.previewVideo.pause();
    DOM.previewVideo.removeAttribute('src');
    DOM.previewVideo.load();
    DOM.previewVideo.hidden = true;
    DOM.previewMarks.hidden = true;
    const artwork = mediaArtworkUrl(clip);
    DOM.previewImage.hidden = !artwork;
    if (artwork) {
      DOM.previewImage.alt = clip.name;
      if (DOM.previewImage.getAttribute('src') !== artwork) DOM.previewImage.src = artwork;
    } else {
      DOM.previewImage.removeAttribute('src');
    }
    DOM.previewSubtitle.textContent = `${subtitleParts.join(' | ')} | NETWORK LINK — plays on program output`;
    return;
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

export function previewMarkDuration(clip) {
  return Math.max(0, Number(clip?.duration_seconds || DOM.previewVideo.duration || 0));
}

export function renderPreviewMarks() {
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

export function updatePreviewPlayhead() {
  const clip = getSelectedClip();
  if (!clip || clip.media_kind !== 'video') return;
  const duration = previewMarkDuration(clip);
  const current = Number(DOM.previewVideo.currentTime || 0);
  const pct = duration > 0 ? Math.min(100, Math.max(0, (current / duration) * 100)) : 0;
  DOM.previewMarksPlayhead.style.left = `${pct}%`;
}

export async function commitPreviewMark(kind) {
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

DOM.previewModal.addEventListener('click', (event) => {
  if (event.target === DOM.previewModal) {
    closePreviewModal();
  }
});

DOM.btnPreviewClose.addEventListener('click', closePreviewModal);

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
    await showNotice('Still Duration', 'Duration must be a positive number of seconds.');
    return;
  }
  await api(`/api/clips/${clip.deck_id}/duration`, { method: 'PATCH', body: JSON.stringify({ seconds }) });
}, 'Media Error');

bindAsync(DOM.btnPreviewTags, 'click', async () => {
  const clip = getSelectedClip();
  if (!clip) return;
  const value = await openAppDialog({
    title: 'Edit Tags',
    message: `Tags for "${clip.name}" (comma separated, empty to clear):`,
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
