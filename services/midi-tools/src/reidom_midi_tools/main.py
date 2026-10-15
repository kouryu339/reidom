from __future__ import annotations

import json
import os
from typing import Any
from uuid import uuid4

from corework_agent_tool import AIOutput, ToolErrorCode, register_tool, serve

from .chord_timeline import build_chord_timeline, public_chord_timeline
from .harmony_planner import plan_piano_harmony, public_harmony_plan
from .instrument_presets import resolve_instrument_preset, supported_preset_keys
from .music_copilot import (
    accompaniment_events,
    analyze_notes,
    bass_events,
    drum_events,
    humanize_edits,
    normalize_notes,
)
from .runtime_rpc import RuntimeHostClient, RuntimeHostError


@register_tool(
    name="MidiGetContext",
    description=(
        "Read the current Reidom project, selection, adapter capabilities, "
        "and AI snapshot before making MIDI edits."
    ),
    parameters=[],
    outputs=[
        {
            "name": "context",
            "field_type": "Object",
            "description": "Current reidom-console-context/v1 value from Runtime Host.",
        }
    ],
    readonly=True,
    destructive=False,
    idempotent=True,
    open_world=False,
    secret=False,
)
def midi_get_context(ctx) -> AIOutput:
    try:
        context = RuntimeHostClient.from_tool_context(ctx).context()
    except RuntimeHostError as exc:
        return _err(str(exc), ToolErrorCode.UNAVAILABLE)
    return _ok({"context": context}, _context_to_ai(context))


@register_tool(
    name="MidiSetSelection",
    description=(
        "Set the active MIDI note and clip selection. Use exact IDs from MidiGetContext. "
        "Pass [] for both lists to clear selection."
    ),
    parameters=[
        {
            "name": "note_ids_json",
            "param_type": "String",
            "required": False,
            "description": "JSON array of note IDs to select, for example [\"n1\",\"n2\"].",
        },
        {
            "name": "clip_ids_json",
            "param_type": "String",
            "required": False,
            "description": "JSON array of clip IDs to select, for example [\"clip-1\"].",
        },
        {
            "name": "reason",
            "param_type": "String",
            "required": True,
            "description": "Why this selection change helps the edit workflow.",
        },
        {
            "name": "project_id",
            "param_type": "String",
            "required": False,
            "description": "Optional project_id. Omit to use the active project.",
        },
    ],
    outputs=[{"name": "command", "field_type": "Object", "description": "Applied command."}],
    readonly=False,
    destructive=False,
    idempotent=False,
    open_world=False,
    secret=False,
)
def midi_set_selection(
    ctx,
    note_ids_json: str = "[]",
    clip_ids_json: str = "[]",
    reason: str = "",
    project_id: str = "",
) -> AIOutput:
    try:
        payload = {
            "note_ids": _id_list(note_ids_json, "note_ids_json"),
            "clip_ids": _id_list(clip_ids_json, "clip_ids_json"),
        }
    except ValueError as exc:
        return _err(str(exc), ToolErrorCode.INVALID_ARGUMENT)
    return _run_reidom_command(ctx, "selection.set", payload, reason, project_id)


@register_tool(
    name="MidiAddNote",
    description="Add one MIDI note to a target clip or track, then select the added note.",
    parameters=[
        {
            "name": "pitch",
            "param_type": "Integer",
            "required": True,
            "description": "MIDI pitch 0-127.",
        },
        {
            "name": "start_beats",
            "param_type": "Number",
            "required": True,
            "description": "Start position in quarter-note beats.",
        },
        {
            "name": "duration_beats",
            "param_type": "Number",
            "required": True,
            "description": "Duration in quarter-note beats.",
        },
        {
            "name": "velocity",
            "param_type": "Integer",
            "required": False,
            "description": "MIDI velocity 1-127. Defaults to 96.",
        },
        {
            "name": "track_id",
            "param_type": "String",
            "required": False,
            "description": "Target track ID. Omit when clip_id is supplied.",
        },
        {
            "name": "clip_id",
            "param_type": "String",
            "required": False,
            "description": "Target clip ID. Preferred when known.",
        },
        {
            "name": "reason",
            "param_type": "String",
            "required": True,
            "description": "Musical reason for adding this one note.",
        },
    ],
    outputs=[{"name": "command", "field_type": "Object", "description": "Applied command."}],
    readonly=False,
    destructive=False,
    idempotent=False,
    open_world=False,
    secret=False,
)
def midi_add_note(
    ctx,
    pitch: int,
    start_beats: float,
    duration_beats: float,
    velocity: int = 96,
    track_id: str = "",
    clip_id: str = "",
    reason: str = "",
) -> AIOutput:
    payload: dict[str, Any] = {
        "pitch": int(pitch),
        "start_beats": float(start_beats),
        "duration_beats": float(duration_beats),
        "velocity": int(velocity),
    }
    if track_id.strip():
        payload["track_id"] = track_id.strip()
    if clip_id.strip():
        payload["clip_id"] = clip_id.strip()
    return _run_reidom_command(ctx, "notes.add", payload, reason)


@register_tool(
    name="MidiDeleteNotes",
    description=(
        "Delete selected notes or exact note IDs. This is destructive within the command "
        "step, but still undoable through Reidom command history."
    ),
    parameters=[
        {
            "name": "note_ids_json",
            "param_type": "String",
            "required": False,
            "description": "Optional JSON array of note IDs. Omit to delete active selected notes.",
        },
        {
            "name": "reason",
            "param_type": "String",
            "required": True,
            "description": "Why these notes should be removed.",
        },
    ],
    outputs=[{"name": "command", "field_type": "Object", "description": "Applied command."}],
    readonly=False,
    destructive=True,
    idempotent=False,
    open_world=False,
    secret=False,
)
def midi_delete_notes(ctx, note_ids_json: str = "", reason: str = "") -> AIOutput:
    try:
        payload = _payload_with_optional_ids("note_ids", note_ids_json, "note_ids_json")
    except ValueError as exc:
        return _err(str(exc), ToolErrorCode.INVALID_ARGUMENT)
    return _run_reidom_command(ctx, "notes.delete", payload, reason)


@register_tool(
    name="MidiMoveNotes",
    description="Move selected notes or exact note IDs by beats and/or semitones.",
    parameters=[
        {
            "name": "delta_beats",
            "param_type": "Number",
            "required": False,
            "description": "Beat offset. Positive moves later, negative moves earlier.",
        },
        {
            "name": "delta_pitch",
            "param_type": "Integer",
            "required": False,
            "description": "Semitone offset. Positive moves up, negative moves down.",
        },
        {
            "name": "note_ids_json",
            "param_type": "String",
            "required": False,
            "description": "Optional JSON array of note IDs. Omit to use active selected notes.",
        },
        {
            "name": "reason",
            "param_type": "String",
            "required": True,
            "description": "Musical reason for this timing or pitch move.",
        },
    ],
    outputs=[{"name": "command", "field_type": "Object", "description": "Applied command."}],
    readonly=False,
    destructive=False,
    idempotent=False,
    open_world=False,
    secret=False,
)
def midi_move_notes(
    ctx,
    delta_beats: float = 0,
    delta_pitch: int = 0,
    note_ids_json: str = "",
    reason: str = "",
) -> AIOutput:
    try:
        payload = _payload_with_optional_ids("note_ids", note_ids_json, "note_ids_json")
    except ValueError as exc:
        return _err(str(exc), ToolErrorCode.INVALID_ARGUMENT)
    payload.update({"delta_beats": float(delta_beats), "delta_pitch": int(delta_pitch)})
    return _run_reidom_command(ctx, "notes.move", payload, reason)


@register_tool(
    name="MidiResizeNotes",
    description="Resize selected notes or exact note IDs by a beat delta.",
    parameters=[
        {
            "name": "delta_beats",
            "param_type": "Number",
            "required": True,
            "description": "Duration delta in beats. Positive lengthens, negative shortens.",
        },
        {
            "name": "note_ids_json",
            "param_type": "String",
            "required": False,
            "description": "Optional JSON array of note IDs. Omit to use active selected notes.",
        },
        {
            "name": "reason",
            "param_type": "String",
            "required": True,
            "description": "Musical reason for changing note length.",
        },
    ],
    outputs=[{"name": "command", "field_type": "Object", "description": "Applied command."}],
    readonly=False,
    destructive=False,
    idempotent=False,
    open_world=False,
    secret=False,
)
def midi_resize_notes(
    ctx,
    delta_beats: float,
    note_ids_json: str = "",
    reason: str = "",
) -> AIOutput:
    try:
        payload = _payload_with_optional_ids("note_ids", note_ids_json, "note_ids_json")
    except ValueError as exc:
        return _err(str(exc), ToolErrorCode.INVALID_ARGUMENT)
    payload["delta_beats"] = float(delta_beats)
    return _run_reidom_command(ctx, "notes.resize", payload, reason)


@register_tool(
    name="MidiTransposeNotes",
    description="Transpose selected notes or exact note IDs by semitones.",
    parameters=[
        {
            "name": "semitones",
            "param_type": "Integer",
            "required": True,
            "description": "Semitone delta. Positive transposes up, negative transposes down.",
        },
        {
            "name": "note_ids_json",
            "param_type": "String",
            "required": False,
            "description": "Optional JSON array of note IDs. Omit to use active selected notes.",
        },
        {
            "name": "reason",
            "param_type": "String",
            "required": True,
            "description": "Musical reason for this transposition.",
        },
    ],
    outputs=[{"name": "command", "field_type": "Object", "description": "Applied command."}],
    readonly=False,
    destructive=False,
    idempotent=False,
    open_world=False,
    secret=False,
)
def midi_transpose_notes(
    ctx,
    semitones: int,
    note_ids_json: str = "",
    reason: str = "",
) -> AIOutput:
    try:
        payload = _payload_with_optional_ids("note_ids", note_ids_json, "note_ids_json")
    except ValueError as exc:
        return _err(str(exc), ToolErrorCode.INVALID_ARGUMENT)
    payload["semitones"] = int(semitones)
    return _run_reidom_command(ctx, "notes.transpose", payload, reason)


@register_tool(
    name="MidiSetNoteVelocity",
    description="Set velocity for selected notes or exact note IDs.",
    parameters=[
        {
            "name": "velocity",
            "param_type": "Integer",
            "required": True,
            "description": "Target MIDI velocity 1-127.",
        },
        {
            "name": "note_ids_json",
            "param_type": "String",
            "required": False,
            "description": "Optional JSON array of note IDs. Omit to use active selected notes.",
        },
        {
            "name": "reason",
            "param_type": "String",
            "required": True,
            "description": "Musical reason for this dynamic change.",
        },
    ],
    outputs=[{"name": "command", "field_type": "Object", "description": "Applied command."}],
    readonly=False,
    destructive=False,
    idempotent=False,
    open_world=False,
    secret=False,
)
def midi_set_note_velocity(
    ctx,
    velocity: int,
    note_ids_json: str = "",
    reason: str = "",
) -> AIOutput:
    try:
        payload = _payload_with_optional_ids("note_ids", note_ids_json, "note_ids_json")
    except ValueError as exc:
        return _err(str(exc), ToolErrorCode.INVALID_ARGUMENT)
    payload["velocity"] = int(velocity)
    return _run_reidom_command(ctx, "notes.velocity", payload, reason)


@register_tool(
    name="MidiDuplicateNotes",
    description="Duplicate selected notes or exact note IDs by a beat offset.",
    parameters=[
        {
            "name": "delta_beats",
            "param_type": "Number",
            "required": False,
            "description": "Beat offset for duplicated notes. Defaults to 0.25.",
        },
        {
            "name": "note_ids_json",
            "param_type": "String",
            "required": False,
            "description": "Optional JSON array of note IDs. Omit to use active selected notes.",
        },
        {
            "name": "reason",
            "param_type": "String",
            "required": True,
            "description": "Musical reason for duplicating the notes.",
        },
    ],
    outputs=[{"name": "command", "field_type": "Object", "description": "Applied command."}],
    readonly=False,
    destructive=False,
    idempotent=False,
    open_world=False,
    secret=False,
)
def midi_duplicate_notes(
    ctx,
    delta_beats: float = 0.25,
    note_ids_json: str = "",
    reason: str = "",
) -> AIOutput:
    try:
        payload = _payload_with_optional_ids("note_ids", note_ids_json, "note_ids_json")
    except ValueError as exc:
        return _err(str(exc), ToolErrorCode.INVALID_ARGUMENT)
    payload["delta_beats"] = float(delta_beats)
    return _run_reidom_command(ctx, "notes.duplicate", payload, reason)


@register_tool(
    name="MidiQuantizeNotes",
    description="Quantize selected notes or exact note IDs to a beat grid.",
    parameters=[
        {
            "name": "grid_beats",
            "param_type": "Number",
            "required": True,
            "description": "Grid size in beats, for example 0.25 for sixteenth notes.",
        },
        {
            "name": "note_ids_json",
            "param_type": "String",
            "required": False,
            "description": "Optional JSON array of note IDs. Omit to use active selected notes.",
        },
        {
            "name": "reason",
            "param_type": "String",
            "required": True,
            "description": "Musical reason for quantizing these notes.",
        },
    ],
    outputs=[{"name": "command", "field_type": "Object", "description": "Applied command."}],
    readonly=False,
    destructive=False,
    idempotent=False,
    open_world=False,
    secret=False,
)
def midi_quantize_notes(
    ctx,
    grid_beats: float,
    note_ids_json: str = "",
    reason: str = "",
) -> AIOutput:
    try:
        payload = _payload_with_optional_ids("note_ids", note_ids_json, "note_ids_json")
    except ValueError as exc:
        return _err(str(exc), ToolErrorCode.INVALID_ARGUMENT)
    payload["grid_beats"] = float(grid_beats)
    return _run_reidom_command(ctx, "notes.quantize", payload, reason)


@register_tool(
    name="MidiMoveClips",
    description="Move selected clips or exact clip IDs by a beat offset.",
    parameters=[
        {
            "name": "delta_beats",
            "param_type": "Number",
            "required": True,
            "description": "Beat offset. Positive moves later, negative moves earlier.",
        },
        {
            "name": "clip_ids_json",
            "param_type": "String",
            "required": False,
            "description": "Optional JSON array of clip IDs. Omit to use active selected clips.",
        },
        {
            "name": "reason",
            "param_type": "String",
            "required": True,
            "description": "Musical or arrangement reason for moving these clips.",
        },
    ],
    outputs=[{"name": "command", "field_type": "Object", "description": "Applied command."}],
    readonly=False,
    destructive=False,
    idempotent=False,
    open_world=False,
    secret=False,
)
def midi_move_clips(
    ctx,
    delta_beats: float,
    clip_ids_json: str = "",
    reason: str = "",
) -> AIOutput:
    try:
        payload = _payload_with_optional_ids("clip_ids", clip_ids_json, "clip_ids_json")
    except ValueError as exc:
        return _err(str(exc), ToolErrorCode.INVALID_ARGUMENT)
    payload["delta_beats"] = float(delta_beats)
    return _run_reidom_command(ctx, "clips.move", payload, reason)


@register_tool(
    name="MidiResizeClips",
    description="Resize selected clips or exact clip IDs by a beat delta.",
    parameters=[
        {
            "name": "delta_beats",
            "param_type": "Number",
            "required": True,
            "description": "Duration delta in beats. Positive lengthens, negative shortens.",
        },
        {
            "name": "clip_ids_json",
            "param_type": "String",
            "required": False,
            "description": "Optional JSON array of clip IDs. Omit to use active selected clips.",
        },
        {
            "name": "reason",
            "param_type": "String",
            "required": True,
            "description": "Musical or arrangement reason for resizing these clips.",
        },
    ],
    outputs=[{"name": "command", "field_type": "Object", "description": "Applied command."}],
    readonly=False,
    destructive=False,
    idempotent=False,
    open_world=False,
    secret=False,
)
def midi_resize_clips(
    ctx,
    delta_beats: float,
    clip_ids_json: str = "",
    reason: str = "",
) -> AIOutput:
    try:
        payload = _payload_with_optional_ids("clip_ids", clip_ids_json, "clip_ids_json")
    except ValueError as exc:
        return _err(str(exc), ToolErrorCode.INVALID_ARGUMENT)
    payload["delta_beats"] = float(delta_beats)
    return _run_reidom_command(ctx, "clips.resize", payload, reason)


@register_tool(
    name="MidiDuplicateClips",
    description="Duplicate selected clips or exact clip IDs by a beat offset.",
    parameters=[
        {
            "name": "delta_beats",
            "param_type": "Number",
            "required": False,
            "description": "Beat offset for duplicated clips. Defaults to 4 beats.",
        },
        {
            "name": "clip_ids_json",
            "param_type": "String",
            "required": False,
            "description": "Optional JSON array of clip IDs. Omit to use active selected clips.",
        },
        {
            "name": "reason",
            "param_type": "String",
            "required": True,
            "description": "Musical or arrangement reason for duplicating these clips.",
        },
    ],
    outputs=[{"name": "command", "field_type": "Object", "description": "Applied command."}],
    readonly=False,
    destructive=False,
    idempotent=False,
    open_world=False,
    secret=False,
)
def midi_duplicate_clips(
    ctx,
    delta_beats: float = 4,
    clip_ids_json: str = "",
    reason: str = "",
) -> AIOutput:
    try:
        payload = _payload_with_optional_ids("clip_ids", clip_ids_json, "clip_ids_json")
    except ValueError as exc:
        return _err(str(exc), ToolErrorCode.INVALID_ARGUMENT)
    payload["delta_beats"] = float(delta_beats)
    return _run_reidom_command(ctx, "clips.duplicate", payload, reason)


def _run_reidom_command(
    ctx: Any,
    command_type: str,
    payload: dict[str, Any],
    reason: str,
    project_id: str = "",
) -> AIOutput:
    if not reason.strip():
        return _err("MIDI commands require a musical reason for the command log.", ToolErrorCode.MISSING_ARGUMENT)
    client = RuntimeHostClient.from_tool_context(ctx)
    try:
        context = client.context()
        project = _active_project(context)
        active_project_id = project_id.strip() or str(project["project_id"])
        base_revision = int(project["revision"])
        command_id = f"cmd-ai-{uuid4().hex[:12]}"
        result = client.run_command(
            active_project_id,
            command_type,
            payload,
            reason=reason.strip(),
            command_id=command_id,
            base_revision=base_revision,
        )
    except RuntimeHostError as exc:
        return _err(str(exc), ToolErrorCode.UNAVAILABLE)
    except (KeyError, TypeError, ValueError) as exc:
        return _err(f"Cannot run command: {exc}", ToolErrorCode.CONFLICT)

    updated_project = result.get("project") or {}
    selection = result.get("selection") or {}
    notes = _selection_note_count(selection)
    return _ok(
        {
            "command_id": command_id,
            "project_id": active_project_id,
            "type": command_type,
            "result_revision": updated_project.get("revision"),
            "selection": selection,
        },
        f"已完成{command_type}，当前有 {notes} 个音符，可撤销。",
    )


@register_tool(
    name="MidiUndo",
    description="Undo one reversible Reidom command on the active project.",
    parameters=[
        {
            "name": "project_id",
            "param_type": "String",
            "required": False,
            "description": "Optional project_id. Omit to use the active project.",
        }
    ],
    outputs=[{"name": "project", "field_type": "Object", "description": "Project after undo."}],
    readonly=False,
    destructive=False,
    idempotent=False,
    open_world=False,
    secret=False,
)
def midi_undo(ctx, project_id: str = "") -> AIOutput:
    return _history_step(ctx, "undo", project_id)


@register_tool(
    name="MidiRedo",
    description="Redo one previously undone Reidom command on the active project.",
    parameters=[
        {
            "name": "project_id",
            "param_type": "String",
            "required": False,
            "description": "Optional project_id. Omit to use the active project.",
        }
    ],
    outputs=[{"name": "project", "field_type": "Object", "description": "Project after redo."}],
    readonly=False,
    destructive=False,
    idempotent=False,
    open_world=False,
    secret=False,
)
def midi_redo(ctx, project_id: str = "") -> AIOutput:
    return _history_step(ctx, "redo", project_id)


@register_tool(
    name="MidiGetCommandLog",
    description=(
        "Read the reversible command history for the current project. "
        "Use it to explain, audit, or step through human and AI edits."
    ),
    parameters=[
        {
            "name": "project_id",
            "param_type": "String",
            "required": False,
            "description": "Optional project_id. Omit to use the active project.",
        },
        {
            "name": "include_snapshots",
            "param_type": "Boolean",
            "required": False,
            "description": "Set true only when a replay UI needs before/after snapshots.",
        },
    ],
    outputs=[{"name": "command_log", "field_type": "Object", "description": "Command history."}],
    readonly=True,
    destructive=False,
    idempotent=True,
    open_world=False,
    secret=False,
)
def midi_get_command_log(
    ctx,
    project_id: str = "",
    include_snapshots: bool = False,
) -> AIOutput:
    try:
        client = RuntimeHostClient.from_tool_context(ctx)
        active_project_id = project_id.strip() or str(_active_project(client.context())["project_id"])
        command_log = client.command_log(active_project_id, include_snapshots=bool(include_snapshots))
    except RuntimeHostError as exc:
        return _err(str(exc), ToolErrorCode.UNAVAILABLE)
    except (KeyError, TypeError, ValueError) as exc:
        return _err(f"Cannot read command log: {exc}", ToolErrorCode.NOT_FOUND)
    return _ok({"command_log": command_log}, _command_log_to_ai(command_log))


@register_tool(
    name="MidiAnalyzeSelection",
    description=(
        "Analyze the active MIDI selection for note counts, pitch range, density, "
        "selected material, and simple edit risks before choosing small commands."
    ),
    parameters=[],
    outputs=[{"name": "analysis", "field_type": "Object", "description": "Selection analysis."}],
    readonly=True,
    destructive=False,
    idempotent=True,
    open_world=False,
    secret=False,
)
def midi_analyze_selection(ctx) -> AIOutput:
    try:
        context = RuntimeHostClient.from_tool_context(ctx).context()
    except RuntimeHostError as exc:
        return _err(str(exc), ToolErrorCode.UNAVAILABLE)
    analysis = _selection_analysis(context)
    try:
        analysis["musical"] = analyze_notes(_source_notes(context, ""))
    except ValueError:
        analysis["musical"] = analyze_notes([])
    return _ok({"analysis": analysis}, _analysis_to_ai(analysis))


@register_tool(
    name="MidiGeneratePianoHarmony",
    description="Create a voiced piano harmony track from the selected or named melody track.",
    parameters=[
        {"name": "style", "param_type": "String", "required": False, "description": "pop, ballad, rock, rnb, jazz, or cinematic."},
        {"name": "complexity", "param_type": "String", "required": False, "description": "simple, balanced, or rich."},
        {"name": "harmonic_rhythm", "param_type": "String", "required": False, "description": "auto, half_bar, bar, or two_bars."},
        {"name": "key", "param_type": "String", "required": False, "description": "Key name or auto."},
        {"name": "source_track_id", "param_type": "String", "required": False, "description": "Melody track ID. Omit to use selected notes or the first populated track."},
    ],
    outputs=[{"name": "harmony", "field_type": "Object", "description": "Applied harmony plan."}],
    readonly=False,
    destructive=False,
    idempotent=False,
    open_world=False,
    secret=False,
)
def midi_generate_piano_harmony(
    ctx,
    style: str = "pop",
    complexity: str = "balanced",
    harmonic_rhythm: str = "auto",
    key: str = "auto",
    source_track_id: str = "",
) -> AIOutput:
    try:
        client, context, project = _music_context(ctx)
        melody = _source_notes(context, source_track_id)
        plan = plan_piano_harmony(
            melody,
            style=style.strip().lower(),
            complexity=complexity.strip().lower(),
            harmonic_rhythm=harmonic_rhythm.strip().lower(),
            key=key.strip() or "auto",
        )
        command = _apply_generated_track(
            client,
            project,
            name="Piano Harmony",
            role="harmony",
            instrument="piano",
            events=plan["events"],
            reason=f"Generate {style} piano harmony from the melody.",
        )
    except (RuntimeHostError, KeyError, TypeError, ValueError) as exc:
        return _err(str(exc), ToolErrorCode.INVALID_ARGUMENT)
    public = public_harmony_plan(plan)
    return _ok(
        {"harmony": public, "command": command},
        f"已生成钢琴和声：{public['key']}，{len(public['progression'])} 个和弦位置，质量评分 {public['quality']['overall']}。",
    )


@register_tool(
    name="MidiRenderChordTimeline",
    description="Render a timed chord sequence such as 4/4 @1:1-5:1 | Am7(4) Fmaj7(4) G7(4) Cadd9(4) || block.",
    parameters=[
        {"name": "timeline", "param_type": "String", "required": True, "description": "Chord timeline with bar, beat, duration, and optional arpeggio performance."},
        {"name": "track_name", "param_type": "String", "required": False, "description": "New piano track name."},
    ],
    outputs=[{"name": "timeline", "field_type": "Object", "description": "Applied chord timeline."}],
    readonly=False,
    destructive=False,
    idempotent=False,
    open_world=False,
    secret=False,
)
def midi_render_chord_timeline(ctx, timeline: str, track_name: str = "Piano Chords") -> AIOutput:
    try:
        client, _, project = _music_context(ctx)
        plan = build_chord_timeline(timeline)
        command = _apply_generated_track(
            client,
            project,
            name=track_name.strip() or "Piano Chords",
            role="harmony",
            instrument="piano",
            events=plan["events"],
            reason="Render the requested chord timeline as a piano part.",
        )
    except (RuntimeHostError, KeyError, TypeError, ValueError) as exc:
        return _err(str(exc), ToolErrorCode.INVALID_ARGUMENT)
    public = public_chord_timeline(plan)
    return _ok(
        {"timeline": public, "command": command},
        f"已写入钢琴和弦：{len(public['chords'])} 次和弦变化，范围 {public['range']['start']} 到 {public['range']['end']}。",
    )


@register_tool(
    name="MidiGenerateBass",
    description="Create an electric-bass track from a chord progression using the fixed bass preset.",
    parameters=[
        {"name": "chords_json", "param_type": "String", "required": True, "description": "JSON chord list, for example [\"Am7\",\"Fmaj7\",\"G7\",\"Cadd9\"]."},
        {"name": "beats_per_chord", "param_type": "Number", "required": False, "description": "Duration of each chord in beats."},
        {"name": "style", "param_type": "String", "required": False, "description": "roots, eighths, or root_fifth."},
    ],
    outputs=[{"name": "command", "field_type": "Object", "description": "Applied bass arrangement."}],
    readonly=False,
    destructive=False,
    idempotent=False,
    open_world=False,
    secret=False,
)
def midi_generate_bass(ctx, chords_json: str, beats_per_chord: float = 4, style: str = "root_fifth") -> AIOutput:
    try:
        chords = _chord_list(chords_json)
        events = bass_events(chords, float(beats_per_chord), style.strip().lower(), 2)
        client, _, project = _music_context(ctx)
        command = _apply_generated_track(client, project, name="Electric Bass", role="bass", instrument="electric_bass", events=events, reason="Generate a bass part from the chord progression.")
    except (RuntimeHostError, KeyError, TypeError, ValueError) as exc:
        return _err(str(exc), ToolErrorCode.INVALID_ARGUMENT)
    return _ok({"command": command}, f"已生成电贝斯：{len(chords)} 个和弦，{len(events)} 个音符。")


@register_tool(
    name="MidiGenerateDrums",
    description="Create a drum track with the fixed standard drum-kit preset.",
    parameters=[
        {"name": "bars", "param_type": "Integer", "required": True, "description": "Number of 4/4 bars."},
        {"name": "style", "param_type": "String", "required": False, "description": "backbeat, four_on_floor, or half_time."},
        {"name": "velocity", "param_type": "Integer", "required": False, "description": "Base velocity."},
    ],
    outputs=[{"name": "command", "field_type": "Object", "description": "Applied drum arrangement."}],
    readonly=False,
    destructive=False,
    idempotent=False,
    open_world=False,
    secret=False,
)
def midi_generate_drums(ctx, bars: int, style: str = "backbeat", velocity: int = 88) -> AIOutput:
    try:
        if not 1 <= int(bars) <= 128:
            raise ValueError("bars must be between 1 and 128")
        events = drum_events(style.strip().lower(), int(bars), int(velocity))
        client, _, project = _music_context(ctx)
        command = _apply_generated_track(client, project, name="Drums", role="rhythm", instrument="drums", events=events, reason="Generate a drum groove for the arrangement.")
    except (RuntimeHostError, KeyError, TypeError, ValueError) as exc:
        return _err(str(exc), ToolErrorCode.INVALID_ARGUMENT)
    return _ok({"command": command}, f"已生成鼓组：{bars} 小节，{len(events)} 个鼓点。")


@register_tool(
    name="MidiGenerateAccompaniment",
    description="Create a chord accompaniment using a stable built-in instrument preset.",
    parameters=[
        {"name": "chords_json", "param_type": "String", "required": True, "description": "JSON chord list."},
        {"name": "instrument", "param_type": "String", "required": False, "description": "Preset: piano, electric_piano, electric_guitar, acoustic_guitar, strings, organ, or synth."},
        {"name": "beats_per_chord", "param_type": "Number", "required": False, "description": "Duration of each chord in beats."},
        {"name": "rhythm", "param_type": "String", "required": False, "description": "block, half, or quarters."},
    ],
    outputs=[{"name": "command", "field_type": "Object", "description": "Applied accompaniment."}],
    readonly=False,
    destructive=False,
    idempotent=False,
    open_world=False,
    secret=False,
)
def midi_generate_accompaniment(ctx, chords_json: str, instrument: str = "piano", beats_per_chord: float = 4, rhythm: str = "block") -> AIOutput:
    try:
        preset = resolve_instrument_preset(instrument)
        if preset is None or preset.key in {"drums", "electric_bass"}:
            raise ValueError(f"instrument must be one of {', '.join(key for key in supported_preset_keys() if key not in {'drums', 'electric_bass'})}")
        chords = _chord_list(chords_json)
        events = accompaniment_events(chords, float(beats_per_chord), rhythm.strip().lower(), 4)
        client, _, project = _music_context(ctx)
        command = _apply_generated_track(client, project, name=preset.patch_name, role="accompaniment", instrument=preset.key, events=events, reason=f"Generate {preset.label} accompaniment from the chord progression.")
    except (RuntimeHostError, KeyError, TypeError, ValueError) as exc:
        return _err(str(exc), ToolErrorCode.INVALID_ARGUMENT)
    return _ok({"command": command, "preset": preset.key}, f"已生成{preset.label}伴奏：{len(chords)} 个和弦，{len(events)} 个音符。")


@register_tool(
    name="MidiHumanizeSelection",
    description="Humanize selected notes as one undoable JUCE project command.",
    parameters=[
        {"name": "timing_amount_beats", "param_type": "Number", "required": False, "description": "Maximum timing offset, normally 0.01 to 0.04 beats."},
        {"name": "velocity_amount", "param_type": "Integer", "required": False, "description": "Maximum velocity variation."},
        {"name": "seed", "param_type": "Integer", "required": False, "description": "Stable variation seed."},
    ],
    outputs=[{"name": "command", "field_type": "Object", "description": "Applied humanize command."}],
    readonly=False,
    destructive=False,
    idempotent=False,
    open_world=False,
    secret=False,
)
def midi_humanize_selection(ctx, timing_amount_beats: float = 0.02, velocity_amount: int = 6, seed: int = 1) -> AIOutput:
    try:
        client, context, project = _music_context(ctx)
        notes = _source_notes(context, "", require_selection=True)
        edits = humanize_edits(notes, max(0.0, min(float(timing_amount_beats), 0.125)), max(0, min(int(velocity_amount), 24)), int(seed))
        command = _apply_command(client, project, "notes.batch_update", {"edits": edits}, "Humanize the selected notes with stable timing and velocity variation.")
    except (RuntimeHostError, KeyError, TypeError, ValueError) as exc:
        return _err(str(exc), ToolErrorCode.INVALID_ARGUMENT)
    return _ok({"command": command}, f"已自然化 {len(edits)} 个音符，可一步撤销。")


def _music_context(ctx: Any) -> tuple[RuntimeHostClient, dict[str, Any], dict[str, Any]]:
    client = RuntimeHostClient.from_tool_context(ctx)
    context = client.context()
    return client, context, _active_project(context)


def _source_notes(
    context: dict[str, Any],
    source_track_id: str,
    *,
    require_selection: bool = False,
) -> list[Any]:
    selection = context.get("active_selection") or {}
    selected_ids = {str(item) for item in selection.get("selected_note_ids") or []}
    tracks = selection.get("tracks") or []
    requested = source_track_id.strip()
    raw_notes: list[dict[str, Any]] = []
    for track in tracks:
        if requested and str(track.get("track_id")) != requested:
            continue
        for note in track.get("notes") or []:
            if require_selection and str(note.get("note_id")) not in selected_ids:
                continue
            if not requested and selected_ids and str(note.get("note_id")) not in selected_ids:
                continue
            raw_notes.append(note)
        if raw_notes and (requested or not selected_ids):
            break
    if require_selection and not selected_ids:
        raise ValueError("select notes before humanizing")
    notes = normalize_notes(raw_notes)
    if not notes:
        raise ValueError("the source melody has no usable notes")
    return notes


def _chord_list(value: str) -> list[str]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError(f"chords_json must be a JSON array: {exc}") from exc
    if not isinstance(parsed, list) or not 1 <= len(parsed) <= 128:
        raise ValueError("chords_json must contain 1 to 128 chord names")
    chords = [str(item).strip() for item in parsed]
    if any(not item for item in chords):
        raise ValueError("chords_json contains an empty chord")
    return chords


def _apply_generated_track(
    client: RuntimeHostClient,
    project: dict[str, Any],
    *,
    name: str,
    role: str,
    instrument: str,
    events: list[dict[str, Any]],
    reason: str,
) -> dict[str, Any]:
    preset = resolve_instrument_preset(instrument)
    if preset is None:
        raise ValueError(f"unknown instrument preset: {instrument}")
    return _apply_command(
        client,
        project,
        "arrangement.add_track",
        {
            "name": name,
            "clip_name": name,
            "role": role,
            "instrument": preset.key,
            "notes": events,
        },
        reason,
    )


def _apply_command(
    client: RuntimeHostClient,
    project: dict[str, Any],
    command_type: str,
    payload: dict[str, Any],
    reason: str,
) -> dict[str, Any]:
    command_id = f"cmd-ai-{uuid4().hex[:12]}"
    result = client.run_command(
        str(project["project_id"]),
        command_type,
        payload,
        reason=reason,
        command_id=command_id,
        base_revision=int(project["revision"]),
    )
    updated = result.get("project") or {}
    return {
        "command_id": command_id,
        "type": command_type,
        "result_revision": updated.get("revision"),
    }


def _history_step(ctx: Any, action: str, project_id: str) -> AIOutput:
    try:
        client = RuntimeHostClient.from_tool_context(ctx)
        active_project_id = project_id.strip() or str(_active_project(client.context())["project_id"])
        result = client.undo(active_project_id) if action == "undo" else client.redo(active_project_id)
    except RuntimeHostError as exc:
        return _err(str(exc), ToolErrorCode.UNAVAILABLE)
    except (KeyError, TypeError, ValueError) as exc:
        return _err(f"Cannot {action}: {exc}", ToolErrorCode.NOT_FOUND)
    selection = result.get("selection") or {}
    return _ok(
        result,
        f"已{('撤销' if action == 'undo' else '重做')}，当前有 {_selection_note_count(selection)} 个音符。",
    )


def _payload_with_optional_ids(
    field_name: str,
    ids_json: str,
    argument_name: str,
) -> dict[str, Any]:
    if not ids_json.strip():
        return {}
    return {field_name: _id_list(ids_json, argument_name)}


def _id_list(value: str, argument_name: str) -> list[str]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{argument_name} must be a JSON array of strings: {exc}") from exc
    if not isinstance(parsed, list):
        raise TypeError(f"{argument_name} must be a JSON array of strings")
    ids = [str(item).strip() for item in parsed]
    if any(not item for item in ids):
        raise ValueError(f"{argument_name} contains an empty ID")
    return ids


def _active_project(context: dict[str, Any]) -> dict[str, Any]:
    project = context.get("active_project")
    if not isinstance(project, dict):
        raise KeyError("no active project; import MIDI or load a demo first")
    if not project.get("project_id"):
        raise KeyError("active project has no project_id")
    return project


def _ok(result: dict[str, Any], to_ai: str) -> AIOutput:
    return AIOutput(result=result, to_ai=to_ai, error_code=ToolErrorCode.OK)


def _err(message: str, code: ToolErrorCode) -> AIOutput:
    return AIOutput(
        result={"error": message},
        to_ai=f"未完成：{message}",
        error_code=code,
    )


def _context_to_ai(context: dict[str, Any]) -> str:
    project = context.get("active_project") or {}
    selection = context.get("active_selection") or {}
    notes = _selection_note_count(selection)
    if not project:
        return "当前没有工程，请先导入 MIDI 或载入示例。"
    return (
        f"当前工程《{project.get('name')}》：{len(selection.get('tracks', []))} 条轨道，"
        f"{notes} 个音符，{_tempo(project)} BPM，调性 {project.get('key_signature', '未知')}。"
    )


def _command_log_to_ai(command_log: dict[str, Any]) -> str:
    undo_entries = command_log.get("undo_entries") or []
    redo_entries = command_log.get("redo_entries") or []
    lines = [f"共有 {len(undo_entries)} 步可撤销，{len(redo_entries)} 步可重做。"]
    for entry in undo_entries[-5:]:
        reason = entry.get("reason") or "no reason recorded"
        lines.append(
            f"- {entry.get('type')}：{reason}"
        )
    if not undo_entries:
        lines.append("- 还没有修改记录。")
    return "\n".join(lines)


def _selection_analysis(context: dict[str, Any]) -> dict[str, Any]:
    project = context.get("active_project") or {}
    selection = context.get("active_selection") or {}
    tracks = selection.get("tracks") or []
    notes = [
        {**note, "track_id": track.get("track_id"), "role": track.get("role", "unknown")}
        for track in tracks
        for note in track.get("notes", [])
    ]
    selected = set(selection.get("selected_note_ids") or [])
    selected_notes = [note for note in notes if note.get("note_id") in selected]
    active_notes = selected_notes or notes
    pitches = [int(note.get("pitch", 0)) for note in active_notes]
    velocities = [int(note.get("velocity", 0)) for note in active_notes]
    duration = max(
        0.0,
        float((selection.get("range") or {}).get("end_beats", 0))
        - float((selection.get("range") or {}).get("start_beats", 0)),
    )
    risks = []
    if not notes:
        risks.append("selection is empty")
    if selected and not selected_notes:
        risks.append("selected_note_ids do not match visible notes")
    if duration and len(active_notes) / duration > 8:
        risks.append("high note density; prefer smaller edits")
    return {
        "project_id": project.get("project_id"),
        "revision": project.get("revision"),
        "key_signature": project.get("key_signature", "unknown"),
        "tempo": _tempo(project),
        "track_count": len(tracks),
        "note_count": len(notes),
        "selected_note_count": len(selected_notes),
        "active_note_count": len(active_notes),
        "pitch_range": [min(pitches), max(pitches)] if pitches else None,
        "average_velocity": round(sum(velocities) / len(velocities), 1) if velocities else None,
        "density_notes_per_beat": round(len(active_notes) / duration, 2) if duration else 0,
        "risks": risks,
    }


def _analysis_to_ai(analysis: dict[str, Any]) -> str:
    risks = analysis.get("risks") or []
    risk_text = "；".join(risks) if risks else "未发现明显风险"
    return (
        f"选区共 {analysis.get('note_count')} 个音符，已选 {analysis.get('selected_note_count')} 个，"
        f"音域 {analysis.get('pitch_range')}，密度 {analysis.get('density_notes_per_beat')} 音/拍。{risk_text}。"
    )


def _selection_note_count(selection: dict[str, Any]) -> int:
    return sum(len(track.get("notes", [])) for track in selection.get("tracks", []))


def _tempo(project: dict[str, Any]) -> Any:
    tempo_map = project.get("tempo_map") or []
    if not tempo_map:
        return "unknown"
    return tempo_map[0].get("bpm", "unknown")


def main() -> None:
    host = os.getenv("REIDOM_MIDI_TOOL_HOST", "127.0.0.1")
    port = int(os.getenv("REIDOM_MIDI_TOOL_PORT", "50120"))
    serve(host=host, port=port)


if __name__ == "__main__":
    main()
