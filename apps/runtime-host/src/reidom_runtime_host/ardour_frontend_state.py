from __future__ import annotations

from typing import Any


def build_ardour_frontend_state(
    project: dict[str, Any] | None,
    selection: dict[str, Any] | None = None,
    adapter: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Project/session projection used by the Tauri Ardour-style frontend."""

    project = project or _empty_project()
    selection = selection or project.get("selection") or {}
    tracks = list(project.get("tracks") or [])
    clips = list(project.get("clips") or [])
    command_log = {
        "undo_depth": len(project.get("undo_stack") or []),
        "redo_depth": len(project.get("redo_stack") or []),
    }
    route_rows = [
        _route_state(track, index, _track_clips(track, clips), selection)
        for index, track in enumerate(tracks)
    ]
    return {
        "schema": "reidom-ardour-frontend-state/v1",
        "source": _source(project, selection, adapter),
        "transport": _transport(project),
        "editor": {
            "ruler": _ruler(project),
            "global_tracks": _global_tracks(project),
            "routes": route_rows,
            "regions": _regions(project),
        },
        "mixer": {
            "strips": [_mixer_strip(route) for route in route_rows],
            "master": _master_strip(project),
        },
        "recorder": {
            "routes": [_recorder_route(route, index) for index, route in enumerate(route_rows)],
            "takes": _takes(project),
        },
        "cue_grid": {
            "scenes": _scenes(project),
            "rows": [_cue_row(route, _track_clips({"track_id": route["track_id"]}, clips)) for route in route_rows],
        },
        "bridge": {
            "command_log": command_log,
            "capabilities": _adapter_capabilities(adapter),
            "command_vocabulary": [
                "selection.set",
                "notes.add",
                "notes.delete",
                "notes.move",
                "notes.resize",
                "notes.velocity",
                "notes.transpose",
                "notes.duplicate",
                "notes.quantize",
                "clips.move",
                "clips.resize",
                "clips.duplicate",
                "routes.set_state",
                "transport.set_state",
            ],
        },
    }


def _empty_project() -> dict[str, Any]:
    return {
        "schema": "reidom-project/v1",
        "project_id": "empty",
        "name": "Untitled",
        "revision": 0,
        "tempo_map": [{"start_beats": 0, "bpm": 120}],
        "time_signatures": [{"start_beats": 0, "numerator": 4, "denominator": 4}],
        "tracks": [],
        "clips": [],
        "sections": [],
        "markers": [],
    }


def _source(
    project: dict[str, Any],
    selection: dict[str, Any],
    adapter: dict[str, Any] | None,
) -> dict[str, Any]:
    source = selection.get("source") if isinstance(selection, dict) else {}
    source = source if isinstance(source, dict) else {}
    return {
        "adapter_id": adapter.get("id") if adapter else source.get("daw_id", "midi-file"),
        "adapter_name": adapter.get("name") if adapter else source.get("daw_id", "MIDI File"),
        "project_id": project.get("project_id", "empty"),
        "project_name": project.get("name", "Untitled"),
        "revision": int(project.get("revision", 0)),
    }


def _transport(project: dict[str, Any]) -> dict[str, Any]:
    signature = (project.get("time_signatures") or [{"numerator": 4, "denominator": 4}])[0]
    stored = project.get("transport") or {}
    return {
        "position": stored.get("position", "001.1.1"),
        "tempo": float(stored.get("tempo", _tempo(project))),
        "time_signature": f"{signature.get('numerator', 4)}/{signature.get('denominator', 4)}",
        "loop": bool(stored.get("loop", False)),
        "punch": bool(stored.get("punch", False)),
        "metronome": bool(stored.get("metronome", True)),
        "sync": stored.get("sync", "internal"),
        "playing": bool(stored.get("playing", False)),
        "recording": bool(stored.get("recording", False)),
    }


def _tempo(project: dict[str, Any]) -> float:
    tempo = (project.get("tempo_map") or [{"bpm": 120}])[0]
    return float(tempo.get("bpm", 120))


def _ruler(project: dict[str, Any]) -> dict[str, Any]:
    end = _project_end(project)
    bar_step = 4
    bars = [
        {"beat": beat, "label": f"{int(beat / 4) + 1:03d}"}
        for beat in range(0, max(4, int(end) + 1), bar_step)
    ][:12]
    return {"start_beats": 0, "end_beats": end, "bars": bars}


def _global_tracks(project: dict[str, Any]) -> list[dict[str, Any]]:
    signature = (project.get("time_signatures") or [{"numerator": 4, "denominator": 4}])[0]
    return [
        {"key": "marker", "label": "Marker", "values": _markers(project)},
        {
            "key": "signature",
            "label": "Signature",
            "values": [f"{signature.get('numerator', 4)}/{signature.get('denominator', 4)}"] * 4,
        },
        {"key": "tempo", "label": "Tempo", "values": [str(round(_tempo(project)))] * 4},
    ]


def _markers(project: dict[str, Any]) -> list[str]:
    markers = project.get("markers") or []
    if markers:
        return [str(marker.get("name") or marker.get("start_beats") or "Marker") for marker in markers[:4]]
    sections = project.get("sections") or []
    if sections:
        return [str(section.get("name") or "Section") for section in sections[:4]]
    return ["Intro", "Verse", "Hook", "Bridge"]


def _regions(project: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "region_id": clip.get("clip_id"),
            "route_id": clip.get("track_id"),
            "name": clip.get("name", "Region"),
            "start_beats": float(clip.get("start_beats", 0)),
            "duration_beats": float(clip.get("duration_beats", 0)),
            "note_count": len(clip.get("notes") or []),
            "color": clip.get("color"),
        }
        for clip in project.get("clips", [])
    ]


def _route_state(
    track: dict[str, Any],
    index: int,
    clips: list[dict[str, Any]],
    selection: dict[str, Any],
) -> dict[str, Any]:
    note_count = sum(len(clip.get("notes") or []) for clip in clips)
    track_id = str(track.get("track_id", f"route-{index + 1}"))
    selected_clips = set(selection.get("selected_clip_ids") or [])
    selected_notes = set(selection.get("selected_note_ids") or [])
    return {
        "track_id": track_id,
        "number": index + 1,
        "name": track.get("name", track_id),
        "type": track.get("type", "midi"),
        "role": track.get("role", "midi"),
        "color": track.get("color") or _fallback_color(index),
        "record": bool(track.get("arm", False)),
        "monitor": bool(track.get("monitor", False)),
        "mute": bool(track.get("mute", False)),
        "solo": bool(track.get("solo", False)),
        "playlist": "Main",
        "automation": track.get("automation", "Read"),
        "group": track.get("group") or "-",
        "input": "Ardour MIDI Inputs",
        "output": "Master",
        "pan": float(track.get("pan", 0)),
        "gain": float(track.get("volume", 0.85)),
        "meter": _meter_value(index, note_count),
        "region_count": len(clips),
        "note_count": note_count,
        "selected": any(clip.get("clip_id") in selected_clips for clip in clips)
        or any(note.get("note_id") in selected_notes for clip in clips for note in clip.get("notes", [])),
    }


def _mixer_strip(route: dict[str, Any]) -> dict[str, Any]:
    return {
        **route,
        "processors": ["Input", "Instrument", "EQ", "Send"],
        "fader": route["gain"],
        "pan_label": _pan_label(route["pan"]),
    }


def _master_strip(project: dict[str, Any]) -> dict[str, Any]:
    return {
        "track_id": "master",
        "name": "Master",
        "type": "bus",
        "role": "master",
        "color": "#b8f547",
        "processors": ["Limiter", "Meter", "Dither"],
        "meter": min(0.92, 0.55 + len(project.get("tracks") or []) * 0.06),
        "fader": 0.72,
        "pan_label": "Out",
    }


def _recorder_route(route: dict[str, Any], index: int) -> dict[str, Any]:
    return {
        **route,
        "take": f"Take {index + 1:02d}",
        "record_safe": False,
        "input_status": "ready" if route["record"] or route["monitor"] else "idle",
    }


def _takes(project: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {"label": "Current take", "number": "01", "status": "playlist-safe"},
        {"label": "Previous take", "number": f"{max(0, len(project.get('undo_stack') or [])):02d}", "status": "undoable"},
        {"label": "Comp playlist", "number": "A", "status": "available"},
    ]


def _scenes(project: dict[str, Any]) -> list[dict[str, Any]]:
    sections = project.get("sections") or []
    if sections:
        return [
            {
                "scene_id": section.get("section_id", f"scene-{index + 1}"),
                "label": str(section.get("name", f"Scene {index + 1}")),
                "start_beats": float(section.get("start_beats", index * 8)),
            }
            for index, section in enumerate(sections[:5])
        ]
    return [{"scene_id": f"scene-{index + 1}", "label": chr(65 + index), "start_beats": index * 8} for index in range(5)]


def _cue_row(route: dict[str, Any], clips: list[dict[str, Any]]) -> dict[str, Any]:
    slots = []
    for index in range(5):
        clip = clips[index] if index < len(clips) else None
        slots.append(
            {
                "slot_id": f"{route['track_id']}-slot-{index + 1}",
                "scene": chr(65 + index),
                "clip_id": clip.get("clip_id") if clip else None,
                "label": clip.get("name") if clip else f"Scene {chr(65 + index)}",
                "filled": clip is not None,
            }
        )
    return {"route": route, "slots": slots}


def _track_clips(track: dict[str, Any], clips: list[dict[str, Any]]) -> list[dict[str, Any]]:
    track_id = track.get("track_id")
    return [clip for clip in clips if clip.get("track_id") == track_id]


def _project_end(project: dict[str, Any]) -> float:
    return max(
        [
            8.0,
            *[
                float(clip.get("start_beats", 0)) + float(clip.get("duration_beats", 0))
                for clip in project.get("clips", [])
            ],
        ]
    )


def _meter_value(index: int, note_count: int) -> float:
    return min(0.96, 0.28 + ((index * 17) % 42) / 100 + min(note_count, 64) / 160)


def _pan_label(value: float) -> str:
    if value < -0.05:
        return f"L{round(abs(value) * 100)}"
    if value > 0.05:
        return f"R{round(value * 100)}"
    return "C"


def _adapter_capabilities(adapter: dict[str, Any] | None) -> dict[str, Any]:
    if not adapter:
        return {
            "read_midi_selection": True,
            "midi_command_tools": True,
            "command_log": True,
            "undo_redo": True,
        }
    return dict(adapter.get("capabilities") or {})


def _fallback_color(index: int) -> str:
    return ["#45b4ff", "#ffae4a", "#75df69", "#c28bff", "#37d0b2", "#f4cf58"][index % 6]
