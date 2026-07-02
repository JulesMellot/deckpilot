// Shared interaction primitives: the app dialog (confirm / text / select /
// notice), the async event binder that funnels handler errors into a notice,
// and the safe-mode guard.

import { getErrorMessage } from './util.js';
import { DOM } from './dom.js';
import { liveActionBlocked, state } from './store.js';

export function bindAsync(target, eventName, handler, errorTitle = 'Operation Error') {
  target.addEventListener(eventName, (event) => {
    Promise.resolve(handler(event)).catch(async (error) => {
      console.error(error);
      await showNotice(errorTitle, getErrorMessage(error));
    });
  });
}

export async function runShortcut(action, errorTitle) {
  try {
    await action();
  } catch (error) {
    console.error(error);
    await showNotice(errorTitle, getErrorMessage(error));
  }
}

export function closeAppDialog(result) {
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

export function submitAppDialog() {
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

export function openAppDialog({
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

export async function requestText(options) {
  const value = await openAppDialog({ ...options, showInput: true });
  const normalized = typeof value === 'string' ? value.trim() : '';
  return normalized || null;
}

export async function requestSelect(options) {
  const value = await openAppDialog({ ...options, showSelect: true });
  const normalized = typeof value === 'string' ? value.trim() : '';
  return normalized || null;
}

export async function requestConfirm(options) {
  return Boolean(await openAppDialog(options));
}

export async function showNotice(title, message) {
  await openAppDialog({
    title,
    message,
    confirmLabel: 'OK',
    showCancel: false,
  });
}

export async function ensureLiveActionAllowed(actionLabel) {
  if (!liveActionBlocked()) return true;
  await showNotice('Safe Mode', `${actionLabel} is locked while Safe Mode is enabled. Click ARM LIVE first.`);
  return false;
}

DOM.appDialogBackdrop.addEventListener('click', (event) => {
  if (event.target === DOM.appDialogBackdrop) {
    closeAppDialog(null);
  }
});

DOM.btnAppDialogClose.addEventListener('click', () => closeAppDialog(null));

DOM.btnAppDialogCancel.addEventListener('click', () => closeAppDialog(null));

DOM.btnAppDialogConfirm.addEventListener('click', submitAppDialog);
