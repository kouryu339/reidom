export function createStatusCenter(element) {
  let clearTimer = null;

  function show(message, tone = "info", timeout = 2600) {
    if (!element) return;
    window.clearTimeout(clearTimer);
    element.textContent = message;
    element.dataset.tone = tone;
    element.hidden = false;
    if (timeout > 0) {
      clearTimer = window.setTimeout(() => {
        element.hidden = true;
      }, timeout);
    }
  }

  return {
    info: (message, timeout) => show(message, "info", timeout),
    success: (message, timeout) => show(message, "success", timeout),
    error: (message, timeout = 5200) => show(message, "error", timeout),
    busy: (message) => show(message, "busy", 0),
    clear: () => {
      window.clearTimeout(clearTimer);
      if (element) element.hidden = true;
    },
  };
}
