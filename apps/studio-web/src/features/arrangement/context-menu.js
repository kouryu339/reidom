export function createContextMenu(report, enabled = () => true) {
  let menu = null, anchor = null;
  function close() { menu?.remove(); menu = null; }
  document.addEventListener("pointerdown", event => { if (menu && !menu.contains(event.target)) close(); });
  window.addEventListener("resize", close);
  document.addEventListener("scroll", close, true);
  document.addEventListener("keydown", event => {
    if (!menu) return;
    if (event.key === "Escape") { event.preventDefault(); event.stopImmediatePropagation(); close(); anchor?.focus(); }
    if (["ArrowDown", "ArrowUp"].includes(event.key)) {
      event.preventDefault();
      const buttons = [...menu.querySelectorAll("button:not(:disabled)")];
      const index = buttons.indexOf(document.activeElement);
      buttons[(index + (event.key === "ArrowDown" ? 1 : -1) + buttons.length) % buttons.length]?.focus();
    }
  }, true);
  return { close, open(event, actions) {
    event.preventDefault(); event.stopPropagation(); close(); anchor = event.target.closest(".clip, header");
    menu = document.createElement("div"); menu.className = "arrangement-context-menu"; menu.setAttribute("role", "menu");
    for (const action of actions) {
      const button = document.createElement("button"); button.type = "button"; button.textContent = action.label;
      button.setAttribute("role", "menuitem"); button.disabled = Boolean(action.disabled);
      if (action.danger) button.className = "danger";
      button.onclick = async () => { close(); if (!enabled()) return; try { await action.run(); } catch (error) { report(error.message); } };
      menu.append(button);
    }
    document.body.append(menu);
    const rect = menu.getBoundingClientRect();
    menu.style.left = Math.max(8, Math.min(event.clientX, innerWidth - rect.width - 8)) + "px";
    menu.style.top = Math.max(8, Math.min(event.clientY, innerHeight - rect.height - 8)) + "px";
    menu.querySelector("button:not(:disabled)")?.focus();
  }};
}
