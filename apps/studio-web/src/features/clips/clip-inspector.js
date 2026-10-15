export function createClipInspector({ root, getProject, getSelection, executeCommand, getPlayheadBeat }) {
  if (!root) return { render() {} };
  const empty = root.querySelector("[data-clip-empty]");
  const form = root.querySelector("[data-clip-form]");
  const name = root.querySelector("[name='clip-name']");
  const start = root.querySelector("[name='clip-start']");
  const duration = root.querySelector("[name='clip-duration']");
  let activeClipId = null;
  let activeClipDuration = 4;

  function selectedClip() {
    const ids = getSelection()?.selected_clip_ids || [];
    if (ids.length !== 1) return null;
    return getProject()?.clips?.find((clip) => clip.clip_id === ids[0]) || null;
  }

  function render() {
    const clip = selectedClip();
    activeClipId = clip?.clip_id || null;
    activeClipDuration = Number(clip?.duration_beats || 4);
    empty.hidden = Boolean(clip);
    form.hidden = !clip;
    if (!clip) return;
    name.value = clip.name || "MIDI 片段";
    start.value = Number(clip.start_beats || 0).toFixed(2);
    duration.value = Number(clip.duration_beats || 0).toFixed(2);
  }

  form?.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!activeClipId) return;
    await executeCommand("clips.set_properties", {
      clip_ids: [activeClipId],
      name: name.value.trim(),
      start_beats: Number(start.value),
      duration_beats: Number(duration.value),
    });
  });
  root.querySelector("[data-clip-action='duplicate']")?.addEventListener("click", () => {
    if (activeClipId) void executeCommand("clips.duplicate", { clip_ids: [activeClipId], delta_beats: activeClipDuration });
  });
  root.querySelector("[data-clip-action='split']")?.addEventListener("click", () => {
    if (activeClipId) void executeCommand("clips.split", { clip_ids: [activeClipId], at_beats: getPlayheadBeat() });
  });
  root.querySelector("[data-clip-action='delete']")?.addEventListener("click", async () => {
    const clipId = activeClipId;
    if (clipId && await confirmAction("删除这个片段？可通过撤销恢复。", "删除片段", "删除片段"))
      await executeCommand("clips.delete", { clip_ids: [clipId] });
  });

  return { render };
}
import { confirmAction } from "../../shared/dialogs.js";

