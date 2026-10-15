from __future__ import annotations

from copy import deepcopy
from typing import Any

from .ai_snapshot import build_ai_snapshot_fields


def build_snapshot_bundle(
    project: dict[str, Any] | None,
    selection: dict[str, Any] | None = None,
    adapter: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build UI and AI projections from one committed project revision."""

    project = deepcopy(project or _empty_project())
    revision = int(project.get("revision") or 0)
    project_id = str(project.get("project_id") or "empty")
    selection = _normalized_selection(project, selection, revision)
    project_snapshot = _project_snapshot(project, selection, revision)
    ui_snapshot = _ui_snapshot(project_snapshot, selection, adapter)
    ai_fields = build_ai_snapshot_fields(project, selection, adapter)
    ai_snapshot = {
        "schema": "reidom-ai-snapshot/v2",
        "project_id": project_id,
        "source_revision": revision,
        "selection_id": selection.get("selection_id"),
        "fields": ai_fields,
    }
    return {
        "schema": "reidom-snapshot-bundle/v2",
        "snapshot_id": f"{project_id}:{revision}",
        "project_id": project_id,
        "source_revision": revision,
        "source": {
            "owner": "project-engine",
            "implementation": "legacy-python-project-store",
        },
        "project_snapshot": project_snapshot,
        "ui_snapshot": ui_snapshot,
        "ai_snapshot": ai_snapshot,
    }


def _project_snapshot(
    project: dict[str, Any],
    selection: dict[str, Any],
    revision: int,
) -> dict[str, Any]:
    return {
        "schema": "reidom-project-snapshot/v2",
        "project_id": str(project.get("project_id") or "empty"),
        "name": str(project.get("name") or "Untitled"),
        "source_revision": revision,
        "dirty": bool(project.get("dirty", False)),
        "tempo_map": deepcopy(project.get("tempo_map") or []),
        "time_signatures": deepcopy(project.get("time_signatures") or []),
        "key_signature": str(project.get("key_signature") or "unknown"),
        "transport": deepcopy(project.get("transport") or {}),
        "tracks": deepcopy(project.get("tracks") or []),
        "clips": deepcopy(project.get("clips") or []),
        "sections": deepcopy(project.get("sections") or []),
        "markers": deepcopy(project.get("markers") or []),
        "selection": deepcopy(selection),
        "history": {
            "undo_available": bool(project.get("undo_stack")),
            "redo_available": bool(project.get("redo_stack")),
            "undo_depth": len(project.get("undo_stack") or []),
            "redo_depth": len(project.get("redo_stack") or []),
        },
    }


def _ui_snapshot(
    project_snapshot: dict[str, Any],
    selection: dict[str, Any],
    adapter: dict[str, Any] | None,
) -> dict[str, Any]:
    project = deepcopy(project_snapshot)
    project["schema"] = "reidom-project/v1"
    project["revision"] = project.pop("source_revision")
    project["undo_stack"] = []
    project["redo_stack"] = []
    project.pop("history", None)
    return {
        "schema": "reidom-ui-snapshot/v2",
        "project_id": project_snapshot["project_id"],
        "source_revision": project_snapshot["source_revision"],
        "project": project,
        "selection": deepcopy(selection),
        "history": deepcopy(project_snapshot["history"]),
        "capabilities": _capabilities(adapter),
    }


def _normalized_selection(
    project: dict[str, Any],
    selection: dict[str, Any] | None,
    revision: int,
) -> dict[str, Any]:
    project_selection = project.get("selection")
    value = deepcopy(
        project_selection if isinstance(project_selection, dict) else selection or {}
    )
    project_id = str(project.get("project_id") or "empty")
    value["schema"] = "reidom-midi-selection/v1"
    value["selection_id"] = str(value.get("selection_id") or f"selection-{revision}")
    value["project_id"] = project_id
    value["revision"] = revision
    value.setdefault("selected_note_ids", [])
    value.setdefault("selected_clip_ids", [])
    value.setdefault("tracks", [])
    return value


def _capabilities(adapter: dict[str, Any] | None) -> dict[str, Any]:
    if adapter:
        return deepcopy(adapter.get("capabilities") or {})
    return {
        "read_midi_selection": True,
        "midi_command_tools": True,
        "command_log": True,
        "undo_redo": True,
    }


def _empty_project() -> dict[str, Any]:
    return {
        "schema": "reidom-project/v1",
        "project_id": "empty",
        "name": "Untitled",
        "revision": 0,
        "tempo_map": [{"start_beats": 0, "bpm": 120}],
        "time_signatures": [{"start_beats": 0, "numerator": 4, "denominator": 4}],
        "key_signature": "unknown",
        "transport": {
            "position": "001.1.1",
            "tempo": 120,
            "loop": False,
            "metronome": True,
            "playing": False,
            "recording": False,
        },
        "tracks": [],
        "clips": [],
        "sections": [],
        "markers": [],
        "selection": {},
        "undo_stack": [],
        "redo_stack": [],
    }
