from pathlib import Path

from reidom_runtime_host.ai_snapshot import (
    build_ai_snapshot_fields,
    build_ai_snapshot_text,
)
from reidom_runtime_host.project_store import ProjectStore


def test_ai_snapshot_summarizes_project_and_selection(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path)
    project = store.demo_project()
    note_ids = [
        note["note_id"]
        for clip in project["clips"]
        if clip["track_id"] == "bass"
        for note in clip["notes"][:3]
    ]
    project = store.apply_command(
        project["project_id"],
        {
            "schema": "reidom-command/v1",
            "command_id": "select-bass",
            "base_revision": project["revision"],
            "source": "user",
            "type": "selection.set",
            "payload": {"note_ids": note_ids},
            "preview": False,
        },
    )

    fields = build_ai_snapshot_fields(project, project["selection"])

    assert set(fields) == {
        "reidom.adapter",
        "reidom.arrangement",
        "reidom.project",
        "reidom.selection",
    }
    assert "Current host-observed Reidom project state" in fields["reidom.project"]
    assert "Tempo: 126 BPM" in fields["reidom.project"]
    assert "Sub Bass" in fields["reidom.selection"]
    assert "bass material" in fields["reidom.selection"]
    assert "Selected notes: b1, b2, b3" in fields["reidom.selection"]
    assert "record each change" in fields["reidom.adapter"]


def test_ai_snapshot_reads_chordal_harmony_material(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path)
    project = store.demo_project()
    chord_ids = [
        note["note_id"]
        for clip in project["clips"]
        if clip["track_id"] == "chords"
        for note in clip["notes"][:3]
    ]
    project = store.apply_command(
        project["project_id"],
        {
            "schema": "reidom-command/v1",
            "command_id": "select-chord",
            "base_revision": project["revision"],
            "source": "user",
            "type": "selection.set",
            "payload": {"note_ids": chord_ids},
            "preview": False,
        },
    )

    fields = build_ai_snapshot_fields(project, project["selection"])
    text = build_ai_snapshot_text(fields)

    assert "Warm Chords" in fields["reidom.selection"]
    assert "chordal/polyphonic" in text
    assert "harmony/accompaniment material" in text


def test_ai_snapshot_uses_adapter_capabilities(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path)
    project = store.demo_project()
    adapter = {
        "id": "reaper",
        "name": "REAPER",
        "capabilities": {
            "read_midi_selection": True,
            "midi_command_tools": "planned",
            "command_log": "planned",
            "undo_redo": True,
        },
    }

    fields = build_ai_snapshot_fields(project, project["selection"], adapter)

    assert "Adapter: REAPER" in fields["reidom.adapter"]
    assert "MIDI command tools: planned" in fields["reidom.adapter"]
    assert "Undo/redo: yes" in fields["reidom.adapter"]
