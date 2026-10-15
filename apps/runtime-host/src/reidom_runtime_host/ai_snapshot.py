from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any


SnapshotFields = dict[str, str]

MAX_IDS = 12


def build_ai_snapshot_fields(
    project: dict[str, Any] | None,
    selection: dict[str, Any] | None = None,
    adapter: dict[str, Any] | None = None,
) -> SnapshotFields:
    """Build compact host-observed state fields for Runtime dynamic snapshots."""

    project = project or {}
    selection = selection or project.get("selection") or {}
    notes = _project_notes(project)
    selection_notes = _selected_or_ranged_notes(selection, notes)
    return {
        "reidom.project": _project_snapshot(project, notes),
        "reidom.arrangement": _arrangement_snapshot(project, notes),
        "reidom.selection": _selection_snapshot(project, selection, selection_notes),
        "reidom.adapter": _adapter_snapshot(selection, adapter),
    }


def build_ai_snapshot_text(fields: SnapshotFields) -> str:
    """Combine field snapshots into a readable diagnostic block."""

    return "\n\n".join(fields[key] for key in sorted(fields))


def _project_snapshot(project: dict[str, Any], notes: list[dict[str, Any]]) -> str:
    tempo = _tempo(project)
    signature = _signature(project)
    end_beat = _project_end_beat(project, notes)
    return "\n".join(
        [
            "[reidom.project]",
            "Current host-observed Reidom project state, not a user request.",
            f"Project: {_value(project.get('name'), 'Untitled')} ({_value(project.get('project_id'))})",
            f"Revision: {_value(project.get('revision'), 0)}",
            f"Tempo: {tempo:g} BPM",
            f"Time signature: {signature}",
            f"Key: {_value(project.get('key_signature'), 'unknown')}",
            f"Length: {_format_beats(end_beat)} beats",
            f"Tracks: {len(project.get('tracks') or [])}",
            f"Clips: {len(project.get('clips') or [])}",
            f"Notes: {len(notes)}",
            f"Undo available: {_yes_no(project.get('undo_stack'))}",
            f"Redo available: {_yes_no(project.get('redo_stack'))}",
        ]
    )


def _arrangement_snapshot(project: dict[str, Any], notes: list[dict[str, Any]]) -> str:
    lines = [
        "[reidom.arrangement]",
        "Current arrangement overview for musical judgment, not instructions.",
        f"Sections: {_sections_summary(project)}",
    ]
    notes_by_track: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for note in notes:
        notes_by_track[str(note.get("track_id") or "")].append(note)

    tracks = project.get("tracks") or []
    if not tracks:
        lines.append("Tracks: none")
        return "\n".join(lines)

    lines.append("Tracks:")
    for track in tracks[:12]:
        track_id = str(track.get("track_id") or "")
        track_notes = notes_by_track.get(track_id, [])
        reading = _musical_reading(track_notes, str(track.get("role") or "unknown"))
        lines.append(
            "- "
            f"{_value(track.get('name'), track_id)} "
            f"({track_id}): role={_value(track.get('role'), 'unknown')}, "
            f"notes={len(track_notes)}, "
            f"range={_pitch_range(track_notes)}, "
            f"density={_density(track_notes)}, "
            f"grid={_grid_feel(track_notes)}, "
            f"reading={reading}"
        )
    if len(tracks) > 12:
        lines.append(f"- ... {len(tracks) - 12} more track(s) omitted")
    return "\n".join(lines)


def _selection_snapshot(
    project: dict[str, Any],
    selection: dict[str, Any],
    selected_notes: list[dict[str, Any]],
) -> str:
    selected_note_ids = _string_list(selection.get("selected_note_ids"))
    selected_clip_ids = _string_list(selection.get("selected_clip_ids"))
    active_tracks = _active_track_names(project, selected_notes, selected_clip_ids)
    range_text = _range_summary(selection)
    lines = [
        "[reidom.selection]",
        "Current host-observed MIDI selection, not a user request.",
        f"Selection id: {_value(selection.get('selection_id'), 'none')}",
        f"Project id: {_value(selection.get('project_id') or project.get('project_id'), 'none')}",
        f"Base revision: {_value(selection.get('revision') or project.get('revision'), 0)}",
        f"Source: {_selection_source(selection)}",
        f"Range: {range_text}",
        f"Selected clips: {_ids_summary(selected_clip_ids)}",
        f"Selected notes: {_ids_summary(selected_note_ids)}",
        f"Active tracks: {_list_summary(active_tracks)}",
        "Musical selection summary:",
        f"- note count: {len(selected_notes)}",
        f"- pitch range: {_pitch_range(selected_notes)}",
        f"- average velocity: {_average_velocity(selected_notes)}",
        f"- density: {_density(selected_notes)}",
        f"- grid feel: {_grid_feel(selected_notes)}",
        f"- phrase shape: {_phrase_shape(selected_notes)}",
        f"- likely material: {_musical_reading(selected_notes, _dominant_role(project, selected_notes))}",
    ]
    if not selected_note_ids and not selected_clip_ids:
        lines.append("Selection focus: no explicit note or clip selection; treat the visible/bounded MIDI context as reference material.")
    return "\n".join(lines)


def _adapter_snapshot(selection: dict[str, Any], adapter: dict[str, Any] | None) -> str:
    capabilities = (adapter or {}).get("capabilities") or {}
    lines = [
        "[reidom.adapter]",
        "Current DAW/adapter and safety state, not a user request.",
        f"Adapter: {_value((adapter or {}).get('name'), _selection_source(selection))}",
        f"Adapter id: {_value((adapter or {}).get('id'), _selection_source(selection))}",
        f"Read MIDI selection: {_capability(capabilities.get('read_midi_selection'), default='yes')}",
        f"MIDI command tools: {_capability(capabilities.get('midi_command_tools'), default='dedicated reversible edit tools')}",
        f"Command log: {_capability(capabilities.get('command_log'), default='host command history')}",
        f"Undo/redo: {_capability(capabilities.get('undo_redo'), default='host command history')}",
        "AI safety boundary:",
        "- use small explainable MIDI commands against the current context/base revision",
        "- record each change with source, reason, and command metadata",
        "- use undo/redo instead of trying to manually reverse unknown state",
        "- do not invent track, clip, note, selection, or revision IDs",
    ]
    return "\n".join(lines)


def _project_notes(project: dict[str, Any]) -> list[dict[str, Any]]:
    tracks_by_id = {track.get("track_id"): track for track in project.get("tracks") or []}
    notes: list[dict[str, Any]] = []
    for clip in project.get("clips") or []:
        track_id = clip.get("track_id")
        track = tracks_by_id.get(track_id) or {}
        for note in clip.get("notes") or []:
            notes.append(
                {
                    **note,
                    "track_id": track_id,
                    "clip_id": clip.get("clip_id"),
                    "track_name": track.get("name") or track_id,
                    "track_role": track.get("role") or "unknown",
                    "clip_start_beats": float(clip.get("start_beats") or 0),
                }
            )
    return notes


def _selected_or_ranged_notes(
    selection: dict[str, Any],
    project_notes: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    selected_ids = set(_string_list(selection.get("selected_note_ids")))
    if selected_ids:
        return [note for note in project_notes if note.get("note_id") in selected_ids]

    selected_clip_ids = set(_string_list(selection.get("selected_clip_ids")))
    if selected_clip_ids:
        return [note for note in project_notes if note.get("clip_id") in selected_clip_ids]

    if project_notes:
        range_bounds = _range_bounds(selection)
        if range_bounds is not None:
            start, end = range_bounds
            return [
                note
                for note in project_notes
                if _note_overlaps_range(note, start, end)
            ]
        return project_notes

    selection_notes = []
    for track in selection.get("tracks") or []:
        for note in track.get("notes") or []:
            selection_notes.append(
                {
                    **note,
                    "track_id": track.get("track_id"),
                    "track_name": track.get("name") or track.get("track_id"),
                    "track_role": track.get("role") or "unknown",
                }
            )
    return selection_notes


def _note_overlaps_range(note: dict[str, Any], start: float, end: float) -> bool:
    note_start = float(note.get("start_beats") or 0)
    note_end = note_start + float(note.get("duration_beats") or 0)
    return note_start < end and note_end > start


def _range_bounds(selection: dict[str, Any]) -> tuple[float, float] | None:
    value = selection.get("range")
    if not isinstance(value, dict):
        return None
    start = value.get("start_beats")
    if start is None:
        return None
    if value.get("end_beats") is not None:
        end = float(value["end_beats"])
    elif value.get("duration_beats") is not None:
        end = float(start) + float(value["duration_beats"])
    else:
        return None
    return float(start), end


def _range_summary(selection: dict[str, Any]) -> str:
    bounds = _range_bounds(selection)
    if bounds is None:
        return "not specified"
    start, end = bounds
    return f"beats {_format_beats(start)} to {_format_beats(end)} ({_format_beats(end - start)} beats)"


def _project_end_beat(project: dict[str, Any], notes: list[dict[str, Any]]) -> float:
    candidates = [0.0]
    for clip in project.get("clips") or []:
        candidates.append(float(clip.get("start_beats") or 0) + float(clip.get("duration_beats") or 0))
    for note in notes:
        candidates.append(float(note.get("start_beats") or 0) + float(note.get("duration_beats") or 0))
    return max(candidates)


def _tempo(project: dict[str, Any]) -> float:
    tempo_map = project.get("tempo_map") or [{"bpm": 120}]
    return float((tempo_map[0] if tempo_map else {}).get("bpm") or 120)


def _signature(project: dict[str, Any]) -> str:
    signatures = project.get("time_signatures") or [{"numerator": 4, "denominator": 4}]
    signature = signatures[0] if signatures else {}
    return f"{int(signature.get('numerator') or 4)}/{int(signature.get('denominator') or 4)}"


def _sections_summary(project: dict[str, Any]) -> str:
    sections = project.get("sections") or []
    if not sections:
        return "none"
    values = [
        f"{section.get('name') or section.get('section_id')}@{_format_beats(section.get('start_beats') or 0)}+{_format_beats(section.get('duration_beats') or 0)}"
        for section in sections[:10]
    ]
    if len(sections) > 10:
        values.append(f"... {len(sections) - 10} more")
    return ", ".join(values)


def _active_track_names(
    project: dict[str, Any],
    selected_notes: list[dict[str, Any]],
    selected_clip_ids: list[str],
) -> list[str]:
    if selected_notes:
        return sorted({str(note.get("track_name") or note.get("track_id")) for note in selected_notes})
    if selected_clip_ids:
        clip_track_ids = {
            clip.get("track_id")
            for clip in project.get("clips") or []
            if clip.get("clip_id") in set(selected_clip_ids)
        }
        return [
            str(track.get("name") or track.get("track_id"))
            for track in project.get("tracks") or []
            if track.get("track_id") in clip_track_ids
        ]
    return []


def _dominant_role(project: dict[str, Any], notes: list[dict[str, Any]]) -> str:
    roles = [str(note.get("track_role") or "unknown") for note in notes if note.get("track_role")]
    if roles:
        return Counter(roles).most_common(1)[0][0]
    tracks = project.get("tracks") or []
    return str((tracks[0] if tracks else {}).get("role") or "unknown")


def _pitch_range(notes: list[dict[str, Any]]) -> str:
    if not notes:
        return "none"
    pitches = [int(note.get("pitch") or 0) for note in notes]
    return f"{_pitch_name(min(pitches))}-{_pitch_name(max(pitches))}"


def _average_velocity(notes: list[dict[str, Any]]) -> str:
    if not notes:
        return "none"
    return str(round(sum(int(note.get("velocity") or 0) for note in notes) / len(notes)))


def _density(notes: list[dict[str, Any]]) -> str:
    if not notes:
        return "none"
    start = min(float(note.get("start_beats") or 0) for note in notes)
    end = max(
        float(note.get("start_beats") or 0) + float(note.get("duration_beats") or 0)
        for note in notes
    )
    span = max(1.0, end - start)
    notes_per_beat = len(notes) / span
    if notes_per_beat < 0.35:
        label = "sparse"
    elif notes_per_beat < 1.2:
        label = "medium"
    else:
        label = "busy"
    return f"{label} ({notes_per_beat:.2f} notes/beat)"


def _grid_feel(notes: list[dict[str, Any]]) -> str:
    if len(notes) < 2:
        return "insufficient notes"
    starts = sorted({round(float(note.get("start_beats") or 0), 4) for note in notes})
    gaps = [round(starts[index + 1] - starts[index], 4) for index in range(len(starts) - 1)]
    positive = [gap for gap in gaps if gap > 0]
    if not positive:
        return "stacked/chordal"
    common = Counter(_nearest_grid(gap) for gap in positive).most_common(2)
    primary, count = common[0]
    confidence = count / len(positive)
    if confidence >= 0.65:
        return f"mostly {primary}"
    if len(common) > 1:
        return f"mixed {primary}/{common[1][0]}"
    return f"mixed around {primary}"


def _phrase_shape(notes: list[dict[str, Any]]) -> str:
    if not notes:
        return "none"
    starts: dict[float, list[int]] = defaultdict(list)
    for note in notes:
        starts[round(float(note.get("start_beats") or 0), 4)].append(int(note.get("pitch") or 0))
    chord_sizes = [len(pitches) for pitches in starts.values()]
    max_stack = max(chord_sizes)
    average_stack = sum(chord_sizes) / len(chord_sizes)
    if max_stack >= 3 and average_stack >= 1.8:
        return "chordal/polyphonic"
    if max_stack >= 2:
        return "mostly melodic with occasional intervals"
    ordered = [sum(pitches) / len(pitches) for _, pitches in sorted(starts.items())]
    if len(ordered) < 3:
        return "short motif"
    trend = ordered[-1] - ordered[0]
    if trend >= 5:
        return "ascending melodic contour"
    if trend <= -5:
        return "descending melodic contour"
    return "level or arch-like motif"


def _musical_reading(notes: list[dict[str, Any]], role: str) -> str:
    if not notes:
        return "empty or silent"
    role = role.lower()
    channels = {int(note.get("channel") or 0) for note in notes}
    pitches = [int(note.get("pitch") or 0) for note in notes]
    average_pitch = sum(pitches) / len(pitches)
    if role == "drums" or 9 in channels:
        return "drum/percussion pattern"
    shape = _phrase_shape(notes)
    if role == "bass" or average_pitch < 48:
        return f"bass material, {shape}"
    if role in {"harmony", "chords", "pad", "strings"} or "chordal" in shape:
        return f"harmony/accompaniment material, {shape}"
    if average_pitch >= 72:
        return f"upper melody/lead material, {shape}"
    return f"melodic or supporting MIDI material, {shape}"


def _nearest_grid(gap: float) -> str:
    grids = [
        (0.125, "1/32"),
        (0.25, "1/16"),
        (0.5, "1/8"),
        (1.0, "1/4"),
        (2.0, "1/2"),
        (4.0, "1 bar"),
    ]
    return min(grids, key=lambda item: abs(item[0] - gap))[1]


def _pitch_name(pitch: int) -> str:
    pitch = max(0, min(127, int(pitch)))
    names = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
    return f"{names[pitch % 12]}{pitch // 12 - 1}"


def _selection_source(selection: dict[str, Any]) -> str:
    source = selection.get("source") if isinstance(selection.get("source"), dict) else {}
    return str(source.get("daw_id") or source.get("adapter_id") or "unknown")


def _capability(value: Any, *, default: str) -> str:
    if value is None:
        return default
    if isinstance(value, bool):
        return "yes" if value else "no"
    return str(value)


def _ids_summary(ids: list[str]) -> str:
    if not ids:
        return "none"
    visible = ", ".join(ids[:MAX_IDS])
    if len(ids) > MAX_IDS:
        return f"{visible}, ... {len(ids) - MAX_IDS} more"
    return visible


def _list_summary(values: list[str]) -> str:
    if not values:
        return "none"
    visible = ", ".join(values[:MAX_IDS])
    if len(values) > MAX_IDS:
        return f"{visible}, ... {len(values) - MAX_IDS} more"
    return visible


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def _format_beats(value: Any) -> str:
    number = float(value or 0)
    text = f"{number:.4f}".rstrip("0").rstrip(".")
    return text or "0"


def _yes_no(value: Any) -> str:
    return "yes" if value else "no"


def _value(value: Any, fallback: Any = "unknown") -> str:
    if value is None or value == "":
        return str(fallback)
    return str(value)
