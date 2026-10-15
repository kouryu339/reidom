export function createDirtyState({ appName = "Reidom", onChange } = {}) {
  let dirty = false;

  function update(next) {
    if (dirty === next) return;
    dirty = next;
    document.title = `${dirty ? "● " : ""}${appName}`;
    document.documentElement.dataset.projectDirty = String(dirty);
    onChange?.(dirty);
  }

  const beforeUnload = (event) => {
    if (!dirty) return;
    event.preventDefault();
    event.returnValue = "";
  };
  if (!("__TAURI_INTERNALS__" in window)) window.addEventListener("beforeunload", beforeUnload);

  return {
    isDirty: () => dirty,
    markDirty: () => update(true),
    markSaved: () => update(false),
    async confirmDiscard(message = "当前工程还有未保存修改，确定继续吗？") {
      return !dirty || await confirmAction(message, "未保存的修改", "继续");
    },
    dispose() {
      window.removeEventListener("beforeunload", beforeUnload);
    },
  };
}
import { confirmAction } from "../../shared/dialogs.js";

