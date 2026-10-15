export function createPianoRollController({
  state,
  elements,
  executeCommand,
  getProjectNotes,
  getProjectEndBeat,
  getSelectedNoteIds,
  getCurrentTrack,
  helpers,
}) {
  const el = elements;
  const ctx = el.canvas.getContext("2d");
  const executeProjectCommand = executeCommand;
  const projectNotes = () => {
    const notes = getProjectNotes();
    return state.editorClipId ? notes.filter(note => note.clip_id === state.editorClipId) : notes;
  };
  const projectEndBeat = getProjectEndBeat;
  const selectedNoteIds = getSelectedNoteIds;
  const currentTrack = getCurrentTrack;
  const { clamp, formatBeat, noteName, roundRect, snapBeat, trackColor } = helpers;
  const clearButton = document.querySelector("#clear-note-selection");
  clearButton?.addEventListener("click", () => {
    cancelPendingClearSelection();
    state.interaction = null;
    void executeProjectCommand("selection.set", { note_ids: [], clip_ids: [] }, { quiet: true });
  });

  function runViewAction(action) {
    if (action === "fit") {
      state.view.zoomX = 1;
      state.view.scrollBeat = 0;
    }
    if (action === "zoom-in") {
      zoomPianoRoll(1.35);
    }
    if (action === "zoom-out") {
      zoomPianoRoll(1 / 1.35);
    }
    clampViewToProject();
    renderPianoRoll();
  }

  function handlePianoRollWheel(event) {
    if (state.project.project_id === "empty") return;
    event.preventDefault();
    if (event.ctrlKey || event.metaKey) {
      zoomPianoRoll(event.deltaY < 0 ? 1.16 : 1 / 1.16, canvasPoint(event));
    } else if (event.shiftKey) {
      const metrics = state.rollMetrics;
      const visibleDuration = metrics?.visibleDuration || Math.max(8, projectEndBeat());
      state.view.scrollBeat += (event.deltaY / 420) * visibleDuration;
    } else {
      state.view.pitchTop -= event.deltaY / 32;
      clampPitchView();
    }
    clampViewToProject();
    renderPianoRoll();
  }

  function zoomPianoRoll(factor, anchorPoint = null) {
    const metrics = state.rollMetrics;
    const projectLength = Math.max(8, projectEndBeat());
    const oldZoom = state.view.zoomX;
    const nextZoom = clamp(oldZoom * factor, 1, 12);
    if (!metrics || !anchorPoint) {
      state.view.zoomX = nextZoom;
      clampViewToProject();
      return;
    }
    const anchorRatio = clamp((anchorPoint.x - metrics.left) / metrics.rollWidth, 0, 1);
    const anchorBeat = metrics.visibleStartBeat + anchorRatio * metrics.visibleDuration;
    const nextDuration = projectLength / nextZoom;
    state.view.zoomX = nextZoom;
    state.view.scrollBeat = anchorBeat - anchorRatio * nextDuration;
    clampViewToProject();
  }

  function handlePianoRollPointerDown(event) {
    if (state.project?.editing?.mode !== "manual") return;
    if (shouldIgnoreMouseFallback(event)) return;
    if (event.button !== 0 || state.project.project_id === "empty") return;
    markPointerInput(event);
    event.preventDefault();
    const point = canvasPoint(event);
    const velocityHit = hitTestVelocity(point);
    if (velocityHit) cancelPendingClearSelection();
    const hit = hitTestNote(point);
    if (hit) cancelPendingClearSelection();
    state.interaction = {
      type: velocityHit ? "velocity-edit" : hit?.edge === "end" ? "note-resize" : hit ? "note-drag" : "box-select",
      start: point,
      current: point,
      hit: velocityHit || hit,
      hasMoved: false,
      shiftKey: event.shiftKey,
      selectedAtStart: selectedNoteIds(),
    };
    if (event.pointerId !== undefined && el.canvas.setPointerCapture) {
      el.canvas.setPointerCapture(event.pointerId);
    }
  }

  function handlePianoRollPointerMove(event) {
    if (shouldIgnoreMouseFallback(event)) return;
    if (!state.interaction) {
      updatePianoRollCursor(event);
      return;
    }
    markPointerInput(event);
    event.preventDefault();
    const point = canvasPoint(event);
    const distance = Math.hypot(point.x - state.interaction.start.x, point.y - state.interaction.start.y);
    state.interaction.current = point;
    state.interaction.hasMoved = state.interaction.hasMoved || distance > 3;
    renderPianoRoll();
  }

  async function handlePianoRollPointerUp(event) {
    if (shouldIgnoreMouseFallback(event)) return;
    if (!state.interaction) return;
    markPointerInput(event);
    event.preventDefault();
    const interaction = state.interaction;
    state.interaction = null;
    if (event.pointerId !== undefined && el.canvas.hasPointerCapture?.(event.pointerId)) {
      el.canvas.releasePointerCapture(event.pointerId);
    }

    if (interaction.type === "velocity-edit" && interaction.hit) {
      const noteIds = selectedOrHitNoteIds(interaction.hit, interaction.selectedAtStart);
      state.velocityCommandAppliedAt = Date.now();
      await executeProjectCommand(
        "notes.velocity",
        { note_ids: noteIds, velocity: velocityFromPoint(interaction.current) },
        { quiet: true },
      );
      return;
    }

    if (!interaction.hasMoved) {
      if (interaction.hit) {
        await selectNotesFromHit(interaction.hit, interaction.shiftKey);
      } else {
        scheduleClearSelection();
      }
      return;
    }

    if (interaction.type === "note-drag" && interaction.hit) {
      const delta = dragDelta(interaction.start, interaction.current);
      const noteIds = selectedOrHitNoteIds(interaction.hit, interaction.selectedAtStart);
      if (delta.delta_beats === 0 && delta.delta_pitch === 0) {
        await selectNotesFromHit(interaction.hit, interaction.shiftKey);
        return;
      }
      await executeProjectCommand(
        "notes.move",
        { note_ids: noteIds, delta_beats: delta.delta_beats, delta_pitch: delta.delta_pitch },
        { quiet: true },
      );
      return;
    }

    if (interaction.type === "note-resize" && interaction.hit) {
      const delta = resizeDelta(interaction.start, interaction.current);
      const noteIds = selectedOrHitNoteIds(interaction.hit, interaction.selectedAtStart);
      if (delta.delta_beats === 0) {
        await selectNotesFromHit(interaction.hit, interaction.shiftKey);
        return;
      }
      await executeProjectCommand(
        "notes.resize",
        { note_ids: noteIds, delta_beats: delta.delta_beats },
        { quiet: true },
      );
      return;
    }

    if (interaction.type === "box-select") {
      const box = normalizedRect(interaction.start, interaction.current);
      const boxed = state.noteHitRegions
        .filter((region) => rectsIntersect(box, region))
        .map((region) => region.note_id);
      const noteIds = interaction.shiftKey ? toggleNoteIds(interaction.selectedAtStart, boxed) : boxed;
      await executeProjectCommand("selection.set", { note_ids: noteIds }, { quiet: true });
      return;
    }

    renderPianoRoll();
  }

  function shouldIgnoreMouseFallback(event) {
    return event.type.startsWith("mouse") && Date.now() - state.recentPointerInputAt < 500;
  }

  function markPointerInput(event) {
    if (event.type.startsWith("pointer")) {
      state.recentPointerInputAt = Date.now();
    }
  }

  async function handlePianoRollClickFallback(event) {
    if (state.interaction || state.project.project_id === "empty") return;
    if (Date.now() - state.velocityCommandAppliedAt < 500) return;
    const point = canvasPoint(event);
    const hit = hitTestVelocity(point);
    if (!hit) return;
    event.preventDefault();
    state.velocityCommandAppliedAt = Date.now();
    await executeProjectCommand(
      "notes.velocity",
      { note_ids: selectedOrHitNoteIds(hit), velocity: velocityFromPoint(point) },
      { quiet: true },
    );
  }

  function cancelPianoRollInteraction() {
    cancelPendingClearSelection();
    state.interaction = null;
    renderPianoRoll();
  }

  function scheduleClearSelection() {
    cancelPendingClearSelection();
    state.pendingClearSelection = window.setTimeout(() => {
      state.pendingClearSelection = null;
      executeProjectCommand("selection.set", { note_ids: [] }, { quiet: true });
    }, 180);
  }

  function cancelPendingClearSelection() {
    if (!state.pendingClearSelection) return;
    window.clearTimeout(state.pendingClearSelection);
    state.pendingClearSelection = null;
  }

  async function addNoteFromCanvas(event) {
    event.preventDefault();
    cancelPendingClearSelection();
    const point = canvasPoint(event);
    if (hitTestNote(point) || !state.rollMetrics || state.project.project_id === "empty") return;
    const position = pointToBeatPitch(point);
    const target = defaultNoteTarget();
    if (!target) return;
    const clip = state.project.clips.find(item => item.clip_id === target.clip_id);
    if (clip && (position.start_beats < clip.start_beats || position.start_beats >= clip.start_beats + clip.duration_beats)) return;
    await executeProjectCommand(
      "notes.add",
      {
        track_id: target.track_id,
        clip_id: target.clip_id,
        pitch: position.pitch,
        start_beats: position.start_beats,
        duration_beats: Number(el.gridSelect.value || 0.25),
        velocity: 96,
        channel: 0,
      },
      { quiet: true },
    );
  }

  async function selectNotesFromHit(hit, shiftKey) {
    const current = new Set(selectedNoteIds());
    if (shiftKey) {
      if (current.has(hit.note_id)) current.delete(hit.note_id);
      else current.add(hit.note_id);
    } else {
      current.clear();
      current.add(hit.note_id);
    }
    await executeProjectCommand("selection.set", { note_ids: [...current] }, { quiet: true });
  }

  async function selectAllNotes() {
    if (state.editorOpen) {
      const noteIds = projectNotes()
        .filter((note) => note.track_id === state.activeTrackId)
        .map((note) => note.note_id);
      await executeProjectCommand("selection.set", { note_ids: noteIds, clip_ids: [] }, { quiet: true });
      return;
    }
    const clipIds = state.project.clips.map((clip) => clip.clip_id);
    await executeProjectCommand("selection.set", { note_ids: [], clip_ids: clipIds }, { quiet: true });
  }

  function renderPianoRoll() {
    state.rollMetrics = null;
    state.noteHitRegions = [];
    state.velocityHitRegions = [];
    if (!state.editorOpen || !el.canvas || el.canvas.offsetParent === null) return;
    const rect = el.canvas.getBoundingClientRect();
    if (rect.width < 96 || rect.height < 96) return;
    const dpr = window.devicePixelRatio || 1;
    el.canvas.width = Math.max(1, Math.floor(rect.width * dpr));
    el.canvas.height = Math.max(1, Math.floor(rect.height * dpr));
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

    const width = el.canvas.width / dpr;
    const height = el.canvas.height / dpr;
    ctx.clearRect(0, 0, width, height);
    drawBackground(width, height);

    const allNotes = projectNotes().filter((note) => note.track_id === state.activeTrackId);
    state.noteHitRegions = [];
    state.velocityHitRegions = [];

    if (!allNotes.length) {
      ctx.fillStyle = "rgba(238, 244, 248, 0.82)";
      ctx.font = "600 22px Aptos, Segoe UI, sans-serif";
      ctx.fillText("当前轨道没有 MIDI 音符", 36, 68);
      ctx.fillStyle = "rgba(159, 174, 188, 0.72)";
      ctx.font = "13px Aptos, Segoe UI, sans-serif";
      ctx.fillText("请在时间线或左侧轨道列表中选择另一条轨道。", 37, 96);
      return;
    }

    const { minPitch, maxPitch, pitchSpan } = visiblePitchRange();
    const fullEndBeat = Math.max(8, projectEndBeat());
    clampViewToProject();
    const visibleDuration = Math.max(1, fullEndBeat / state.view.zoomX);
    const visibleStartBeat = clamp(state.view.scrollBeat, 0, Math.max(0, fullEndBeat - visibleDuration));
    const visibleEndBeat = visibleStartBeat + visibleDuration;
    const left = 76;
    const top = 36;
    const right = 12;
    const bottom = 14;
    const rollWidth = width - left - right;
    const rollHeight = height - top - bottom;
    state.rollMetrics = {
      left,
      top,
      rollWidth,
      rollHeight,
      fullEndBeat,
      visibleStartBeat,
      visibleEndBeat,
      visibleDuration,
      minPitch,
      maxPitch,
      pitchSpan,
    };

    drawGrid(left, top, rollWidth, rollHeight, visibleStartBeat, visibleEndBeat, minPitch, maxPitch, Number(el.gridSelect.value || 0.25));

    const selected = new Set(selectedNoteIds());
    allNotes.forEach((midiNote) => {
      const noteEnd = midiNote.start_beats + midiNote.duration_beats;
      if (noteEnd < visibleStartBeat || midiNote.start_beats > visibleEndBeat) return;
      if (midiNote.pitch < minPitch || midiNote.pitch > maxPitch) return;
      const rawX = left + ((midiNote.start_beats - visibleStartBeat) / visibleDuration) * rollWidth;
      const rawW = (midiNote.duration_beats / visibleDuration) * rollWidth;
      const x = clamp(rawX, left, left + rollWidth);
      const y = top + ((maxPitch - midiNote.pitch) / pitchSpan) * rollHeight;
      const w = Math.max(4, Math.min(left + rollWidth, rawX + rawW) - x);
      const h = Math.max(7, rollHeight / pitchSpan - 1);
      ctx.fillStyle = trackColor(midiNote.trackIndex);
      ctx.globalAlpha = midiNote.track_id === state.activeTrackId ? 1 : 0.58;
      roundRect(ctx, x, y, w, h, 5);
      ctx.fill();
      ctx.globalAlpha = 1;
      if (w >= 26 && h >= 8) {
        ctx.fillStyle = "rgba(5, 12, 17, 0.82)";
        ctx.font = `${Math.min(9, h - 2)}px Cascadia Code, monospace`;
        ctx.textBaseline = "middle";
        ctx.fillText(noteName(midiNote.pitch), x + 5, y + h / 2, Math.max(0, w - 8));
        ctx.textBaseline = "alphabetic";
      }
      if (selected.has(midiNote.note_id)) {
        ctx.strokeStyle = "#eef2f7";
        ctx.lineWidth = 2;
        roundRect(ctx, x - 1, y - 1, w + 2, h + 2, 6);
        ctx.stroke();
      }
      state.noteHitRegions.push({
        note_id: midiNote.note_id,
        track_id: midiNote.track_id,
        clip_id: midiNote.clip_id,
        x,
        y,
        width: w,
        height: h,
      });
    });
    drawViewportRuler();
    drawInteractionOverlay();
  }

  function canvasPoint(event) {
    const bounds = el.canvas.getBoundingClientRect();
    return {
      x: event.clientX - bounds.left,
      y: event.clientY - bounds.top,
    };
  }

  function hitTestNote(point) {
    const region = [...state.noteHitRegions].reverse().find((candidate) => {
      return (
        point.x >= candidate.x &&
        point.x <= candidate.x + candidate.width &&
        point.y >= candidate.y &&
        point.y <= candidate.y + candidate.height
      );
    });
    if (!region) return null;
    const edgeSize = Math.max(6, Math.min(10, region.width * 0.28));
    return {
      ...region,
      edge: point.x >= region.x + region.width - edgeSize ? "end" : "body",
    };
  }

  function hitTestVelocity(point) {
    const metrics = state.rollMetrics;
    if (
      !metrics ||
      point.y < metrics.velocityTop ||
      point.y > metrics.velocityTop + metrics.velocityHeight ||
      point.x < metrics.left ||
      point.x > metrics.left + metrics.rollWidth
    ) {
      return null;
    }
    const selectedIds = selectedNoteIds();
    if (selectedIds.length) {
      return { note_id: selectedIds[0] };
    }
    const exact = [...state.velocityHitRegions].reverse().find((region) => {
      return point.x >= region.x && point.x <= region.x + region.width;
    });
    if (exact) return exact;

    return state.velocityHitRegions
      .map((region) => ({
        ...region,
        distance: Math.abs(point.x - (region.x + region.width / 2)),
      }))
      .sort((a, b) => a.distance - b.distance)[0] || null;
  }

  function selectedOrHitNoteIds(hit, selectedAtStart = selectedNoteIds()) {
    return selectedAtStart.includes(hit.note_id) ? selectedAtStart : [hit.note_id];
  }

  function dragDelta(start, current) {
    const metrics = state.rollMetrics;
    if (!metrics) return { delta_beats: 0, delta_pitch: 0 };
    const grid = Number(el.gridSelect.value || 0.25);
    const deltaBeats = snapBeat(((current.x - start.x) / metrics.rollWidth) * metrics.visibleDuration, grid);
    const noteHeight = metrics.rollHeight / metrics.pitchSpan;
    const deltaPitch = -Math.round((current.y - start.y) / noteHeight);
    return {
      delta_beats: deltaBeats,
      delta_pitch: deltaPitch,
    };
  }

  function resizeDelta(start, current) {
    const metrics = state.rollMetrics;
    if (!metrics) return { delta_beats: 0 };
    const grid = Number(el.gridSelect.value || 0.25);
    return {
      delta_beats: snapBeat(((current.x - start.x) / metrics.rollWidth) * metrics.visibleDuration, grid),
    };
  }

  function pointToBeatPitch(point) {
    const metrics = state.rollMetrics;
    const grid = Number(el.gridSelect.value || 0.25);
    const x = clamp(point.x, metrics.left, metrics.left + metrics.rollWidth);
    const y = clamp(point.y, metrics.top, metrics.top + metrics.rollHeight);
    const startBeats = snapBeat(
      metrics.visibleStartBeat + ((x - metrics.left) / metrics.rollWidth) * metrics.visibleDuration,
      grid,
    );
    const pitchOffset = Math.floor(((y - metrics.top) / metrics.rollHeight) * metrics.pitchSpan);
    return {
      start_beats: clamp(startBeats, 0, metrics.fullEndBeat),
      pitch: clamp(metrics.maxPitch - pitchOffset, metrics.minPitch, metrics.maxPitch),
    };
  }

  function velocityFromPoint(point) {
    const metrics = state.rollMetrics;
    if (!metrics) return 96;
    const y = clamp(point.y, metrics.velocityTop, metrics.velocityTop + metrics.velocityHeight);
    return Math.round(clamp(127 - ((y - metrics.velocityTop) / metrics.velocityHeight) * 126, 1, 127));
  }

  function defaultNoteTarget() {
    const opened = state.project.clips.find(clip => clip.clip_id === state.editorClipId);
    if (opened) return { track_id: opened.track_id, clip_id: opened.clip_id };
    const selected = new Set(selectedNoteIds());
    const selectedNote = projectNotes().find((note) => selected.has(note.note_id));
    if (selectedNote) {
      return { track_id: selectedNote.track_id, clip_id: selectedNote.clip_id };
    }
    const clip = state.project.clips.find((item) => item.track_id === state.activeTrackId) || state.project.clips[0];
    return clip ? { track_id: clip.track_id, clip_id: clip.clip_id } : null;
  }

  function normalizedRect(start, current) {
    const x = Math.min(start.x, current.x);
    const y = Math.min(start.y, current.y);
    return {
      x,
      y,
      width: Math.abs(current.x - start.x),
      height: Math.abs(current.y - start.y),
    };
  }

  function rectsIntersect(a, b) {
    return a.x <= b.x + b.width && a.x + a.width >= b.x && a.y <= b.y + b.height && a.y + a.height >= b.y;
  }

  function toggleNoteIds(baseIds, toggledIds) {
    const current = new Set(baseIds);
    toggledIds.forEach((noteId) => {
      if (current.has(noteId)) current.delete(noteId);
      else current.add(noteId);
    });
    return [...current];
  }

  function updatePianoRollCursor(event) {
    const point = canvasPoint(event);
    const velocityHit = hitTestVelocity(point);
    const hit = hitTestNote(point);
    el.canvas.dataset.tool = velocityHit ? "velocity" : hit?.edge === "end" ? "resize" : hit ? "move" : "select";
  }

  function drawInteractionOverlay() {
    const interaction = state.interaction;
    if (!interaction?.hasMoved || !state.rollMetrics) return;

    if (interaction.type === "box-select") {
      const box = normalizedRect(interaction.start, interaction.current);
      ctx.fillStyle = "rgba(75, 168, 255, 0.12)";
      ctx.strokeStyle = "rgba(75, 168, 255, 0.78)";
      ctx.lineWidth = 1.5;
      roundRect(ctx, box.x, box.y, box.width, box.height, 8);
      ctx.fill();
      ctx.stroke();
      drawFloatingLabel(
        interaction.current.x + 12,
        interaction.current.y - 28,
        interaction.shiftKey ? "切换选择" : "框选",
        "#4ba8ff",
      );
      return;
    }

    if (interaction.type === "velocity-edit") {
      const velocity = velocityFromPoint(interaction.current);
      const metrics = state.rollMetrics;
      const y = metrics.velocityTop + metrics.velocityHeight - (velocity / 127) * metrics.velocityHeight;
      ctx.beginPath();
      ctx.moveTo(metrics.left, y);
      ctx.lineTo(metrics.left + metrics.rollWidth, y);
      ctx.strokeStyle = "rgba(184, 245, 71, 0.84)";
      ctx.lineWidth = 1.5;
      ctx.stroke();
      drawFloatingLabel(interaction.current.x + 12, interaction.current.y - 28, `力度 ${velocity}`, "#b8f547", 118);
      return;
    }

    if (!["note-drag", "note-resize"].includes(interaction.type) || !interaction.hit) return;
    const delta = interaction.type === "note-resize" ? resizeDelta(interaction.start, interaction.current) : dragDelta(interaction.start, interaction.current);
    const metrics = state.rollMetrics;
    const dx = interaction.type === "note-resize" ? 0 : (delta.delta_beats / metrics.visibleDuration) * metrics.rollWidth;
    const dw = interaction.type === "note-resize" ? (delta.delta_beats / metrics.visibleDuration) * metrics.rollWidth : 0;
    const dy = interaction.type === "note-resize" ? 0 : (-delta.delta_pitch / metrics.pitchSpan) * metrics.rollHeight;
    const dragged = new Set(selectedOrHitNoteIds(interaction.hit, interaction.selectedAtStart));

    ctx.save();
    ctx.globalAlpha = 0.48;
    ctx.fillStyle = "#eef2f7";
    ctx.strokeStyle = "rgba(184, 245, 71, 0.88)";
    ctx.lineWidth = 2;
    state.noteHitRegions
      .filter((region) => dragged.has(region.note_id))
      .forEach((region) => {
        roundRect(ctx, region.x + dx, region.y + dy, Math.max(4, region.width + dw), region.height, 5);
        ctx.fill();
        ctx.stroke();
      });
    ctx.restore();

    const label =
      interaction.type === "note-resize"
        ? `长度 ${delta.delta_beats >= 0 ? "+" : ""}${delta.delta_beats} 拍`
        : `${delta.delta_beats >= 0 ? "+" : ""}${delta.delta_beats} 拍 / ${delta.delta_pitch >= 0 ? "+" : ""}${delta.delta_pitch} 半音`;
    drawFloatingLabel(interaction.current.x + 12, interaction.current.y - 28, label, "#b8f547", 170);
  }

  function drawFloatingLabel(x, y, label, color, width = 132) {
    ctx.fillStyle = "rgba(8, 11, 16, 0.9)";
    ctx.strokeStyle = "rgba(238, 242, 247, 0.18)";
    roundRect(ctx, x, y, width, 24, 9);
    ctx.fill();
    ctx.stroke();
    ctx.fillStyle = color;
    ctx.font = "11px Cascadia Code, monospace";
    ctx.fillText(label, x + 10, y + 16);
  }

  function drawVelocityLane(allNotes, selected) {
    const metrics = state.rollMetrics;
    const { left, rollWidth, velocityTop, velocityHeight, visibleStartBeat, visibleEndBeat, visibleDuration } = metrics;
    ctx.fillStyle = "rgba(238, 242, 247, 0.03)";
    ctx.fillRect(left, velocityTop, rollWidth, velocityHeight);
    ctx.strokeStyle = "rgba(238, 242, 247, 0.1)";
    ctx.strokeRect(left, velocityTop, rollWidth, velocityHeight);
    ctx.fillStyle = "rgba(154, 167, 184, 0.72)";
    ctx.font = "10px Cascadia Code, monospace";
    ctx.fillText("VEL", 13, velocityTop + 16);

    [32, 64, 96, 127].forEach((velocity) => {
      const y = velocityTop + velocityHeight - (velocity / 127) * velocityHeight;
      ctx.beginPath();
      ctx.moveTo(left, y);
      ctx.lineTo(left + rollWidth, y);
      ctx.strokeStyle = velocity === 64 ? "rgba(238, 242, 247, 0.12)" : "rgba(238, 242, 247, 0.06)";
      ctx.stroke();
    });

    state.velocityHitRegions = [];
    allNotes.forEach((note) => {
      const noteEnd = note.start_beats + note.duration_beats;
      if (noteEnd < visibleStartBeat || note.start_beats > visibleEndBeat) return;
      const rawX = left + ((note.start_beats - visibleStartBeat) / visibleDuration) * rollWidth;
      const rawW = (note.duration_beats / visibleDuration) * rollWidth;
      const x = clamp(rawX, left, left + rollWidth);
      const width = Math.max(5, Math.min(left + rollWidth, rawX + rawW) - x);
      const barHeight = Math.max(3, (Number(note.velocity || 96) / 127) * velocityHeight);
      const y = velocityTop + velocityHeight - barHeight;
      ctx.fillStyle = trackColor(note.trackIndex);
      ctx.globalAlpha = selected.has(note.note_id) ? 0.96 : note.track_id === state.activeTrackId ? 0.56 : 0.28;
      roundRect(ctx, x, y, width, barHeight, 3);
      ctx.fill();
      ctx.globalAlpha = 1;
      if (selected.has(note.note_id)) {
        ctx.strokeStyle = "rgba(238, 242, 247, 0.86)";
        ctx.lineWidth = 1.4;
        roundRect(ctx, x - 1, y - 1, width + 2, barHeight + 2, 4);
        ctx.stroke();
      }
      state.velocityHitRegions.push({
        note_id: note.note_id,
        track_id: note.track_id,
        clip_id: note.clip_id,
        x,
        y: velocityTop,
        width,
        height: velocityHeight,
      });
    });
  }

  function drawViewportRuler() {
    const metrics = state.rollMetrics;
    const { left, rollWidth, top, rollHeight, fullEndBeat, visibleStartBeat, visibleDuration } = metrics;
    const y = top + rollHeight + 5;
    ctx.fillStyle = "rgba(238, 242, 247, 0.08)";
    roundRect(ctx, left, y, rollWidth, 5, 3);
    ctx.fill();
    const windowX = left + (visibleStartBeat / fullEndBeat) * rollWidth;
    const windowW = Math.max(20, (visibleDuration / fullEndBeat) * rollWidth);
    ctx.fillStyle = "rgba(184, 245, 71, 0.72)";
    roundRect(ctx, windowX, y, windowW, 5, 3);
    ctx.fill();
  }

  function drawBackground(width, height) {
    const gradient = ctx.createLinearGradient(0, 0, width, height);
    gradient.addColorStop(0, "#101722");
    gradient.addColorStop(0.56, "#080b10");
    gradient.addColorStop(1, "#0d1118");
    ctx.fillStyle = gradient;
    ctx.fillRect(0, 0, width, height);
  }

  function drawGrid(left, top, width, height, visibleStartBeat, visibleEndBeat, minPitch, maxPitch, gridBeats) {
    const visibleDuration = visibleEndBeat - visibleStartBeat;
    const pitchSpan = maxPitch - minPitch + 1;
    const rowHeight = height / pitchSpan;
    const beatsPerBar = Number(state.project.time_signatures?.[0]?.numerator || 4);

    ctx.fillStyle = "rgba(7, 12, 17, 0.96)";
    ctx.fillRect(0, top, left, height);
    for (let pitch = maxPitch; pitch >= minPitch; pitch -= 1) {
      const row = maxPitch - pitch;
      const y = top + row * rowHeight;
      const black = isBlackPitch(pitch);
      ctx.fillStyle = black ? "rgba(8, 15, 22, 0.94)" : "rgba(38, 49, 58, 0.52)";
      ctx.fillRect(left, y, width, rowHeight);
      ctx.fillStyle = "#d7dee3";
      ctx.fillRect(0, y + 0.5, left - 1, Math.max(1, rowHeight - 1));
      if (black) {
        const blackKeyHeight = Math.max(4, rowHeight * 0.68);
        const blackKeyY = y + (rowHeight - blackKeyHeight) / 2;
        ctx.fillStyle = "#111b23";
        ctx.fillRect(0, blackKeyY, left * 0.58, blackKeyHeight);
        ctx.strokeStyle = "rgba(111, 139, 156, 0.42)";
        ctx.strokeRect(0.5, blackKeyY + 0.5, left * 0.58 - 1, Math.max(1, blackKeyHeight - 1));
      }
      ctx.fillStyle = black ? "#d8e0e5" : "#26333c";
      ctx.font = `${Math.max(7, Math.min(9, rowHeight - 2))}px Cascadia Code, monospace`;
      ctx.textAlign = "right";
      ctx.textBaseline = "middle";
      ctx.fillText(noteName(pitch), black ? left * 0.58 - 5 : left - 6, y + rowHeight / 2);
      ctx.beginPath();
      ctx.moveTo(0, y + rowHeight);
      ctx.lineTo(left + width, y + rowHeight);
      ctx.strokeStyle = pitch % 12 === 0 ? "rgba(92, 190, 255, 0.24)" : "rgba(221, 231, 237, 0.055)";
      ctx.lineWidth = pitch % 12 === 0 ? 1.2 : 1;
      ctx.stroke();
    }
    ctx.textAlign = "left";
    ctx.textBaseline = "alphabetic";

    const firstBar = Math.floor(visibleStartBeat / beatsPerBar);
    const lastBar = Math.ceil(visibleEndBeat / beatsPerBar);
    for (let bar = firstBar; bar <= lastBar; bar += 1) {
      if (bar % 2 === 0) continue;
      const start = Math.max(visibleStartBeat, bar * beatsPerBar);
      const end = Math.min(visibleEndBeat, (bar + 1) * beatsPerBar);
      if (end <= start) continue;
      const x = left + ((start - visibleStartBeat) / visibleDuration) * width;
      const barWidth = ((end - start) / visibleDuration) * width;
      ctx.fillStyle = "rgba(184, 245, 71, 0.022)";
      ctx.fillRect(x, top, barWidth, height);
    }

    let step = Math.max(0.0625, Number(gridBeats) || 0.25);
    while ((step / visibleDuration) * width < 7) step *= 2;
    const firstStep = Math.floor(visibleStartBeat / step) * step;
    for (let beat = firstStep; beat <= visibleEndBeat + step * 0.25; beat += step) {
      if (beat < visibleStartBeat - 0.0001) continue;
      const roundedBeat = Math.round(beat * 10000) / 10000;
      const isWholeBeat = Math.abs(roundedBeat - Math.round(roundedBeat)) < 0.0001;
      const wholeBeat = Math.round(roundedBeat);
      const isBar = isWholeBeat && ((wholeBeat % beatsPerBar) + beatsPerBar) % beatsPerBar === 0;
      const x = left + ((roundedBeat - visibleStartBeat) / visibleDuration) * width;
      ctx.beginPath();
      ctx.moveTo(x, top);
      ctx.lineTo(x, top + height);
      ctx.strokeStyle = isBar
        ? "rgba(184, 245, 71, 0.36)"
        : isWholeBeat
          ? "rgba(238, 242, 247, 0.16)"
          : "rgba(238, 242, 247, 0.065)";
      ctx.lineWidth = isBar ? 1.5 : 1;
      ctx.stroke();
      if (isWholeBeat && (1 / visibleDuration) * width >= 22) {
        const barNumber = Math.floor(wholeBeat / beatsPerBar) + 1;
        const beatNumber = ((wholeBeat % beatsPerBar) + beatsPerBar) % beatsPerBar + 1;
        ctx.fillStyle = isBar ? "rgba(205, 252, 119, 0.92)" : "rgba(174, 188, 199, 0.78)";
        ctx.font = isBar ? "600 10px Cascadia Code, monospace" : "9px Cascadia Code, monospace";
        ctx.fillText(`${barNumber}.${beatNumber}`, x + 4, top - 12);
      }
    }
  }

  function isBlackPitch(pitch) {
    return [1, 3, 6, 8, 10].includes(((pitch % 12) + 12) % 12);
  }

  function clampViewToProject() {
    const projectLength = Math.max(8, projectEndBeat());
    state.view.zoomX = clamp(Number(state.view.zoomX) || 1, 1, 12);
    const visibleDuration = Math.max(1, projectLength / state.view.zoomX);
    state.view.scrollBeat = clamp(Number(state.view.scrollBeat) || 0, 0, Math.max(0, projectLength - visibleDuration));
  }

  function clampPitchView() {
    const visiblePitches = clamp(Math.round(Number(state.view.visiblePitches) || 33), 24, 49);
    state.view.visiblePitches = visiblePitches;
    state.view.pitchTop = clamp(
      Math.round(Number(state.view.pitchTop) || 84),
      visiblePitches - 1,
      127,
    );
  }

  function visiblePitchRange() {
    clampPitchView();
    const maxPitch = state.view.pitchTop;
    return {
      minPitch: maxPitch - state.view.visiblePitches + 1,
      maxPitch,
      pitchSpan: state.view.visiblePitches,
    };
  }

  function ensureTrackPitchesVisible(trackId, force = false) {
    const notes = state.project.clips
      .filter((clip) => clip.track_id === trackId)
      .flatMap((clip) => clip.notes || []);
    if (!notes.length) return;

    const range = visiblePitchRange();
    const alreadyVisible = notes.some((note) => note.pitch >= range.minPitch && note.pitch <= range.maxPitch);
    if (!force && alreadyVisible) return;

    const lowest = Math.min(...notes.map((note) => note.pitch));
    const highest = Math.max(...notes.map((note) => note.pitch));
    const center = (lowest + highest) / 2;
    state.view.pitchTop = Math.round(center + (state.view.visiblePitches - 1) / 2);
    clampPitchView();
  }


  return {
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
  };
}
