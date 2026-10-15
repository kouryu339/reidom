// Use the timeline scale, not a percentage of clip width: resizing the
// container must reveal/crop notes without visually stretching their timing.
export function regionPreviewBars(clip, pixelsPerBeat) {
  const clipStart = Number(clip.start_beats ?? 0);
  const notes = (clip.notes || []).filter((note) =>
    Number(note.start_beats ?? 0) + Number(note.duration_beats ?? 0.25) > clipStart,
  );
  if (!notes.length) return "";
  const pitches = notes.map((note) => Number(note.pitch ?? 60));
  const minPitch = Math.min(...pitches);
  const pitchSpan = Math.max(1, Math.max(...pitches) - minPitch);
  return notes.slice(0, 96).map((note) => {
    const left = (Number(note.start_beats ?? 0) - clipStart) * pixelsPerBeat;
    const width = Number(note.duration_beats ?? 0.25) * pixelsPerBeat;
    const bottom = 5 + ((Number(note.pitch ?? 60) - minPitch) / pitchSpan) * 82;
    return `<b style="left:${left.toFixed(3)}px;bottom:${bottom.toFixed(1)}%;width:${width.toFixed(3)}px;height:2px"></b>`;
  }).join("");
}
