let active = false;

export function showDialog({ title, message = "", confirmLabel = "确定", value, maxLength = 80, danger = false }) {
  if (active) return Promise.resolve(null);
  active = true;
  const previousFocus = document.activeElement;
  const dialog = document.createElement("dialog");
  dialog.className = "settings-dialog new-project-dialog app-dialog";
  dialog.setAttribute("aria-labelledby", "app-dialog-title");
  const form = document.createElement("form");
  const heading = document.createElement("h2");
  heading.id = "app-dialog-title"; heading.textContent = title;
  form.append(heading);
  if (message) {
    const copy = document.createElement("p");
    copy.id = "app-dialog-message"; copy.textContent = message;
    dialog.setAttribute("aria-describedby", copy.id); form.append(copy);
  }
  let input;
  if (value !== undefined) {
    const label = document.createElement("label"); label.textContent = "名称";
    input = document.createElement("input"); input.value = value; input.required = true; input.maxLength = maxLength;
    input.addEventListener("input", () => input.setCustomValidity(""));
    label.append(input); form.append(label);
  }
  const footer = document.createElement("footer");
  const cancel = document.createElement("button"); cancel.type = "button"; cancel.textContent = "取消";
  const confirm = document.createElement("button"); confirm.type = "submit"; confirm.textContent = confirmLabel;
  confirm.className = danger ? "dialog-danger" : "dialog-primary";
  footer.append(cancel, confirm); form.append(footer); dialog.append(form); document.body.append(dialog);
  return new Promise(resolve => {
    let result = null;
    dialog.addEventListener("close", () => {
      active = false; dialog.remove();
      if (previousFocus?.isConnected) previousFocus.focus();
      resolve(result);
    }, { once: true });
    cancel.onclick = () => dialog.close();
    form.onsubmit = event => {
      event.preventDefault();
      if (input && !input.value.trim()) { input.setCustomValidity("请输入名称"); input.reportValidity(); return; }
      result = input ? input.value.trim() : true; dialog.close();
    };
    dialog.showModal();
    if (input) { input.focus(); input.select(); } else cancel.focus();
  });
}

export async function confirmAction(message, title = "确认操作", confirmLabel = "确定") {
  return await showDialog({ title, message, confirmLabel, danger: true }) === true;
}

export function requestName(title, value) { return showDialog({ title, value, confirmLabel: "保存" }); }
