import { createContextMenu } from "./context-menu.js";
import { INSTRUMENTS } from "../project/new-track-dialog.js";
import { confirmAction } from "../../shared/dialogs.js";
import { regionPreviewBars } from "./region-preview.js";

export function createArrangementController({
  state,
  elements,
  editorModel,
  executeCommand,
  getProjectEndBeat,
  getSelectedClipIds,
  getSelectedTrackIds,
  getTransportBeat,
  beatToPosition,
  getBeatsPerBar,
  renderTransport,
  renderApp,
  setDetailPanel,
  ensureTrackPitchesVisible,
  toggleTrackControl,
  openTrackEffects,
  countEnabledEffects,
  trackControlButton,
  routeControlValue,
  roleLabel,
  addTrack,
  reportError,
  helpers,
}) {
  const el = elements;
  const EDITOR_MODEL = editorModel;
  const executeProjectCommand = executeCommand;
  const projectEndBeat = getProjectEndBeat;
  const selectedClipIds = getSelectedClipIds;
  const selectedTrackIds = getSelectedTrackIds;
  const transportPositionBeats = getTransportBeat;
  const beatToTransportPosition = beatToPosition;
  const currentBeatsPerBar = getBeatsPerBar;
  const render = renderApp;
  const { clamp, escapeHtml, snapBeat } = helpers;
  const manual = () => state.project?.editing?.mode === "manual";
  const menu = createContextMenu(reportError, manual);
  let timelineBeats = 0;
  let timelineProjectId = null;
  let autoScrollFrame = null;
  let dragPointer = null;
  function cancelDrag() {
    stopAutoScroll();
    if (!state.clipInteraction) return;
    state.clipInteraction = null;
    renderArrangement();
  }
  window.addEventListener("pointercancel", cancelDrag);
  window.addEventListener("blur", cancelDrag);
  el.arrangementGrid.addEventListener("contextmenu", event => {
    if (event.target.closest(".arrangement-row")) return;
    event.preventDefault();
    if (!manual()) { menu.close(); return; }
    menu.open(event, [{ label: "新建轨道", run: addTrack }]);
  });

  function updateTimeline(requestedScroll = el.arrangementGrid.scrollLeft) {
    const bar = currentBeatsPerBar();
    if (timelineProjectId !== state.project.project_id) {
      timelineProjectId = state.project.project_id;
      timelineBeats = 0;
    }
    const ppb = state.arrangementPixelsPerBeat;
    const visibleWidth = Math.max(0, el.arrangementGrid.clientWidth - 236);
    const visibleEnd = (requestedScroll + visibleWidth) / ppb;
    const needed = Math.max(projectEndBeat() + bar * 4, visibleEnd + bar * 4, bar * 16);
    const chunk = bar * 16;
    timelineBeats = Math.max(timelineBeats, Math.ceil(needed / chunk) * chunk);
    const width = Math.max(visibleWidth, timelineBeats * ppb);
    el.arrangementGrid.style.setProperty("--timeline-width", width + "px");
    el.arrangementGrid.style.setProperty("--beat-width", ppb + "px");
    el.arrangementGrid.style.setProperty("--bar-width", ppb * bar + "px");
    renderTimelineRuler(timelineBeats, bar, ppb, width, requestedScroll);
  }

  function stopAutoScroll() {
    if (autoScrollFrame !== null) cancelAnimationFrame(autoScrollFrame);
    autoScrollFrame = null; dragPointer = null;
  }
  function startAutoScroll(event) {
    dragPointer = { clientX: event.clientX, clientY: event.clientY };
    if (autoScrollFrame !== null) return;
    let previous = performance.now();
    function frame(now) {
      if (!state.clipInteraction || !manual() || !dragPointer) { stopAutoScroll(); return; }
      const rect = el.arrangementGrid.getBoundingClientRect();
      const edge = 48;
      const speed = dragPointer.clientX > rect.right - edge
        ? Math.min(1, (dragPointer.clientX - rect.right + edge) / edge) * 600
        : dragPointer.clientX < rect.left + 236 + edge
          ? -Math.min(1, (rect.left + 236 + edge - dragPointer.clientX) / edge) * 600 : 0;
      const delta = speed * Math.min(0.05, (now - previous) / 1000);
      previous = now;
      if (delta) {
        const scroll = Math.max(0, el.arrangementGrid.scrollLeft + delta);
        updateTimeline(scroll);
        el.arrangementGrid.scrollLeft = scroll;
        syncArrangementScroll();
        previewClip(dragPointer);
      }
      autoScrollFrame = requestAnimationFrame(frame);
    }
    autoScrollFrame = requestAnimationFrame(frame);
  }
  async function openClip(clip) {
    state.activeTrackId = clip.track_id;
    state.editorClipId = clip.clip_id;
    await executeProjectCommand("selection.set", { track_ids: [clip.track_id], note_ids: [], clip_ids: [clip.clip_id] }, { quiet: true });
    ensureTrackPitchesVisible(clip.track_id, true);
    setDetailPanel("editor");
    render();
  }

  function renderArrangement() {
    if (!manual()) { menu.close(); stopAutoScroll(); }
    const selectedClips = new Set(selectedClipIds());
    const pixelsPerBeat = state.arrangementPixelsPerBeat;
    updateTimeline(state.arrangementScrollLeft);
    const routes = state.project.tracks;
    el.arrangementGrid.replaceChildren(
      ...routes.map((track, index) => {
        const row = document.createElement("article");
        const trackSelected = selectedTrackIds().includes(track.track_id);
        row.className = `arrangement-row${track.track_id === state.activeTrackId ? " active" : ""}${trackSelected ? " selected" : ""}`;
        row.dataset.trackId = track.track_id;
        row.style.setProperty("--track-color", track.color || trackColor(index));
        const clips = state.project.clips.filter((clip) => clip.track_id === track.track_id);
        const enabledEffects = countEnabledEffects(track);
        row.innerHTML = `
          <header role="button" tabindex="0" aria-label="Select ${escapeHtml(track.name || track.track_id)} track">
            <span class="route-color"></span>
            <span class="route-number">${String(track.number || index + 1).padStart(2, "0")}</span>
            <div class="route-main">
              <strong>${escapeHtml(track.name || track.track_id)}</strong>
              <small>${escapeHtml(INSTRUMENTS[track.instrument] || track.instrument || roleLabel(track.role))}</small>
            </div>
            <div class="arrange-track-controls">
              ${EDITOR_MODEL.trackControls
                .map(
                  (control) =>
                    `<button class="${routeControlValue(track.track_id, control.key) ? "active" : ""}" data-control="${control.key}" title="${escapeHtml(control.title)}">${control.label}</button>`,
                )
                .join("")}
              <button class="track-fx-button${enabledEffects ? " active" : ""}" data-track-effects title="打开轨道声音设置">FX${enabledEffects ? " " + enabledEffects : ""}</button>
            </div>
          </header>
          <div class="clip-lane">
            <div class="lane-beat-grid" aria-hidden="true"></div>
          </div>
        `;
        const trackHeader = row.querySelector("header");
        const lane = row.querySelector(".clip-lane");
        lane.dataset.trackId = track.track_id;
        row.addEventListener("contextmenu", event => {
          event.preventDefault();
          if (!manual()) { event.stopPropagation(); menu.close(); return; }
          const clipElement = event.target.closest(".clip");
          const clip = clipElement && state.project.clips.find(item => item.clip_id === clipElement.dataset.clipId);
          if (clip) {
            menu.open(event, [
              { label: "打开音符编辑器", run: () => openClip(clip) },
              { label: "复制片段", disabled: !manual(), run: () => executeProjectCommand("clips.duplicate", { clip_ids: [clip.clip_id], delta_beats: clip.duration_beats }, { quiet: true }) },
              { label: "删除片段", danger: true, disabled: !manual(), run: () => executeProjectCommand("clips.delete", { clip_ids: [clip.clip_id] }, { quiet: true }) },
            ]);
          } else {
            const beat = event.target.closest(".clip-lane") ? Math.max(0, snapBeat(beatAtLanePointer(event, lane))) : transportPositionBeats();
            menu.open(event, [
              { label: "在此处新建片段", disabled: !manual(), run: () => executeProjectCommand("clips.create", { track_id: track.track_id, start_beats: beat, duration_beats: currentBeatsPerBar(), name: track.name + " 片段" }, { quiet: true }) },
              { label: "新建轨道", run: addTrack },
              { label: "轨道声音设置", disabled: !manual(), run: () => openTrackEffects(track.track_id) },
              { label: "删除整个轨道", danger: true, disabled: !manual(), run: async () => {
                if (clips.length && !await confirmAction("这条轨道及其全部片段将被删除。可通过撤销恢复。", "删除轨道", "删除轨道")) return;
                await executeProjectCommand("tracks.delete", { track_id: track.track_id }, { quiet: true });
              }},
            ]);
          }
        });
        trackHeader.addEventListener("click", () => void selectArrangementTrack(track.track_id));
        trackHeader.addEventListener("keydown", (event) => {
          if (event.key !== "Enter" && event.key !== " ") return;
          event.preventDefault();
          void selectArrangementTrack(track.track_id);
        });
        trackHeader.querySelectorAll("[data-control]").forEach((button) => {
          button.addEventListener("click", (event) => {
            event.stopPropagation();
            void toggleTrackControl(track.track_id, button.dataset.control);
          });
        });
        trackHeader.querySelector("[data-track-effects]")?.addEventListener("click", (event) => {
          event.stopPropagation();
          openTrackEffects(track.track_id);
        });
        lane.addEventListener("pointerdown", (event) => handleRangePointerDown(event, lane, track.track_id));
        lane.addEventListener("dblclick", (event) => {
          if (!manual()) return;
          if (event.target.closest(".clip")) return;
          event.preventDefault();
          const start = Math.max(0, snapBeat(beatAtLanePointer(event, lane)));
          void executeProjectCommand(
            "clips.create",
            { track_id: track.track_id, start_beats: start, duration_beats: currentBeatsPerBar(), name: "MIDI 片段" },
            { quiet: true },
          );
        });
        const playhead = document.createElement("i");
        playhead.className = "arrangement-playhead";
        playhead.style.left = `${transportPositionBeats() * pixelsPerBeat}px`;
        playhead.setAttribute("aria-hidden", "true");
        lane.append(playhead);
        clips.forEach((clip) => {
          const clipEl = document.createElement("span");
          clipEl.className = `clip${selectedClips.has(clip.clip_id) ? " selected" : ""}`;
          clipEl.dataset.clipId = clip.clip_id;
          clipEl.tabIndex = 0;
          clipEl.setAttribute("role", "button");
          clipEl.setAttribute("aria-label", `${clip.name || "MIDI 片段"}，双击打开钢琴卷帘`);
          clipEl.title = manual() ? "拖动移动片段；拖动边缘调整范围，不拉伸音符；双击编辑音符" : "双击查看音符";
          clipEl.style.left = `${Number(clip.start_beats || 0) * pixelsPerBeat}px`;
          clipEl.style.width = `${Math.max(12, Number(clip.duration_beats || 0.25) * pixelsPerBeat)}px`;
          clipEl.innerHTML = `
            <span>${escapeHtml(clip.name || "片段")}</span>
            <em aria-hidden="true">${regionPreviewBars(clip, pixelsPerBeat)}</em>
            <i title="调整片段结束位置，不拉伸或自动增加音符"></i>
          `;
          clipEl.addEventListener("pointerdown", (event) => handleClipPointerDown(event, clip));
          clipEl.addEventListener("keydown", (event) => {
            if (event.key === "Enter") {
              event.preventDefault();
              void executeProjectCommand("selection.set", { note_ids: [], clip_ids: [clip.clip_id] }, { quiet: true });
            }
          });
          clipEl.addEventListener("dblclick", (event) => {
            event.preventDefault();
            event.stopPropagation();
            void openClip(clip);
          });
          lane.append(clipEl);
        });
        return row;
      }),
    );

    el.arrangementGrid.scrollLeft = state.arrangementScrollLeft;
    if (el.timelineViewport) el.timelineViewport.scrollLeft = state.arrangementScrollLeft;
  }

  function syncSelectionVisuals() {
    const selectedTracks = new Set(selectedTrackIds());
    const selectedClips = new Set(selectedClipIds());
    document.querySelectorAll(".arrangement-row").forEach((row) => {
      const trackId = row.dataset.trackId || row.querySelector(".clip-lane")?.dataset.trackId;
      row.classList.toggle("active", trackId === state.activeTrackId);
      row.classList.toggle("selected", selectedTracks.has(trackId));
    });
    document.querySelectorAll(".arrangement-row .clip").forEach((clip) => {
      clip.classList.toggle("selected", selectedClips.has(clip.dataset.clipId));
    });
    document.querySelectorAll(".track-item").forEach((item) => {
      const trackId = item.dataset.trackId;
      item.classList.toggle("active", trackId === state.activeTrackId);
      item.classList.toggle("selected", selectedTracks.has(trackId));
    });
  }

  async function selectArrangementTrack(trackId) {
    state.activeTrackId = trackId;
    if (state.editorOpen) ensureTrackPitchesVisible(trackId);
    await executeProjectCommand(
      "selection.set",
      { track_ids: [trackId], note_ids: [], clip_ids: [] },
      { quiet: true },
    );
  }

  function renderTimelineRuler(timelineBeats, beatsPerBar, pixelsPerBeat, timelineWidth, scrollLeft = state.arrangementScrollLeft) {
    if (!el.barScale) return;
    el.barScale.style.width = `${timelineWidth}px`;
    el.barScale.style.setProperty("--beat-width", `${pixelsPerBeat}px`);
    el.barScale.style.setProperty("--bar-width", `${pixelsPerBeat * beatsPerBar}px`);
    const firstBeat = Math.max(0, Math.floor(scrollLeft / pixelsPerBeat) - beatsPerBar * 2);
    const lastBeat = Math.min(Math.ceil(timelineBeats), Math.ceil((scrollLeft + el.arrangementGrid.clientWidth) / pixelsPerBeat) + beatsPerBar * 2);
    el.barScale.replaceChildren(
      ...Array.from({ length: lastBeat - firstBeat + 1 }, (_, offset) => {
        const index = firstBeat + offset;
        const tick = document.createElement("span");
        const beatInBar = index % beatsPerBar;
        const isBar = beatInBar === 0;
        tick.className = `ruler-tick ${isBar ? "bar-tick" : "beat-tick"}`;
        tick.style.left = `${index * pixelsPerBeat}px`;
        if (isBar) {
          tick.textContent = `${String(Math.floor(index / beatsPerBar) + 1).padStart(3, "0")}.1`;
        } else if (pixelsPerBeat >= 24) {
          tick.textContent = `.${beatInBar + 1}`;
        }
        return tick;
      }),
    );
  }

  function syncArrangementScroll() {
    state.arrangementScrollLeft = el.arrangementGrid.scrollLeft;
    updateTimeline(state.arrangementScrollLeft);
    if (el.timelineViewport) el.timelineViewport.scrollLeft = state.arrangementScrollLeft;
  }

  function handleArrangementWheel(event) {
    if (event.ctrlKey || event.metaKey) {
      event.preventDefault();
      const gridRect = el.arrangementGrid.getBoundingClientRect();
      const anchorX = clamp(event.clientX - gridRect.left, 236, gridRect.width);
      const timelineX = state.arrangementScrollLeft + anchorX - 236;
      const anchorBeat = Math.max(0, timelineX / state.arrangementPixelsPerBeat);
      const factor = Math.exp(-event.deltaY * 0.002);
      state.arrangementPixelsPerBeat = clamp(state.arrangementPixelsPerBeat * factor, 12, 96);
      state.arrangementScrollLeft = Math.max(0, anchorBeat * state.arrangementPixelsPerBeat - anchorX + 236);
      renderArrangement();
      return;
    }
    if (event.shiftKey && Math.abs(event.deltaY) > Math.abs(event.deltaX)) {
      event.preventDefault();
      updateTimeline(Math.max(0, el.arrangementGrid.scrollLeft + event.deltaY));
      el.arrangementGrid.scrollLeft += event.deltaY;
    }
  }

  function handleTimelineRulerClick(event) {
    const rect = el.barScale.getBoundingClientRect();
    const beat = (event.clientX - rect.left) / state.arrangementPixelsPerBeat;
    void setArrangementPlayhead(beat);
  }

  function beatAtLanePointer(event, lane) {
    return (event.clientX - lane.getBoundingClientRect().left) / state.arrangementPixelsPerBeat;
  }

  async function setArrangementPlayhead(beat) {
    const position = beatToTransportPosition(Math.max(0, snapBeat(beat)));
    state.project.transport.position = position;
    renderTransport();
    renderArrangement();
    await executeProjectCommand("transport.set_state", { position }, { quiet: true });
  }

  function trackGlyph(role) {
    return {
      lead: "♪",
      harmony: "♬",
      guitar: "⌁",
      bass: "𝄢",
      drums: "◉",
      pad: "≈",
    }[role] || "♪";
  }

  function handleClipPointerDown(event, clip) {
    if (state.project?.editing?.mode !== "manual") return;
    if (event.button !== 0) return;
    event.preventDefault();
    event.stopPropagation();
    state.activeTrackId = clip.track_id;
    document.querySelectorAll(".arrangement-row").forEach((row) => row.classList.remove("active"));
    event.currentTarget.closest(".arrangement-row")?.classList.add("active");
    const clipRect = event.currentTarget.getBoundingClientRect();
    const laneRect = event.currentTarget.parentElement.getBoundingClientRect();
    state.clipInteraction = {
      clipId: clip.clip_id,
      type: event.clientX <= clipRect.left + 10 ? "trim-start" : event.clientX >= clipRect.right - 10 ? "resize" : "move",
      startX: event.clientX,
      startScroll: el.arrangementGrid.scrollLeft,
      currentX: event.clientX,
      laneWidth: laneRect.width,
      pixelsPerBeat: state.arrangementPixelsPerBeat,
      baseWidth: clipRect.width,
      hasMoved: false,
      element: event.currentTarget,
      additive: event.ctrlKey || event.metaKey,
      sourceTrackId: clip.track_id,
    };
    event.currentTarget.setPointerCapture?.(event.pointerId);
  }

  function handleClipPointerMove(event) {
    const interaction = state.clipInteraction;
    if (!interaction) return;
    event.preventDefault();
    startAutoScroll(event);
    previewClip(event);
  }

  function previewClip(event) {
    const interaction = state.clipInteraction;
    if (!interaction) return;
    const dx = event.clientX - interaction.startX + el.arrangementGrid.scrollLeft - interaction.startScroll;
    interaction.deltaX = dx;
    interaction.currentX = event.clientX;
    interaction.hasMoved = interaction.hasMoved || Math.abs(dx) > 3;
    if (interaction.type === "move") {
      interaction.element.style.transform = `translateX(${dx}px)`;
    } else if (interaction.type === "resize") {
      interaction.element.style.width = `${Math.max(12, interaction.baseWidth + dx)}px`;
    } else {
      interaction.element.style.transform = `translateX(${dx}px)`;
      interaction.element.style.width = `${Math.max(12, interaction.baseWidth - dx)}px`;
    }
  }

  async function handleClipPointerUp(event) {
    stopAutoScroll();
    const interaction = state.clipInteraction;
    if (!interaction) return;
    const visualWidth = interaction.element.getBoundingClientRect().width;
    state.clipInteraction = null;
    interaction.element.style.transform = "";
    interaction.element.style.width = `${Math.max(12, visualWidth)}px`;
    const deltaBeats = snapBeat(
      (interaction.deltaX || 0) / interaction.pixelsPerBeat,
    );
    if (!interaction.hasMoved || deltaBeats === 0) {
      const selected = new Set(selectedClipIds());
      if (interaction.additive) {
        if (selected.has(interaction.clipId)) selected.delete(interaction.clipId);
        else selected.add(interaction.clipId);
      } else {
        selected.clear();
        selected.add(interaction.clipId);
      }
      await executeProjectCommand(
        "selection.set",
        { note_ids: [], clip_ids: [...selected] },
        { quiet: true },
      );
      return;
    }
    const targetLane = document.elementFromPoint(event.clientX, event.clientY)?.closest?.(".clip-lane");
    const targetTrackId = targetLane?.dataset.trackId || interaction.sourceTrackId;
    await executeProjectCommand(
      interaction.type === "resize" ? "clips.resize" : interaction.type === "trim-start" ? "clips.trim_start" : "clips.move",
      { clip_ids: [interaction.clipId], delta_beats: deltaBeats, target_track_id: targetTrackId },
      { quiet: true },
    );
  }

  function handleRangePointerDown(event, lane, trackId) {
    if (!manual()) return;
    if (event.button !== 0 || event.target.closest(".clip")) return;
    event.preventDefault();
    const startBeat = Math.max(0, snapBeat(beatAtLanePointer(event, lane)));
    const overlay = document.createElement("span");
    overlay.className = "arrangement-range-selection";
    overlay.style.left = `${startBeat * state.arrangementPixelsPerBeat}px`;
    overlay.style.width = "1px";
    lane.append(overlay);
    state.rangeInteraction = { lane, trackId, startBeat, currentBeat: startBeat, overlay, moved: false };
    lane.setPointerCapture?.(event.pointerId);
  }

  function handleRangePointerMove(event) {
    const interaction = state.rangeInteraction;
    if (!interaction) return;
    const beat = Math.max(0, snapBeat(beatAtLanePointer(event, interaction.lane)));
    interaction.currentBeat = beat;
    interaction.moved = interaction.moved || Math.abs(beat - interaction.startBeat) >= Number(el.gridSelect.value || 0.25);
    const start = Math.min(interaction.startBeat, beat);
    const end = Math.max(interaction.startBeat, beat);
    interaction.overlay.style.left = `${start * state.arrangementPixelsPerBeat}px`;
    interaction.overlay.style.width = `${Math.max(1, (end - start) * state.arrangementPixelsPerBeat)}px`;
  }

  async function handleRangePointerUp() {
    const interaction = state.rangeInteraction;
    if (!interaction) return;
    state.rangeInteraction = null;
    interaction.overlay.remove();
    const start = Math.min(interaction.startBeat, interaction.currentBeat);
    const end = Math.max(interaction.startBeat, interaction.currentBeat);
    state.activeTrackId = interaction.trackId;
    if (!interaction.moved) {
      await setArrangementPlayhead(start);
      return;
    }
    const clipIds = state.project.clips
      .filter((clip) => clip.track_id === interaction.trackId && clip.start_beats < end && clip.start_beats + clip.duration_beats > start)
      .map((clip) => clip.clip_id);
    await executeProjectCommand(
      "selection.set",
      { track_ids: [interaction.trackId], note_ids: [], clip_ids: clipIds, range: { start_beats: start, end_beats: end } },
      { quiet: true },
    );
  }


  return {
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
  };
}
