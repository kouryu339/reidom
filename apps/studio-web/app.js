import "@agent-runtime/conversation-element";
import { configureAssistant } from "./src/features/assistant/conversation.js";
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { ReidomRuntimeBridge, ReidomService } from "./service.js";
import { countEnabledEffects, createTrackEffectsController } from "./src/features/effects/track-effects.js";
import { createQuickActions } from "./src/features/workspace/quick-actions.js";
import { createClipInspector } from "./src/features/clips/clip-inspector.js";
import { createDirtyState } from "./src/features/project/dirty-state.js";
import { createDeviceSettingsController } from "./src/features/settings/device-settings.js";
import { createStatusCenter } from "./src/shared/ui-status.js";
import { createArrangementController } from "./src/features/arrangement/arrangement-controller.js";
import { createPianoRollController } from "./src/features/piano-roll/piano-roll-controller.js";
import { createEditMode } from "./src/features/workspace/edit-mode.js";
import { requestNewProject } from "./src/features/project/new-project-dialog.js";
import { createProjectLibrary } from "./src/features/project/project-library.js";
import { requestNewTrack } from "./src/features/project/new-track-dialog.js";
import { confirmAction, requestName } from "./src/shared/dialogs.js";

let assistantConversation = null;

const EDITOR_MODEL = {
  transportStates: [
    { key: "loop", label: "循环", value: "开" },
    { key: "punch", label: "穿插录音", value: "关" },
    { key: "metro", label: "节拍器", value: "开" },
    { key: "sync", label: "同步", value: "内部" },
  ],
  trackControls: [
    { key: "record", label: "●", title: "录音预备" },
    { key: "monitor", label: "◉", title: "输入监听" },
    { key: "mute", label: "静", title: "静音" },
    { key: "solo", label: "独", title: "独奏" },
  ],
  inspectorRack: [
    { key: "input", label: "输入", value: "全部 MIDI 输入" },
    { key: "output", label: "输出", value: "主输出" },
    { key: "playlist", label: "片段列表", value: "主版本" },
    { key: "insert", label: "效果器", value: "乐器 / 效果" },
    { key: "send", label: "发送", value: "辅助 / 返送" },
    { key: "group", label: "编组", value: "无" },
  ],
  routeProperties: [
    { label: "类型", value: "MIDI 轨道" },
    { label: "片段列表", value: "主版本" },
    { label: "输入", value: "全部 MIDI 输入" },
    { label: "输出", value: "主输出" },
    { label: "自动化", value: "读取" },
    { label: "延迟", value: "0 采样" },
  ],
  globalTracks: [
    { key: "marker", label: "段落", values: ["前奏", "主歌", "副歌", "尾奏"] },
    { key: "signature", label: "拍号", values: ["4/4", "4/4", "4/4", "4/4"] },
    { key: "tempo", label: "速度", values: ["96", "96", "98", "96"] },
  ],
  controllerLanes: [
    { key: "velocity", label: "力度", values: [58, 74, 91, 68, 82, 97, 73, 88] },
    { key: "cc1", label: "调制", values: [18, 28, 36, 52, 64, 58, 42, 30] },
    { key: "cc11", label: "表情", values: [72, 76, 80, 78, 70, 66, 74, 82] },
  ],
  eventColumns: [
    { key: "start", label: "起点", value: (note) => formatBeat(note.start_beats) },
    { key: "pitch", label: "音高", value: (note) => noteName(note.pitch) },
    { key: "length", label: "长度", value: (note) => formatBeat(note.duration_beats) },
    { key: "velocity", label: "力度", value: (note) => note.velocity || 0 },
    { key: "track", label: "轨道", value: (note) => note.track_id },
  ],
};

const state = {
  service: null,
  runtime: null,
  runtimeStatus: null,
  snapshotBundle: null,
  project: emptyProject(),
  selection: emptySelection(),
  commandLog: null,
  trackControls: {},
  activeTrackId: null,
  editorOpen: false,
  detailPanel: null,
  view: { zoomX: 1, scrollBeat: 0, pitchTop: 84, visiblePitches: 33 },
  arrangementScrollLeft: 0,
  arrangementPixelsPerBeat: 32,
  noteHitRegions: [],
  velocityHitRegions: [],
  rollMetrics: null,
  interaction: null,
  clipInteraction: null,
  rangeInteraction: null,
  pendingClearSelection: null,
  recentPointerInputAt: 0,
  velocityCommandAppliedAt: 0,
  messages: [
    {
      role: "assistant",
      text: "告诉我你想创作、编配或改善什么。",
    },
  ],
};

const el = {
  appShell: document.querySelector("#app-shell"),
  toggleBrowser: document.querySelector("#toggle-browser"),
  toggleCopilot: document.querySelector("#toggle-copilot"),
  centerWorkspace: document.querySelector("#center-workspace"),
  dropZone: document.querySelector("#drop-zone"),
  fileInput: document.querySelector("#midi-file"),
  projectFileInput: document.querySelector("#project-file"),
  importMidiButton: document.querySelector("#import-midi"),
  newProject: document.querySelector("#new-project"),
  openProject: document.querySelector("#open-project"),
  saveProject: document.querySelector("#save-project"),
  projectTitle: document.querySelector("#project-title"),
  trackCount: document.querySelector("#track-count"),
  noteCount: document.querySelector("#note-count"),
  tempoValue: document.querySelector("#tempo-value"),
  tempoInput: document.querySelector("#tempo-input"),
  barReadout: document.querySelector("#bar-readout"),
  transportButtons: document.querySelectorAll("[data-transport]"),
  trackList: document.querySelector("#track-list"),
  addTrack: document.querySelector("#add-track"),
  arrangementGrid: document.querySelector("#arrangement-grid"),
  timelineViewport: document.querySelector("#timeline-viewport"),
  barScale: document.querySelector("#bar-scale"),
  activeTrackLabel: document.querySelector("#active-track-label"),
  canvas: document.querySelector("#piano-roll"),
  hostPill: document.querySelector("#host-pill"),
  aiContext: document.querySelector("#ai-context"),
  selectionJson: document.querySelector("#selection-json"),
  publishSelection: document.querySelector("#publish-selection"),
  mockMidi: document.querySelector("#mock-midi"),
  undo: document.querySelector("#undo-command"),
  redo: document.querySelector("#redo-command"),
  exportMidi: document.querySelector("#export-midi"),
  exportWav: document.querySelector("#export-wav"),
  gridSelect: document.querySelector("#grid-select"),
  selectionSummary: document.querySelector("#selection-summary"),
  selectionDetails: document.querySelector("#selection-details"),
  conversation: document.querySelector("#conversation"),
  commandLog: document.querySelector("#command-log"),
  eventList: document.querySelector("#event-list"),
  inspectorRack: document.querySelector("#inspector-rack"),
  globalTracks: document.querySelector("#global-tracks"),
  controllerLanes: document.querySelector("#controller-lanes"),
  routeProperties: document.querySelector("#route-properties"),
  closeEditor: document.querySelector("#close-editor"),
  setLoopRange: document.querySelector("#set-loop-range"),
  openDeviceSettings: document.querySelector("#open-device-settings"),
  deviceSettingsDialog: document.querySelector("#device-settings-dialog"),
  globalStatus: document.querySelector("#global-status"),
  clipInspector: document.querySelector("#clip-inspector"),
  contextBar: document.querySelector("#context-bar"),
  trackEffectsPanel: document.querySelector("#track-effects-panel"),
  closeClipProperties: document.querySelector("#close-clip-properties"),
};

let projectRefreshTimer = null;
let autosaveTimer = null;
let transportPollInFlight = false;
let conversationConnectInFlight = null;
const statusCenter = createStatusCenter(el.globalStatus);
const dirtyState = createDirtyState({
  appName: "Reidom Studio",
  onChange: (dirty) => el.saveProject?.classList.toggle("dirty", dirty),
});
let deviceSettings = null;
const editMode = createEditMode({ state, service: () => state.service,
  refresh: () => refreshHostContext(), report: (message) => statusCenter.error(message) });
const projectLibrary = createProjectLibrary({
  service: () => state.service, current: () => state.project,
  open: openLibraryProject, create: createNewProject, save: saveLocalProject,
  importFile: () => el.projectFileInput.click(),
});
const exportProjectButton = document.createElement("button");
exportProjectButton.type = "button";
exportProjectButton.textContent = "导出工程文件";
exportProjectButton.addEventListener("click", exportProjectFile);
document.querySelector(".project-menu-body").append(exportProjectButton);
el.openProject.textContent = "导入工程文件";
const clipInspector = createClipInspector({
  root: el.clipInspector,
  getProject: () => state.project,
  getSelection: () => state.selection,
  executeCommand: (type, payload) => executeProjectCommand(type, payload, { quiet: true }),
  getPlayheadBeat: transportPositionBeats,
});
const quickActions = createQuickActions({
  root: el.contextBar,
  getProject: () => state.project,
  getSelection: () => state.selection,
  getActiveTrack: currentTrack,
  onAction: handleQuickAction,
});
const trackEffects = createTrackEffectsController({
  root: el.trackEffectsPanel,
  getTrack: currentTrack,
  executeCommand: (type, payload) => executeProjectCommand(type, payload, { quiet: true }),
  updateRoute: updateRouteState,
  resolveInstrumentRole: instrumentRole,
  onClose: () => setDetailPanel(null),
});

const pianoRoll = createPianoRollController({
  state,
  elements: { canvas: el.canvas, gridSelect: el.gridSelect },
  executeCommand: executeProjectCommand,
  getProjectNotes: projectNotes,
  getProjectEndBeat: projectEndBeat,
  getSelectedNoteIds: selectedNoteIds,
  getCurrentTrack: currentTrack,
  helpers: { clamp, formatBeat, noteName, roundRect, snapBeat, trackColor },
});
const {
  render: renderPianoRoll,
  runViewAction,
  handleWheel: handlePianoRollWheel,
  handlePointerDown: handlePianoRollPointerDown,
  handlePointerMove: handlePianoRollPointerMove,
  handlePointerUp: handlePianoRollPointerUp,
  handleClickFallback: handlePianoRollClickFallback,
  addNote: addNoteFromCanvas,
  cancelInteraction: cancelPianoRollInteraction,
  selectAllNotes,
  ensureTrackPitchesVisible,
  clampViewToProject,
} = pianoRoll;

const arrangement = createArrangementController({
  state,
  elements: {
    arrangementGrid: el.arrangementGrid,
    timelineViewport: el.timelineViewport,
    barScale: el.barScale,
  },
  editorModel: EDITOR_MODEL,
  executeCommand: executeProjectCommand,
  getProjectEndBeat: projectEndBeat,
  getSelectedClipIds: selectedClipIds,
  getSelectedTrackIds: selectedTrackIds,
  getTransportBeat: transportPositionBeats,
  beatToPosition: beatToTransportPosition,
  getBeatsPerBar: currentBeatsPerBar,
  renderTransport,
  renderApp: render,
  setDetailPanel,
  ensureTrackPitchesVisible,
  toggleTrackControl,
  openTrackEffects,
  countEnabledEffects,
  trackControlButton,
  routeControlValue,
  roleLabel,
  addTrack,
  reportError: message => statusCenter.error(message),
  helpers: { clamp, escapeHtml, snapBeat },
});
const {
  render: renderArrangement,
  syncSelectionVisuals,
  selectTrack: selectArrangementTrack,
  syncScroll: syncArrangementScroll,
  handleWheel: handleArrangementWheel,
  handleRulerClick: handleTimelineRulerClick,
  handleClipPointerMove,
  handleClipPointerUp,
  handleRangePointerMove,
  handleRangePointerUp,
} = arrangement;

boot();

async function boot() {
  state.service = new ReidomService();
  await state.service.hydrate();
  deviceSettings = createDeviceSettingsController({
    dialog: el.deviceSettingsDialog,
    service: state.service,
    status: statusCenter,
  });
  state.runtime = new ReidomRuntimeBridge();
  state.runtimeStatus = await state.runtime.hydrate({
    onStatus: (status) => {
      state.runtimeStatus = status;
      updateHostPill();
      if (status.healthy) void connectConversation();
    },
    onDiagnostic: (payload) => {
      console.warn("AI runtime diagnostic", payload);
    },
  });
  configureConversation();
  wireEvents();
  render();
  const restored = await state.service.restoreAutosave().catch(() => null);
  if (restored) {
    setProjectState(restored.project, restored.selection);
    render();
    dirtyState.markDirty();
    statusCenter.info("已恢复上次自动保存的工程");
  } else {
    await refreshHostContext();
  }
  window.setInterval(refreshTransportPosition, 80);
  if (state.service.isNative) {
    const { getCurrentWindow } = await import("@tauri-apps/api/window");
    const windowHandle = getCurrentWindow();
    let allowClose = false, closing = false;
    await windowHandle.onCloseRequested(async event => {
      if (allowClose) return;
      event.preventDefault();
      if (closing) return;
      closing = true;
      try {
        await saveLocalProject();
        allowClose = true;
        await windowHandle.destroy();
      } catch (error) {
        const discard = await confirmAction(`保存失败：${error.message}。取消后可以重试保存，或放弃本次未保存修改并退出。`, "无法保存作品", "仍然退出");
        if (discard) { allowClose = true; await windowHandle.destroy(); }
      } finally { closing = false; }
    });
  }
  if (state.runtimeStatus?.healthy) void connectConversation();
}

function configureConversation() {
  if (!el.conversation) return;
  assistantConversation = configureAssistant({
    conversation: el.conversation, invoke, listen,
    getProjectId: () => state.project.project_id,
    onStateChange: scheduleProjectRefresh,
    onError: (message) => { console.warn("Orbit conversation", message); statusCenter.error(message); },
  });
}

async function connectConversation() {
  if (!el.conversation || conversationConnectInFlight) return conversationConnectInFlight;
  conversationConnectInFlight = invoke("ai_prepare_conversation", { projectId: state.project.project_id })
    .then(({ conversation_id }) => el.conversation.openConversation(conversation_id))
    .catch((error) => console.warn("Orbit conversation connection failed", error))
    .finally(() => {
      conversationConnectInFlight = null;
    });
  return conversationConnectInFlight;
}

function wireEvents() {
  let startingManual = false;
  const startManual = async (operation) => {
    if (startingManual) return;
    startingManual = true;
    const buttons = document.querySelectorAll(".song-empty-actions button");
    buttons.forEach(button => button.disabled = true);
    try {
      if (state.project?.editing?.mode !== "manual") {
        await state.service.setEditMode("manual");
        await refreshHostContext();
      }
      await operation();
    } catch (error) { showProjectError("无法开始编辑", error); }
    finally { startingManual = false; buttons.forEach(button => button.disabled = false); }
  };
  document.querySelector("#empty-add-track").addEventListener("click", () => startManual(async () => {
    await addTrack();
  }));
  const emptyMidiFile = document.querySelector("#empty-midi-file");
  document.querySelector("#empty-import-midi").addEventListener("click", () => emptyMidiFile.click());
  emptyMidiFile.addEventListener("change", () => {
    const file = emptyMidiFile.files[0];
    emptyMidiFile.value = "";
    if (file) void startManual(() => importMidi(file));
  });
  el.toggleBrowser?.addEventListener("click", () => {
    const collapsed = el.appShell?.classList.toggle("browser-collapsed");
    el.toggleBrowser.setAttribute("aria-pressed", String(Boolean(collapsed)));
    window.setTimeout(renderPianoRoll, 220);
  });
  el.toggleCopilot?.addEventListener("click", () => {
    const collapsed = el.appShell?.classList.toggle("copilot-collapsed");
    el.toggleCopilot.setAttribute("aria-pressed", String(Boolean(collapsed)));
    window.setTimeout(renderPianoRoll, 220);
  });
  el.closeEditor?.addEventListener("click", () => setDetailPanel(null));
  el.closeClipProperties?.addEventListener("click", () => setDetailPanel(null));

  el.fileInput.addEventListener("change", async (event) => {
    const [file] = event.target.files || [];
    if (file) await importMidi(file);
  });
  el.importMidiButton?.addEventListener("click", () => el.fileInput.click());
  el.projectFileInput?.addEventListener("change", async (event) => {
    const [file] = event.target.files || [];
    if (file) await openProjectFile(file);
    event.target.value = "";
  });
  el.newProject?.addEventListener("click", createNewProject);
  document.addEventListener("click", (event) => {
    if (!selectedNoteIds().length) return;
    // Editing tools must retain their target; other surfaces dismiss note selection.
    const preservesSelection = event.composedPath().some((node) => node instanceof Element &&
      node.matches("#piano-roll, .clip, .editor-tools, .context-actions, [data-edit], [data-quick-action], #clip-inspector, dialog"));
    if (preservesSelection) return;
    cancelPianoRollInteraction();
    void executeProjectCommand("selection.set", { note_ids: [], clip_ids: [] }, { quiet: true });
  });
  el.openProject?.addEventListener("click", () => el.projectFileInput?.click());
  el.saveProject?.addEventListener("click", saveProjectFile);

  for (const type of ["dragenter", "dragover"]) {
    el.dropZone.addEventListener(type, (event) => {
      event.preventDefault();
      el.dropZone.classList.add("dragging");
    });
  }

  for (const type of ["dragleave", "drop"]) {
    el.dropZone.addEventListener(type, (event) => {
      event.preventDefault();
      el.dropZone.classList.remove("dragging");
    });
  }

  el.dropZone.addEventListener("drop", async (event) => {
    const [file] = event.dataTransfer.files || [];
    if (file) await importMidi(file);
  });

  el.publishSelection.addEventListener("click", publishSelection);
  el.mockMidi.addEventListener("click", loadDemoProject);
  el.undo.addEventListener("click", undoProject);
  el.redo.addEventListener("click", redoProject);
  el.exportMidi.addEventListener("click", exportMidiFile);
  el.exportWav?.addEventListener("click", exportWavFile);
  el.addTrack?.addEventListener("click", addTrack);
  el.openDeviceSettings?.addEventListener("click", () => void deviceSettings?.open());
  el.setLoopRange?.addEventListener("click", setLoopFromSelection);
  el.tempoInput.addEventListener("change", () => {
    const tempo = clamp(Number(el.tempoInput.value || currentTempo()), 20, 300);
    executeProjectCommand("transport.set_state", { tempo }, { quiet: true });
  });
  el.transportButtons.forEach((button) => {
    button.addEventListener("click", () => runTransportAction(button.dataset.transport));
  });
  el.arrangementGrid.addEventListener("scroll", syncArrangementScroll);
  el.arrangementGrid.addEventListener("wheel", handleArrangementWheel, { passive: false });
  el.barScale?.addEventListener("click", handleTimelineRulerClick);
  el.canvas.addEventListener("pointerdown", handlePianoRollPointerDown);
  el.canvas.addEventListener("pointermove", handlePianoRollPointerMove);
  el.canvas.addEventListener("pointerup", handlePianoRollPointerUp);
  el.canvas.addEventListener("pointercancel", cancelPianoRollInteraction);
  el.canvas.addEventListener("mousedown", handlePianoRollPointerDown);
  el.canvas.addEventListener("mousemove", handlePianoRollPointerMove);
  window.addEventListener("mouseup", handlePianoRollPointerUp);
  window.addEventListener("pointermove", handleClipPointerMove);
  window.addEventListener("pointerup", handleClipPointerUp);
  window.addEventListener("pointermove", handleRangePointerMove);
  window.addEventListener("pointerup", handleRangePointerUp);
  el.canvas.addEventListener("click", handlePianoRollClickFallback);
  el.canvas.addEventListener("dblclick", addNoteFromCanvas);
  el.canvas.addEventListener("wheel", handlePianoRollWheel, { passive: false });
  document.querySelectorAll("[data-edit]").forEach((button) => {
    button.addEventListener("click", () => runEditAction(button.dataset.edit));
  });

  document.querySelectorAll("[data-view]").forEach((button) => {
    button.addEventListener("click", () => runViewAction(button.dataset.view));
  });


  document.querySelectorAll("[data-prompt]").forEach((button) => {
    button.addEventListener("click", () => {
      el.prompt.value = button.dataset.prompt;
      el.prompt.focus();
    });
  });

  window.addEventListener("resize", renderPianoRoll);
  window.addEventListener("keydown", handleKeyboardShortcuts);
}

async function addTrack() {
  if (state.project.project_id === "empty") {
    statusCenter.info("请先新建工程");
    return;
  }
  const draft = await requestNewTrack(state.project.tracks.length + 1);
  if (!draft) return;
  if (state.project?.editing?.mode !== "manual") {
    await state.service.setEditMode("manual");
    await refreshHostContext();
  }
  await executeProjectCommand("tracks.add", {
    name: draft.name,
    instrument: draft.instrument,
    role: draft.instrument,
    start_beats: transportPositionBeats(),
    duration_beats: currentBeatsPerBar(),
  }, { quiet: true });
}

async function createClipAtPlayhead() {
  const track = currentTrack();
  if (!track) {
    statusCenter.info("请先选择一条轨道");
    return;
  }
  await executeProjectCommand("clips.create", {
    track_id: track.track_id,
    start_beats: snapBeat(transportPositionBeats()),
    duration_beats: currentBeatsPerBar(),
    name: (track.name || "MIDI") + " 片段",
  }, { quiet: true });
}

async function handleQuickAction(action) {
  if (action === "new-track") {
    await addTrack();
    return;
  }
  if (action === "new-clip") {
    await createClipAtPlayhead();
    return;
  }
  if (action === "open-editor") {
    openSelectedClipEditor();
    return;
  }
  if (action === "clip-properties") {
    setDetailPanel("clip");
    clipInspector.render();
    return;
  }
  if (action === "effects") {
    openTrackEffects();
    return;
  }
  if (action === "loop") {
    await setLoopFromSelection();
    return;
  }
  if (["duplicate", "split", "quantize", "delete"].includes(action)) {
    await runEditAction(action);
  }
}

function openSelectedClipEditor() {
  const clip = selectedProjectClips()[0];
  if (!clip) {
    statusCenter.info("请先选择一个片段");
    return;
  }
  state.activeTrackId = clip.track_id;
  ensureTrackPitchesVisible(clip.track_id, true);
  setDetailPanel("editor");
  render();
}

function openTrackEffects(trackId = null) {
  const selectedClip = selectedProjectClips()[0];
  const targetTrackId = trackId || selectedClip?.track_id || state.activeTrackId;
  if (!targetTrackId || !state.project.tracks.some((track) => track.track_id === targetTrackId)) {
    statusCenter.info("请先选择一条轨道");
    return;
  }
  state.activeTrackId = targetTrackId;
  setDetailPanel("effects");
  render();
}

function setDetailPanel(panel) {
  state.detailPanel = panel;
  state.editorOpen = panel === "editor";
  renderWorkspaceShell();
  trackEffects.render();
  clipInspector.render();
  if (state.editorOpen) window.requestAnimationFrame(renderPianoRoll);
}

async function refreshHostContext(renderOptions = {}) {
  try {
    const context = await state.service.context();
    updateHostPill(context);
    const snapshotBundle = context.snapshot_bundle;
    const uiSnapshot = snapshotBundle?.ui_snapshot;
    if (uiSnapshot?.project) {
      state.snapshotBundle = snapshotBundle;
      setProjectState(uiSnapshot.project, uiSnapshot.selection);
      await refreshCommandLog();
      if (!renderOptions.deferRender) render(renderOptions);
    } else if (context.active_project) {
      setProjectState(context.active_project, context.active_selection);
      if (!renderOptions.deferRender) render(renderOptions);
    }
  } catch {
    el.hostPill.textContent = "离线";
    el.hostPill.dataset.state = "offline";
  }
}

async function refreshCommandLog() {
  if (!state.project?.project_id || state.project.project_id === "empty") {
    state.commandLog = null;
    return;
  }
  try {
    state.commandLog = await state.service.commandLog(state.project.project_id);
  } catch {
    state.commandLog = null;
  }
}

async function importMidi(file) {
  try {
    statusCenter.busy(`正在导入 ${file.name}…`);
    state.messages.push({ role: "assistant", text: `正在导入 ${file.name}……` });
    renderMessages();
    const response = await state.service.importMidiFile(file);
    setProjectState(response.project, response.selection);
    await refreshCommandLog();
    await refreshHostContext();
    scheduleAutosave();
    dirtyState.markDirty();
    statusCenter.success(`已导入 ${file.name}`);
    state.messages.push({
      role: "assistant",
      text: `已导入 ${file.name}：${state.project.tracks.length} 条轨道，${countNotes(state.selection)} 个音符。`,
    });
    render();
  } catch (error) {
    statusCenter.error(`MIDI 导入失败：${error.message}`);
    state.messages.push({ role: "assistant", text: `MIDI 导入失败：${error.message}` });
    renderMessages();
  }
}

async function loadDemoProject() {
  try {
    const response = await state.service.createDemoProject();
    setProjectState(response.project, response.selection);
    await refreshCommandLog();
    await refreshHostContext();
    scheduleAutosave();
    dirtyState.markDirty();
    statusCenter.success("示例工程已载入");
    state.messages.push({
      role: "assistant",
      text: "示例工程已载入。你可以直接编辑，也可以让我继续编曲。",
    });
    render();
  } catch (error) {
    statusCenter.error(`示例工程载入失败：${error.message}`);
    state.messages.push({ role: "assistant", text: `示例工程载入失败：${error.message}` });
    renderMessages();
  }
}

async function createNewProject() {
  const draft = await requestNewProject();
  if (!draft) return;
  try {
    await saveLocalProject();
    await pauseProjectConversation();
    const response = await state.service.createProject(draft.name, draft.tempo);
    setProjectState(response.project, response.selection);
    await refreshCommandLog();
    scheduleAutosave();
    dirtyState.markDirty();
    statusCenter.success("已创建新工程");
    render();
    if (state.runtimeStatus?.healthy) await connectConversation();
  } catch (error) {
    showProjectError("新建工程失败", error);
  }
}

async function openProjectFile(file) {
  try {
    await saveLocalProject();
    await pauseProjectConversation();
    const response = await state.service.importProjectFile(file);
    setProjectState(response.project, response.selection);
    await refreshCommandLog();
    scheduleAutosave();
    dirtyState.markSaved();
    statusCenter.success(`已打开 ${file.name}`);
    render();
    if (state.runtimeStatus?.healthy) await connectConversation();
  } catch (error) {
    showProjectError("打开工程失败", error);
  }
}

async function saveProjectFile() {
  try { await saveLocalProject(); statusCenter.success("已保存到本机项目库"); }
  catch (error) { showProjectError("保存失败", error); }
}

async function exportProjectFile() {
  try {
    statusCenter.busy("正在保存工程…");
    const exported = await state.service.exportProject();
    downloadBlob(
      new Blob([JSON.stringify(exported, null, 2)], { type: "application/json" }),
      exported.file_name || `${state.project.name || "reidom"}.reidom`,
    );
    await state.service.writeAutosave();
    dirtyState.markSaved();
    statusCenter.success("工程已保存");
  } catch (error) {
    showProjectError("保存工程失败", error);
  }
}

function showProjectError(prefix, error) {
  statusCenter.error(`${prefix}：${error.message}`);
  state.messages.push({ role: "assistant", text: `${prefix}：${error.message}` });
  renderMessages();
}

function scheduleAutosave() {
  projectLibrary.status("等待保存…");
  window.clearTimeout(autosaveTimer);
  autosaveTimer = window.setTimeout(() => {
    saveLocalProject({ saveConversation: false }).catch((error) => console.warn("Autosave failed", error));
  }, 450);
}

async function saveLocalProject({ saveConversation = true } = {}) {
  window.clearTimeout(autosaveTimer);
  projectLibrary.status("正在保存…");
  const id = state.project.project_id, revision = state.project.revision;
  try {
    await state.service.writeAutosave();
    if (saveConversation) await assistantConversation?.save();
    if (state.project.project_id === id && state.project.revision === revision) {
      dirtyState.markSaved();
      projectLibrary.status("已保存到本机");
    }
  } catch (error) {
    projectLibrary.status("保存失败 · 请重试", true);
    throw error;
  }
}

async function openLibraryProject(id) {
  await saveLocalProject();
  await pauseProjectConversation();
  const response = await state.service.openLibraryProject(id);
  setProjectState(response.project, response.selection);
  state.interaction = null; state.clipInteraction = null;
  setDetailPanel(null);
  await refreshCommandLog();
  render();
  await saveLocalProject();
  statusCenter.success("已打开作品");
  if (state.runtimeStatus?.healthy) await connectConversation();
}

async function pauseProjectConversation() {
  if (conversationConnectInFlight) await conversationConnectInFlight;
  if (el.conversation?.conversationId && state.runtimeStatus?.healthy) {
    const paused = await invoke("ai_pause_conversation", { args: { conversationId: el.conversation.conversationId } });
    if (!paused.accepted) throw new Error("请先停止当前 AI 任务，再切换项目");
    el.conversation.disconnect();
  }
}

async function publishSelection() {
  if (!state.selection.tracks.length) {
    state.messages.push({ role: "assistant", text: "还没有 MIDI 内容，请先导入文件或载入示例工程。" });
    renderMessages();
    return;
  }

  try {
    await state.service.publishMidiSelection(state.selection);
    state.messages.push({ role: "assistant", text: "选择范围已更新。" });
  } catch (error) {
    state.messages.push({ role: "assistant", text: `发布失败：${error.message}` });
  }
  renderMessages();
}

async function sendMessage(event) {
  event.preventDefault();
  const text = el.prompt.value.trim();
  if (!text) return;

  state.messages.push({ role: "user", text });
  el.prompt.value = "";
  renderMessages();

  try {
    await refreshHostContext();
    if (state.runtimeStatus?.healthy) {
      const result = await state.runtime.sendMessage(text);
      if (!result.accepted) throw new Error(result.command_id || "runtime rejected the message");
    } else throw new Error("AI Runtime is unavailable");
  } catch {
    state.messages.push({ role: "assistant", text: "暂时无法回复，请稍后再试。" });
  }
  renderMessages();
}

function updateHostPill(context = null) {
  const runtimeHealthy = state.runtimeStatus?.healthy;
  const engineOnline = Boolean(context?.snapshot_bundle);
  if (runtimeHealthy) {
    el.hostPill.textContent = "就绪";
    el.hostPill.dataset.state = "online";
    el.hostPill.title = state.runtimeStatus.runtime || "";
    return;
  }
  if (engineOnline) {
    el.hostPill.textContent = "音乐引擎就绪";
    el.hostPill.dataset.state = "online";
    el.hostPill.title = state.runtimeStatus?.diagnostic || "";
    return;
  }
  el.hostPill.textContent = "离线";
  el.hostPill.dataset.state = "offline";
  el.hostPill.title = state.runtimeStatus?.diagnostic || "";
}

function handleRuntimeFrontendEvent(payload) {
  const role = payload?.role || payload?.message?.role || payload?.author?.role;
  if (role === "user") return;
  scheduleProjectRefresh();
  const eventType = String(payload?.type || payload?.event || "").toLowerCase();
  const isComplete = Boolean(payload?.done) || eventType.includes("complete") || eventType.includes("finish");
  const text =
    payload?.message?.content ||
    payload?.assistant?.content ||
    payload?.content ||
    payload?.delta?.content ||
    "";
  const lastMessage = state.messages[state.messages.length - 1];
  if (!text) {
    if (isComplete && lastMessage?.streaming) lastMessage.streaming = false;
    return;
  }
  if (payload?.delta?.content) {
    if (lastMessage?.role === "assistant" && lastMessage.streaming) lastMessage.text += text;
    else state.messages.push({ role: "assistant", text, streaming: !isComplete });
  } else if (lastMessage?.role === "assistant" && lastMessage.streaming) {
    lastMessage.text = text;
    lastMessage.streaming = false;
  } else {
    state.messages.push({ role: "assistant", text, streaming: false });
  }
  renderMessages();
}

function scheduleProjectRefresh() {
  if (!state.service?.isNative) return;
  window.clearTimeout(projectRefreshTimer);
  projectRefreshTimer = window.setTimeout(async () => {
    try {
      const context = await state.service.context();
      const uiSnapshot = context?.snapshot_bundle?.ui_snapshot;
      const nextProject = uiSnapshot?.project;
      if (!nextProject || nextProject.revision === state.project?.revision) return;
      state.snapshotBundle = context.snapshot_bundle;
      setProjectState(nextProject, uiSnapshot.selection);
      scheduleAutosave();
      dirtyState.markDirty();
      await refreshCommandLog();
      render();
    } catch (error) {
      console.warn("Project refresh after AI event failed", error);
    }
  }, 220);
}

function setProjectState(project, selection) {
  const changedProject = state.project?.project_id !== project?.project_id;
  if (changedProject) state.arrangementScrollLeft = 0;
  state.project = project || emptyProject();
  if (changedProject || (state.editorClipId && !state.project.clips.some(clip => clip.clip_id === state.editorClipId))) {
    state.editorClipId = null;
    state.detailPanel = null;
    state.editorOpen = false;
  }
  state.selection = selection || project?.selection || emptySelection();
  reconcileActiveTrack();
}

function reconcileActiveTrack() {
  const tracks = state.project.tracks || [];
  if (!tracks.length) {
    state.activeTrackId = null;
    state.view.scrollBeat = 0;
    state.view.zoomX = 1;
    state.view.pitchTop = 84;
    return;
  }
  const selected = new Set(selectedNoteIds());
  const selectedNote = projectNotes().find((note) => selected.has(note.note_id));
  if (selectedNote) {
    state.activeTrackId = selectedNote.track_id;
    return;
  }
  if (!state.activeTrackId || !tracks.some((track) => track.track_id === state.activeTrackId)) {
    state.activeTrackId = tracks[0].track_id;
  }
  clampViewToProject();
}

async function runEditAction(action) {
  const selectedNoteIds = state.selection.selected_note_ids || [];
  const selectedClips = selectedClipIds();
  const grid = Number(el.gridSelect.value || 0.25);
  if (!selectedNoteIds.length && selectedClips.length) {
    if (action === "split") {
      await executeProjectCommand(
        "clips.split",
        { clip_ids: selectedClips, at_beats: transportPositionBeats() },
        { quiet: true },
      );
      return;
    }
    const clipActions = {
      "nudge-left": { type: "clips.move", payload: { clip_ids: selectedClips, delta_beats: -grid } },
      "nudge-right": { type: "clips.move", payload: { clip_ids: selectedClips, delta_beats: grid } },
      duplicate: { type: "clips.duplicate", payload: { clip_ids: selectedClips, delta_beats: grid } },
      delete: { type: "clips.delete", payload: { clip_ids: selectedClips } },
    };
    const clipCommand = clipActions[action];
    if (clipCommand) await executeProjectCommand(clipCommand.type, clipCommand.payload, { quiet: true });
    return;
  }
  if (!selectedNoteIds.length) {
    state.messages.push({ role: "assistant", text: "请先在钢琴卷帘中选择一个或多个音符。" });
    renderMessages();
    return;
  }

  const actionMap = {
    "transpose-down": { type: "notes.transpose", payload: { note_ids: selectedNoteIds, semitones: -12 } },
    "transpose-up": { type: "notes.transpose", payload: { note_ids: selectedNoteIds, semitones: 12 } },
    "nudge-left": { type: "notes.move", payload: { note_ids: selectedNoteIds, delta_beats: -grid } },
    "nudge-right": { type: "notes.move", payload: { note_ids: selectedNoteIds, delta_beats: grid } },
    duplicate: { type: "notes.duplicate", payload: { note_ids: selectedNoteIds, delta_beats: grid } },
    "velocity-down": {
      type: "notes.velocity",
      payload: { note_ids: selectedNoteIds, velocity: selectedVelocityDelta(-8) },
    },
    "velocity-up": {
      type: "notes.velocity",
      payload: { note_ids: selectedNoteIds, velocity: selectedVelocityDelta(8) },
    },
    quantize: { type: "notes.quantize", payload: { note_ids: selectedNoteIds, grid_beats: grid } },
    delete: { type: "notes.delete", payload: { note_ids: selectedNoteIds } },
  };
  const command = actionMap[action];
  if (!command) return;
  await executeProjectCommand(command.type, command.payload);
}

function handleKeyboardShortcuts(event) {
  if (document.querySelector("dialog[open]") || event.composedPath().some((node) => node?.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(node?.tagName))) return;
  const target = event.target;
  if (target instanceof HTMLTextAreaElement || target instanceof HTMLInputElement || target instanceof HTMLSelectElement) {
    return;
  }
  const isUndo = (event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "z" && !event.shiftKey;
  const isRedo =
    ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "y") ||
    ((event.ctrlKey || event.metaKey) && event.shiftKey && event.key.toLowerCase() === "z");
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") {
    event.preventDefault();
    void saveProjectFile();
    return;
  }
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "o") {
    event.preventDefault();
    el.projectFileInput?.click();
    return;
  }
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "n") {
    event.preventDefault();
    void createNewProject();
    return;
  }
  if (isUndo) {
    event.preventDefault();
    undoProject();
    return;
  }
  if (isRedo) {
    event.preventDefault();
    redoProject();
    return;
  }
  if (event.code === "Space") {
    event.preventDefault();
    void runTransportAction("play");
    return;
  }
  if (event.key === "Escape") {
    event.preventDefault();
    cancelPianoRollInteraction();
    state.clipInteraction = null;
    state.rangeInteraction = null;
    if (selectedNoteIds().length || selectedClipIds().length) {
      void executeProjectCommand("selection.set", { note_ids: [], clip_ids: [] }, { quiet: true });
      return;
    }
    setDetailPanel(null);
    render();
    return;
  }
  if (event.key === "Home") {
    event.preventDefault();
    void runTransportAction("rewind");
    return;
  }
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "a") {
    event.preventDefault();
    selectAllNotes();
    return;
  }
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "d") {
    event.preventDefault();
    runEditAction("duplicate");
    return;
  }
  if (!event.ctrlKey && !event.metaKey && !event.altKey) {
    const key = event.key.toLowerCase();
    if (key === "q" && selectedNoteIds().length) {
      event.preventDefault();
      runEditAction("quantize");
      return;
    }
    if (key === "s" && selectedClipIds().length) {
      event.preventDefault();
      runEditAction("split");
      return;
    }
    if (key === "l" && selectedClipIds().length) {
      event.preventDefault();
      setLoopFromSelection();
      return;
    }
  }
  const keyMap = {
    Delete: "delete",
    Backspace: "delete",
    ArrowLeft: "nudge-left",
    ArrowRight: "nudge-right",
    ArrowUp: "transpose-semitone-up",
    ArrowDown: "transpose-semitone-down",
  };
  if (event.shiftKey && event.key === "ArrowUp") {
    event.preventDefault();
    runEditAction("transpose-up");
    return;
  }
  if (event.shiftKey && event.key === "ArrowDown") {
    event.preventDefault();
    runEditAction("transpose-down");
    return;
  }
  const action = keyMap[event.key];
  if (action) {
    event.preventDefault();
    if (action.startsWith("transpose-semitone")) {
      runKeyboardTranspose(action);
      return;
    }
    runEditAction(action);
  }
}

async function runKeyboardTranspose(action) {
  const selectedNoteIds = state.selection.selected_note_ids || [];
  if (!selectedNoteIds.length) return;
  await executeProjectCommand(
    "notes.transpose",
    {
      note_ids: selectedNoteIds,
      semitones: action === "transpose-semitone-up" ? 1 : -1,
    },
    { quiet: true },
  );
}

async function executeProjectCommand(type, payload, options = {}) {
  if (state.project.project_id === "empty") return;
  if (!editMode.manual() && isPersistentCommand(type, payload)) {
    statusCenter.error("进入手动编辑后才能修改作品");
    return;
  }
  try {
    const renderOptions = { preserveArrangement: type === "selection.set" };
    const response = await state.service.executeCommand(state.project.project_id, {
      command_id: `cmd-${Date.now()}`,
      base_revision: state.project.revision,
      source: "user",
      type,
      payload,
      preview: false,
    });
    setProjectState(response.project, response.selection);
    await refreshHostContext({ ...renderOptions, deferRender: true });
    if (isPersistentCommand(type, payload)) {
      scheduleAutosave();
      dirtyState.markDirty();
    }
    if (!options.quiet) {
      state.messages.push({ role: "assistant", text: `Applied ${type} through the JUCE command engine.` });
    }
    render(renderOptions);
  } catch (error) {
    statusCenter.error(`操作失败：${error.message}`);
    state.messages.push({ role: "assistant", text: `Command failed: ${error.message}` });
    renderMessages();
  }
}

function isPersistentCommand(type, payload) {
  if (type === "selection.set") return false;
  if (type !== "transport.set_state") return true;
  return ["tempo", "bpm", "loop", "loop_start_beats", "loop_end_beats", "metronome", "recording"]
    .some((key) => key in payload);
}

async function undoProject() {
  if (state.project.project_id === "empty") return;
  try {
    const response = await state.service.undo(state.project.project_id);
    setProjectState(response.project, response.selection);
    await refreshHostContext();
    scheduleAutosave();
    dirtyState.markDirty();
    statusCenter.success("已撤销");
    render();
  } catch (error) {
    statusCenter.error(`撤销失败：${error.message}`);
    state.messages.push({ role: "assistant", text: `Undo failed: ${error.message}` });
    renderMessages();
  }
}

async function redoProject() {
  if (state.project.project_id === "empty") return;
  try {
    const response = await state.service.redo(state.project.project_id);
    setProjectState(response.project, response.selection);
    await refreshHostContext();
    scheduleAutosave();
    dirtyState.markDirty();
    statusCenter.success("已重做");
    render();
  } catch (error) {
    statusCenter.error(`重做失败：${error.message}`);
    state.messages.push({ role: "assistant", text: `Redo failed: ${error.message}` });
    renderMessages();
    statusCenter.success(`已导出 ${fileName}`);
  }
}

async function exportMidiFile() {
  if (state.project.project_id === "empty") return;
  try {
    const exported = await state.service.exportMidi(state.project.project_id);
    const bytes = base64ToBytes(exported.data_base64);
    const blob = new Blob([bytes], { type: "audio/midi" });
    const fileName = exported.file_name || `${state.project.name || "reidom"}.mid`;
    downloadBlob(blob, fileName);
    state.messages.push({ role: "assistant", text: `已导出 ${fileName}` });
    renderMessages();
  } catch (error) {
    statusCenter.error(`MIDI 导出失败：${error.message}`);
    state.messages.push({ role: "assistant", text: `Export failed: ${error.message}` });
    renderMessages();
    statusCenter.success(`已导出 ${fileName}`);
  }
}

async function exportWavFile() {
  if (state.project.project_id === "empty") return;
  try {
    const exported = await state.service.renderWav();
    const blob = new Blob([base64ToBytes(exported.data_base64)], { type: "audio/wav" });
    const fileName = exported.file_name || `${state.project.name || "reidom"}.wav`;
    downloadBlob(blob, fileName);
    state.messages.push({ role: "assistant", text: `已导出 ${fileName}` });
    renderMessages();
  } catch (error) {
    showProjectError("WAV 导出失败", error);
  }
}

function downloadBlob(blob, fileName) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = fileName;
  document.body.append(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

function render(renderOptions = {}) {
  const notes = countNotes(state.selection);
  const tempo = currentTempo();
  const projectName = state.project.name || "未命名工程";

  el.projectTitle.textContent = projectName;
  const activeTrack = currentTrack();
  el.activeTrackLabel.textContent = activeTrack ? `正在编辑：${activeTrack.name || activeTrack.track_id}` : "未选择轨道";
  el.trackCount.textContent = state.project.tracks.length;
  el.noteCount.textContent = notes;
  el.tempoValue.textContent = Math.round(tempo);
  el.tempoInput.value = Math.round(tempo);
  if (el.aiContext) {
    el.aiContext.textContent = notes
      ? `${state.project.tracks.length} 轨 / ${notes} 音符 / ${Math.round(tempo)} BPM / 已选 ${selectedNoteIds().length} 音符 + ${selectedClipIds().length} 片段`
      : "未选择 MIDI 内容";
  }
  el.selectionSummary.textContent = `已选 ${selectedNoteIds().length} 个音符 / ${selectedClipIds().length} 个片段`;
  if (el.selectionJson) el.selectionJson.textContent = JSON.stringify(state.selection, null, 2);

  if (renderOptions.preserveArrangement) {
    syncSelectionVisuals();
  } else {
    renderTrackList();
  }
  renderWorkspaceShell();
  renderTransport();
  renderInspectorRack();
  renderGlobalTracks();
  if (!renderOptions.preserveArrangement) renderArrangement();
  renderSelectionDetails();
  renderEventList();
  renderCommandLog();
  renderControllerLanes();
  renderRouteProperties();
  quickActions.render();
  trackEffects.render();
  clipInspector.render();
  renderMessages();
  renderPianoRoll();
  editMode.render();
  projectLibrary.render();
  const deselect = document.querySelector("#clear-note-selection");
  if (deselect) deselect.disabled = !selectedNoteIds().length && !selectedClipIds().length;
}

function renderWorkspaceShell() {
  editMode.render();
  if (!el.centerWorkspace) return;
  el.centerWorkspace.classList.toggle("editor-open", state.detailPanel === "editor");
  el.centerWorkspace.classList.toggle("effects-open", state.detailPanel === "effects");
  el.centerWorkspace.classList.toggle("clip-properties-open", state.detailPanel === "clip");
}

function renderTransport() {
  const transport = state.project.transport || {};
  if (el.barReadout) el.barReadout.textContent = transport.position || "001.1.1";
  el.transportButtons.forEach((button) => {
    const key = button.dataset.transport;
    const active =
      (key === "play" && transport.playing) ||
      (key === "recording" && transport.recording) ||
      Boolean(transport[key]);
    button.classList.toggle("active", active);
    if (key === "play") button.textContent = transport.playing ? "■" : "▶";
  });
  if (el.setLoopRange) {
    const hasRange = Number(transport.loop_end_beats || 0) > Number(transport.loop_start_beats || 0);
    el.setLoopRange.classList.toggle("active", Boolean(transport.loop && hasRange));
    el.setLoopRange.textContent = hasRange
      ? `${formatBeat(transport.loop_start_beats)}–${formatBeat(transport.loop_end_beats)}`
      : "循环区间";
  }
}

async function refreshTransportPosition() {
  if (transportPollInFlight || !state.project.transport?.playing) return;
  transportPollInFlight = true;
  try {
    const context = await state.service.context();
    const project = context?.snapshot_bundle?.ui_snapshot?.project;
    if (!project?.transport) return;
    state.project.transport = project.transport;
    renderTransport();
    const left = `${transportPositionBeats() * state.arrangementPixelsPerBeat}px`;
    document.querySelectorAll(".arrangement-playhead").forEach((playhead) => {
      playhead.style.left = left;
    });
  } catch (error) {
    console.warn("Transport refresh failed", error);
  } finally {
    transportPollInFlight = false;
  }
}

async function runTransportAction(action) {
  if (state.project.project_id === "empty") return;
  const transport = state.project.transport || {};
  if (action === "rewind") {
    await executeProjectCommand("transport.set_state", { position: "001.1.1", playing: false }, { quiet: true });
    return;
  }
  if (action === "play") {
    await executeProjectCommand("transport.set_state", { playing: !transport.playing, recording: false }, { quiet: true });
    return;
  }
  if (action === "recording") {
    await executeProjectCommand(
      "transport.set_state",
      { recording: !transport.recording, playing: !transport.recording },
      { quiet: true },
    );
    return;
  }
  if (["loop", "metronome"].includes(action)) {
    await executeProjectCommand("transport.set_state", { [action]: !transport[action] }, { quiet: true });
  }
}

async function setLoopFromSelection() {
  if (state.project.project_id === "empty") return;
  const range = state.selection?.range || {};
  let start = Number(range.start_beats || 0);
  let end = Number(range.end_beats || 0);
  if (end <= start) {
    const clip = selectedProjectClips()[0];
    if (clip) {
      start = Number(clip.start_beats || 0);
      end = start + Number(clip.duration_beats || 0);
    }
  }
  if (end <= start) {
    statusCenter.info("先在时间线上拖出范围，或选择一个片段");
    return;
  }
  await executeProjectCommand("transport.set_state", {
    loop: true,
    loop_start_beats: start,
    loop_end_beats: end,
  }, { quiet: true });
  statusCenter.success(`循环区间：${formatBeat(start)} – ${formatBeat(end)}`);
}

function renderInspectorRack() {
  if (!el.inspectorRack) return;
  const activeTrack = currentTrack();
  const trackName = activeTrack?.name || "未选择轨道";
  el.inspectorRack.replaceChildren(
    ...EDITOR_MODEL.inspectorRack.map((section) => {
      const item = document.createElement("article");
      item.className = "rack-row";
      const value = section.key === "output" && activeTrack ? `${trackName} 输出` : section.value;
      item.innerHTML = `
        <span>${escapeHtml(section.label)}</span>
        <strong>${escapeHtml(value)}</strong>
      `;
      return item;
    }),
  );
}

function renderGlobalTracks() {
  if (!el.globalTracks) return;
  const tempo = Math.round(currentTempo());
  const signature = currentTimeSignature();
  const markers = state.project.markers?.length
    ? state.project.markers.slice(0, 4).map((marker) => marker.name || `M${formatBeat(marker.start_beats || 0)}`)
    : EDITOR_MODEL.globalTracks.find((track) => track.key === "marker").values;
  const data = {
    marker: markers,
    signature: [signature, signature, signature, signature],
    tempo: [tempo, tempo, tempo, tempo],
  };
  el.globalTracks.replaceChildren(
    ...EDITOR_MODEL.globalTracks.map((track) => {
      const row = document.createElement("div");
      row.className = `global-track global-track-${track.key}`;
      row.innerHTML = `
        <span>${escapeHtml(track.label)}</span>
        <div>${(data[track.key] || track.values)
          .map((value) => `<b>${escapeHtml(value)}</b>`)
          .join("")}</div>
      `;
      return row;
    }),
  );
}

function renderTrackList() {
  el.trackList.replaceChildren(
    ...state.project.tracks.map((track, index) => {
      const item = document.createElement("article");
      const selected = selectedTrackIds().includes(track.track_id);
      item.className = `track-item${track.track_id === state.activeTrackId ? " active" : ""}${selected ? " selected" : ""}`;
      item.tabIndex = 0;
      item.draggable = true;
      item.dataset.trackId = track.track_id;
      item.dataset.trackIndex = String(index);
      item.style.setProperty("--track-color", track.color || trackColor(index));
      item.addEventListener("click", () => void selectArrangementTrack(track.track_id));
      item.addEventListener("keydown", (event) => {
        if (event.key !== "Enter" && event.key !== " ") return;
        event.preventDefault();
        void selectArrangementTrack(track.track_id);
      });
      item.addEventListener("dblclick", async () => {
        const name = await requestName("重命名轨道", track.name || "MIDI 轨道");
        if (name) await executeProjectCommand("tracks.rename", { track_id: track.track_id, name }, { quiet: true });
      });
      item.addEventListener("dragstart", (event) => {
        event.dataTransfer.setData("text/reidom-track-index", String(index));
        event.dataTransfer.effectAllowed = "move";
      });
      item.addEventListener("dragover", (event) => event.preventDefault());
      item.addEventListener("drop", (event) => {
        event.preventDefault();
        const from = Number(event.dataTransfer.getData("text/reidom-track-index"));
        if (Number.isInteger(from) && from !== index) {
          const source = state.project.tracks[from];
          if (source) void executeProjectCommand("tracks.reorder", { track_id: source.track_id, index }, { quiet: true });
        }
      });
      item.innerHTML = `
        <span>${String(index + 1).padStart(2, "0")}</span>
        <div>
          <strong>${escapeHtml(track.name || track.track_id)}</strong>
          <small>${escapeHtml(routeSummary(track))}</small>
          <div class="track-controls" data-track-id="${escapeHtml(track.track_id)}">
            ${EDITOR_MODEL.trackControls
              .map((control) => trackControlButton(track.track_id, control.key, control.label, control.title))
              .join("")}
          </div>
          <div class="track-setup">
            <select class="track-instrument" aria-label="${escapeHtml(track.name || track.track_id)} 音源">
              ${instrumentOptions(track.instrument_ref || track.instrument)}
            </select>
            <button class="track-delete" title="删除轨道" aria-label="删除 ${escapeHtml(track.name || track.track_id)}">×</button>
          </div>
          <div class="track-mix">
            <label title="音量"><span>音量</span><input type="range" min="0" max="100" value="${Math.round((track.volume ?? 0.85) * 100)}" data-track-volume></label>
            <label title="声像"><span>声像</span><input type="range" min="-1" max="1" step="0.01" value="${Number(track.pan ?? 0)}" data-track-pan></label>
          </div>
        </div>
      `;
      item.querySelectorAll(".track-control").forEach((button) => {
        button.addEventListener("click", (event) => {
          event.stopPropagation();
          toggleTrackControl(track.track_id, button.dataset.control);
        });
      });
      item.querySelector(".track-instrument")?.addEventListener("change", (event) => {
        event.stopPropagation();
        void executeProjectCommand(
          "tracks.set_instrument",
          { track_id: track.track_id, instrument: event.target.value, role: instrumentRole(event.target.value) },
          { quiet: true },
        );
      });
      item.querySelector("[data-track-volume]")?.addEventListener("change", (event) => {
        event.stopPropagation();
        void updateRouteState(track.track_id, { volume: clamp(Number(event.target.value) / 100, 0, 1) });
      });
      item.querySelectorAll(".track-mix input").forEach((input) => {
        input.addEventListener("click", (event) => event.stopPropagation());
        input.addEventListener("pointerdown", (event) => event.stopPropagation());
      });
      item.querySelector("[data-track-pan]")?.addEventListener("change", (event) => {
        event.stopPropagation();
        void updateRouteState(track.track_id, { pan: clamp(Number(event.target.value), -1, 1) });
      });
      item.querySelector(".track-delete")?.addEventListener("click", async (event) => {
        event.stopPropagation();
        if (await confirmAction(`删除轨道“${track.name || track.track_id}”及其全部片段？可通过撤销恢复。`, "删除轨道", "删除轨道")) {
          void executeProjectCommand("tracks.delete", { track_id: track.track_id }, { quiet: true });
        }
      });
      return item;
    }),
  );
}

function instrumentOptions(selected) {
  return [
    ["piano", "钢琴"],
    ["electric-guitar", "电吉他"],
    ["electric-bass", "电贝斯"],
    ["synth-lead", "合成器主奏"],
    ["warm-pad", "温暖 Pad"],
    ["drum-kit", "鼓组"],
  ].map(([value, label]) => `<option value="${value}"${value === selected ? " selected" : ""}>${label}</option>`).join("");
}

function instrumentRole(instrument) {
  if (instrument.includes("drum")) return "drums";
  if (instrument.includes("bass")) return "bass";
  if (instrument.includes("guitar")) return "guitar";
  if (instrument.includes("pad")) return "pad";
  if (instrument.includes("lead")) return "lead";
  return "harmony";
}

function trackControlButton(trackId, control, label, title = control) {
  const active = routeControlValue(trackId, control) ? " active" : "";
  return `<button class="track-control${active}" data-control="${control}" title="${escapeHtml(title)}">${label}</button>`;
}

async function toggleTrackControl(trackId, control) {
  const nextValue = !routeControlValue(trackId, control);
  await updateRouteState(trackId, { [control]: nextValue });
}

async function updateRouteState(trackId, patch) {
  if (state.project.project_id !== "empty") {
    await executeProjectCommand(
      "routes.set_state",
      {
        track_id: trackId,
        state: patch,
      },
      { quiet: true },
    );
    return;
  }
  const controls = state.trackControls[trackId] || {};
  state.trackControls[trackId] = { ...controls, ...patch };
  render();
}

function routeControlValue(trackId, control) {
  const local = state.trackControls[trackId] || {};
  if (control in local) return Boolean(local[control]);
  const track = state.project.tracks.find((item) => item.track_id === trackId);
  if (!track) return false;
  if (control === "record") return Boolean(track.arm);
  return Boolean(track[control]);
}

function routeSummary(track) {
  const noteCount = track.note_count ?? clipNoteCount(track.track_id);
  const output = track.output || "主输出";
  return `${roleLabel(track.role)} / ${noteCount} 个事件 / ${output}`;
}

function roleLabel(role) {
  return {
    lead: "主旋律",
    harmony: "和声",
    guitar: "吉他",
    bass: "贝斯",
    drums: "鼓组",
    pad: "氛围",
    midi: "MIDI",
  }[role] || role || "MIDI";
}

function transportPositionBeats() {
  const [barValue = "1", beatValue = "1", subdivisionValue = "1"] = String(
    state.project.transport?.position || "001.1.1",
  ).split(".");
  const beatsPerBar = currentBeatsPerBar();
  return Math.max(
    0,
    (Number(barValue) - 1) * beatsPerBar + (Number(beatValue) - 1) + (Number(subdivisionValue) - 1) / 4,
  );
}

function beatToTransportPosition(value) {
  const beatsPerBar = currentBeatsPerBar();
  const bar = Math.floor(value / beatsPerBar) + 1;
  const withinBar = value - (bar - 1) * beatsPerBar;
  const beat = Math.floor(withinBar) + 1;
  const subdivision = Math.floor((withinBar - Math.floor(withinBar)) * 4 + 0.001) + 1;
  return `${String(bar).padStart(3, "0")}.${beat}.${subdivision}`;
}

function currentBeatsPerBar() {
  const signature = state.project.time_signatures?.[0];
  const numerator = Number(signature?.numerator || 4);
  const denominator = Number(signature?.denominator || 4);
  return Math.max(1, numerator * (4 / denominator));
}

function renderControllerLanes() {
  if (!el.controllerLanes) return;
  const selected = new Set(selectedNoteIds());
  const selectedNotes = projectNotes().filter((note) => selected.has(note.note_id)).slice(0, 8);
  el.controllerLanes.replaceChildren(
    ...EDITOR_MODEL.controllerLanes.map((lane) => {
      const values =
        lane.key === "velocity" && selectedNotes.length
          ? selectedNotes.map((note) => Number(note.velocity || 96))
          : lane.values;
      const item = document.createElement("section");
      item.className = "controller-lane";
      item.innerHTML = `
        <span>${escapeHtml(lane.label)}</span>
        <div>${values
          .map((value) => `<i style="height:${clamp(Number(value), 4, 127) / 1.27}%"></i>`)
          .join("")}</div>
      `;
      return item;
    }),
  );
}

function renderRouteProperties() {
  if (!el.routeProperties) return;
  const activeTrack = currentTrack();
  const selectedClips = selectedProjectClips();
  const selectedNotes = projectNotes().filter((note) => new Set(selectedNoteIds()).has(note.note_id));
  const route = activeTrack;
  el.aiContext.textContent = route
    ? `${route.name || route.track_id} / ${route.region_count ?? selectedClips.length} 个片段 / ${route.note_count ?? selectedNotes.length} 个 MIDI 事件`
    : "未选择轨道";
  const dynamic = [
    { label: "轨道", value: route?.name || "无" },
    { label: "片段", value: route?.region_count ?? state.project.clips.filter((clip) => clip.track_id === activeTrack?.track_id).length },
    { label: "事件", value: route?.note_count ?? clipNoteCount(activeTrack?.track_id || "") },
    { label: "输入", value: route?.input || "全部 MIDI 输入" },
    { label: "输出", value: route?.output || "主输出" },
    { label: "自动化", value: route?.automation || "读取" },
  ];
  el.routeProperties.replaceChildren(
    ...[...dynamic, ...EDITOR_MODEL.routeProperties].map((property) => {
      const row = document.createElement("div");
      row.className = "route-property";
      row.innerHTML = `<span>${escapeHtml(property.label)}</span><strong>${escapeHtml(property.value)}</strong>`;
      return row;
    }),
  );
}

function renderSelectionDetails() {
  const selected = new Set(selectedNoteIds());
  const selectedNotes = projectNotes().filter((note) => selected.has(note.note_id));
  if (!selectedNotes.length) {
    const selectedClips = selectedProjectClips();
    if (selectedClips.length) {
      const starts = selectedClips.map((clip) => Number(clip.start_beats || 0));
      const ends = selectedClips.map((clip) => Number(clip.start_beats || 0) + Number(clip.duration_beats || 0));
      el.selectionDetails.replaceChildren(
        selectionMetric("片段", selectedClips.length),
        selectionMetric("范围", `${formatBeat(Math.min(...starts))} - ${formatBeat(Math.max(...ends))}`),
        selectionMetric("长度", formatBeat(Math.max(...ends) - Math.min(...starts))),
        selectionMetric("轨道", selectedClips[0]?.trackName || "多轨"),
      );
      return;
    }
    el.selectionDetails.replaceChildren(selectionMetric("状态", "未选择"), selectionMetric("网格", gridLabel()));
    return;
  }

  const starts = selectedNotes.map((note) => Number(note.start_beats));
  const ends = selectedNotes.map((note) => Number(note.start_beats) + Number(note.duration_beats));
  const pitches = selectedNotes.map((note) => Number(note.pitch));
  const velocities = selectedNotes.map((note) => Number(note.velocity || 0));
  el.selectionDetails.replaceChildren(
    selectionMetric("数量", selectedNotes.length),
    selectionMetric("范围", `${formatBeat(Math.min(...starts))} - ${formatBeat(Math.max(...ends))}`),
    selectionMetric("音高", `${noteName(Math.min(...pitches))} - ${noteName(Math.max(...pitches))}`),
    selectionMetric("力度", Math.round(velocities.reduce((total, item) => total + item, 0) / velocities.length)),
  );
}

function renderEventList() {
  const selected = new Set(selectedNoteIds());
  const rows = projectNotes()
    .filter((note) => !selected.size || selected.has(note.note_id))
    .sort((a, b) => Number(a.start_beats) - Number(b.start_beats))
    .slice(0, 10);
  if (!rows.length) {
    el.eventList.replaceChildren(emptyEventRow("未选择 MIDI 事件"));
    return;
  }
  el.eventList.replaceChildren(
    eventHeader(),
    ...rows.map((note) => {
      const row = document.createElement("div");
      row.className = "event-row";
      row.innerHTML = EDITOR_MODEL.eventColumns
        .map((column) => `<span>${escapeHtml(column.value(note))}</span>`)
        .join("");
      return row;
    }),
  );
}

function eventHeader() {
  const row = document.createElement("div");
  row.className = "event-row event-header";
  row.innerHTML = EDITOR_MODEL.eventColumns.map((column) => `<span>${escapeHtml(column.label)}</span>`).join("");
  return row;
}

function emptyEventRow(text) {
  const row = document.createElement("div");
  row.className = "event-empty";
  row.textContent = text;
  return row;
}

function renderCommandLog() {
  const undoEntries = state.commandLog?.undo_entries || [];
  const redoEntries = state.commandLog?.redo_entries || [];
  if (!el.commandLog) return;
  if (!undoEntries.length && !redoEntries.length) {
    el.commandLog.replaceChildren(emptyCommandLogRow("还没有修改记录"));
    return;
  }
  const entries = undoEntries.slice(-6).reverse();
  el.commandLog.replaceChildren(
    ...entries.map((entry) => {
      const item = document.createElement("article");
      item.className = "command-log-row";
      item.innerHTML = `
        <span>${escapeHtml(entry.source || "unknown")}</span>
        <strong>${escapeHtml(entry.type || "command")}</strong>
        <small>${escapeHtml(entry.reason || "已记录操作")}</small>
      `;
      return item;
    }),
  );
}

function emptyCommandLogRow(text) {
  const item = document.createElement("article");
  item.className = "command-log-empty";
  item.textContent = text;
  return item;
}

function selectionMetric(label, value) {
  const item = document.createElement("div");
  item.className = "selection-metric";
  item.innerHTML = `<span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong>`;
  return item;
}

function renderMessages() {
  if (!el.messages) return;
  el.messages.replaceChildren(
    ...state.messages.map((message) => {
      const item = document.createElement("article");
      item.className = `message ${message.role}`;
      item.textContent = message.text;
      return item;
    }),
  );
  el.messages.scrollTop = el.messages.scrollHeight;
}

function projectNotes() {
  const trackIndexes = new Map(state.project.tracks.map((track, index) => [track.track_id, index]));
  return state.project.clips.flatMap((clip) =>
    (clip.notes || []).map((note) => ({
      ...note,
      track_id: clip.track_id,
      clip_id: clip.clip_id,
      trackIndex: trackIndexes.get(clip.track_id) ?? 0,
    })),
  );
}

function emptyProject() {
  return {
    schema: "reidom-project/v1",
    project_id: "empty",
    name: "Untitled MIDI",
    revision: 0,
    tempo_map: [{ start_beats: 0, bpm: 120 }],
    time_signatures: [{ start_beats: 0, numerator: 4, denominator: 4 }],
    key_signature: "unknown",
    tracks: [],
    clips: [],
    sections: [],
    markers: [],
    selection: {},
    undo_stack: [],
    redo_stack: [],
    source_files: [],
  };
}

function emptySelection() {
  return {
    schema: "reidom-midi-selection/v1",
    selection_id: "empty",
    project_id: "empty",
    revision: 0,
    source: { engine: "juce" },
    range: { start_beats: 0, end_beats: 0 },
    tempo: 120,
    time_signature: { numerator: 4, denominator: 4 },
    tracks: [],
    selected_track_ids: [],
    selected_note_ids: [],
    selected_clip_ids: [],
  };
}

function countNotes(selection) {
  return selection.tracks.reduce((total, track) => total + track.notes.length, 0);
}

function clipNoteCount(trackId) {
  return state.project.clips
    .filter((clip) => clip.track_id === trackId)
    .reduce((total, clip) => total + clip.notes.length, 0);
}

function currentTempo() {
  return state.project.tempo_map?.[0]?.bpm || state.selection.tempo || 120;
}

function currentTimeSignature() {
  const signature = state.project.time_signatures?.[0] || state.selection.time_signature || {};
  return `${signature.numerator || 4}/${signature.denominator || 4}`;
}

function currentTrack() {
  return state.project.tracks.find((track) => track.track_id === state.activeTrackId) || null;
}

function selectedNoteIds() {
  return state.selection.selected_note_ids || [];
}

function selectedTrackIds() {
  return state.selection.selected_track_ids || [];
}

function selectedClipIds() {
  return state.selection.selected_clip_ids || [];
}

function selectedProjectClips() {
  const selected = new Set(selectedClipIds());
  const trackNames = new Map(state.project.tracks.map((track) => [track.track_id, track.name || track.track_id]));
  return state.project.clips
    .filter((clip) => selected.has(clip.clip_id))
    .map((clip) => ({ ...clip, trackName: trackNames.get(clip.track_id) || clip.track_id }));
}

function selectedVelocityDelta(delta) {
  const selected = new Set(selectedNoteIds());
  const notes = projectNotes().filter((note) => selected.has(note.note_id));
  const average = notes.length
    ? notes.reduce((total, note) => total + Number(note.velocity || 96), 0) / notes.length
    : 96;
  return clamp(Math.round(average + delta), 1, 127);
}

function projectEndBeat() {
  return Math.max(
    0,
    ...state.project.clips.map((clip) => clip.start_beats + clip.duration_beats),
    state.selection.range?.end_beats || 0,
  );
}

function gridLabel() {
  const labels = {
    "0.25": "1/16",
    "0.5": "1/8",
    "1": "1/4",
  };
  return labels[Number(el.gridSelect.value || 0.25)] || `${el.gridSelect.value} beat`;
}

function formatBeat(value) {
  return Number(value).toFixed(2).replace(/\.?0+$/, "");
}

function snapBeat(value, grid = Number(el.gridSelect.value || 0.25)) {
  return Math.round(value / grid) * grid;
}

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

function trackColor(index) {
  return ["#b8f547", "#45b4ff", "#ff9b50", "#75df69", "#c28bff", "#37d0b2"][
    index % 6
  ];
}

function noteName(pitch) {
  return ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"][
    pitch % 12
  ] + Math.floor(pitch / 12 - 1);
}

function roundRect(context, x, y, width, height, radius) {
  const safeWidth = Math.max(0, Number.isFinite(width) ? width : 0);
  const safeHeight = Math.max(0, Number.isFinite(height) ? height : 0);
  const r = Math.max(0, Math.min(Math.abs(radius), safeWidth / 2, safeHeight / 2));
  context.beginPath();
  if (safeWidth === 0 || safeHeight === 0) return;
  context.moveTo(x + r, y);
  context.arcTo(x + safeWidth, y, x + safeWidth, y + safeHeight, r);
  context.arcTo(x + safeWidth, y + safeHeight, x, y + safeHeight, r);
  context.arcTo(x, y + safeHeight, x, y, r);
  context.arcTo(x, y, x + safeWidth, y, r);
  context.closePath();
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (char) => {
    return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char];
  });
}

function base64ToBytes(value) {
  const binary = atob(value);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index);
  }
  return bytes;
}
