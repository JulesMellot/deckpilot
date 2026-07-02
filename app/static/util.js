// Pure helpers — no DOM, no state, no imports.

export function formatClock(seconds) {
  const total = Math.max(0, Math.round(seconds || 0));
  const hrs = Math.floor(total / 3600).toString().padStart(2, '0');
  const mins = Math.floor((total % 3600) / 60).toString().padStart(2, '0');
  const secs = (total % 60).toString().padStart(2, '0');
  return `${hrs}:${mins}:${secs}`;
}

export function formatRemainingClock(seconds) {
  return `-${formatClock(seconds)}`;
}

export function formatEta(seconds) {
  if (seconds === null || seconds === undefined) return 'ETA --';
  return `ETA ${formatClock(seconds)}`;
}

export function formatUptimeMinutes(minutes) {
  const total = Math.max(0, Number(minutes || 0));
  if (total < 60) return `${total}m`;
  const hours = Math.floor(total / 60);
  if (hours < 24) return `${hours}h ${total % 60}m`;
  return `${Math.floor(hours / 24)}d ${hours % 24}h`;
}

export function formatDateTime(timestampSeconds) {
  if (!timestampSeconds) return 'n/a';
  return new Date(timestampSeconds * 1000).toLocaleString('en-GB', { hour12: false });
}

export function formatBytes(value) {
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

export async function api(path, options = {}) {
  const isFormData = options.body instanceof FormData;
  const headers = isFormData ? (options.headers || {}) : { 'Content-Type': 'application/json', ...(options.headers || {}) };
  const response = await fetch(path, { ...options, headers });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || response.statusText);
  }
  return response.status === 204 ? null : response.json();
}

export function getErrorMessage(error, fallback = 'Unexpected error.') {
  if (error instanceof Error && error.message) return error.message;
  if (typeof error === 'string' && error.trim()) return error;
  return fallback;
}
