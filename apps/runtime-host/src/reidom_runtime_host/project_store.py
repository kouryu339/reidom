from __future__ import annotations

import json
import os
import tempfile
import uuid
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class MidiParseError(ValueError):
    pass


class MidiReader:
    def __init__(self, data: bytes):
        self.data = data
        self.offset = 0

    def remaining(self) -> int:
        return len(self.data) - self.offset

    def read_u8(self) -> int:
        if self.offset >= len(self.data):
            raise MidiParseError("unexpected end of MIDI data")
        value = self.data[self.offset]
        self.offset += 1
        return value

    def read_u16(self) -> int:
        return (self.read_u8() << 8) | self.read_u8()

    def read_u32(self) -> int:
        return (
            (self.read_u8() << 24) | (self.read_u8() << 16) | (self.read_u8() << 8) | self.read_u8()
        )

    def read_text(self, length: int) -> str:
        if self.offset + length > len(self.data):
            raise MidiParseError("unexpected end of MIDI text")
        value = self.data[self.offset : self.offset + length].decode("utf-8", errors="replace")
        self.offset += length
        return value

    def read_vlq(self) -> int:
        value = 0
        while True:
            byte = self.read_u8()
            value = (value << 7) | (byte & 0x7F)
            if not byte & 0x80:
                return value

    def skip(self, length: int) -> None:
        self.offset += length
        if self.offset > len(self.data):
            raise MidiParseError("unexpected end of MIDI skip")


class ProjectStore:
    """File-backed source of truth for Reidom project state."""

    def __init__(self, root: Path):
        self.root = root
        self.projects_dir = root / "projects"
        self.active_project_path = root / "active-project.json"
        self.projects_dir.mkdir(parents=True, exist_ok=True)

    def import_midi(self, file_name: str, data: bytes) -> dict[str, Any]:
        project = midi_bytes_to_project(file_name, data)
        self.save_project(project)
        return project

    def demo_project(self) -> dict[str, Any]:
        project = build_demo_project()
        self.save_project(project)
        return project

    def save_project(self, project: dict[str, Any]) -> None:
        if project.get("schema") != "reidom-project/v1":
            raise ValueError("expected reidom-project/v1")
        project_id = project.get("project_id")
        if not isinstance(project_id, str) or not project_id:
            raise ValueError("project_id is required")
        self._write_json_atomic(self.projects_dir / f"{project_id}.json", project)
        self._write_json_atomic(self.active_project_path, project)

    def project(self, project_id: str) -> dict[str, Any] | None:
        path = self.projects_dir / f"{project_id}.json"
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def active_project(self) -> dict[str, Any] | None:
        if not self.active_project_path.exists():
            return None
        return json.loads(self.active_project_path.read_text(encoding="utf-8"))

    def apply_command(self, project_id: str, command: dict[str, Any]) -> dict[str, Any]:
        project = self.project(project_id)
        if project is None:
            raise KeyError(f"unknown project: {project_id}")
        if command.get("base_revision") != project.get("revision"):
            raise ValueError("stale command base_revision")

        before = _history_snapshot(project)
        project = deepcopy(project)
        _apply_project_command(project, command)
        project["revision"] = int(project.get("revision", 0)) + 1
        project["selection"] = project_to_selection(
            project,
            selected_note_ids=project.get("selection", {}).get("selected_note_ids", []),
            selected_clip_ids=project.get("selection", {}).get("selected_clip_ids", []),
        )
        after = _history_snapshot(project)
        project.setdefault("undo_stack", []).append(
            {
                "command_id": command.get("command_id") or f"cmd-{uuid.uuid4().hex[:12]}",
                "timestamp": datetime.now(UTC).isoformat(),
                "source": command.get("source") or "unknown",
                "type": command.get("type"),
                "reason": command.get("reason") or "",
                "payload": deepcopy(command.get("payload") or {}),
                "base_revision": command.get("base_revision"),
                "result_revision": project.get("revision"),
                "before": before,
                "after": after,
            }
        )
        project["redo_stack"] = []
        self.save_project(project)
        return project

    def undo(self, project_id: str) -> dict[str, Any]:
        project = self.project(project_id)
        if project is None:
            raise KeyError(f"unknown project: {project_id}")
        undo_stack = project.setdefault("undo_stack", [])
        if not undo_stack:
            return project
        entry = undo_stack.pop()
        redo_stack = project.setdefault("redo_stack", [])
        redo_stack.append(entry)
        restored = deepcopy(entry["before"])
        restored["undo_stack"] = undo_stack
        restored["redo_stack"] = redo_stack
        self.save_project(restored)
        return restored

    def redo(self, project_id: str) -> dict[str, Any]:
        project = self.project(project_id)
        if project is None:
            raise KeyError(f"unknown project: {project_id}")
        redo_stack = project.setdefault("redo_stack", [])
        if not redo_stack:
            return project
        entry = redo_stack.pop()
        undo_stack = project.setdefault("undo_stack", [])
        undo_stack.append(entry)
        restored = deepcopy(entry["after"])
        restored["undo_stack"] = undo_stack
        restored["redo_stack"] = redo_stack
        self.save_project(restored)
        return restored

    def command_log(self, project_id: str, *, include_snapshots: bool = False) -> dict[str, Any]:
        project = self.project(project_id)
        if project is None:
            raise KeyError(f"unknown project: {project_id}")
        return {
            "schema": "reidom-command-log/v1",
            "project_id": project_id,
            "revision": project.get("revision"),
            "undo_entries": [
                _command_log_entry(entry, index, include_snapshots=include_snapshots)
                for index, entry in enumerate(project.get("undo_stack", []), start=1)
            ],
            "redo_entries": [
                _command_log_entry(entry, index, include_snapshots=include_snapshots)
                for index, entry in enumerate(project.get("redo_stack", []), start=1)
            ],
        }

    def export_midi(self, project_id: str) -> tuple[str, bytes]:
        project = self.project(project_id)
        if project is None:
            raise KeyError(f"unknown project: {project_id}")
        file_name = f"{project.get('name') or project_id}.mid"
        return file_name, project_to_midi_bytes(project)

    @staticmethod
    def _write_json_atomic(path: Path, value: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
                json.dump(value, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
            os.replace(temp_name, path)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)


def midi_bytes_to_project(file_name: str, data: bytes) -> dict[str, Any]:
    reader = MidiReader(data)
    if reader.read_text(4) != "MThd":
        raise MidiParseError("missing MThd header")
    header_length = reader.read_u32()
    midi_format = reader.read_u16()
    track_count = reader.read_u16()
    division = reader.read_u16()
    if header_length > 6:
        reader.skip(header_length - 6)
    ticks_per_quarter = 480 if division & 0x8000 else division
    if ticks_per_quarter <= 0:
        raise MidiParseError("invalid MIDI division")

    parsed_tracks: list[dict[str, Any]] = []
    tempo = 120.0
    for track_index in range(track_count):
        if reader.remaining() <= 0:
            break
        if reader.read_text(4) != "MTrk":
            raise MidiParseError(f"missing MTrk header for track {track_index + 1}")
        track_length = reader.read_u32()
        track_end = reader.offset + track_length
        parsed = _parse_track(reader, track_end, ticks_per_quarter, track_index)
        if parsed["tempo"] is not None:
            tempo = parsed["tempo"]
        if parsed["notes"]:
            parsed_tracks.append(parsed)
        reader.offset = track_end

    name = Path(file_name).stem or "Untitled MIDI"
    project_id = f"project-{uuid.uuid4().hex[:12]}"
    end_beats = max(
        [
            0.0,
            *[
                note["start_beats"] + note["duration_beats"]
                for track in parsed_tracks
                for note in track["notes"]
            ],
        ]
    )

    tracks: list[dict[str, Any]] = []
    clips: list[dict[str, Any]] = []
    for index, parsed_track in enumerate(parsed_tracks):
        track_id = f"track-{index + 1}"
        clip_id = f"{track_id}-clip-1"
        role = _infer_role(parsed_track["notes"])
        color = _track_color(index)
        tracks.append(
            {
                "track_id": track_id,
                "name": parsed_track["name"] or f"MIDI Track {index + 1}",
                "type": "midi",
                "role": role,
                "color": color,
                "mute": False,
                "solo": False,
                "arm": False,
                "volume": 0.85,
                "pan": 0.0,
                "instrument_ref": "midi",
                "clip_ids": [clip_id],
            }
        )
        clips.append(
            {
                "clip_id": clip_id,
                "track_id": track_id,
                "name": parsed_track["name"] or f"Clip {index + 1}",
                "start_beats": 0,
                "duration_beats": _round_beat(end_beats),
                "loop_enabled": False,
                "source_range": {"start_beats": 0, "end_beats": _round_beat(end_beats)},
                "color": color,
                "notes": parsed_track["notes"],
            }
        )

    project = {
        "schema": "reidom-project/v1",
        "project_id": project_id,
        "name": name,
        "revision": 1,
        "tempo_map": [{"start_beats": 0, "bpm": round(tempo, 4)}],
        "time_signatures": [{"start_beats": 0, "numerator": 4, "denominator": 4}],
        "key_signature": "unknown",
        "transport": _default_transport(tempo),
        "tracks": tracks,
        "clips": clips,
        "sections": _default_sections(end_beats),
        "markers": [],
        "selection": {},
        "undo_stack": [],
        "redo_stack": [],
        "source_files": [
            {
                "source_id": f"source-{uuid.uuid4().hex[:8]}",
                "file_name": file_name,
                "midi_format": midi_format,
                "ticks_per_quarter": ticks_per_quarter,
            }
        ],
    }
    project["selection"] = project_to_selection(project)
    return project


def project_to_selection(
    project: dict[str, Any],
    selected_note_ids: list[str] | None = None,
    selected_clip_ids: list[str] | None = None,
) -> dict[str, Any]:
    notes_by_track: dict[str, list[dict[str, Any]]] = {}
    for clip in project.get("clips", []):
        notes_by_track.setdefault(clip["track_id"], []).extend(clip.get("notes", []))
    tempo = project.get("tempo_map", [{"bpm": 120}])[0].get("bpm", 120)
    signature = project.get("time_signatures", [{"numerator": 4, "denominator": 4}])[0]
    end_beats = max(
        [
            0.0,
            *[
                note["start_beats"] + note["duration_beats"]
                for notes in notes_by_track.values()
                for note in notes
            ],
        ]
    )
    if selected_note_ids is None:
        selected_note_ids = project.get("selection", {}).get("selected_note_ids", [])
    if selected_clip_ids is None:
        selected_clip_ids = project.get("selection", {}).get("selected_clip_ids", [])
    return {
        "schema": "reidom-midi-selection/v1",
        "selection_id": f"selection-{project['revision']}",
        "project_id": project["project_id"],
        "revision": project["revision"],
        "source": {"daw_id": "midi-file", "project_id": project["project_id"]},
        "range": {"start_beats": 0, "end_beats": _round_beat(end_beats)},
        "tempo": tempo,
        "time_signature": {
            "numerator": signature.get("numerator", 4),
            "denominator": signature.get("denominator", 4),
        },
        "tracks": [
            {
                "track_id": track["track_id"],
                "name": track["name"],
                "role": track.get("role", "unknown"),
                "instrument": track.get("instrument_ref", "midi"),
                "notes": notes_by_track.get(track["track_id"], []),
            }
            for track in project.get("tracks", [])
        ],
        "selected_note_ids": selected_note_ids,
        "selected_clip_ids": selected_clip_ids,
    }


def _apply_project_command(project: dict[str, Any], command: dict[str, Any]) -> None:
    command_type = command.get("type")
    payload = command.get("payload") or {}
    if command_type == "transport.set_state":
        transport = project.setdefault("transport", _default_transport(_tempo_from_project(project)))
        for key in ["position", "loop", "punch", "metronome", "sync", "recording", "playing"]:
            if key in payload:
                transport[key] = payload[key]
        if "tempo" in payload or "bpm" in payload:
            bpm = float(payload.get("tempo", payload.get("bpm")))
            project.setdefault("tempo_map", [{"start_beats": 0, "bpm": bpm}])[0]["bpm"] = round(bpm, 4)
            transport["tempo"] = round(bpm, 4)
        project["selection"] = project_to_selection(
            project,
            selected_note_ids=project.get("selection", {}).get("selected_note_ids", []),
            selected_clip_ids=project.get("selection", {}).get("selected_clip_ids", []),
        )
        return

    if command_type == "routes.set_state":
        track_ids = _string_list(payload.get("track_ids"))
        if not track_ids and payload.get("track_id"):
            track_ids = [str(payload["track_id"])]
        state = payload.get("state") or {}
        if not isinstance(state, dict):
            raise ValueError("routes.set_state payload.state must be an object")
        if not track_ids:
            raise ValueError("routes.set_state requires track_id or track_ids")
        tracks = {str(track.get("track_id")): track for track in project.get("tracks", [])}
        missing = [track_id for track_id in track_ids if track_id not in tracks]
        if missing:
            raise ValueError(f"unknown track_ids: {', '.join(missing)}")
        allowed = {
            "record": "arm",
            "arm": "arm",
            "monitor": "monitor",
            "mute": "mute",
            "solo": "solo",
            "volume": "volume",
            "gain": "volume",
            "pan": "pan",
            "group": "group",
            "playlist": "playlist",
            "automation": "automation",
        }
        for track_id in track_ids:
            track = tracks[track_id]
            for input_key, output_key in allowed.items():
                if input_key not in state:
                    continue
                value = state[input_key]
                if output_key in {"arm", "monitor", "mute", "solo"}:
                    track[output_key] = bool(value)
                elif output_key in {"volume", "pan"}:
                    track[output_key] = float(value)
                else:
                    track[output_key] = str(value)
        project["selection"] = project_to_selection(
            project,
            selected_note_ids=project.get("selection", {}).get("selected_note_ids", []),
            selected_clip_ids=project.get("selection", {}).get("selected_clip_ids", []),
        )
        return

    if command_type == "selection.set":
        note_ids = _string_list(payload.get("note_ids"))
        clip_ids = _string_list(payload.get("clip_ids"))
        project["selection"] = project_to_selection(
            project,
            selected_note_ids=note_ids,
            selected_clip_ids=clip_ids,
        )
        return

    if command_type == "notes.add":
        note = _note(
            f"note-{uuid.uuid4().hex[:10]}",
            int(payload.get("pitch", 60)),
            float(payload.get("start_beats", 0)),
            float(payload.get("duration_beats", 0.25)),
            int(payload.get("velocity", 96)),
            int(payload.get("channel", 0)),
        )
        clip = _target_clip(project, payload)
        clip.setdefault("notes", []).append(note)
        clip["notes"].sort(key=lambda item: (float(item.get("start_beats", 0)), int(item.get("pitch", 0))))
        note_end = float(note["start_beats"]) + float(note["duration_beats"])
        clip["duration_beats"] = _round_beat(max(float(clip.get("duration_beats", 0)), note_end))
        source_range = clip.setdefault("source_range", {"start_beats": 0, "end_beats": clip["duration_beats"]})
        source_range["end_beats"] = _round_beat(max(float(source_range.get("end_beats", 0)), note_end))
        project["selection"] = project_to_selection(project, selected_note_ids=[note["note_id"]])
        return

    if command_type == "clips.move":
        clip_ids = _string_list(payload.get("clip_ids"))
        if not clip_ids:
            clip_ids = _string_list(project.get("selection", {}).get("selected_clip_ids"))
        delta_beats = float(payload.get("delta_beats", 0))
        for clip in _selected_clips(project, clip_ids):
            clip["start_beats"] = _round_beat(max(0, float(clip.get("start_beats", 0)) + delta_beats))
        project["selection"] = project_to_selection(project, selected_clip_ids=clip_ids)
        return

    if command_type == "clips.resize":
        clip_ids = _string_list(payload.get("clip_ids"))
        if not clip_ids:
            clip_ids = _string_list(project.get("selection", {}).get("selected_clip_ids"))
        delta_beats = float(payload.get("delta_beats", 0))
        for clip in _selected_clips(project, clip_ids):
            clip["duration_beats"] = _round_beat(
                max(0.25, float(clip.get("duration_beats", 0)) + delta_beats)
            )
            source_range = clip.setdefault("source_range", {"start_beats": 0, "end_beats": 0})
            source_range["end_beats"] = _round_beat(
                max(float(source_range.get("start_beats", 0)) + 0.25, float(source_range.get("end_beats", 0)) + delta_beats)
            )
        project["selection"] = project_to_selection(project, selected_clip_ids=clip_ids)
        return

    if command_type == "clips.duplicate":
        clip_ids = _string_list(payload.get("clip_ids"))
        if not clip_ids:
            clip_ids = _string_list(project.get("selection", {}).get("selected_clip_ids"))
        delta_beats = float(payload.get("delta_beats", 4))
        duplicated_clip_ids = []
        for clip in _selected_clips(project, clip_ids):
            copied = deepcopy(clip)
            copied["clip_id"] = f"clip-{uuid.uuid4().hex[:10]}"
            copied["name"] = f"{clip.get('name') or clip.get('clip_id')} Copy"
            copied["start_beats"] = _round_beat(max(0, float(copied.get("start_beats", 0)) + delta_beats))
            copied["notes"] = [
                {
                    **deepcopy(note),
                    "note_id": f"note-{uuid.uuid4().hex[:10]}",
                }
                for note in copied.get("notes", [])
            ]
            project.setdefault("clips", []).append(copied)
            duplicated_clip_ids.append(copied["clip_id"])
            for track in project.get("tracks", []):
                if track.get("track_id") == copied.get("track_id"):
                    track.setdefault("clip_ids", []).append(copied["clip_id"])
                    break
        project["selection"] = project_to_selection(project, selected_clip_ids=duplicated_clip_ids)
        return

    note_ids = _string_list(payload.get("note_ids"))
    if not note_ids:
        note_ids = _string_list(project.get("selection", {}).get("selected_note_ids"))
    if not note_ids:
        raise ValueError("command requires note_ids or an active note selection")

    if command_type == "notes.transpose":
        semitones = int(payload.get("semitones", 0))
        for note in _selected_notes(project, note_ids):
            note["pitch"] = max(0, min(127, int(note["pitch"]) + semitones))
        project["selection"] = project_to_selection(project, selected_note_ids=note_ids)
        return

    if command_type == "notes.delete":
        note_id_set = set(note_ids)
        for clip in project.get("clips", []):
            clip["notes"] = [
                note for note in clip.get("notes", []) if note.get("note_id") not in note_id_set
            ]
        project["selection"] = project_to_selection(project, selected_note_ids=[])
        return

    if command_type == "notes.move":
        delta_beats = float(payload.get("delta_beats", 0))
        delta_pitch = int(payload.get("delta_pitch", 0))
        for note in _selected_notes(project, note_ids):
            note["start_beats"] = _round_beat(max(0, float(note["start_beats"]) + delta_beats))
            note["pitch"] = max(0, min(127, int(note["pitch"]) + delta_pitch))
        project["selection"] = project_to_selection(project, selected_note_ids=note_ids)
        return

    if command_type == "notes.resize":
        delta_beats = float(payload.get("delta_beats", 0))
        for note in _selected_notes(project, note_ids):
            note["duration_beats"] = _round_beat(
                max(0.0313, float(note["duration_beats"]) + delta_beats)
            )
        project["selection"] = project_to_selection(project, selected_note_ids=note_ids)
        return

    if command_type == "notes.velocity":
        velocity = max(1, min(127, int(payload.get("velocity", 96))))
        for note in _selected_notes(project, note_ids):
            note["velocity"] = velocity
        project["selection"] = project_to_selection(project, selected_note_ids=note_ids)
        return

    if command_type == "notes.duplicate":
        delta_beats = float(payload.get("delta_beats", 0.25))
        duplicated_note_ids = []
        note_id_set = set(note_ids)
        for clip in project.get("clips", []):
            copies = []
            for note in clip.get("notes", []):
                if note.get("note_id") not in note_id_set:
                    continue
                copied = deepcopy(note)
                copied["note_id"] = f"note-{uuid.uuid4().hex[:10]}"
                copied["start_beats"] = _round_beat(max(0, float(copied["start_beats"]) + delta_beats))
                copies.append(copied)
                duplicated_note_ids.append(copied["note_id"])
            if copies:
                clip.setdefault("notes", []).extend(copies)
                clip["notes"].sort(
                    key=lambda item: (float(item.get("start_beats", 0)), int(item.get("pitch", 0)))
                )
        project["selection"] = project_to_selection(project, selected_note_ids=duplicated_note_ids)
        return

    if command_type == "notes.quantize":
        grid = float(payload.get("grid_beats", 0.25))
        if grid <= 0:
            raise ValueError("grid_beats must be positive")
        for note in _selected_notes(project, note_ids):
            note["start_beats"] = _round_beat(round(float(note["start_beats"]) / grid) * grid)
        project["selection"] = project_to_selection(project, selected_note_ids=note_ids)
        return

    raise ValueError(f"unsupported command type: {command_type}")


def _selected_notes(project: dict[str, Any], note_ids: list[str]) -> list[dict[str, Any]]:
    note_id_set = set(note_ids)
    notes = [
        note
        for clip in project.get("clips", [])
        for note in clip.get("notes", [])
        if note.get("note_id") in note_id_set
    ]
    if len(notes) != len(note_id_set):
        found = {note.get("note_id") for note in notes}
        missing = sorted(note_id_set - found)
        raise ValueError(f"unknown note_ids: {', '.join(missing)}")
    return notes


def _selected_clips(project: dict[str, Any], clip_ids: list[str]) -> list[dict[str, Any]]:
    if not clip_ids:
        raise ValueError("command requires clip_ids or an active clip selection")
    clip_id_set = set(clip_ids)
    clips = [clip for clip in project.get("clips", []) if clip.get("clip_id") in clip_id_set]
    if len(clips) != len(clip_id_set):
        found = {clip.get("clip_id") for clip in clips}
        missing = sorted(clip_id_set - found)
        raise ValueError(f"unknown clip_ids: {', '.join(missing)}")
    return clips


def _target_clip(project: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    clip_id = payload.get("clip_id")
    if clip_id:
        for clip in project.get("clips", []):
            if clip.get("clip_id") == clip_id:
                return clip
        raise ValueError(f"unknown clip_id: {clip_id}")

    track_id = payload.get("track_id")
    if track_id:
        for clip in project.get("clips", []):
            if clip.get("track_id") == track_id:
                return clip
        raise ValueError(f"track has no clip: {track_id}")

    clips = project.get("clips", [])
    if not clips:
        raise ValueError("project has no MIDI clip to add notes into")
    return clips[0]


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("expected a list of strings")
    return [str(item) for item in value]


def _history_snapshot(project: dict[str, Any]) -> dict[str, Any]:
    snapshot = deepcopy(project)
    snapshot["undo_stack"] = []
    snapshot["redo_stack"] = []
    return snapshot


def _command_log_entry(
    entry: dict[str, Any],
    index: int,
    *,
    include_snapshots: bool,
) -> dict[str, Any]:
    value = {
        "index": index,
        "command_id": entry.get("command_id"),
        "timestamp": entry.get("timestamp"),
        "source": entry.get("source"),
        "type": entry.get("type"),
        "reason": entry.get("reason") or "",
        "payload": deepcopy(entry.get("payload") or {}),
        "base_revision": entry.get("base_revision"),
        "result_revision": entry.get("result_revision"),
    }
    if include_snapshots:
        value["before"] = deepcopy(entry.get("before"))
        value["after"] = deepcopy(entry.get("after"))
    return value


def build_demo_project() -> dict[str, Any]:
    project_id = f"project-{uuid.uuid4().hex[:12]}"
    project = {
        "schema": "reidom-project/v1",
        "project_id": project_id,
        "name": "Reidom Demo",
        "revision": 1,
        "tempo_map": [{"start_beats": 0, "bpm": 126}],
        "time_signatures": [{"start_beats": 0, "numerator": 4, "denominator": 4}],
        "key_signature": "C minor",
        "transport": _default_transport(126),
        "tracks": [],
        "clips": [],
        "sections": [
            _section("section-1", "intro", 0, 8),
            _section("section-2", "verse", 8, 8),
            _section("section-3", "chorus", 16, 8),
        ],
        "markers": [],
        "selection": {},
        "undo_stack": [],
        "redo_stack": [],
        "source_files": [{"source_id": "demo", "file_name": "Reidom Demo.mid"}],
    }
    demo_tracks = [
        (
            "lead",
            "Neon Lead",
            "lead",
            [
                _note("l1", 72, 0, 0.75),
                _note("l2", 75, 1, 0.5),
                _note("l3", 79, 1.75, 1),
                _note("l4", 77, 3, 0.75),
                _note("l5", 72, 4, 0.75),
                _note("l6", 82, 5.25, 0.5),
                _note("l7", 79, 6, 1.5),
                _note("l8", 84, 12, 0.5),
                _note("l9", 82, 13, 0.75),
                _note("l10", 79, 14, 1.5),
            ],
        ),
        (
            "chords",
            "Warm Chords",
            "harmony",
            [
                _note("c1", 60, 0, 4, 76),
                _note("c2", 63, 0, 4, 76),
                _note("c3", 67, 0, 4, 76),
                _note("c4", 58, 4, 4, 76),
                _note("c5", 62, 4, 4, 76),
                _note("c6", 65, 4, 4, 76),
                _note("c7", 55, 8, 4, 76),
                _note("c8", 59, 8, 4, 76),
                _note("c9", 62, 8, 4, 76),
            ],
        ),
        (
            "bass",
            "Sub Bass",
            "bass",
            [
                _note("b1", 36, 0, 1),
                _note("b2", 36, 2, 0.75),
                _note("b3", 39, 4, 1),
                _note("b4", 43, 6, 0.75),
                _note("b5", 34, 8, 1),
                _note("b6", 36, 10, 1.5),
            ],
        ),
        (
            "drums",
            "Drum Sketch",
            "drums",
            [
                _note(
                    f"d{index}",
                    36 if index % 4 == 0 else 38 if index % 2 == 0 else 42,
                    index,
                    0.25,
                    86,
                )
                for index in range(24)
            ],
        ),
    ]
    for index, (track_id, name, role, notes) in enumerate(demo_tracks):
        clip_id = f"{track_id}-clip-1"
        color = _track_color(index)
        project["tracks"].append(
            {
                "track_id": track_id,
                "name": name,
                "type": "midi",
                "role": role,
                "color": color,
                "mute": False,
                "solo": False,
                "arm": False,
                "volume": 0.85,
                "pan": 0.0,
                "instrument_ref": "midi",
                "clip_ids": [clip_id],
            }
        )
        project["clips"].append(
            {
                "clip_id": clip_id,
                "track_id": track_id,
                "name": name,
                "start_beats": 0,
                "duration_beats": 24,
                "loop_enabled": False,
                "source_range": {"start_beats": 0, "end_beats": 24},
                "color": color,
                "notes": notes,
            }
        )
    project["selection"] = project_to_selection(project)
    return project


def project_to_midi_bytes(project: dict[str, Any]) -> bytes:
    ticks_per_quarter = 480
    chunks = [
        _midi_track_chunk(
            track.get("name", track["track_id"]),
            [
                note
                for clip in project.get("clips", [])
                if clip.get("track_id") == track["track_id"]
                for note in clip.get("notes", [])
            ],
            ticks_per_quarter,
        )
        for track in project.get("tracks", [])
    ]
    if not chunks:
        chunks.append(_midi_track_chunk("Empty", [], ticks_per_quarter))
    header = b"MThd" + (6).to_bytes(4, "big")
    header += (1).to_bytes(2, "big")
    header += len(chunks).to_bytes(2, "big")
    header += ticks_per_quarter.to_bytes(2, "big")
    return header + b"".join(chunks)


def _midi_track_chunk(name: str, notes: list[dict[str, Any]], ticks_per_quarter: int) -> bytes:
    events: list[tuple[int, int, bytes]] = []
    name_bytes = name.encode("utf-8")
    events.append((0, 0, b"\xff\x03" + _vlq(len(name_bytes)) + name_bytes))
    for note in notes:
        start = int(round(float(note["start_beats"]) * ticks_per_quarter))
        end = int(
            round((float(note["start_beats"]) + float(note["duration_beats"])) * ticks_per_quarter)
        )
        pitch = max(0, min(127, int(note["pitch"])))
        velocity = max(1, min(127, int(note.get("velocity", 96))))
        channel = max(0, min(15, int(note.get("channel", 0))))
        events.append((start, 1, bytes([0x90 | channel, pitch, velocity])))
        events.append((end, 0, bytes([0x80 | channel, pitch, 0])))
    events.sort(key=lambda item: (item[0], item[1]))
    body = bytearray()
    current = 0
    for tick, _, payload in events:
        body += _vlq(max(0, tick - current))
        body += payload
        current = tick
    body += b"\x00\xff\x2f\x00"
    return b"MTrk" + len(body).to_bytes(4, "big") + bytes(body)


def _vlq(value: int) -> bytes:
    value = max(0, int(value))
    bytes_reversed = [value & 0x7F]
    value >>= 7
    while value:
        bytes_reversed.append((value & 0x7F) | 0x80)
        value >>= 7
    return bytes(reversed(bytes_reversed))


def _parse_track(
    reader: MidiReader,
    track_end: int,
    ticks_per_quarter: int,
    track_index: int,
) -> dict[str, Any]:
    absolute_ticks = 0
    running_status = 0
    name = ""
    tempo = None
    note_index = 0
    open_notes: dict[str, list[dict[str, int]]] = {}
    notes: list[dict[str, Any]] = []
    while reader.offset < track_end:
        absolute_ticks += reader.read_vlq()
        status = reader.read_u8()
        if status < 0x80:
            reader.offset -= 1
            status = running_status
        else:
            running_status = status
        if status == 0xFF:
            meta_type = reader.read_u8()
            length = reader.read_vlq()
            payload_start = reader.offset
            if meta_type == 0x03:
                name = reader.read_text(length)
            elif meta_type == 0x51 and length == 3:
                micros = (reader.read_u8() << 16) | (reader.read_u8() << 8) | reader.read_u8()
                tempo = 60000000 / micros
            reader.offset = payload_start + length
            continue
        if status in {0xF0, 0xF7}:
            reader.skip(reader.read_vlq())
            continue

        event_type = status & 0xF0
        channel = status & 0x0F
        data1 = reader.read_u8()
        data2 = 0 if event_type in {0xC0, 0xD0} else reader.read_u8()
        if event_type == 0x90 and data2 > 0:
            key = f"{channel}:{data1}"
            open_notes.setdefault(key, []).append(
                {"start_ticks": absolute_ticks, "velocity": data2}
            )
        elif event_type == 0x80 or (event_type == 0x90 and data2 == 0):
            key = f"{channel}:{data1}"
            stack = open_notes.get(key, [])
            if stack:
                started = stack.pop(0)
                note_index += 1
                notes.append(
                    _note(
                        f"t{track_index + 1}-n{note_index}",
                        data1,
                        started["start_ticks"] / ticks_per_quarter,
                        max(0.0313, (absolute_ticks - started["start_ticks"]) / ticks_per_quarter),
                        started["velocity"],
                        channel,
                    )
                )
            if not stack and key in open_notes:
                del open_notes[key]
    return {"name": name, "notes": notes, "tempo": tempo}


def _note(
    note_id: str,
    pitch: int,
    start_beats: float,
    duration_beats: float,
    velocity: int = 96,
    channel: int = 0,
) -> dict[str, Any]:
    return {
        "note_id": note_id,
        "pitch": pitch,
        "channel": channel,
        "start_beats": _round_beat(start_beats),
        "duration_beats": _round_beat(duration_beats),
        "velocity": velocity,
        "muted": False,
    }


def _section(
    section_id: str, name: str, start_beats: float, duration_beats: float
) -> dict[str, Any]:
    return {
        "section_id": section_id,
        "name": name,
        "start_beats": start_beats,
        "duration_beats": duration_beats,
        "color": "#d8ff3e",
    }


def _default_sections(end_beats: float) -> list[dict[str, Any]]:
    if end_beats <= 0:
        return []
    section_size = 8
    sections = []
    names = ["intro", "verse", "chorus", "bridge", "outro"]
    start = 0
    index = 0
    while start < end_beats:
        duration = min(section_size, end_beats - start)
        sections.append(
            _section(f"section-{index + 1}", names[index % len(names)], start, duration)
        )
        start += duration
        index += 1
    return sections


def _infer_role(notes: list[dict[str, Any]]) -> str:
    if any(note["channel"] == 9 for note in notes):
        return "drums"
    average_pitch = sum(note["pitch"] for note in notes) / max(1, len(notes))
    return "bass" if average_pitch < 48 else "midi"


def _track_color(index: int) -> str:
    return ["#d8ff3e", "#62d8ff", "#ff7042", "#f6d365", "#b892ff", "#64f0a8"][index % 6]


def _round_beat(value: float) -> float:
    return round(float(value), 4)


def _tempo_from_project(project: dict[str, Any]) -> float:
    tempo = (project.get("tempo_map") or [{"bpm": 120}])[0]
    return float(tempo.get("bpm", 120))


def _default_transport(tempo: float) -> dict[str, Any]:
    return {
        "position": "001.1.1",
        "tempo": round(float(tempo), 4),
        "loop": False,
        "punch": False,
        "metronome": True,
        "sync": "internal",
        "playing": False,
        "recording": False,
    }
