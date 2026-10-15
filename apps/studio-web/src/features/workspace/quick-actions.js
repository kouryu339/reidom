const ACTIONS = {
  "new-track": { label: "新建轨道", icon: "＋", tone: "primary" },
  "new-clip": { label: "新建片段", icon: "＋" },
  "open-editor": { label: "编辑音符", icon: "⌘", tone: "primary" },
  "clip-properties": { label: "片段属性", icon: "◇" },
  duplicate: { label: "复制", icon: "⧉", shortcut: "Ctrl+D" },
  split: { label: "分割", icon: "╱", shortcut: "S" },
  quantize: { label: "量化", icon: "▦", shortcut: "Q" },
  loop: { label: "设为循环", icon: "↻", shortcut: "L" },
  effects: { label: "轨道设置", icon: "FX" },
  delete: { label: "删除", icon: "×", tone: "danger", shortcut: "Delete" },
};

export function createQuickActions({ root, getProject, getSelection, getActiveTrack, onAction }) {
  if (!root) return { render() {} };

  const contextTitle = root.querySelector("[data-context-title]");
  const contextMeta = root.querySelector("[data-context-meta]");
  const actionList = root.querySelector("[data-context-actions]");

  root.addEventListener("click", (event) => {
    const button = event.target.closest("[data-quick-action]");
    if (!button || button.disabled) return;
    void onAction(button.dataset.quickAction);
  });

  function render() {
    const project = getProject();
    if (project?.editing?.mode !== "manual") {
      contextTitle.textContent = "作品预览";
      contextMeta.textContent = "由 AI 编曲，进入手动编辑可以调整音符和片段";
      actionList.replaceChildren();
      return;
    }
    const selection = getSelection();
    const activeTrack = getActiveTrack();
    const selectedNoteIds = selection?.selected_note_ids || [];
    const selectedClipIds = selection?.selected_clip_ids || [];
    const selectedClips = (project?.clips || []).filter((clip) => selectedClipIds.includes(clip.clip_id));

    let title = activeTrack?.name || "编曲区";
    let meta = activeTrack ? "轨道已就绪" : "先新建轨道或导入 MIDI";
    let actionKeys = ["new-track"];

    if (activeTrack) actionKeys.push("new-clip");

    if (selectedNoteIds.length) {
      title = "已选 " + selectedNoteIds.length + " 个音符";
      meta = (activeTrack?.name || "当前轨道") + " · 可直接移动、量化或复制";
      actionKeys = ["new-track", "new-clip", "duplicate", "quantize", "delete", "effects"];
    } else if (selectedClips.length) {
      const clip = selectedClips[0];
      title = selectedClips.length === 1 ? (clip.name || "MIDI 片段") : "已选 " + selectedClips.length + " 个片段";
      meta = selectedClips.length === 1
        ? formatBeat(clip.start_beats) + " 拍起 · " + formatBeat(clip.duration_beats) + " 拍"
        : "可批量复制、移动或删除";
      actionKeys = ["new-track", "new-clip", "open-editor", "duplicate", "delete"];
    } else if (activeTrack) {
      meta = "双击空白处也可创建片段";
      actionKeys.push("effects");
    }

    contextTitle.textContent = title;
    contextMeta.textContent = meta;
    actionList.replaceChildren(...actionKeys.map(createActionButton));
  }

  return { render };
}

function createActionButton(key) {
  const action = ACTIONS[key];
  const button = document.createElement("button");
  button.type = "button";
  button.dataset.quickAction = key;
  button.className = "context-action" + (action.tone ? " " + action.tone : "");
  button.title = action.shortcut ? action.label + " · " + action.shortcut : action.label;

  const icon = document.createElement("span");
  icon.textContent = action.icon;
  const label = document.createElement("strong");
  label.textContent = action.label;
  button.append(icon, label);
  if (action.shortcut) {
    const shortcut = document.createElement("kbd");
    shortcut.textContent = action.shortcut;
    button.append(shortcut);
  }
  return button;
}

function formatBeat(value) {
  const number = Number(value || 0);
  return Number.isInteger(number) ? String(number) : number.toFixed(2).replace(/0+$/, "").replace(/\.$/, "");
}
